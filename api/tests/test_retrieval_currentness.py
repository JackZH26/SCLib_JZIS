"""RG02 post-generation checks on guarded native PostgreSQL, synthetic only."""
from __future__ import annotations

import asyncio
import threading
from copy import deepcopy
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from main import app
from models import get_db
from models.db import AskHistory, Chunk, Material, Paper, PaperWorkMap, Work, get_engine
from services import provider_resilience, rag, retrieval
from services import retrieval_currentness as currentness
from services.source_lifecycle import resolve_paper_lifecycle
from services.source_visibility import (
    project_source_occurrences,
    resolve_explicit_materials,
    source_visibility,
)


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    async with AsyncSession(get_engine(), expire_on_commit=False) as session:
        yield session


async def _seed(db, *, records=None):
    suffix = uuid4().hex
    paper = Paper(id="synthetic:rg02-current-" + suffix, source="arxiv", title="Synthetic currentness fixture",
                  authors=[], abstract="Synthetic only.", status="published", materials_extracted=[])
    chunk = Chunk(id=paper.id + "_chunk", paper=paper, title=paper.title, section="Results",
                  text="H3S has an observed Tc of 100 K at 2 GPa. OLD_EXCERPT_SENTINEL",
                  materials_mentioned=records or [])
    db.add_all([paper, chunk])
    await db.commit()
    return paper, chunk


async def _pin(db, chunk, *, evidence=None):
    status = (await resolve_paper_lifecycle(db, [chunk.paper_id]))[chunk.paper_id]
    linked = await resolve_explicit_materials(db, [chunk.materials_mentioned])
    occurrences, summary = project_source_occurrences(
        chunk.materials_mentioned, paper_status=status, linked_materials=linked,
    )
    visibility = source_visibility(status)
    visibility["warning_codes"] = sorted(set(visibility["warning_codes"] + summary["warning_codes"]))
    return currentness.selection_pin(chunk, material_evidence=occurrences, source_review=visibility,
                                    evidence=evidence)


@pytest.mark.asyncio
async def test_unchanged_is_snapshot_metadata_not_source_or_scientific_approval(db_session):
    _, chunk = await _seed(db_session)
    pin = await _pin(db_session, chunk)
    result = await currentness.check_selected_sources([pin])
    assert result.status == "unchanged" and result.reason_code is None and result.snapshot_at
    assert set(result.__slots__) == {"status", "reason_code", "snapshot_at"}
    assert (await db_session.get(Chunk, chunk.id)).text == chunk.text


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["text", "materials", "paper_title", "paper_hold", "paper_binding"])
async def test_same_ids_cannot_hide_changed_inputs_in_old_orm_session(db_session, target):
    paper, chunk = await _seed(db_session)
    pin = await _pin(db_session, chunk)
    old_text = chunk.text
    async with AsyncSession(get_engine()) as writer:
        if target == "text":
            await writer.execute(update(Chunk).where(Chunk.id == chunk.id).values(text="Changed source text"))
        elif target == "materials":
            await writer.execute(update(Chunk).where(Chunk.id == chunk.id).values(materials_mentioned=[{"formula": "Nb"}]))
        elif target == "paper_title":
            await writer.execute(update(Paper).where(Paper.id == paper.id).values(title="Changed attribution"))
        elif target == "paper_hold":
            await writer.execute(update(Paper).where(Paper.id == paper.id).values(status="corrected"))
        else:
            other = Paper(id="synthetic:other-" + uuid4().hex, source="arxiv", title="Other work",
                          authors=[], abstract="Other", status="published")
            writer.add(other)
            await writer.flush()
            await writer.execute(update(Chunk).where(Chunk.id == chunk.id).values(paper_id=other.id))
        await writer.commit()
    result = await currentness.check_selected_sources([pin])
    assert result.status == "changed" and result.reason_code.startswith("retrieval_source_")
    assert chunk.text == old_text  # the old ORM identity was not used for the check


@pytest.mark.asyncio
async def test_accepted_work_hold_is_rechecked_after_initial_paper_admission(db_session):
    paper, chunk = await _seed(db_session)
    work = Work(canonical_title="Synthetic work", publication_status="active")
    db_session.add(work)
    await db_session.flush()
    db_session.add(PaperWorkMap(paper_id=paper.id, work_id=work.id, match_method="manual", review_status="accepted"))
    await db_session.commit()
    pin = await _pin(db_session, chunk)
    async with AsyncSession(get_engine()) as writer:
        await writer.execute(update(Work).where(Work.id == work.id).values(publication_status="corrected"))
        await writer.commit()
    result = await currentness.check_selected_sources([pin])
    assert result.status == "changed" and result.reason_code == "retrieval_source_no_longer_eligible"


