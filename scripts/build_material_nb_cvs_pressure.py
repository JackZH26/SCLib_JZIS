"""Reproduce the finite Nb0.07-CVS pressure table from pinned official HTML/PDF.

This is a read-only source projection, not a generic HTML importer or catalogue
update. Original manuscripts stay private; the public snapshot contains facts,
source locators, scientific context and hashes. Uses only the Python stdlib.
"""
import argparse
import hashlib
import html
import json
from pathlib import Path
import re

NAME = "materials-nb-cvs-pressure-2026-10-05.json"
HTML_SHA = "b5f1bc07212429562d977e9def108dbbc075e86977ab6d54e5ea597cd3bacf53"
PDF_SHA = "bddff2c5fbac870cbebdadec91d4fc14687081b97cc72aa10f80834eb2c94f99"
URL = "https://arxiv.org/html/2411.18744v1"
FIELDS = [
    ("inverse_squared_penetration_depth", "λ⁻²(T = 0)", "Inverse squared London penetration depth", "μm⁻²", "table_row_label", ["6.9(3)", "5.7(3)", "10.0(4)", "12.5(1)"]),
    ("london_penetration_depth", "λ(T > 0)", "London penetration depth", "nm", "table_row_label", ["381", "419", "315", "283"]),
    ("phase_fraction", "ω", "Phase fraction in the gap fit", None, "caption_definition_no_printed_unit", ["1", "1", "0.73(4)", "1"]),
    ("fitted_tc", "Tc", "Transition temperature from gap-structure fit", "K", "table_row_label", ["3.000(6)", "3.25(1)", "6.67(7)", "6.94(2)"]),
    ("gap_1", "Δ₁", "First gap parameter", "meV", "table_row_label", ["0.54(9)", "0.47(7)", "0.65(5)", "1.56(4)"]),
    ("gap_2", "Δ₂", "Second gap parameter", "meV", "table_row_label", ["-", "-", "3.5(9)", "-"]),
    ("chi_squared", "χ²", "Fit statistic", None, "caption_definition_no_printed_unit", ["4.5", "2.6", "15.4", "34.8"]),
    ("chi_squared_per_ndf", "χ²/NDF", "Fit statistic per degree of freedom", None, "caption_definition_no_printed_unit", ["0.346", "0.153", "1.1", "1.74"]),
]


def sha(value):
    return hashlib.sha256(value).hexdigest()


def pin(text, start, end, element_id):
    return {"element_id": element_id, "html_char_start": start, "html_char_end": end,
            "sha256": sha(text[start:end].encode("utf-8"))}


def element(text, tag, element_id):
    # This finite source has no nested td/th/p/table elements of the same tag.
    pattern = rf'<{tag} id="{re.escape(element_id)}"[^>]*>(.*?)</{tag}>'
    found = list(re.finditer(pattern, text, re.S))
    if len(found) != 1:
        raise ValueError(f"Expected one pinned source element: {element_id}")
    match = found[0]
    return match, pin(text, match.start(), match.end(), element_id)


