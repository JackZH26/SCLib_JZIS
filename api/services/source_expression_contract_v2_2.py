"""Opt-in thermal-table intake with explicit original cell bindings.

The frozen 2.0 parsed-number contract remains separate. This profile retains
a declared rectangular table and independently hashed original cells. It
establishes neither field interpretation nor a material/sample association.
"""

from __future__ import annotations

import base64
import binascii
import hashlib

from services import source_expression_contract_v2 as frozen
from services.material_literal_field_contract import QUALIFIERS
from services.material_table_field_contract import (
    FIELDS,
    GRID_VERSION,
    MAX_COLUMNS,
    MAX_ROWS,
    PROFILE,
)
from services.material_table_field_contract import REGISTRY_SHA256 as REGISTRY_SHA256
from services.research_release_manifest import canonical, digest

VERSION = "source-expression-package/2.2.0"
MAX_TEXT_BYTES = frozen.MAX_TEXT_BYTES
MAX_EXPRESSIONS = frozen.MAX_EXPRESSIONS
MAX_PACKAGE_BYTES = frozen.MAX_PACKAGE_BYTES
MAX_PROJECTION_BYTES = frozen.MAX_PROJECTION_BYTES
MAX_WINDOW_CHARACTERS = 4096
MAX_VALUE_CHARACTERS = 1200
MAX_UNIT_CHARACTERS = 120
MAX_CUE_CHARACTERS = 200
MAX_UNCERTAINTY_CHARACTERS = 200
ROLES = frozen.ROLES
SOURCE_KEYS = frozen.SOURCE_KEYS
LOCATOR_KEYS = frozen.LOCATOR_KEYS
EXPRESSION_KEYS = frozen.EXPRESSION_KEYS | {
    "profile", "field_role", "cue_spans", "uncertainty_spans", "qualifiers", "table_binding"
}
PACKAGE_KEYS = {
    "version", "profile", "source", "source_text_base64",
    "source_content_sha256", "expressions",
}
SourceExpressionContractError = frozen.SourceExpressionContractError
PreparedPackage = frozen.PreparedPackage
require = frozen.require
closed = frozen.closed
text = frozen.text
sha = frozen.sha
spans = frozen.spans
source_metadata = frozen.source_metadata


def _selection(source_text, selections, *, limit, optional=False):
    require(
        type(selections) is list and len(selections) in ((0, 1) if optional else (1,)),
        "contiguous_literal_span_required",
    )
    return spans(source_text, selections, optional=optional, limit=limit)


def _span_projection(selection):
    if selection is None:
        return None
    return {
        "char_start": selection["start"],
        "char_end": selection["end"],
        "text_sha256": selection["sha256"],
    }


def _inside(selection, window):
    return window["start"] <= selection["start"] < selection["end"] <= window["end"]


def table_binding(source_text, request, window):
    """Check the declared grid against retained bytes, not source-layout truth."""
    grid = request["table_binding"]
    closed(grid, {"version", "caption_spans", "header_spans", "rows", "row_index", "column_index"})
    require(grid["version"] == GRID_VERSION, "table_grid_version_required")
    headers, rows = grid["header_spans"], grid["rows"]
    require(type(headers) is list and 2 <= len(headers) <= MAX_COLUMNS,
            "table_bounded_headers_required")
    require(type(rows) is list and 1 <= len(rows) <= MAX_ROWS,
            "table_bounded_rows_required")
    require(all(type(row) is list and len(row) == len(headers) for row in rows),
            "table_rectangular_grid_required")
    row_index, column_index = grid["row_index"], grid["column_index"]
    require(type(row_index) is int and 0 <= row_index < len(rows)
            and type(column_index) is int and 1 <= column_index < len(headers),
            "table_selected_cell_required")
    caption = _selection(source_text, grid["caption_spans"], limit=1000, optional=True)
    previous_end = window["start"]
    cells = [*grid["caption_spans"], *headers, *(cell for row in rows for cell in row)]
    for cell in cells:
        _selection(source_text, [cell], limit=MAX_VALUE_CHARACTERS)
        require(_inside(cell, window) and previous_end <= cell["start"],
                "table_ordered_original_cells_required")
        previous_end = cell["end"]
    require(request["subject"]["formula_spans"] == [headers[column_index]]
            and request["subject"]["sample_label_spans"] == [],
            "table_exact_column_subject_required")
    require(request["value_spans"] == [rows[row_index][column_index]],
            "table_exact_value_cell_required")
    label = rows[row_index][0]
    require(len(request["unit_spans"]) == 1
            and _inside(request["unit_spans"][0], label)
            and _inside(request["cue_spans"][0], label)
            and request["cue_spans"][0]["end"] <= request["unit_spans"][0]["start"],
            "table_cue_and_unit_in_row_label_required")
    locator = request["locator"]
    closed(locator, LOCATOR_KEYS)
    require(locator["row"] == row_index + 1 and type(locator["row"]) is int
            and locator["column"] == column_index + 1 and type(locator["column"]) is int
            and type(locator["table"]) is str and bool(locator["table"]),
            "table_locator_matches_grid_required")
    return {
        "version": GRID_VERSION, "grid_sha256": digest(grid),
        "verification": "retained_spans_checked_layout_declared",
        "row_index_0_based": row_index, "column_index_0_based": column_index,
        "row_count": len(rows), "column_count": len(headers),
        "raw_caption": caption or None,
        "raw_row_label": _selection(source_text, [label], limit=MAX_VALUE_CHARACTERS),
        "header_span": _span_projection(headers[column_index]),
        "row_label_span": _span_projection(label),
        "caption_span": _span_projection(grid["caption_spans"][0]) if grid["caption_spans"] else None,
    }


