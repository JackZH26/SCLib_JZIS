"""SC07: source reports are not catalogue approvals; no formula-based joins."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from models.db import Chunk, Material, Paper
from routers.search import _best_tc
from services import provider_resilience, rag, retrieval
from services.material_visibility import MATERIAL_VISIBILITY_VERSION
from services.scientific_filters import ResultFilters, matching_result_references
from services.source_visibility import (
    citation_evidence,
    occurrence_visibility,
    project_source_occurrences,
    source_visibility,
)


def _linked(state="catalogue"):
    return {"version": MATERIAL_VISIBILITY_VERSION, "state": state,
            "public_catalogue_eligible": state == "catalogue", "archive_available": state != "quarantined",
            "reason_codes": [], "warning_codes": [], "review_revision": "a" * 64}


def test_unlinked_report_can_match_but_is_not_a_catalogue_claim():
    actual = occurrence_visibility({"formula": "MgB2", "visibility": _linked()}, paper_status="published")
    assert actual["state"] == "unknown"
    assert actual["material_link_status"] == "unlinked"
    assert actual["reported_claim_filter_eligible"] is True
    assert actual["public_catalogue_eligible"] is False
    assert actual["scientific_acceptance"] is False


@pytest.mark.parametrize("material_id", ["missing-material", "", True, {"id": "m"}, "x" * 101])
def test_explicit_unresolved_identity_cannot_bypass_unknown_provenance_restrictions(material_id):
    actual = occurrence_visibility({"material_id": material_id, "formula": "MgB2"}, paper_status="published")
    assert actual["material_link_status"] == "unresolved"
    assert not actual["reported_claim_filter_eligible"]
    assert not actual["archive_available"]
    projected, summary = project_source_occurrences([{"material_id": material_id}], paper_status="published", linked_materials={})
    assert projected == [] and summary["omitted_occurrences"] == 1


@pytest.mark.parametrize("field,value", [("needs_review", "false"), ("disputed", "true"), ("retracted", 0),
                                        ("corrected", []), ("review_status", {}), ("review_reason", 1),
                                        ("source_status", ["published"]), ("provenance_status", True)])
def test_malformed_explicit_governance_is_pending_not_source_eligible(field, value):
    actual = occurrence_visibility({field: value}, paper_status="published")
    assert actual["state"] == "pending"
    assert actual["archive_available"]
    assert not actual["reported_claim_filter_eligible"]
    assert "occurrence_review_metadata_invalid" in actual["reason_codes"]


def test_untrusted_rag_records_cannot_inject_visibility_or_reviewer_payloads():
    malicious = {"formula": "MgB2", "visibility": {**_linked(), "private_reviewer_email": "not-public@example.test"}}
    assert "visibility" not in citation_evidence([malicious])[0]
    source = rag.RagSourceInput(1, "p", "Paper", "A", 2026, "Abstract", "A report", material_evidence=[malicious])
    prompt = rag.build_user_prompt("What is reported?", [source])
    assert "not-public@example.test" not in prompt


def test_tc_sort_cannot_promote_anomalous_value_from_a_family_only_match():
    matches = matching_result_references([{"formula": "X", "family": "mgb2", "tc_kelvin": 900}],
                                        ResultFilters(families=("mgb2",)), scope_id="synthetic")
    assert matches  # a family-only source-report match, not a Tc acceptance
    assert _best_tc(SimpleNamespace(matching_results=matches)) == 0


@pytest.mark.parametrize("state", ["pending", "disputed", "corrected", "retracted", "quarantined", "unknown"])
def test_linked_holds_cannot_satisfy_report_filters(state):
    actual = occurrence_visibility({"material_id": "m"}, paper_status="published", linked_visibility=_linked(state))
    assert not actual["reported_claim_filter_eligible"]
    assert not actual["public_catalogue_eligible"]
    assert actual["archive_available"] == (state != "quarantined")


@pytest.mark.parametrize("status", ["retracted", "withdrawn", "corrected", "disputed"])
def test_lifecycle_holds_preserve_bibliography_not_scientific_eligibility(status):
    actual = source_visibility(status)
    assert actual["bibliography_available"]
    assert not actual["reported_claim_filter_eligible"]
    assert actual["warning_codes"]
    assert not occurrence_visibility({}, paper_status=status)["reported_claim_filter_eligible"]


@pytest.mark.parametrize("hold", [{"needs_review": True}, {"disputed": True}, {"retracted": True},
                                  {"review_status": "corrected"}, {"status": "withdrawn"},
                                  {"source_status": "retracted"}])
def test_record_holds_cannot_be_cleared_by_self_approval(hold):
    actual = occurrence_visibility({**hold, "reviewed": True, "material_id": "m", "visibility": _linked()},
                                   paper_status="published", linked_visibility=_linked())
    assert not actual["reported_claim_filter_eligible"]
    assert not actual["scientific_acceptance"]


def test_same_formula_does_not_inherit_material_identity_or_quarantine():
    records = [{"formula": "MgB2"}, {"formula": "MgB2", "material_id": "m"}]
    projected, summary = project_source_occurrences(records, paper_status="published", linked_materials={"m": _linked("quarantined")})
    assert len(projected) == 1 and projected[0]["visibility"]["material_link_status"] == "unlinked"
    assert summary["omitted_occurrences"] == 1
    assert records[0] == {"formula": "MgB2"}  # read-only projection


def test_public_source_occurrences_remove_private_review_metadata_after_assessment():
    record = {"formula": "MgB2", "tc_kelvin": 39, "review_reason": "A private reviewer note",
              "provenance": {"reviewer_email": "private@example.test", "paper_id": "p"}}
    projected, _ = project_source_occurrences([record], paper_status="published", linked_materials={})
    assert projected[0]["tc_kelvin"] == 39
    assert "private" not in json.dumps(projected)
    assert record["review_reason"] == "A private reviewer note"


@pytest.mark.parametrize("hold", [{"review_reason": "provenance_quarantine_other"}, {"status": "quarantined"},
                                  {"provenance_status": "quarantine"}])
def test_unlinked_occurrence_provenance_holds_omit_structured_raw(hold):
    projected, summary = project_source_occurrences([{"formula": "X", **hold}], paper_status="published", linked_materials={})
    assert projected == []
    assert summary["state_counts"] == {"quarantined": 1}


async def _seed(db_session, *, status="published"):
    suffix = uuid4().hex
    paper_id, material_id = f"arxiv:visibility-{suffix}", f"mat:visibility-{suffix}"
    records = [{"formula": "MgB2", "tc_kelvin": 39, "family": "mgb2", "material_id": material_id},
               {"formula": "MgB2", "tc_kelvin": 38, "family": "mgb2"}]
    paper = Paper(id=paper_id, source="arxiv", title="Source visibility MgB2", authors=[],
                  abstract="Preserved scientific bibliography.", status=status, materials_extracted=records)
    parent = Material(id=material_id + "parent", formula="MgB2", formula_normalized="MgB2-parent",
                      total_papers=1, needs_review=False, review_reason="provenance_quarantine_nims")
    child = Material(id=material_id, formula="MgB2", formula_normalized="MgB2-" + suffix,
                     total_papers=1, needs_review=False, parent_material_id=parent.id,
                     records=[{"paper_id": paper_id, "tc_kelvin": 39}])
    chunk = Chunk(id=paper_id + "-chunk", paper_id=paper_id, title=paper.title,
                  text="The source reports MgB2 superconductivity.", materials_mentioned=records)
    db_session.add_all([paper, parent, child, chunk])
    await db_session.commit()
    return paper_id, chunk.id


@pytest.mark.asyncio
async def test_paper_retains_bibliography_but_hides_explicit_parent_quarantine(client, db_session):
    paper_id, _ = await _seed(db_session, status="corrected")
    response = await client.get(f"/v1/paper/{paper_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["abstract"] == "Preserved scientific bibliography."
    assert body["source_visibility"]["source_status"] == "corrected"
    assert body["occurrence_visibility_summary"]["omitted_occurrences"] == 1
    assert len(body["materials_extracted"]) == 1
    assert body["materials_extracted"][0]["visibility"]["state"] == "corrected"


@pytest.mark.asyncio
async def test_search_keeps_unlinked_report_without_republishing_linked_quarantine(client, db_session, monkeypatch):
    paper_id, chunk_id = await _seed(db_session)
    provider_resilience.reset()
    monkeypatch.setattr("routers.search.vector_search.embed_query", lambda _: (_ for _ in ()).throw(RuntimeError("offline")))
    async def lexical(*_args, **_kwargs):
        return [retrieval.LexicalHit(chunk_id, 1.0)]
    monkeypatch.setattr("routers.search.retrieval.lexical_search", lexical)
    response = await client.post("/v1/search", json={"query": "MgB2 report", "filters": {"tc_min": 37}})
    assert response.status_code == 200, response.text
    body = response.json()["results"][0]
    assert body["paper_id"] == paper_id
    assert len(body["materials"]) == 1
    assert len(body["matching_results"]) == 1
    assert body["matching_results"][0]["record_index"] == 1
    assert not body["matching_results"][0]["visibility"]["public_catalogue_eligible"]
    provider_resilience.reset()


@pytest.mark.asyncio
async def test_corrected_paper_cannot_satisfy_scientific_filter_even_archive_optin(client, db_session, monkeypatch):
    _, chunk_id = await _seed(db_session, status="corrected")
    provider_resilience.reset()
    monkeypatch.setattr("routers.search.vector_search.embed_query", lambda _: (_ for _ in ()).throw(RuntimeError("offline")))
    async def lexical(*_args, **_kwargs):
        return [retrieval.LexicalHit(chunk_id, 1.0)]
    monkeypatch.setattr("routers.search.retrieval.lexical_search", lexical)
    response = await client.post("/v1/search", json={"query": "MgB2 report", "filters": {"tc_min": 37, "exclude_retracted": False}})
    assert response.status_code == 200 and response.json()["results"] == []
    bibliographic = await client.post("/v1/search", json={"query": "MgB2 report"})
    assert len(bibliographic.json()["results"]) == 1
    provider_resilience.reset()


@pytest.mark.asyncio
async def test_ask_does_not_restore_omitted_occurrences_and_passes_visibility_to_prompt(client, db_session, monkeypatch):
    _, chunk_id = await _seed(db_session)
    provider_resilience.reset()
    monkeypatch.setattr("routers.ask.vector_search.embed_query", lambda _: (_ for _ in ()).throw(RuntimeError("offline")))
    async def lexical(*_args, **_kwargs):
        return [retrieval.LexicalHit(chunk_id, 1.0)]
    monkeypatch.setattr("routers.ask.retrieval.lexical_search", lexical)
    captured = []
    def generate(question, sources, **_kwargs):
        captured.append(rag.build_user_prompt(question, sources))
        return rag.RagResult("The unreviewed source reports MgB2 [1].", 2, True, [])
    monkeypatch.setattr("routers.ask.rag.generate_answer", generate)
    response = await client.post("/v1/ask", json={"question": "MgB2 report"})
    assert response.status_code == 200, response.text
    source = response.json()["sources"][0]
    assert len(source["material_evidence"]) == 1
    assert source["material_evidence"][0]["visibility"]["material_link_status"] == "unlinked"
    assert "restricted_or_malformed_occurrences_omitted" in captured[0]
    assert "unlinked_unreviewed_occurrence" in captured[0]
    provider_resilience.reset()


def _audit_module():
    path = Path(__file__).resolve().parents[2] / "scripts/audit_source_visibility_snapshot.py"
    spec = importlib.util.spec_from_file_location("source_visibility_audit", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _governance(mid, **kwargs):
    return {"id": mid, "needs_review": False, "total_papers": 1, "review_reason": None,
            "status": "active", "disputed": False, "retracted": False, "family": None,
            "parent_material_id": None, "anomaly_context": {}, **kwargs}


def test_v1_export_without_governance_is_undetermined_not_reapproved():
    report = _audit_module().audit_snapshot([{"id": "m", "records": []}], [], evaluation_year=2026)
    assert report["state_counts"] == {"undetermined_missing_governance": 1}
    assert report["evaluated_materials"] == 0
    assert not report["ml_training_eligibility_established"]


def test_offline_audit_identifies_legacy_public_retracted_source_without_rewriting_input():
    materials = [{"id": "m", "records": [{"paper_id": "p", "tc_kelvin": 39}]}]
    original = json.dumps(materials)
    audit = _audit_module().audit_snapshot
    report = audit(materials, [{"id": "p", "status": "retracted"}], [_governance("m")], evaluation_year=2026)
    assert report["legacy_scope_transitions"] == {"legacy_true_to_catalogue_false": 1}
    assert report["state_counts"] == {"retracted": 1}
    assert report["database_writes"] == 0 and original == json.dumps(materials)
    assert report == audit(materials, [{"id": "p", "status": "retracted"}], [_governance("m")], evaluation_year=2026)


def test_offline_audit_preserves_parent_quarantine_and_hashes_diagnostic_identifiers():
    materials = [{"id": "private-parent", "records": []}, {"id": "child", "records": []}]
    report = _audit_module().audit_snapshot(materials, [], [
        _governance("private-parent", review_reason="provenance_quarantine_nims"),
        _governance("child", parent_material_id="private-parent"),
    ], evaluation_year=2026)
    assert report["state_counts"] == {"quarantined": 2}
    assert "private-parent" not in json.dumps(report)


def test_offline_audit_rejects_duplicate_identity_and_implicit_year():
    audit = _audit_module().audit_snapshot
    with pytest.raises(ValueError, match="unique"):
        audit([{"id": "m"}, {"id": "m"}], [], evaluation_year=2026)
    with pytest.raises(ValueError, match="evaluation_year"):
        audit([], [], evaluation_year=True)
