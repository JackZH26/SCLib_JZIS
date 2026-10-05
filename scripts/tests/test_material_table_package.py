"""Actual retained Table II package and adversarial binding checks, offline."""
import base64
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))
from services import source_expression_contract_v2_1 as passage
from services import source_expression_contract_v2_2 as table_contract
from services.material_table_field_prepare import prepare_table_package


def actual_table_package():
    capture = json.loads((ROOT / "docs/data/materials-thermal-table-capture-2026-10-05.json").read_text())
    metadata = {
        "source_id": capture["id"], "url": capture["source_url"], "kind": "primary_paper",
        "content_kind": "plain_text", "revision": None, "revision_status": "unresolved",
        "original_parent_sha256": capture["capture_sha256"], "parent_hash_status": "declared",
        "rights_status": "unresolved", "currentness": "unresolved", "captured_at": "2026-10-02T00:00:00Z",
    }
    return prepare_table_package(capture, formulas=["Mo5P1.1B1.9", "Mo5PB2"], source_metadata=metadata)


def test_original_four_cells_compile_with_units_before_values_and_unchanged_text():
    package = actual_table_package()
    prepared = table_contract.compile_package(package)
    assert prepared.source_text == base64.b64decode(package["source_text_base64"]).decode()
    assert [(p["subject"]["formula"], p["value"]["raw_value"], p["value"]["raw_unit"])
            for p in prepared.projections] == [
        ("Mo5P1.1B1.9", "3.16", "mJ/mol-at./K2"), ("Mo5P1.1B1.9", "492", "K"),
        ("Mo5PB2", "3.07", "mJ/mol-at./K2"), ("Mo5PB2", "501", "K"),
    ]
    assert len({p["expression_key"] for p in prepared.projections}) == 4
    for projection in prepared.projections:
        value, binding = projection["value"], projection["table_binding"]
        assert value["unit_span"]["char_end"] < value["value_span"]["char_start"]
        assert value["unit_basis"] == "table_row_label"
        assert value["quantity"] is None and value["normalization"] == "none"
        assert value["raw_uncertainty"] is None
        assert binding["verification"] == "retained_spans_checked_layout_declared"
        assert binding["row_count"] == 5 and binding["column_count"] == 5
        assert projection["locator"]["column"] == binding["column_index_0_based"] + 1
        assert projection["selected_result_association"] == "unestablished"
        assert projection["scientific_acceptance"] is False
        assert projection["canonical_promotions"] == 0


@pytest.mark.parametrize("change, reason", [
    ("different_value_cell", "exact_value_cell"), ("different_formula_header", "exact_column_subject"),
    ("unit_from_other_row", "cue_and_unit"), ("reordered_headers", "ordered_original_cells"),
    ("reordered_cells", "ordered_original_cells"), ("ragged", "rectangular_grid"),
    ("column_zero", "selected_cell"), ("wrong_locator", "locator_matches_grid"),
    ("forged_hash", "span_content_hash"), ("outside_window", "outside_window"),
    ("new_authority", "closed_object"),
])
def test_table_binding_rejects_misassigned_cells_and_rehashed_assembly(change, reason):
    package = actual_table_package()
    entry = package["expressions"][0]
    grid = entry["table_binding"]
    if change == "different_value_cell":
        entry["value_spans"] = [grid["rows"][1][2]]
    elif change == "different_formula_header":
        entry["subject"]["formula_spans"] = [grid["header_spans"][2]]
    elif change == "unit_from_other_row":
        entry["unit_spans"] = deepcopy(package["expressions"][1]["unit_spans"])
    elif change == "reordered_headers":
        grid["header_spans"][1:3] = reversed(grid["header_spans"][1:3])
    elif change == "reordered_cells":
        grid["rows"][1][1:3] = reversed(grid["rows"][1][1:3])
    elif change == "ragged":
        grid["rows"][0].pop()
    elif change == "column_zero":
        grid["column_index"] = 0
    elif change == "wrong_locator":
        entry["locator"]["row"] = 1
    elif change == "forged_hash":
        grid["header_spans"][0]["sha256"] = "0" * 64
    elif change == "outside_window":
        entry["window"]["label_spans"] = [deepcopy(entry["value_spans"][0])]
    else:
        entry["scientific_acceptance"] = True
    with pytest.raises(table_contract.SourceExpressionContractError, match=reason):
        table_contract.compile_package(package)


def test_passage_profile_remains_closed_to_table_packages_and_pre_value_units():
    package = actual_table_package()
    with pytest.raises(passage.SourceExpressionContractError):
        passage.compile_package(package)
    package["version"], package["profile"] = passage.VERSION, passage.PROFILE
    for entry in package["expressions"]:
        del entry["table_binding"]
        entry["profile"] = passage.PROFILE
    with pytest.raises(passage.SourceExpressionContractError, match="unit_after_amount"):
        passage.compile_package(package)


def test_exact_formula_headers_only_without_refined_or_cited_composition_inference():
    capture = json.loads((ROOT / "docs/data/materials-thermal-table-capture-2026-10-05.json").read_text())
    metadata = actual_table_package()["source"]
    for formula in ("Mo5P1.07B1.93", "Mo5P0.9B2.1", "Mo5SiB2", "W5SiB2"):
        with pytest.raises(Exception, match="exact_column_candidates"):
            prepare_table_package(capture, formulas=[formula], source_metadata=metadata)
    with pytest.raises(Exception, match="source_declarations_changed"):
        prepare_table_package(capture, formulas=["Mo5PB2"], source_metadata={**metadata, "url": "https://example.org/other-paper"})