def project(source, source_text, request):
    closed(request, EXPRESSION_KEYS)
    field = request["field_id"]
    require(
        request["profile"] == PROFILE
        and type(field) is str
        and field in FIELDS
        and request["field_role"] == FIELDS[field]
        and type(request["source_role"]) is str
        and request["source_role"] in ROLES
        and type(request["knowledge_origin"]) is str
        and request["knowledge_origin"] in {"Observed", "Computed", "unknown"},
        "closed_literal_field_profile_role_required",
    )
    require(type(request["conditions"]) is list and not request["conditions"],
            "literal_conditions_must_be_empty")
    qualifiers = request["qualifiers"]
    require(
        type(qualifiers) is list
        and len(qualifiers) <= len(QUALIFIERS)
        and all(type(value) is str and value in QUALIFIERS for value in qualifiers)
        and len(set(qualifiers)) == len(qualifiers),
        "closed_literal_qualifiers_required",
    )
    closed(request["window"], {"id", "label_spans"})
    raw_window = _selection(source_text, request["window"]["label_spans"],
                            limit=MAX_WINDOW_CHARACTERS)
    window_selection = request["window"]["label_spans"][0]
    window = {"id": text(request["window"]["id"]), "raw_label": raw_window}
    closed(request["subject"], {"formula_spans", "sample_label_spans"})
    formula = _selection(source_text, request["subject"]["formula_spans"], limit=200)
    subject = {
        "formula": formula,
        "sample_label": spans(source_text, request["subject"]["sample_label_spans"],
                              optional=True, limit=200) or None,
        "formula_scope": "retained_formula_span",
    }
    raw_amount = _selection(source_text, request["value_spans"], limit=MAX_VALUE_CHARACTERS)
    printed_unit = _selection(source_text, request["unit_spans"],
                              optional=True, limit=MAX_UNIT_CHARACTERS)
    cue = _selection(source_text, request["cue_spans"], limit=MAX_CUE_CHARACTERS)
    uncertainty = _selection(source_text, request["uncertainty_spans"],
                             optional=True, limit=MAX_UNCERTAINTY_CHARACTERS)
    value_selection = request["value_spans"][0]
    unit_selection = request["unit_spans"][0] if request["unit_spans"] else None
    cue_selection = request["cue_spans"][0]
    uncertainty_selection = (request["uncertainty_spans"][0]
                             if request["uncertainty_spans"] else None)
    for selection in (
        request["subject"]["formula_spans"][0], value_selection,
        unit_selection, cue_selection, uncertainty_selection,
    ):
        require(selection is None or _inside(selection, window_selection),
                "literal_selection_outside_window")
    binding = table_binding(source_text, request, window_selection)
    require(
        uncertainty_selection is None or _inside(uncertainty_selection, value_selection),
        "literal_uncertainty_inside_amount_required",
    )
    value = {
        "status": "raw_literal",
        "raw_value": raw_amount,
        "raw_amount": raw_amount,
        "raw_unit": printed_unit.strip() if unit_selection else None,
        "raw_uncertainty": uncertainty if uncertainty_selection else None,
        "quantity": None,
        "normalization": "none",
        "unit_basis": "table_row_label",
        "field_cue": cue,
        "role": FIELDS[field],
        "qualifiers": list(qualifiers),
        "value_span": _span_projection(value_selection),
        "unit_span": _span_projection(unit_selection),
        "cue_span": _span_projection(cue_selection),
        "uncertainty_span": _span_projection(uncertainty_selection),
    }
    model = spans(source_text, request["model_spans"], optional=True, limit=500) or None
    closed(request["origin_basis"], {"statement", "spans"})
    text(request["origin_basis"]["statement"], 500, nullable=True)
    basis = {
        "statement": request["origin_basis"]["statement"],
        "retained_text": spans(source_text, request["origin_basis"]["spans"],
                               optional=True, limit=1000) or None,
        "verification": "declared_inspection_basis",
    }
    closed(request["locator"], LOCATOR_KEYS)
    for key, val in request["locator"].items():
        if key in {"page", "slide", "row", "column"}:
            require(val is None or type(val) is int and 1 <= val <= 100000,
                    "bounded_numeric_locator_required")
        else:
            text(val, 200, nullable=True)
    parent = request["predecessor"]
    if parent is not None:
        closed(parent, {"revision_id", "record_sha256", "revision_number"})
        from services.source_property_pending import identifier

        identifier(parent["revision_id"])
        sha(parent["record_sha256"])
        require(type(parent["revision_number"]) is int and 1 <= parent["revision_number"] <= 10000,
                "bounded_revision_required")
    identity = {
        "source_id": source["source_id"], "field_id": field,
        "profile": PROFILE, "field_role": FIELDS[field], "subject": subject,
        "window": window, "source_role": request["source_role"], "model": model,
        "table_binding": binding,
    }
    return {
        **identity,
        "expression_key": digest(identity),
        "knowledge_origin": request["knowledge_origin"],
        "origin_basis": basis,
        "value": value,
        "conditions": [],
        "locator": request["locator"],
        "status": "pending",
        "selected_result_association": "unestablished",
        "sample_identity_established": False,
        "phase_identity_established": False,
        "field_interpretation_reviewed": False,
        "scientific_acceptance": False,
        "canonical_promotions": 0,
        "public_content_release": False,
        "ml_training_approved": False,
        "missingness_scope": "not_supplied_in_retained_expression_is_not_source_absence",
    }