@pytest.mark.asyncio
async def test_explicit_material_hold_is_recomputed_not_trusted_from_old_occurrence(db_session):
    material = Material(id="mat:rg02-" + uuid4().hex, formula="Nb", formula_normalized="Nb",
                        records=[], needs_review=False)
    db_session.add(material)
    await db_session.commit()
    _, chunk = await _seed(db_session, records=[{"material_id": material.id, "formula": "Nb"}])
    pin = await _pin(db_session, chunk)
    async with AsyncSession(get_engine()) as writer:
        await writer.execute(update(Material).where(Material.id == material.id).values(needs_review=True))
        await writer.commit()
    assert (await currentness.check_selected_sources([pin])).status == "changed"


@pytest.mark.asyncio
async def test_typed_resolver_pin_detects_renderer_or_parent_changes(db_session):
    _, chunk = await _seed(db_session)
    descriptor = {"version": "synthetic/1", "rendering_version": "fixture/1", "parent_result_sha256": "a" * 64}
    pin = await _pin(db_session, chunk, evidence=descriptor)
    before = deepcopy(descriptor)
    async def resolver(_db, _chunks):
        return {chunk.id: descriptor}
    assert (await currentness.check_selected_sources([pin], evidence_resolver=resolver)).status == "unchanged"
    descriptor["rendering_version"] = "fixture/2"
    assert (await currentness.check_selected_sources([pin], evidence_resolver=resolver)).status == "changed"
    descriptor.update(before, parent_result_sha256="b" * 64)
    assert (await currentness.check_selected_sources([pin], evidence_resolver=resolver)).status == "changed"
    assert (await currentness.check_selected_sources([pin])).status == "unavailable"


@pytest.mark.asyncio
async def test_fresh_resolver_runs_only_in_bounded_readonly_repeatable_snapshot(db_session):
    _, chunk = await _seed(db_session)
    descriptor = {"version": "synthetic/1"}
    pin = await _pin(db_session, chunk, evidence=descriptor)
    checked = []
    async def resolver(db, chunks):
        checked.append({name: (await db.execute(text("SHOW " + name))).scalar_one() for name in (
            "transaction_isolation", "transaction_read_only", "statement_timeout",
        )})
        return {chunks[0].id: descriptor}
    result = await currentness.check_selected_sources([pin], evidence_resolver=resolver)
    assert result.status == "unchanged"
    assert checked == [{"transaction_isolation": "repeatable read", "transaction_read_only": "on",
                        "statement_timeout": "5s"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["sql", "timeout", "budget"])
async def test_error_timeout_and_size_preflight_fail_closed(db_session, monkeypatch, failure):
    _, chunk = await _seed(db_session)
    pin = await _pin(db_session, chunk)
    if failure == "budget":
        monkeypatch.setattr(currentness, "MAX_CATALOGUE_BYTES", 1)
    elif failure == "sql":
        async def fail(db, *_args):
            await db.execute(text("SELECT 1 / 0"))
        monkeypatch.setattr(currentness, "_check_snapshot", fail)
    else:
        async def wait(*_args):
            await asyncio.Event().wait()
        monkeypatch.setattr(currentness, "_check_snapshot", wait)
        monkeypatch.setattr(currentness, "CHECK_TIMEOUT_SECONDS", 0.01)
    result = await currentness.check_selected_sources([pin])
    assert result.status == "unavailable"
    assert result.reason_code == ("retrieval_currentness_timeout" if failure == "timeout" else "retrieval_currentness_unavailable")
    assert "source" not in result.__slots__ and "input_sha256" not in result.__slots__


@pytest.mark.asyncio
async def test_inventory_bounds_refuse_before_connecting(monkeypatch):
    def forbidden():
        raise AssertionError("invalid inventory must not connect")
    monkeypatch.setattr(currentness, "get_engine", forbidden)
    pin = currentness.SelectionPin("chunk", "paper", "a" * 64)
    for pins in ([], [pin, pin], [pin] * 21, [object()], None):
        assert (await currentness.check_selected_sources(pins)).status == "unavailable"


def _offline_retrieval(monkeypatch, chunk_id):
    async def lexical(*_args, **_kwargs):
        return [retrieval.LexicalHit(chunk_id, 1.0)]
    monkeypatch.setattr("routers.ask.retrieval.lexical_search", lexical)


async def _register_fact(db, chunk, *, extraction_version="synthetic-extraction/1", permission="unresolved",
                         rendering_version=None):
    from services.rag_evidence import CURRENT_FACT_RENDERER_VERSION, register_chunk_evidence
    return await register_chunk_evidence(db, chunk_id=chunk.id, candidate={
        "version": "rag-evidence/1.0.0", "chunk_kind": "derived_fact",
        "parent_record": chunk.materials_mentioned[0], "extraction_version": extraction_version,
        "rendering_version": rendering_version or CURRENT_FACT_RENDERER_VERSION,
        "permission_status": permission,
    }, dry_run=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("restriction", ["restricted", "old_renderer"])
async def test_initial_typed_restriction_never_reaches_provider_or_snippet(client, db_session, monkeypatch, restriction):
    _, chunk = await _seed(db_session, records=[{"formula": "H3S", "tc_kelvin": 100}])
    await _register_fact(db_session, chunk, permission="restricted" if restriction == "restricted" else "unresolved",
                         rendering_version="synthetic-old/1" if restriction == "old_renderer" else None)
    await db_session.commit()
    _offline_retrieval(monkeypatch, chunk.id)
    generated = []
    def forbidden(*_args, **_kwargs):
        generated.append(True)
        raise AssertionError("Restricted/stale text must not reach generation")
    monkeypatch.setattr(rag, "generate_answer", forbidden)
    response = await client.post("/v1/ask", json={"question": "Synthetic restricted query?"})
    assert response.status_code == 200, response.text
    assert response.json()["sources"] == [] and "OLD_EXCERPT_SENTINEL" not in response.text
    assert generated == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "sql", "inventory"])
