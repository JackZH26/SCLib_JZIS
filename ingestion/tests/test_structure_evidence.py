"""Synthetic SC11 normalization/aggregation; no cloud or scientific approval."""
from copy import deepcopy
from uuid import UUID

from ingestion.claims.mapper import map_record_to_claim
from ingestion.extract.material_ner import normalize_material_records
from ingestion.extract.materials_aggregator import _derive_summary
from ingestion.structure_evidence import build_structure_evidence


def test_ner_no_longer_broadcasts_a_paper_phase_to_other_materials():
    raw = [{"formula": "La3Ni2O7", "structure_phase": "1212", "evidence_text": "La3Ni2O7 has a 1212 phase."}, {"formula": "MgB2"}]
    before = deepcopy(raw)
    result = normalize_material_records(raw, paper_type="experimental", body="La3Ni2O7 has a 1212 phase. MgB2 was a reference.", paper_id="synthetic:sc11")
    assert raw == before
    assert result[0]["raw_extraction"] == raw[0]
    assert result[0]["structure_phase"] == "1212"
    assert "structure_phase" not in result[1]
    assert not result[1]["structure_evidence"]["proposals"]
    assert result[1]["structure_evidence"]["unassigned_mentions"]


def test_raw_ner_structure_values_stay_unchanged_while_summary_aliases_are_pending():
    raw = {"formula": "H3S", "tc_kelvin": "100 K", "space_group": "Im-3m", "structure_phase": "sample phase", "crystal_structure": "cubic",
           "evidence_text": "H3S adopts Im-3m.", "paper_id": "synthetic:sc11", "pressure_gpa": 150,
           "evidence_type": "primary_experimental", "measurement": "resistivity"}
    records = normalize_material_records([raw], paper_type="experimental", body=raw["evidence_text"], paper_id="synthetic:sc11")
    records[0]["paper_id"] = "synthetic:sc11"
    before = deepcopy(records)
    summary = _derive_summary("H3S", records)
    assert records == before
    assert records[0]["raw_extraction"] == raw
    assert summary["tc_max"] == 100
    for field in ("structure_phase", "space_group", "crystal_structure"):
        assert summary[field] is None
        assert records[0][field] == raw[field]


def test_structure_annotation_and_public_redaction_do_not_mint_new_typed_claims():
    raw = {"formula": "MgB2", "tc_kelvin": 39, "paper_id": "synthetic:sc11-claim", "space_group": "P6/mmm"}
    snapshot = UUID("11111111-1111-4111-8111-111111111111")
    def claim(record):
        return map_record_to_claim(record, material_id="mat:synthetic", source_snapshot_id=snapshot)
    original = claim(raw)
    for annotation in ({"proposals": [{"evidence": {"text": "private bounded source excerpt"}}]},
                       build_structure_evidence([raw], scope_id="mat:synthetic")):
        changed = claim({**raw, "structure_evidence": annotation})
        assert changed["id"] == original["id"]
        assert changed["source_record_hash"] == original["source_record_hash"]
        assert changed["semantic_fingerprint"] == original["semantic_fingerprint"]
    source_changed = claim({**raw, "structure_claims": [{"field": "space_group", "value": "P1"}]})
    assert source_changed["id"] != original["id"]
    assert source_changed["source_record_hash"] != original["source_record_hash"]