def compile_package(package):
    closed(package, PACKAGE_KEYS)
    require(package["version"] == VERSION and package["profile"] == PROFILE,
            "supported_literal_package_profile_required")
    source_metadata(package["source"])
    encoded = package["source_text_base64"]
    require(type(encoded) is str and len(encoded) <= 4 * ((MAX_TEXT_BYTES + 2) // 3),
            "bounded_source_bytes_required")
    try:
        raw = base64.b64decode(encoded, validate=True)
        source_text = raw.decode("utf-8")
    except (ValueError, binascii.Error, UnicodeError):
        raise SourceExpressionContractError("canonical_utf8_base64_required") from None
    require(
        base64.b64encode(raw).decode("ascii") == encoded
        and 1 <= len(raw) <= MAX_TEXT_BYTES and "\x00" not in source_text,
        "canonical_utf8_base64_required",
    )
    require(hashlib.sha256(raw).hexdigest() == sha(package["source_content_sha256"]),
            "source_content_hash_mismatch")
    require(type(package["expressions"]) is list
            and 1 <= len(package["expressions"]) <= MAX_EXPRESSIONS,
            "bounded_expressions_required")
    projections = [project(package["source"], source_text, entry)
                   for entry in package["expressions"]]
    require(all(len(canonical(projection)) <= MAX_PROJECTION_BYTES for projection in projections),
            "bounded_projection_bytes_required")
    require(len({projection["expression_key"] for projection in projections}) == len(projections),
            "distinct_expression_identity_required")
    retained = {key: value for key, value in package.items() if key != "source_text_base64"}
    require(len(canonical(retained)) <= MAX_PACKAGE_BYTES, "bounded_package_bytes_required")
    return PreparedPackage(source_text, retained, digest(retained), projections)