async def test_initial_lineage_failure_is_bounded_and_never_generates_or_saves_old_text(
    client, db_session, registered_user, monkeypatch, caplog, failure,
):
    user, token = registered_user
    _, chunk = await _seed(db_session)
    _offline_retrieval(monkeypatch, chunk.id)
    resolver_entered, resolver_cancelled, generated = [], [], []

    async def broken_resolver(db, _chunks):
        resolver_entered.append(True)
        if failure == "timeout":
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                resolver_cancelled.append(True)
                raise
        if failure == "sql":
            await db.execute(text("SELECT 1 / 0"))
        return {"UNTRUSTED_INVENTORY_SENTINEL": {}}

    def forbidden(*_args, **_kwargs):
        generated.append(True)
        raise AssertionError("Unchecked initial text must not reach generation")

    monkeypatch.setattr("services.rag_evidence.resolve_chunk_evidence", broken_resolver)
    monkeypatch.setattr(rag, "generate_answer", forbidden)
    if failure == "timeout":
        monkeypatch.setattr("routers.ask.EVIDENCE_RESOLUTION_TIMEOUT_SECONDS", 0.01)
    response = await asyncio.wait_for(client.post(
        "/v1/ask", json={"question": "Synthetic initial lineage failure?"},
        headers={"Authorization": "Bearer " + token},
    ), 5)
    assert response.status_code == 200, response.text
    body = response.json()
    reason = "retrieval_currentness_timeout" if failure == "timeout" else "retrieval_currentness_unavailable"
    assert resolver_entered == [True] and generated == []
    assert resolver_cancelled == ([True] if failure == "timeout" else [])
    assert body["sources"] == [] and body["claim_assessments"] == []
    assert body["answer_mode"] == "abstention" and body["assessment_scope"] == "none"
    assert body["scientific_support_status"] == "not_checked"
    assert body["citation_warnings"] == body["support_warnings"] == [reason]
    assert "after generation" not in body["answer"]
    assert "OLD_EXCERPT_SENTINEL" not in response.text
    assert "UNTRUSTED_INVENTORY_SENTINEL" not in response.text + caplog.text
    saved = (await db_session.execute(select(AskHistory).where(AskHistory.user_id == user.id))).scalar_one()
    assert saved.answer == body["answer"] and saved.sources == []


