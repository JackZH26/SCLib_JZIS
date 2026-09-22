"""Synthetic SC11 contracts: no scientific acceptance or real-paper claims."""
from copy import deepcopy
from pathlib import Path

import pytest

from services.structure_evidence import (
    MAX_SOURCE_CHARS,
    STRUCTURE_EVIDENCE_FIELDS,
    STRUCTURE_EVIDENCE_VERSION,
    annotate_structure_records,
    build_structure_evidence,
)


def _record(**extra):
    return {"formula": "H3S", "paper_id": "synthetic:sc11", "space_group": "Im-3m", **extra}


def _annotated(record, body=None):
    return annotate_structure_records([record], body=body if body is not None else record.get("evidence_text", ""), paper_id="synthetic:sc11")[0]


def _build(records, **extra):
    return build_structure_evidence(records, scope_id="synthetic:material", **extra)


def test_mirror_bytes_are_identical():
    root = Path(__file__).resolve().parents[2]
    assert (root / "api/services/structure_evidence.py").read_bytes() == (root / "ingestion/ingestion/structure_evidence.py").read_bytes()


def test_literal_local_text_remains_pending_and_not_coordinates():
    quote = "H3S adopts Im-3m at 150 GPa."
    raw = _record(evidence_text=quote, pressure_gpa=150)
    annotated = _annotated(raw)
    proposal = annotated["structure_evidence"]["proposals"][0]
    assert proposal["association"] == "literal_local"
    assert proposal["status"] == "pending" and proposal["scientific_acceptance"] is False
    assert proposal["coordinate_artifact_id"] is None
    locator = proposal["evidence"]["locator"]
    assert quote[locator["start"]:locator["end"]] == proposal["evidence"]["text"]
    result = _build([annotated])
    assert result["properties"]["space_group"]["status"] == "pending"
    assert result["properties"]["space_group"]["value"] is None
    assert all(p["evidence"]["verification"] == "not_rechecked_against_source" for p in result["proposals"])
    assert all(p["evidence"]["text"] is None for p in result["proposals"])
    assert all(p["evidence"]["excerpt_status"] == "withheld_pending_source_permission" for p in result["proposals"])


def test_one_phase_never_broadcast_to_a_second_material():
    body = "H3S adopts Im-3m at 150 GPa. MgB2 was also studied."
    records = [_record(evidence_text="H3S adopts Im-3m at 150 GPa.", pressure_gpa=150), {"formula": "MgB2"}]
    result = annotate_structure_records(records, body=body, paper_id="synthetic:sc11")
    assert result[0]["structure_evidence"]["proposals"][0]["association"] == "literal_local"
    assert not result[1]["structure_evidence"]["proposals"]
    assert "space_group" not in result[1]


def test_pressure_transition_retains_separate_source_bound_proposals():
    first = _record(evidence_text="H3S adopts Im-3m at 150 GPa.", pressure_gpa=150)
    second = _record(space_group="R3m", evidence_text="H3S adopts R3m at 100 GPa.", pressure_gpa=100)
    body = first["evidence_text"] + " " + second["evidence_text"]
    records = annotate_structure_records([first, second], body=body, paper_id="synthetic:sc11")
    proposals = [r["structure_evidence"]["proposals"][0] for r in records]
    assert {p["subject"]["pressure"]["value"] for p in proposals} == {100, 150}
    assert len({p["proposal_id"] for p in proposals}) == 2
    assert all(p["association"] == "literal_local" and p["status"] == "pending" for p in proposals)