def build(source_html, source_pdf):
    if sha(source_html) != HTML_SHA or sha(source_pdf) != PDF_SHA:
        raise ValueError("Original HTML or PDF differs from the inspected source version")
    text = source_html.decode("utf-8")
    table, table_pin = element(text, "table", "S3.T1.2")
    caption = re.search(r'<figcaption[^>]*>(.*?)</figcaption>', text[table.end():], re.S)
    if caption is None:
        raise ValueError("Missing table caption")
    caption_pin = pin(text, table.end() + caption.start(), table.end() + caption.end(), "S3.T1")
    pressures = []
    pressure_label, pressure_label_pin = element(text, "th", "S3.T1.2.1.1")
    if pressure_label.group(1) != "Pressure (GPa)":
        raise ValueError("Pressure header has changed")
    for i, expected in enumerate(["0", "0.4", "0.8", "1.2"], 2):
        match, locator = element(text, "td", f"S3.T1.2.1.{i}")
        if match.group(1) != expected:
            raise ValueError("Pressure column has changed")
        pressures.append({"raw_value": expected, "raw_unit": "GPa", "unit_basis": "table_header",
                          "value_locator": pin(text, match.start(1), match.end(1), locator["element_id"]),
                          "unit_locator": pressure_label_pin,
                          "model": "Double nodeless s-wave" if expected == "0.8" else "Single nodeless s-wave",
                          "model_locator": caption_pin})
    fields = []
    for row, (key, symbol, label, unit, basis, expected_values) in enumerate(FIELDS, 2):
        header, header_pin = element(text, "th", f"S3.T1.2.{row}.1")
        math_source = [html.unescape(value) for value in re.findall(r'alttext="([^"]+)"', header.group(1))]
        cells = []
        for col, expected in enumerate(expected_values, 2):
            match, locator = element(text, "td", f"S3.T1.2.{row}.{col}")
            value = match.group(1)
            if value != expected or not re.fullmatch(r"(?:\d+(?:\.\d+)?(?:\(\d+\))?|-)", value):
                raise ValueError("Pressure table cell differs from inspected values")
            uncertainty = re.search(r"\(\d+\)$", value)
            cells.append({"pressure_column_index_0_based": col - 2, "raw_value": value,
                          "raw_uncertainty": uncertainty.group() if uncertainty else None,
                          "state": "source_dash" if value == "-" else "source_literal",
                          "normalized_value": None,
                          "value_locator": pin(text, match.start(1), match.end(1), locator["element_id"])})
        fields.append({"id": key, "symbol": symbol, "label": label, "display_unit": unit,
                       "unit_basis": basis, "source_row_index_1_based": row - 1,
                       "row_label_locator": header_pin, "row_label_math_alt_text": math_source,
                       "role": "source_reported_fit_statistic" if key.startswith("chi_squared") else "source_reported_fit_parameter",
                       "cells": cells})
    contexts = {}
    for key, source_id in [("composition", "S1.p3.1"), ("sample_type", "S2.p1.1"),
                           ("ambient_prose_fit", "S3.p3.1"), ("pressure_method", "S3.p4.1")]:
        _, contexts[key] = element(text, "p", source_id)
    _, figure_pin = element(text, "figure", "S3.F5")
    return {
        "version": "materials-nb-cvs-pressure/1.0.0", "prepared_on": "2026-10-05",
        "source": {"paper_id": "arxiv:2411.18744", "edition": "v1", "html_url": URL,
                   "pdf_url": "https://arxiv.org/pdf/2411.18744v1", "html_sha256": HTML_SHA,
                   "pdf_sha256": PDF_SHA, "captured_at_utc": "2026-10-05T09:35:45.606574+00:00",
                   "pdf_table_page_1_based": 8, "html_table_label": "Table 1", "pdf_table_label": "Table I",
                   "table_locator": table_pin, "caption_locator": caption_pin,
                   "character_indexing": "zero-based Unicode code points in original HTML; end exclusive",
                   "publisher_and_retained_ingestion_equivalence": "unestablished",
                   "current_publication_status": "not_checked"},
        "subject": {"source_alias": "Nb0.07-CVS", "source_formula": "Cs(V0.93Nb0.07)3Sb5",
                    "physical_sample_id": None, "catalogue_result_association": "unestablished",
                    "sample_type_basis": "Paper-wide single-crystal default unless otherwise stated; no unique specimen identifier for Table 1.",
                    "composition_locator": contexts["composition"], "sample_type_locator": contexts["sample_type"]},
        "method": {"origin": "fit_of_experimental_data", "probe": "Transverse-field μSR",
                   "applied_field": {"raw_value": "10", "raw_unit": "mT"},
                   "tc_role": "Parameter in the superconducting gap-structure analysis; no resistive onset/midpoint/zero criterion assigned.",
                   "ac_comparison": "The separate AC susceptibility data were collected under zero-field conditions.",
                   "conditions_locator": contexts["pressure_method"], "figure_locator": figure_pin,
                   "temperature_domain": "Temperature-dependent fits; tabulated λ⁻² has T = 0 and λ retains the printed T > 0 label.",
                   "pressure_reference": "Printed applied hydrostatic pressure columns; no absolute/gauge or numerical ambient-pressure conversion supplied.",
                   "uncertainty_semantics": "Parenthetical notation retained without statistical reinterpretation or conversion."},
        "pressure_columns": pressures, "fields": fields,
        "comparison": {"legacy_snapshot": "materials-source-observations-2026-10-02.json",
                       "already_displayed_cells": ["S3.T1.2.3.2", "S3.T1.2.5.2", "S3.T1.2.6.2"],
                       "ambient_prose_locator": contexts["ambient_prose_fit"],
                       "ambient_prose_values": {"tc": "4.70(3) K", "lambda": "316(5) nm", "gap": "0.590(5) meV"},
                       "relationship_to_table": "Separate reported fits; physical sample/dataset correspondence remains unresolved."},
        "counts": {"parameter_rows": 8, "pressure_columns": 4, "table_cells": 32, "numeric_cells": 29,
                   "source_dashes": 3, "property_parameter_numeric_cells": 21, "fit_statistic_numeric_cells": 8,
                   "previously_displayed_numeric_cells": 3, "additional_property_parameters": 18, "additional_numeric_cells": 26,
                   "independent_experiments": None, "formal_property_promotions": 0},
        "scope": {"normalization": "none", "lambda_is_epc_coupling": False,
                  "omega_is_superconducting_volume_fraction": False,
                  "dash_means_zero_or_measured_absence": False, "fit_statistics_are_acceptance_scores": False},
        "authority": {"independent_human_review": False, "scientific_acceptance": False,
                      "ml_training_approved": False, "database_changed": False},
    }


def serialized(snapshot):
    return (json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", type=Path, required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = serialized(build(args.html.read_bytes(), args.pdf.read_bytes()))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / NAME).write_bytes(output)
    (args.output_dir / (NAME + ".sha256")).write_text(f"{sha(output)}  {NAME}\n", encoding="utf-8")
    print(f"29 source numbers (26 additional), 3 source dashes, 0 catalogue promotions; SHA-256 {sha(output)}")


if __name__ == "__main__":
    main()
