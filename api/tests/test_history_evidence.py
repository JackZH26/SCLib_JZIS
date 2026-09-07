"""SC08 history projections preserve snapshots while checking live metadata."""
from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import AskHistory, Material, Paper, get_engine
from services.history_evidence import current_history_evidence

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    async with AsyncSession(get_engine().execution_options(isolation_level="REPEATABLE READ"), expire_on_commit=False) as session:
        yield session


async def _saved(db, user, *, records=None):
    key = uuid4().hex
    paper = Paper(id="arxiv:history-" + key, source="arxiv", title="Historical source",
                  authors=[], abstract="Historical abstract.", status="published", materials_extracted=records or [])
    saved = [{"index": 1, "paper_id": paper.id, "title": "Original title",
              "source_visibility": {"source_status": "active", "reported_claim_filter_eligible": True},
              "material_evidence": [{"formula": "Nb"}]}]
    history = AskHistory(user_id=user.id, question="What was reported?", answer="Saved report [1].",
                         sources=deepcopy(saved), latency_ms=12, language="en")
    db.add_all([paper, history])
    await db.commit()
    return paper, history, saved


@pytest.mark.parametrize("status", ["retracted", "corrected", "disputed"])
async def test_history_reads_live_source_holds_without_rewriting_saved_answer(client, db_session, registered_user, status):
    user, token = registered_user
    paper, history, saved = await _saved(db_session, user)
    headers = {"Authorization": "Bearer " + token}
    initial = await client.get("/v1/history", headers=headers)
    assert initial.status_code == 200, initial.text
    assert initial.json()["results"][0]["current_evidence"]["sources"][0]["source_visibility"]["source_status"] == "active"
    paper.status = status
    await db_session.commit()
    for _ in range(2):
        response = await client.get("/v1/history", headers={**headers, "If-None-Match": '"old"'})
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
        entry = response.json()["results"][0]
        assert entry["answer"] == "Saved report [1]." and entry["sources"] == saved
        current = entry["current_evidence"]
        assert current["scope"] == "current_paper_metadata_not_saved_excerpt"
        assert current["saved_answer_revalidated"] is False
        assert current["scientific_acceptance"] is False
        assert current["ml_training_eligibility_established"] is False
        assert current["sources"][0]["source_visibility"]["source_status"] == status
        assert not current["sources"][0]["source_visibility"]["reported_claim_filter_eligible"]
    await db_session.refresh(history)
    assert history.sources == saved and history.answer == "Saved report [1]."


async def test_history_current_occurrences_use_explicit_links_and_live_parent_holds(client, db_session, registered_user):
    user, token = registered_user
    key = uuid4().hex
    parent = Material(id="parent:" + key, formula="Nb", formula_normalized="parent" + key,
                      needs_review=False, total_papers=1, records=[])
    child = Material(id="child:" + key, formula="Nb", formula_normalized="child" + key,
                     parent_material_id=parent.id, needs_review=False, total_papers=1, records=[])
    db_session.add_all([parent, child])
    paper, history, saved = await _saved(db_session, user, records=[
        {"material_id": child.id, "formula": "Nb", "tc_kelvin": 9.2},
        {"formula": "Nb", "tc_kelvin": 9.2},
    ])
    parent.review_reason = "provenance_quarantine_synthetic"
    await db_session.commit()
    response = await client.get("/v1/history", headers={"Authorization": "Bearer " + token})
    assert response.status_code == 200, response.text
    row = response.json()["results"][0]
    assert row["sources"] == saved
    evidence = row["current_evidence"]["sources"][0]
    assert evidence["source_visibility"]["source_status"] == "active"
    assert evidence["occurrence_visibility_summary"]["state_counts"] == {"quarantined": 1, "unknown": 1}
    assert evidence["occurrence_visibility_summary"]["omitted_occurrences"] == 1
    assert "material_evidence" not in evidence  # counts only, not repeated scientific records
    assert row["current_evidence"]["saved_answer_revalidated"] is False
    await db_session.refresh(history)
    assert history.sources == saved


async def test_missing_legacy_citation_is_unavailable_not_implicitly_active(db_session):
    row = SimpleNamespace(id=uuid4(), sources=[{"paper_id": "arxiv:missing-history"}, {"title": "No identity"}])
    current = (await current_history_evidence(db_session, [row]))[row.id]
    assert len(current["sources"]) == 2
    for source in current["sources"]:
        assert source["metadata_status"] == "unavailable"
        assert not source["source_visibility"]["reported_claim_filter_eligible"]
        assert "material_evidence" not in source