@pytest.mark.parametrize("quote, extra", [
    ("H3S does not adopt Im-3m at 150 GPa.", {}),
    ("H3S possibly adopts Im-3m at 150 GPa.", {}),
    ("H3S adopts Im-3m at 150 GPa [12].", {}),
    ("H3S adopts Im-3m at 150 GPa.", {"evidence_type": "cited"}),
    ("H3S adopts Im-3m at 100 GPa.", {}),
    ("H3S adopts Im-3m between 100 GPa and 150 GPa.", {}),
    ("H3S adopts Im-3m at 150 GPa.", {"sample_id": "sample-B"}),
    ("H3S adopts Im-3m at 150 GPa for x=0.1.", {"doping_level": 0.2}),
    ("H3S adopts Im-3m at 150 GPa. This assignment is disputed.", {}),
])
def test_ambiguous_cited_negative_or_wrong_state_never_literal_linked(quote, extra):
    proposal = _annotated(_record(evidence_text=quote, pressure_gpa=150, **extra))["structure_evidence"]["proposals"][0]
    assert proposal["association"] != "literal_local"
    assert proposal["status"] == "pending"


def test_multiple_material_quote_is_unresolved_even_if_structure_token_present():
    quote = "H3S and MgB2 have Im-3m structures."
    rows = annotate_structure_records([_record(evidence_text=quote), {"formula": "MgB2"}], body=quote, paper_id="synthetic:sc11")
    assert "multiple_materials_in_local_span" in rows[0]["structure_evidence"]["proposals"][0]["reason_codes"]


def test_unknown_pressure_is_not_assigned_from_local_phrase():
    record = _annotated(_record(evidence_text="H3S adopts Im-3m at 150 GPa."))
    assert record["structure_evidence"]["proposals"][0]["association"] != "literal_local"
    assert "pressure_gpa" not in record


@pytest.mark.parametrize("body", ["The text does not contain the proposed quotation.", "H3S adopts Im-3m. H3S adopts Im-3m."])
def test_missing_or_repeated_quotation_does_not_get_a_verified_locator(body):
    proposal = _annotated(_record(evidence_text="H3S adopts Im-3m."), body)["structure_evidence"]["proposals"][0]
    assert proposal["evidence"]["locator"] is None
    assert proposal["association"] != "literal_local"


def test_content_hash_is_not_a_canonical_publication_revision():
    row = _annotated(_record(evidence_text="H3S adopts Im-3m."))
    source = row["structure_evidence"]["proposals"][0]["source"]
    assert len(source["content_sha256"]) == 64
    assert source["content_identity_basis"] == "assembled_ner_input_utf8"
    assert source["publication_revision"] is None and source["publication_revision_status"] == "unknown"


def test_unassigned_phase_mentions_and_aliases_do_not_create_properties():
    row = annotate_structure_records([{"formula": "MgB2"}], body="The YBCO reference has a 1212 phase.", paper_id="synthetic:sc11")[0]
    assert row["structure_evidence"]["unassigned_mentions"]
    assert not row["structure_evidence"]["proposals"]
    result = _build([row])
    assert result["unassigned_mentions"]
    assert all(p["status"] == "unknown" and p["value"] is None for p in result["properties"].values())
    mention = row["structure_evidence"]["unassigned_mentions"][0]
    assert "reference" in mention["evidence"]["text"]
    assert mention["evidence"]["mention_locator"] != mention["evidence"]["locator"]


def test_raw_and_typed_conflicts_remain_separate_pending_alternatives():
    row = _record(structure_claims=[{"field": "space_group", "value": "R3m", "evidence_text": "H3S adopts R3m."}])
    result = _annotated(row)
    proposals = result["structure_evidence"]["proposals"]
    assert {p["value"] for p in proposals} == {"R3m", "Im-3m"}
    assert all(p["association"] == "conflicted" for p in proposals)


def test_annotation_and_projection_preserve_input_and_are_idempotent():
    rows = [_record(evidence_text="H3S adopts Im-3m."), _record(space_group="R3m")]
    original = deepcopy(rows)
    annotated = annotate_structure_records(rows, body="H3S adopts Im-3m.", paper_id="synthetic:sc11")
    assert rows == original
    assert annotate_structure_records(annotated, body="H3S adopts Im-3m.", paper_id="synthetic:sc11") == annotated
    assert _build(annotated) == _build(list(reversed(annotated)))
    before = deepcopy(annotated)
    _build(annotated)
    assert annotated == before


