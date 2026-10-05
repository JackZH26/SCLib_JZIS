"""Reproduce four Table II source readings from the retained, byte-pinned capture.

The public output contains numerical facts and locators, not paper full text,
private enrichment subjects or catalogue associations. No network or DB access.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
from services.material_enrichment import extract_table_candidates  # noqa: E402 - API service path above

NAME = "materials-thermal-table-2026-10-05.json"
PDF_SHA256 = "e132a511543478639f01bf06f43bd7f4d4d1ef4d29415e2024b1a5b1f8747c3e"
TEXT_SHA256 = "cad135f61877a5c6ef43162ec5276992efd5c1df24e6455b7fa80a9990885122"
TABLE_SHA256 = "2138d37a234d510afdc05be03601afabf233585dfef9a66f04c4fb168b0ddc1c"
CAPTURE = ROOT / "docs/data/materials-thermal-table-capture-2026-10-05.json"


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def project_capture(source):
    """Finite snapshot projection; changes need a new inspected source snapshot."""
    expected = json.loads(CAPTURE.read_text(encoding="utf-8"))
    if source != expected or sha256(source["text"].encode()) != TABLE_SHA256:
        raise ValueError("Retained Table II capture does not match the inspected snapshot")
    readings = []
    for formula in ("Mo5P1.1B1.9", "Mo5PB2"):
        subject = {"id": "source-study:" + formula, "formula": formula}
        candidates = extract_table_candidates(subject, {"paper_id": source["paper_id"]}, source)
        if len(candidates) != 2:
            raise ValueError("Expected exactly two column-bound thermal readings")
        for candidate in candidates:
            value = candidate["source_value"]
            field = candidate["field"]
            if field not in {"electronic_specific_heat_coefficient_source_value", "debye_temperature_source_value"}:
                raise ValueError("Unexpected thermal field")
            pins = {"value": value["value_span"], "unit": value["unit_span"], "cue": value["cue_span"],
                    "composition": candidate["table_binding"]["header_span"],
                    "row_label": candidate["table_binding"]["label_span"],
                    "caption": candidate["table_binding"]["caption_span"]}
            for pin in pins.values():
                if sha256(source["text"][pin["char_start"]:pin["char_end"]].encode()) != pin["text_sha256"]:
                    raise ValueError("Table evidence span does not match the capture")
            readings.append({
                "id": f"mo-table-II-column-{candidate['subject']['table_column'] + 1}-{'gamma' if field.startswith('electronic') else 'debye'}",
                "formula_as_printed": formula, "field_id": field,
                "raw_value": candidate["raw_value"], "raw_unit": value["raw_unit"],
                "raw_uncertainty": value["raw_uncertainty"], "normalization": "none",
                "unit_basis": "table_row_label", "identity_basis": "exact_table_column_formula",
                "row_index_0_based": candidate["source"]["locator"]["row"],
                "column_index_0_based": candidate["source"]["locator"]["column"],
                "field_cue": value["field_cue"], "raw_row_label": candidate["table_row_label"],
                "spans_in_table_text": deepcopy(pins),
            })
    return {
        "version": "materials-thermal-table/1.0.0", "prepared_on": "2026-10-05",
        "reading_count": 4, "source_composition_count": 2,
        "source": {"paper_id": source["paper_id"], "source_url": source["source_url"],
                   "captured_on": "2026-10-02", "pdf_page_1_based": 5, "table": "II",
                   "pdf_sha256": PDF_SHA256, "full_text_sha256": TEXT_SHA256,
                   "table_text_sha256": TABLE_SHA256,
                   "table_span_in_full_text": {"char_start": 18837, "char_end": 19127},
                   "character_indexing": "zero-based Unicode code points; end exclusive",
                   "row_indexing": "zero-based data rows, excluding the Composition header",
                   "column_indexing": "zero-based columns, including the row-label column",
                   "publication_revision_verified": False},
        "readings": readings,
        "scope": {"catalogue_result_association": "unestablished", "table_I_sample_association": "unestablished",
                  "pressure": "not_supplied_in_table", "uncertainty": "not_supplied_in_selected_cells",
                  "comparison_columns_included": False, "independent_experiment_count": None},
        "authority": {"independent_human_review": False, "scientific_acceptance": False,
                      "ml_training_approved": False, "canonical_promotions": 0, "database_changed": False},
    }


def build(source, full_text, pdf):
    if sha256(full_text) != TEXT_SHA256 or sha256(pdf) != PDF_SHA256:
        raise ValueError("Original text or PDF bytes do not match the retained capture")
    if full_text.decode("utf-8")[18837:19127] != source["text"]:
        raise ValueError("Table text does not match its original full-text window")
    return project_capture(source)


def serialized(snapshot):
    return (json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", type=Path, required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = serialized(build(json.loads(CAPTURE.read_text(encoding="utf-8")), args.text.read_bytes(), args.pdf.read_bytes()))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / NAME).write_bytes(output)
    (args.output_dir / (NAME + ".sha256")).write_text(f"{sha256(output)}  {NAME}\n", encoding="utf-8")
    print(f"4 source readings; 0 catalogue promotions; SHA-256 {sha256(output)}")


if __name__ == "__main__":
    main()
