"""SC11 derived annotations are not new original scientific occurrences."""
from copy import deepcopy
from pathlib import Path

import pytest

from services.anomaly_review import assess_record_anomalies
from services.material_semantics import build_material_semantics
from services.property_evidence import legacy_result_id
from services.scientific_filters import ResultFilters, matching_result_references
from services.structure_evidence import annotate_structure_records, build_structure_evidence
from services.timeline_points import extract_timeline_points


def _record():
    return {"formula": "MgB2", "tc_kelvin": 39, "year": 2025, "pressure_gpa": 1,
            "paper_id": "synthetic:sc11-id", "evidence_type": "primary_experimental",
            "measurement": "resistivity", "is_unconventional": True,
            "space_group": "P6/mmm", "evidence_text": "MgB2 adopts P6/mmm at 1 GPa."}


def _identities(record):
    scope = "mat:synthetic-structure-id"
    matches = matching_result_references([record], ResultFilters(tc_min=20), scope_id=scope, current_year=2026)
    semantics = build_material_semantics([record], scope_id=scope)
    timeline = extract_timeline_points(scope, [record], {}, current_year=2026)
    return {
        "property": legacy_result_id(record, scope_id=scope),
        "filter": matches[0]["result_id"],
        "anomaly": assess_record_anomalies(record, scope_id=scope, current_year=2026)["result_id"],
        "semantics": semantics["properties"]["is_unconventional"]["evidence"][0]["occurrence_id"],
        "timeline": timeline[0].id,
    }


@pytest.mark.parametrize("annotation", [
    {},
    {"version": "structure-evidence/1.0.0", "proposals": [{"evidence": {"text": "source quote"}, "status": "pending"}]},
    {"version": "structure-evidence/1.0.0", "proposals": [{"evidence": {"text": None, "excerpt_status": "withheld_pending_source_permission"}}]},
    {"version": "future-version", "proposals": [{"scientific_acceptance": True}]},
    ["malformed-derived-envelope"],
])
@pytest.mark.parametrize("key", ["structure_evidence", "ingestion_capture", "temporal_provenance"])
def test_annotation_only_changes_preserve_all_original_identity_paths(annotation, key):
    record = _record()
    assert _identities({**record, key: annotation}) == _identities(record)


def test_real_extraction_annotation_and_public_redaction_preserve_identity():
    record = _record()
    annotated = annotate_structure_records([record], body=record["evidence_text"], paper_id=record["paper_id"])[0]
    public = {**record, "structure_evidence": build_structure_evidence([annotated], scope_id="mat:synthetic-structure-id")}
    assert _identities(annotated) == _identities(public) == _identities(record)
    assert record == _record()


@pytest.mark.parametrize("change", [
    {"space_group": "P1"},
    {"structure_claims": [{"field": "space_group", "value": "P1", "evidence_text": "MgB2 adopts P1."}]},
    {"tc_kelvin": 40},
])
def test_original_scientific_fields_and_structure_claims_still_change_identity(change):
    original = _identities(_record())
    changed = _identities({**_record(), **deepcopy(change)})
    assert all(changed[key] != original[key] for key in original)


def test_updated_shared_identity_modules_still_match_ingestion_bytes():
    root = Path(__file__).resolve().parents[2]
    for filename in ("property_evidence.py", "material_semantics.py", "structure_evidence.py"):
        assert (root / "api/services" / filename).read_bytes() == (root / "ingestion/ingestion" / filename).read_bytes()
