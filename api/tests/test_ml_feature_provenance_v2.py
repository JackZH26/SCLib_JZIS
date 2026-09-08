"""Small deterministic guards supplement the actual SQL compiler regressions."""
from types import SimpleNamespace

import pytest

from services.ml_dataset_builder_v2 import _target_ancestry
from services.ml_feature_provenance_v2 import (
    INPUT_VERSION,
    OUTPUT_VERSION,
    _number,
    computed_lineage,
)
from services.research_release_manifest import canonical, digest


@pytest.mark.parametrize("value", [True, False, None, "0", float("inf"), float("nan"), 10**1000, -(10**1000)])
def test_condition_numbers_fail_closed_without_overflow(value):
    assert _number(value) is False


@pytest.mark.parametrize("kind", ["tc", "non_transition"])
def test_all_superconductivity_outcomes_are_target_ancestry(kind):
    claim, feature = ("material_claims", "outcome"), ("event_properties", "feature")
    nodes = {claim: SimpleNamespace(result_data={"property_type": kind}),
             feature: SimpleNamespace(result_data={"property_key": "dos_at_fermi"})}
    assert _target_ancestry(feature, {claim: set(), feature: {claim}}, nodes)


@pytest.mark.parametrize("change", ["structure", "run", "target_flag", "invalid_extra_reference", "output"])
def test_resolvable_manifest_relations_survive_other_admission_failure(change):
    index, artifacts = {}, {}

    def row(table, identifier, value):
        body = {"id": identifier, **value}
        index[(table, identifier)] = {"data": body, "row_sha256": digest(body)}

    def artifact(identifier, version, document):
        payload = canonical(document)
        sha = digest(document)
        artifacts[sha] = payload
        row("evidence_artifacts", identifier, {"kind": "run_manifest", "schema_version": version,
            "hash_status": "verified", "record_sha256": sha, "bytes_sha256": sha})

    row("event_properties", "feature", {"event_id": "event"})
    row("research_events", "event", {"producer_run_id": "run", "structure_id": "structure"})
    row("research_runs", "run", {"run_kind": "dft", "status": "completed", "parent_run_id": None,
        "input_manifest_id": "input", "output_manifest_id": "output"})
    row("structure_records", "structure", {})
    row("material_claims", "outcome", {"property_type": "non_transition"})
    dependency = {"table": "material_claims", "row_id": "outcome", "row_sha256": index[("material_claims", "outcome")]["row_sha256"]}
    source = {"version": INPUT_VERSION, "run_id": "run", "structure_id": "structure",
        "structure_row_sha256": index[("structure_records", "structure")]["row_sha256"],
        "normal_state": True, "target_data_used": False, "dependency_results": [dependency]}
    output = {"version": OUTPUT_VERSION, "run_id": "run", "result_refs": [
        {"table": "event_properties", "row_id": "feature", "row_sha256": index[("event_properties", "feature")]["row_sha256"]}]}
    if change == "structure": source["structure_row_sha256"] = "f" * 64
    elif change == "run": source["run_id"] = "wrong-run"
    elif change == "target_flag": source["target_data_used"] = True
    elif change == "invalid_extra_reference": source["dependency_results"].append({"invalid": True})
    else: output["result_refs"] = []
    artifact("input", INPUT_VERSION, source)
    artifact("output", OUTPUT_VERSION, output)
    result = computed_lineage(index, artifacts, ("event_properties", "feature"))
    assert result["dependencies"] == [("material_claims", "outcome")]
    assert result["reason_codes"] == ["computed_run_manifest_unresolved"]