@pytest.mark.parametrize("records", [[{}] * 201, {"not": "an occurrence array"}])
async def test_oversized_or_malformed_current_inventory_is_incomplete_not_truncated(db_session, registered_user, records):
    user, _ = registered_user
    paper, history, _ = await _saved(db_session, user, records=records)
    current = (await current_history_evidence(db_session, [history]))[history.id]
    assert current["sources"][0]["metadata_status"] == "incomplete"
    assert "material_evidence" not in current["sources"][0]
    assert current["sources"][0]["occurrence_visibility_summary"] is None
    assert current["saved_answer_revalidated"] is False


async def test_saved_source_budget_is_explicit_and_empty_history_is_safe(db_session):
    row = SimpleNamespace(id=uuid4(), sources=[{"title": "Legacy citation"}] * 51)
    current = (await current_history_evidence(db_session, [row]))[row.id]
    assert len(current["sources"]) == 50
    assert "saved_source_inventory_truncated" in current["warning_codes"]
    assert await current_history_evidence(db_session, []) == {}


async def test_oversized_linked_material_does_not_load_full_rows_or_restore_occurrences(db_session, registered_user, monkeypatch):
    user, _ = registered_user
    key = uuid4().hex
    material = Material(id="oversized:" + key, formula="Nb", formula_normalized="oversized" + key,
                        total_papers=1, needs_review=False, records=[{"paper_id": "x", "note": "x" * 2048}])
    db_session.add(material)
    _, history, _ = await _saved(db_session, user, records=[
        {"material_id": material.id, "formula": "Nb"}, {"formula": "Nb"},
    ])
    monkeypatch.setattr("services.history_evidence.MAX_MATERIAL_BYTES", 1024)
    async def unexpected(*_args, **_kwargs):
        raise AssertionError("oversized full material rows must not be loaded")
    monkeypatch.setattr("services.history_evidence.resolve_explicit_materials", unexpected)
    current = (await current_history_evidence(db_session, [history]))[history.id]
    source = current["sources"][0]
    assert source["metadata_status"] == "incomplete"
    assert "material_evidence" not in source
    assert source["occurrence_visibility_summary"] is None
    assert not source["source_visibility"]["reported_claim_filter_eligible"]
    assert "current_explicit_material_inventory_unavailable" in source["warning_codes"]


async def test_unknown_source_cannot_export_nested_unlinked_eligibility(db_session, registered_user):
    user, _ = registered_user
    key = uuid4().hex
    material = Material(id="unknown:" + key, formula="Nb", formula_normalized="unknown" + key,
                        total_papers=1, needs_review=False, records=[])
    db_session.add(material)
    paper, history, _ = await _saved(db_session, user, records=[
        {"material_id": material.id, "formula": "Nb"}, {"formula": "Nb"},
    ])
    paper.status = "unrecognized"
    await db_session.commit()
    source = (await current_history_evidence(db_session, [history]))[history.id]["sources"][0]
    assert source["metadata_status"] == "incomplete"
    assert not source["source_visibility"]["reported_claim_filter_eligible"]
    assert source["occurrence_visibility_summary"] is None
    assert "material_evidence" not in source
    assert "current_source_status_unresolved" in source["warning_codes"]


async def test_repeated_saved_entries_count_toward_serialized_output_budget(db_session, registered_user, monkeypatch):
    user, _ = registered_user
    paper, history, saved = await _saved(db_session, user, records=[{"formula": "Nb", "tc_kelvin": 9.2}] * 50)
    rows = [SimpleNamespace(id=uuid4(), sources=deepcopy(saved) * 50) for _ in range(200)]
    originals = deepcopy([row.sources for row in rows])
    budget = 128 * 1024
    monkeypatch.setattr("services.history_evidence.MAX_CURRENT_EVIDENCE_BYTES", budget)
    current = await current_history_evidence(db_session, rows)
    wire = json.dumps(list(current.values()), ensure_ascii=False, separators=(",", ":")).encode()
    assert len(wire) <= budget
    assert any("current_evidence_output_budget_exhausted" in row["warning_codes"] for row in current.values())
    assert sum(len(row["sources"]) for row in current.values()) < 10000
    assert all("material_evidence" not in source for row in current.values() for source in row["sources"])
    assert [row.sources for row in rows] == originals
    await db_session.refresh(history)
    assert history.sources == saved


async def test_history_remains_owner_private(client, db_session, registered_user):
    user, token = registered_user
    await _saved(db_session, user)
    anonymous = await client.get("/v1/history")
    assert anonymous.status_code == 401
    assert "no-store" in anonymous.headers["cache-control"]
    bad_page = await client.get("/v1/history?limit=201", headers={"Authorization": "Bearer " + token})
    assert bad_page.status_code == 422
    assert "no-store" in bad_page.headers["cache-control"]