@pytest.mark.asyncio
async def test_stable_sealed_fallback_is_not_reassessed_as_an_original_draft(client, db_session, monkeypatch):
    _, chunk = await _seed(db_session)
    _offline_retrieval(monkeypatch, chunk.id)
    generated = []
    def generate(_question, sources, **_kwargs):
        result = rag.extractive_fallback(sources, reason="synthetic_sealed_fallback")
        generated.append(result.answer)
        return result
    def forbidden(*_args, **_kwargs):
        raise AssertionError("An unchanged sealed fallback must not become a new draft")
    monkeypatch.setattr(rag, "generate_answer", generate)
    monkeypatch.setattr("services.claim_support.assess_answer", forbidden)
    response = await client.post("/v1/ask", json={"question": "Synthetic unchanged query?"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert generated == [body["answer"]]
    assert len(body["sources"]) == 1 and body["assessment_scope"] == "none"
    assert body["scientific_support_status"] == "not_checked"
    assert "support_checker_unavailable" not in body["support_warnings"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["text", "materials", "corrected", "corrected_then_published",
                                     "renderer_version", "parent_revision", "permission_restricted"])
async def test_db_barrier_during_generation_discards_old_draft_excerpt_and_history(
    client, db_session, registered_user, monkeypatch, change,
):
    user, token = registered_user
    typed = change in {"renderer_version", "parent_revision", "permission_restricted"}
    paper, chunk = await _seed(db_session, records=[{"formula": "H3S", "tc_kelvin": 100}] if typed else None)
    if typed:
        await _register_fact(db_session, chunk)
        await db_session.commit()
    _offline_retrieval(monkeypatch, chunk.id)
    started, release = threading.Event(), threading.Event()
    request_pids = []
    async def request_db():
        async with AsyncSession(get_engine(), expire_on_commit=False) as session:
            request_pids.append((await session.execute(select(func.pg_backend_pid()))).scalar_one())
            yield session
    app.dependency_overrides[get_db] = request_db
    def generate(_question, sources, **_kwargs):
        started.set()
        if not release.wait(8):
            raise AssertionError("synthetic generation barrier not released")
        # Exercise the already-sealed fallback case: it must not be treated as
        # the original draft again after a source change.
        return rag.extractive_fallback(sources, reason="synthetic_provider_fallback")
    monkeypatch.setattr(rag, "generate_answer", generate)
    provider_resilience.reset()
    request = asyncio.create_task(client.post("/v1/ask", json={"question": "Synthetic currentness query?"},
                                             headers={"Authorization": "Bearer " + token}))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        # Request's old connection is idle or released, not holding an open
        # pre-generation transaction across the provider barrier.
        async with AsyncSession(get_engine()) as writer:
            xact = (await writer.execute(text("SELECT xact_start FROM pg_stat_activity WHERE pid=:pid"),
                                         {"pid": request_pids[0]})).scalar_one_or_none()
            assert xact is None
            if change == "text":
                await writer.execute(update(Chunk).where(Chunk.id == chunk.id).values(text="New source text"))
            elif change == "materials":
                await writer.execute(update(Chunk).where(Chunk.id == chunk.id).values(materials_mentioned=[{"not_detected": True}]))
            elif change == "renderer_version":
                monkeypatch.setattr("services.rag_evidence.CURRENT_FACT_RENDERER_VERSION", "synthetic-new/3")
            elif change == "parent_revision":
                await _register_fact(writer, chunk, extraction_version="synthetic-extraction/2")
            elif change == "permission_restricted":
                await _register_fact(writer, chunk, permission="restricted")
            else:
                await writer.execute(update(Paper).where(Paper.id == paper.id).values(status="corrected"))
            await writer.commit()
            if change == "corrected_then_published":
                await writer.execute(update(Paper).where(Paper.id == paper.id).values(status="published"))
                await writer.commit()
        release.set()
        response = await asyncio.wait_for(request, 10)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["sources"] == [] and body["claim_assessments"] == []
        assert body["answer_mode"] == "abstention" and body["scientific_support_status"] == "not_checked"
        assert body["assessment_scope"] == "none" and "OLD_EXCERPT_SENTINEL" not in str(body)
        assert "selected evidence changed" in body["answer"]
        saved = (await db_session.execute(select(AskHistory).where(AskHistory.user_id == user.id))).scalar_one()
        assert saved.answer == body["answer"] and saved.sources == []
    finally:
        release.set()
        if not request.done():
            request.cancel()
            try:
                await request
            except asyncio.CancelledError:
                pass
        app.dependency_overrides.pop(get_db, None)
        provider_resilience.reset()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["unavailable", "timeout"])
async def test_http_currentness_failure_never_returns_old_provider_content(client, db_session, monkeypatch, status):
    _, chunk = await _seed(db_session)
    _offline_retrieval(monkeypatch, chunk.id)
    def generate(_question, sources, **_kwargs):
        return rag.extractive_fallback(sources)
    async def fail(*_args, **_kwargs):
        return currentness.CurrentnessCheck("unavailable", "retrieval_currentness_" + status)
    monkeypatch.setattr(rag, "generate_answer", generate)
    monkeypatch.setattr(currentness, "check_selected_sources", fail)
    response = await client.post("/v1/ask", json={"question": "Synthetic query?"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sources"] == [] and body["answer_mode"] == "abstention"
    assert "OLD_EXCERPT_SENTINEL" not in str(body)
    assert "retrieval_currentness_" + status in body["support_warnings"]
