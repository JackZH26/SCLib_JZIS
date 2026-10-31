"""Sample-level source checks must not inflate errors or accept invented quotes."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("materials_canary", Path(__file__).parents[1] / "materials_ner_canary_gate.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def fixture():
    quote = "Parts of Film A contain (La, Pr)2NiO4 monolayer intergrowths."
    check = {"id": "phase-scope", "kind": "component_formula_not_sample_identity",
        "work_id": "synthetic:source", "bundle_sha256": "frozen", "sample_label": "Film A",
        "component_formula_raw": "(La, Pr)2NiO4", "evidence": {"block_id": "b1",
        "start_char": 0, "end_char": len(quote), "quote": quote, "quote_sha256": module.sha(quote.encode())}}
    sample = {"id": "A", "label": "Film A", "formula_raw": "La2PrNi2O7",
              "additional_formula_assertions": [{"formula_raw": "(La,Pr)2NiO4"}]}
    rows = [{"row_id": str(i), "work_id": "synthetic:source", "bundle_sha256": "frozen", "sample": sample} for i in range(3)]
    bundles = {("synthetic:source", "frozen"): {"blocks": [{"id": "b1", "text": quote}]}}
    return rows, check, bundles


def test_shared_sample_is_one_finding_with_all_affected_rows():
    rows, check, bundles = fixture()
    findings = module.scoped_formula_hazards(rows, [check], bundles)
    assert len(findings) == 1 and findings[0]["affected_row_ids"] == ["0", "1", "2"]
    assert not findings[0]["independently_reviewed"]


def test_unrelated_source_or_correctly_scoped_parent_formula_is_not_flagged():
    rows, check, bundles = fixture()
    rows[0] = deepcopy(rows[0]); rows[0]["work_id"] = "synthetic:another"
    rows[1]["sample"]["additional_formula_assertions"] = []
    assert module.scoped_formula_hazards(rows, [check], bundles) == []


@pytest.mark.parametrize("mutation", ["quote", "offset", "hash", "bundle", "kind"])
def test_unlocated_or_unsupported_reference_cannot_create_a_semantic_finding(mutation):
    rows, check, bundles = fixture()
    if mutation == "quote": check["evidence"]["quote"] = "Invented phase claim"
    if mutation == "offset": check["evidence"]["end_char"] -= 1
    if mutation == "hash": check["evidence"]["quote_sha256"] = "0" * 64
    if mutation == "bundle": check["bundle_sha256"] = "other"
    if mutation == "kind": check["kind"] = "infer_phase_from_name"
    with pytest.raises(ValueError): module.scoped_formula_hazards(rows, [check], bundles)