def test_forged_stored_approval_ids_and_private_fields_are_never_trusted():
    row = _annotated(_record(evidence_text="H3S adopts Im-3m."))
    item = row["structure_evidence"]["proposals"][0]
    item.update(status="accepted", proposal_id="forged-accepted-id", scientific_acceptance=True, reviewer_email="private@example.invalid")
    item["source"]["content_sha256"] = "bad-hash"
    item["evidence"]["locator"] = {"kind": "assembled_text_char_span", "start": -1, "end": 300}
    result = _build([row])
    assert "private@example.invalid" not in str(result) and "forged-accepted-id" not in str(result)
    assert result["scientific_acceptance"] is False
    assert all(p["status"] == "pending" and p["coordinate_artifact_id"] is None for p in result["proposals"])


def test_legacy_broadcast_label_is_preserved_only_as_unlinked_pending_channel():
    row = {"formula": "MgB2", "structure_phase": "1212", "raw_extraction": {"formula": "MgB2"}}
    report = _build([row])
    assert report["properties"]["structure_phase"]["status"] == "pending"
    assert any("legacy_normalized_channel_unlinked_to_original_extraction" in p["reason_codes"] for p in report["proposals"])
    assert all(p["association"] == "unassigned" for p in report["proposals"])


def test_mismatched_stored_source_subject_and_value_are_not_rebound():
    row = _annotated(_record(evidence_text="H3S adopts Im-3m."))
    item = row["structure_evidence"]["proposals"][0]
    item["subject"]["formula"] = "MgB2"
    item["source"]["paper_id"] = "synthetic:other-paper"
    item["value"] = "R3m"
    report = _build([row])
    item = next(p for p in report["proposals"] if p["value"] == "R3m")
    assert item["subject"]["formula"] == "MgB2"
    assert item["association"] == "unassigned"
    assert {"stored_annotation_source_mismatch", "stored_annotation_subject_mismatch", "stored_annotation_value_mismatch"} <= set(item["reason_codes"])


def test_all_public_quote_paths_are_withheld_even_when_source_is_active():
    quote = "H3S adopts Im-3m; the YBCO reference has a 1212 phase."
    row = _annotated(_record(evidence_text=quote))
    report = _build([row], source_statuses={"synthetic:sc11": "active"})
    assert quote not in str(report)
    for item in report["proposals"] + report["unassigned_mentions"]:
        assert item["evidence"]["text"] is None
        assert item["evidence"]["excerpt_status"] == "withheld_pending_source_permission"
        assert len(item["evidence"]["text_sha256"]) == 64
    assert row["structure_evidence"]["proposals"][0]["evidence"]["text"] == quote


@pytest.mark.parametrize("records", [None, {}, [None], [{"structure_claims": {}}], [{"structure_claims": [None, {"field": []}]}]])
def test_malformed_inputs_fail_closed_without_crashing(records):
    result = _build(records)
    assert result["coverage"]["assessment_complete"] is False
    assert all(p["value"] is None for p in result["properties"].values())


def test_oversized_source_scope_is_explicit_and_does_not_literal_link():
    row = _annotated(_record(evidence_text="H3S adopts Im-3m."), "H3S adopts Im-3m." + " " * MAX_SOURCE_CHARS)
    assert row["structure_evidence"]["assessment_complete"] is False
    assert row["structure_evidence"]["proposals"][0]["association"] != "literal_local"


@pytest.mark.parametrize("state", ["retracted", "pending", None, {}, []])
def test_current_source_holds_remain_visible_in_pending_proposals(state):
    report = _build([_record()], source_statuses={"synthetic:sc11": state})
    assert "current_source_status_unresolved_or_held" in report["warnings"]
    assert report["properties"]["space_group"]["value"] is None


def test_empty_contract_and_unknown_states_are_explicit():
    report = _build([])
    assert report["version"] == STRUCTURE_EVIDENCE_VERSION
    assert set(report["properties"]) == set(STRUCTURE_EVIDENCE_FIELDS)
    assert report["coordinate_status"] == "not_validated"
    assert report["coverage"]["assessment_complete"] is True
