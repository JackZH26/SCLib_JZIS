"""Saved-output receipts over actual typed inputs; synthetic, not scientific gold."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from models.answer_evidence import (
    AnswerEvidenceBindings,
    canonical,
    validate_body,
    validate_response,
)
from models.db import Base, Chunk, Paper, get_session_factory
from models.evidence_packing import PackingCandidate
from models.index_read import generation_read_metadata
from models.search import AskRequest, AskResponse, AskSource
from services import answer_evidence as service
from services import evidence_packing, retrieval_currentness
from services.scientific_query import interpret_scientific_query
from services.scientific_query_lookup import prepare_scientific_lookup
from tests.index_generation_fixtures import publish_and_activate
from tests.test_complementary_ask import complementary as _complementary
from tests.test_complementary_ask import fake_provider
from tests.test_scientific_lookup_preparation import prepared_runtime as _prepared_runtime
from tests.test_scientific_mixed_ask import AMBIENT_MIXED, _stage_mixed
from tests.test_scientific_mixed_ask import mixed_generation as _mixed_generation
from tests.test_scientific_query_http import record, stage_records

prepared_runtime = _prepared_runtime
complementary = _complementary
mixed_generation = _mixed_generation


def legacy():
    text = "Synthetic retained source. A pending result is not scientific acceptance."
    paper = Paper(id="receipt-synthetic-paper", source="arxiv", title="Synthetic receipt source",
        arxiv_id=None, authors=["Synthetic Fixture"], date_submitted=date(2020, 1, 1), status="published",
        materials_extracted=[], quality_flags={})
    chunk = Chunk(id="receipt-synthetic-chunk", paper_id=paper.id, paper=paper, text=text,
        title=paper.title, section="Results", chunk_index=0, materials_mentioned=[], has_table=False, has_equation=False)
    candidate = PackingCandidate(chunk_id=chunk.id, paper_id=paper.id, source_snapshot_sha256=None,
        content_sha256=hashlib.sha256(text.encode()).hexdigest(), accepted_work_id=None,
        chunk_kind="legacy_unknown", role_hint="results")
    plan = evidence_packing.pack_evidence([candidate], cost=lambda ids: 100 + 100 * len(ids), byte_budget=4096, max_chunks=2)
    source = AskSource(index=1, paper_id=paper.id, arxiv_id=None, title=paper.title,
        authors_short="Synthetic Fixture", year=2020, section=chunk.section, snippet=text,
        packing_info=plan.selected[0])
    pin = retrieval_currentness.selection_pin(chunk, material_evidence=[], source_review={}, evidence=None)
    request = AskRequest(question="Discuss this synthetic source", max_sources=2, language="en")
    response = AskResponse(answer="A historical synthetic answer [1].", sources=[source], tokens_used=None,
        query_time_ms=7, evidence_packing=evidence_packing.public_summary(plan))
    capture = service.capture_inputs(request=request, sources=(source,), chunks=(chunk,), selection_pins=(pin,))
    return request, response, capture, chunk, pin


def empty(*, tokens=None):
    request = AskRequest(question="An unresolved question?", max_sources=1, language="auto")
    response = AskResponse(answer="No evidence was selected.", sources=[], tokens_used=tokens, query_time_ms=1)
    return request, response, service.capture_inputs(request=request)


def test_empty_and_legacy_complete_output_without_quota_or_persistence_fields():
    for request, response, captured, *_ in (empty(), legacy()):
        document = service.finish_capture(captured, response).document
        assert document["request"] == request.model_dump(mode="json")
        assert document["response"]["tokens_used"] is None
        assert {"history", "guest_remaining", "remaining"}.isdisjoint(document["response"])
        assert set(document["response"]) == set(AskResponse.model_fields) - {"history", "guest_remaining", "remaining"}
        assert service.binding_scope(document["bindings"]) in {"legacy_snapshot", "no_selected_evidence"}


def test_capture_detaches_source_aliases_and_private_seal_rejects_replacement():
    _, response, captured, chunk, _ = legacy()
    frozen = service.finish_capture(captured, response).document
    chunk.text = "CHANGED_SOURCE"
    response.sources[0].snippet = "CHANGED_SOURCE"
    with pytest.raises(service.AnswerEvidenceError):
        service.finish_capture(captured, response)
    with pytest.raises(service.AnswerEvidenceError):
        service.finish_capture(replace(captured, _json='{"changed":true}'), empty()[1])
    prepared = service.finish_capture(empty()[2], empty()[1])
    with pytest.raises(service.AnswerEvidenceError):
        _ = replace(prepared, _signature="0" * 64).document
    changed = prepared.document
    changed["request"]["question"] = "Changed after copy"
    assert prepared.document["request"]["question"] != changed["request"]["question"]
    assert frozen["response"]["sources"][0]["snippet"] != "CHANGED_SOURCE"


def test_final_withdrawal_drops_all_previously_selected_private_identifiers():
    _, _, captured, chunk, _ = legacy()
    result = service.finish_capture(captured, AskResponse(answer="Selected evidence was withheld.", sources=[],
        tokens_used=None, query_time_ms=9)).document
    assert result["bindings"]["mode"] == "no_selected_evidence" and result["bindings"]["items"] == []
    assert chunk.id.encode() not in canonical(result) and chunk.paper_id.encode() not in canonical(result)


@pytest.mark.parametrize("part", ["request", "source", "chunk", "pin"])
def test_capture_refuses_duck_typed_inputs(part):
    request, response, _, chunk, pin = legacy()
    values = dict(request=request, sources=(response.sources[0],), chunks=(chunk,), selection_pins=(pin,))
    key = {"request": "request", "source": "sources", "chunk": "chunks", "pin": "selection_pins"}[part]
    old = values[key] if part == "request" else values[key][0]
    replacement = SimpleNamespace(**old.__dict__) if hasattr(old, "__dict__") else SimpleNamespace(chunk_id=pin.chunk_id)
    values[key] = replacement if part == "request" else (replacement,)
    with pytest.raises(service.AnswerEvidenceError):
        service.capture_inputs(**values)


@pytest.mark.parametrize("field,value", [("tokens_used", True), ("tokens_used", float("nan")),
    ("query_time_ms", "1"), ("hidden_field", "PRIVATE"), ("remaining", 1), ("sources", [dict(index=True)])])
def test_saved_response_strictness_and_closed_inventory(field, value):
    _, response, captured = empty()
    body = service.finish_capture(captured, response).document["response"]
    with pytest.raises(ValueError):
        validate_response({**body, field: value})


@pytest.mark.parametrize("field,value", [("position", True), ("position", 2), ("chunk_id", "changed"),
    ("content_sha256", "A" * 64), ("has_evidence_pin", 0), ("source_snapshot_sha256", "a" * 64),
    ("member_record_sha256", "a" * 64), ("selection_generation_pin_sha256", "a" * 64)])
def test_binding_shape_and_source_bijection_are_strict(field, value):
    _, response, captured, *_ = legacy()
    document = service.finish_capture(captured, response).document
    document["bindings"]["items"][0][field] = value
    with pytest.raises(ValueError):
        validate_body(**document)


def test_missing_duplicate_and_extra_bindings_fail_closed():
    _, response, captured, *_ = legacy()
    document = service.finish_capture(captured, response).document
    for items in ([], document["bindings"]["items"] * 2):
        with pytest.raises(ValueError):
            validate_body(**{**document, "bindings": {**document["bindings"], "items": items}})
    with pytest.raises(ValueError):
        AnswerEvidenceBindings.model_validate({**document["bindings"], "approval": True})


def test_budget_is_rejected_before_output_receipt_and_retains_unknown_tokens():
    request, response, captured = empty()
    response.answer = "界" * (1024 * 1024 // 2)
    with pytest.raises(service.AnswerEvidenceError):
        service.finish_capture(captured, response)
    assert empty()[1].tokens_used is None


async def store(db, prepared):
    await db.rollback()
    await db.execute(sa.text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
    await db.execute(sa.text("SET LOCAL TimeZone='UTC'"))
    await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
    user_id, history_id = uuid4(), uuid4()
    await db.execute(Base.metadata.tables["users"].insert().values(id=user_id,
        email=f"receipt-{user_id}@example.test", name="Synthetic receipt owner", is_active=True, email_verified=True))
    fields = await service.receipt_fields(db, prepared)
    request, response = prepared.document["request"], prepared.document["response"]
    await db.execute(Base.metadata.tables["ask_history"].insert().values(id=history_id, user_id=user_id,
        question=request["question"], answer=response["answer"], sources=response["sources"],
        tokens_used=response["tokens_used"], latency_ms=response["query_time_ms"], language=request["language"],
        evidence_receipt_version=service.VERSION))
    fields = {**fields, "generation_id": UUID(fields["generation_id"]) if fields["generation_id"] else None,
              "activation_event_id": UUID(fields["activation_event_id"]) if fields["activation_event_id"] else None}
    await db.execute(Base.metadata.tables["answer_evidence_receipts"].insert().values(history_id=history_id, **fields))
    await db.commit()
    await db.execute(sa.text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
    await db.execute(sa.text("SET LOCAL TimeZone='UTC'"))
    await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
    return dict((await db.execute(sa.select(Base.metadata.tables["answer_evidence_receipts"]).where(
        Base.metadata.tables["answer_evidence_receipts"].c.history_id == history_id))).mappings().one())


async def test_actual_numeric_parent_receipt_and_historical_member_verification(prepared_runtime):
    db, pin, _, _, _ = prepared_runtime
    request = AskRequest(question="What is the Tc of MgB2?", max_sources=3, language="en")
    interpretation = interpret_scientific_query(request.question)
    inputs = (await prepare_scientific_lookup(db, pin, interpretation, limit=3)).consume()
    assert len(inputs.parents) == 3
    captured = service.capture_inputs(request=request, generation_pin=pin, scientific_inputs=inputs)
    response = AskResponse(answer="Qualified synthetic extraction records.", sources=[], tokens_used=0, query_time_ms=5,
        retrieval_generation=generation_read_metadata(pin), scientific_query=interpretation,
        scientific_lookup=inputs.outcome.status, scientific_results=inputs.outcome.results)
    prepared = service.finish_capture(captured, response)
    assert service.binding_scope(prepared.document["bindings"]) == "generation_members"
    stored = await store(db, prepared)
    receipt = await service.verify_historical(db, stored)
    assert receipt["response"]["scientific_results"] == response.model_dump(mode="json")["scientific_results"]
    assert receipt["response"]["tokens_used"] == 0
    assert {item["parent_result_revision_id"] for item in receipt["bindings"]["items"]} == {
        parent.parent_result_revision_id for parent in inputs.parents}
    changed = deepcopy(stored)
    value = json.loads(changed["response_json"])
    value["answer"] = "Tampered private historical answer"
    changed["response_json"] = canonical(value).decode()
    changed["response_sha256"] = hashlib.sha256(changed["response_json"].encode()).hexdigest()
    with pytest.raises(service.AnswerEvidenceError):
        await service.verify_historical(db, changed)


async def test_actual_empty_receipt_sql_numeric_spelling_and_unknown_token_preserved(prepared_runtime):
    db, *_ = prepared_runtime
    request, response, captured = empty()
    response.support_coverage = {"tiny": 1e-7, "zero": -0.0}
    stored = await store(db, service.finish_capture(captured, response))
    assert "1e-07" not in stored["response_json"]
    receipt = await service.verify_historical(db, stored)
    assert receipt["response"]["tokens_used"] is None
    assert receipt["response"]["support_coverage"]["tiny"] == 1e-7
    assert receipt["bindings"]["items"] == []


async def test_capture_rejects_scalar_tampering_even_with_correct_retained_parent_ids(prepared_runtime):
    db, pin, *_ = prepared_runtime
    request = AskRequest(question="What is the Tc of MgB2?", max_sources=3, language="en")
    inputs = (await prepare_scientific_lookup(db, pin, interpret_scientific_query(request.question))).consume()
    value = json.loads(inputs._outcome_json)
    value["results"][0]["result"]["tc"]["value"] = 101.0
    changed = replace(inputs, _outcome_json=canonical(value).decode())
    # Existing prepared-input shape validation correctly does not recalculate
    # the quantity. The saved-answer capture must compare the actual raw row.
    assert changed.outcome.results[0].binding == inputs.outcome.results[0].binding
    with pytest.raises(service.AnswerEvidenceError, match="capture_unavailable"):
        service.capture_inputs(request=request, generation_pin=pin, scientific_inputs=changed)


async def readonly(db):
    await db.rollback()
    await db.execute(sa.text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
    await db.execute(sa.text("SET LOCAL TimeZone='UTC'"))
    await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))


async def test_numeric_receipt_keeps_actual_old_three_members_after_one_chunk_replacement(prepared_runtime, monkeypatch):
    from config import get_settings
    from services import index_retrieval
    db, pin, _, meta, _ = prepared_runtime
    request = AskRequest(question="What is the Tc of MgB2?", max_sources=3, language="en")
    parsed = interpret_scientific_query(request.question)
    inputs = (await prepare_scientific_lookup(db, pin, parsed)).consume()
    captured = service.capture_inputs(request=request, generation_pin=pin, scientific_inputs=inputs)
    response = AskResponse(answer="Synthetic retained result records", sources=[], tokens_used=0, query_time_ms=1,
        retrieval_generation=generation_read_metadata(pin), scientific_query=parsed,
        scientific_lookup=inputs.outcome.status, scientific_results=inputs.outcome.results)
    stored = await store(db, service.finish_capture(captured, response))
    before = await service.verify_historical(db, stored)
    await db.rollback()
    _, _, staged = await stage_records(monkeypatch, db, get_settings().retrieval_logical_index,
                                       [record(tc="10 K")], meta=meta)
    active, _, _ = await publish_and_activate(db, staged, expected_event_id=pin["activation_event_id"])
    assert active["generation_id"] != pin["generation_id"]
    assert await db.scalar(sa.select(sa.func.count()).select_from(Chunk).where(Chunk.paper_id == meta.paper_id)) == 1
    await readonly(db)
    async def no_current(*args, **kwargs):
        raise AssertionError("Historical receipt must not consult current pointer or mutable chunks")
    with monkeypatch.context() as patch:
        patch.setattr(index_retrieval, "load_pin", no_current)
        patch.setattr(index_retrieval, "hydrate", no_current)
        assert await service.verify_historical(db, stored) == before
    assert len(before["bindings"]["items"]) == 3


def capture_spy(monkeypatch):
    captured = []
    actual = service.capture_inputs
    def observe(**kwargs):
        value = actual(**kwargs)
        captured.append(value)
        return value
    monkeypatch.setattr(service, "capture_inputs", observe)
    return captured


async def test_actual_ordinary_http_capture_and_saved_full_response(client, complementary, monkeypatch):
    captured = capture_spy(monkeypatch)
    calls = fake_provider(monkeypatch)
    result = await client.post("/v1/ask", json={"question": "Explain the pairing mechanism", "language": "en"})
    assert result.status_code == 200
    response = AskResponse.model_validate(result.json())
    assert len(response.sources) == 3 and len(captured) == 1
    assert [kind for kind, _ in calls] == ["count", "generate"]
    async with get_session_factory()() as db:
        stored = await store(db, service.finish_capture(captured[0], response))
        receipt = await service.verify_historical(db, stored)
    assert receipt["response"]["sources"] == response.model_dump(mode="json")["sources"]
    assert receipt["response"]["tokens_used"] == 130
    assert len({item["chunk_id"] for item in receipt["bindings"]["items"]}) == 3


async def test_actual_mixed_http_capture_original_and_numeric_refs_survive_new_generation(client, mixed_generation, monkeypatch):
    captured = capture_spy(monkeypatch)
    result = await client.post("/v1/ask", json={"question": AMBIENT_MIXED, "max_sources": 3, "language": "en"})
    assert result.status_code == 200
    response = AskResponse.model_validate(result.json())
    assert len(response.sources) == 2 and len(response.scientific_results) == 1
    assert len(captured) == 1 and not mixed_generation["forbidden_calls"]
    async with get_session_factory()() as db:
        stored = await store(db, service.finish_capture(captured[0], response))
        before = await service.verify_historical(db, stored)
        await db.rollback()
        _, _, staged = await _stage_mixed(monkeypatch, mixed_generation["logical"],
            meta=mixed_generation["meta"], label="new different bytes")
        await publish_and_activate(db, staged, expected_event_id=mixed_generation["pin"]["activation_event_id"])
        await readonly(db)
        after = await service.verify_historical(db, stored)
    assert before == after
    assert [item["kind"] for item in after["bindings"]["items"]] == ["source", "source", "scientific_result"]
    assert after["response"]["scientific_mixed"]["status"] == "completed"
    assert after["response"]["input_budget"]["status"] == "not_requested"
    assert all(pair["status"] == "not_established" for pair in after["response"]["scientific_mixed"]["associations"])


@pytest.mark.parametrize("isolation,read_only,zone,timeout", [
    ("READ COMMITTED", True, "UTC", 5000), ("REPEATABLE READ", False, "UTC", 5000),
    ("REPEATABLE READ", True, "Asia/Singapore", 5000), ("REPEATABLE READ", True, "UTC", 0),
    ("REPEATABLE READ", True, "UTC", 10001)])
async def test_historical_session_admission_is_bounded_and_readonly(isolation, read_only, zone, timeout):
    async with get_session_factory()() as db:
        await db.execute(sa.text("SET TRANSACTION ISOLATION LEVEL " + isolation + (", READ ONLY" if read_only else ", READ WRITE")))
        await db.execute(sa.text("SET LOCAL TimeZone='" + zone + "'"))
        await db.execute(sa.text("SET LOCAL statement_timeout='" + str(timeout) + "ms'"))
        with pytest.raises(service.AnswerEvidenceError):
            await service.verify_historical(db, {})
        with pytest.raises(service.AnswerEvidenceError):
            await service._session(db, readonly=True)


@pytest.mark.parametrize("function", ["verify_historical", "receipt_fields"])
async def test_dirty_session_refused_before_any_autoflush_or_sql(function, monkeypatch):
    async with get_session_factory()() as db:
        db.add(Paper(id="unsaved-receipt-" + uuid4().hex, source="arxiv", title="Unsaved synthetic paper"))
        execute = AsyncMock(side_effect=AssertionError("Dirty session must not execute SQL"))
        monkeypatch.setattr(db, "execute", execute)
        argument = {} if function == "verify_historical" else service.finish_capture(empty()[2], empty()[1])
        with pytest.raises(service.AnswerEvidenceError):
            await getattr(service, function)(db, argument)
        execute.assert_not_called()


@pytest.mark.parametrize("question", ["Compare MgB2 Tc under the same unreported conditions", "What is Tc for MgB2 at -4 GPa?"])
async def test_clarification_http_final_output_has_no_invented_evidence(client, monkeypatch, question):
    captured = capture_spy(monkeypatch)
    result = await client.post("/v1/ask", json={"question": question, "max_sources": 2})
    assert result.status_code == 200
    response = AskResponse.model_validate(result.json())
    assert response.scientific_query.status == "clarification_required"
    assert len(captured) == 1
    prepared = service.finish_capture(captured[0], response)
    assert prepared.document["bindings"]["mode"] == "no_selected_evidence"
    assert prepared.document["response"]["tokens_used"] == 0
