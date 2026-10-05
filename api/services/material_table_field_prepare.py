"""Build private, inspectable table packages from captured original cells.

This prepares a source package only. It neither selects a catalogue result nor
creates a target/association, and it has no network or database side effects.
"""
from __future__ import annotations

import base64
from copy import deepcopy

from services import material_enrichment as enrichment
from services import source_expression_contract_v2_2 as contract
from services.research_release_manifest import digest


def span(pin):
    return {"start": pin["char_start"], "end": pin["char_end"], "sha256": pin["text_sha256"]}


def captured_cell(text, cell):
    contract.closed(cell, {"text", "char_start", "char_end"})
    start, end = cell["char_start"], cell["char_end"]
    contract.require(type(start) is int and type(end) is int and 0 <= start < end <= len(text)
                     and text[start:end] == cell["text"], "table_prepare_cell_changed")
    return {"start": start, "end": end, "sha256": enrichment.text_digest(text[start:end])}


def prepare_table_package(capture, *, formulas, source_metadata):
    enrichment.validate_source(capture)
    contract.source_metadata(source_metadata)
    contract.require(source_metadata["url"] == capture.get("source_url")
                     and source_metadata["original_parent_sha256"] == capture.get("capture_sha256"),
                     "table_prepare_source_declarations_changed")
    contract.require(type(formulas) is list and 1 <= len(formulas) <= 10
                     and all(type(formula) is str and formula for formula in formulas)
                     and len(set(formulas)) == len(formulas), "table_prepare_formula_inventory_required")
    contract.require(capture.get("kind") == "table" and type(capture.get("table")) is dict,
                     "table_prepare_original_capture_required")
    table, text = capture["table"], capture["text"]
    contract.require(type(table.get("header_cells")) is list
                     and 2 <= len(table["header_cells"]) <= contract.MAX_COLUMNS
                     and type(table.get("rows")) is list and 1 <= len(table["rows"]) <= contract.MAX_ROWS
                     and all(type(row) is dict and type(row.get("cells")) is list
                             and len(row["cells"]) == len(table["header_cells"]) for row in table["rows"]),
                     "table_prepare_original_capture_required")
    headers = [captured_cell(text, cell) for cell in table["header_cells"]]
    rows = [[captured_cell(text, cell) for cell in row["cells"]] for row in table["rows"]]
    caption = [captured_cell(text, table["caption"])] if table.get("caption") else []
    entries = []
    for formula in formulas:
        candidates = enrichment.extract_table_candidates(
            {"id": "source-study:" + formula, "formula": formula},
            {"paper_id": capture["paper_id"]}, capture,
        )
        candidates = [candidate for candidate in candidates if candidate["field"] in contract.FIELDS]
        contract.require(bool(candidates), "table_prepare_exact_column_candidates_required")
        for candidate in candidates:
            enrichment.validate_candidate_identity(candidate)
            contract.require(candidate["subject"]["identity_basis"] == "exact_table_column_formula",
                             "table_prepare_exact_column_candidates_required")
            value = candidate["source_value"]
            uncertainty = []
            if value["raw_uncertainty"] is not None:
                amount_span = span(value["value_span"])
                amount = text[amount_span["start"]:amount_span["end"]]
                token = value["raw_uncertainty"]
                contract.require(amount.count(token) == 1, "table_prepare_uncertainty_binding_required")
                start = amount_span["start"] + amount.index(token)
                uncertainty = [{"start": start, "end": start + len(token), "sha256": enrichment.text_digest(token)}]
            loc = candidate["source"]["locator"]
            locator = {key: loc.get(key) for key in contract.LOCATOR_KEYS}
            locator.update(row=loc["row"] + 1, column=loc["column"] + 1, member=capture["id"])
            entries.append({
                "field_id": candidate["field"], "profile": contract.PROFILE,
                "field_role": contract.FIELDS[candidate["field"]],
                "subject": {"formula_spans": [span(candidate["table_binding"]["header_span"])],
                            "sample_label_spans": []},
                "window": {"id": "captured-table:" + digest([capture["id"], capture["content_sha256"]]),
                           "label_spans": [{"start": 0, "end": len(text), "sha256": enrichment.text_digest(text)}]},
                "source_role": "source_proposed", "knowledge_origin": "unknown",
                "origin_basis": {"statement": "Original table cell capture; layout, publication revision and material state require inspection.", "spans": []},
                "model_spans": [], "value_spans": [span(value["value_span"])],
                "unit_spans": [span(value["unit_span"])], "cue_spans": [span(value["cue_span"])],
                "uncertainty_spans": uncertainty, "qualifiers": value["qualifiers"], "conditions": [],
                "locator": locator, "predecessor": None,
                "table_binding": {"version": contract.GRID_VERSION, "caption_spans": caption,
                                  "header_spans": headers, "rows": rows,
                                  "row_index": loc["row"], "column_index": loc["column"]},
            })
    package = {"version": contract.VERSION, "profile": contract.PROFILE,
               "source": deepcopy(source_metadata), "source_content_sha256": enrichment.text_digest(text),
               "source_text_base64": base64.b64encode(text.encode()).decode(), "expressions": deepcopy(entries)}
    contract.compile_package(package)
    return package
