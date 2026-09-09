"""0068 raw SQL invariants on exclusively guarded disposable PostgreSQL."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.answer_evidence_v1 import TABLE_NAME, VERSION
from models.db import AskHistory, Base, get_session_factory
from models.index_read import generation_read_metadata
from models.search import AskResponse, AskSource
from services.index_generations import activate_generation, load_generation_members
from services.index_retrieval import hydrate, resolve_evidence
from tests.test_index_generations import staged, validated
from tests.test_research_freeze import add, state


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    async with get_session_factory()() as session:
        yield session


async def canonical(db, value):
    return await db.scalar(sa.text("SELECT public.sclib_answer_evidence_canonical_v1(CAST(:value AS jsonb))"),
                           {"value": json.dumps(value, ensure_ascii=False, allow_nan=False)})


async def prepared(db, *, source=False):
    user_id = uuid4()
    await add(db, "users", id=user_id, email=f"answer-fixture-{user_id}@example.test",
              name="Synthetic saved-answer fixture", is_active=True, email_verified=True)
    request = {"question": "What does this synthetic fixture retain?", "language": "auto", "max_sources": 20}
    pin = None
    items, sources = [], []
    packing = None
    if source:
        generation, _ = await staged(db, logical_index="saved-answer-" + uuid4().hex)
        validation = await validated(db, generation)
        await activate_generation(db, generation_id=generation["generation_id"], validation_id=validation["validation_id"],
            expected_event_id=None, idempotency_key="synthetic-saved-answer", dry_run=False)
        from services.index_generations import load_active_generation
        pin = await load_active_generation(db, logical_index=(await db.scalar(sa.text(
            "SELECT logical_index FROM index_generations WHERE id=:id"), {"id": generation["generation_id"]})))
        member = (await load_generation_members(db, generation_id=pin["generation_id"]))[0]
        chunks = await hydrate(db, pin, [member["vector_id"]])
        evidence = (await resolve_evidence(db, list(chunks.values())))[member["vector_id"]]
        from services.evidence_packing import pack_evidence, public_summary
        plan = pack_evidence([{"chunk_id": member["vector_id"], "paper_id": member["paper_id"],
            "content_sha256": member["content_sha256"], "source_snapshot_sha256": member["source_snapshot_sha256"],
            "chunk_kind": "derived_fact"}], cost=lambda ids: 10 + len(ids), byte_budget=64)
        packing = public_summary(plan)
        sources = [AskSource(index=1, paper_id=member["paper_id"], arxiv_id=None, title="Synthetic title",
            authors_short="Synthetic", year=None, section=None, snippet=member["snapshot_json"]["text"],
            evidence_provenance=evidence, packing_info=plan.selected[0])]
        items = [{"kind": "source", "position": 1, "paper_id": member["paper_id"], "chunk_id": member["vector_id"],
            **{key: member[key] for key in ("content_sha256", "chunk_revision_sha256", "vector_sha256", "source_snapshot_sha256")},
            "member_record_sha256": member["record_sha256"], "evidence_revision_id": evidence["evidence_revision_id"],
            "evidence_record_sha256": evidence["evidence_record_sha256"],
            "parent_result_revision_id": evidence["parent_result_revision_id"], "parent_result_sha256": evidence["parent_result_sha256"],
            "selection_input_sha256": "a" * 64,
            "selection_generation_pin_sha256": hashlib.sha256(json.dumps(pin, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest(),
            "selection_grouping_sha256": None, "has_evidence_pin": True}]
    response = AskResponse(answer="Synthetic historical snapshot; no scientific approval.", sources=sources,
        tokens_used=None, query_time_ms=12, retrieval_generation=generation_read_metadata(pin),
        **({"evidence_packing": packing} if packing else {})).model_dump(mode="json")
    response.pop("remaining", None)
    response.pop("guest_remaining", None)
    response.pop("answer_evidence", None)
    response.pop("persistence", None)
    response.pop("history", None)
    bindings = {"version": VERSION, "mode": "generation_bound" if items else "no_selected_evidence",
        **{key: pin[key] if pin else None for key in ("generation_id", "activation_event_id", "manifest_sha256")}, "items": items}
    return {"user_id": user_id, "request": request, "response": response, "bindings": bindings}


async def insert_history(db, value, *, receipt=True, marker=VERSION, created_at=None):
    request, response, bindings = value["request"], value["response"], value["bindings"]
    identifier = uuid4()
    values = {"id": identifier, "user_id": value["user_id"], "question": request["question"],
        "answer": response["answer"], "sources": response["sources"], "tokens_used": response["tokens_used"],
        "latency_ms": response["query_time_ms"], "language": request["language"], "evidence_receipt_version": marker}
    if created_at is not None:
        values["created_at"] = created_at
    await db.execute(sa.insert(AskHistory).values(**values))
    row = {"history_id": identifier, "version": VERSION,
        **{key: UUID(bindings[key]) if bindings[key] else None for key in ("generation_id", "activation_event_id")}}
    for name in ("request", "response", "bindings"):
        encoded = await canonical(db, value[name])
        row[name + "_json"] = encoded
        row[name + "_sha256"] = hashlib.sha256(encoded.encode()).hexdigest()
    if receipt:
        await db.execute(Base.metadata.tables[TABLE_NAME].insert().values(**row))
        await db.execute(sa.text("SET CONSTRAINTS ae68_complete IMMEDIATE"))
        await db.execute(sa.text("SET CONSTRAINTS ae68_complete DEFERRED"))
    return identifier, row


async def test_empty_final_response_exact_hashes_and_nullable_tokens(db_session):
    value = await prepared(db_session)
    identifier, row = await insert_history(db_session, value)
    stored = (await db_session.execute(sa.select(Base.metadata.tables[TABLE_NAME]).where(
        Base.metadata.tables[TABLE_NAME].c.history_id == identifier))).mappings().one()
    for key in ("request", "response", "bindings"):
        assert stored[key + "_sha256"] == hashlib.sha256(stored[key + "_json"].encode()).hexdigest()
    assert await db_session.scalar(sa.text("SELECT record_sha256=public.sclib_answer_evidence_record_hash_v1(to_jsonb(r)) "
                                         "FROM answer_evidence_receipts r WHERE history_id=:id"), {"id": identifier}) is True
    assert json.loads(row["response_json"])["tokens_used"] is None


async def test_sql_canonical_numbers_unicode_and_duplicate_keys_are_not_python_hash_guesses(db_session):
    value = await prepared(db_session)
    value["response"]["support_coverage"] = {"tiny": 1e-5, "zero": -0.0, "label": "中文"}
    _, row = await insert_history(db_session, value)
    assert '"tiny":0.00001' in row["response_json"] and "中文" in row["response_json"]
    before = await state(db_session)
    async with db_session.begin_nested():
        identifier, wrong = await insert_history(db_session, value, receipt=False)
        wrong["request_json"] = wrong["request_json"].replace('{', '{"question":"hidden duplicate",', 1)
        wrong["request_sha256"] = hashlib.sha256(wrong["request_json"].encode()).hexdigest()
        with pytest.raises(DBAPIError, match="canonical_hash_mismatch"):
            async with db_session.begin_nested():
                await db_session.execute(Base.metadata.tables[TABLE_NAME].insert().values(**wrong))
        await db_session.execute(sa.delete(AskHistory).where(AskHistory.id == identifier))
    assert await state(db_session) == before


async def test_marked_history_requires_atomic_receipt_and_cannot_be_backdated(db_session):
    value = await prepared(db_session)
    before = await state(db_session)
    with pytest.raises(DBAPIError, match="complete_receipt_required"):
        async with db_session.begin_nested():
            await insert_history(db_session, value, receipt=False)
            await db_session.execute(sa.text("SET CONSTRAINTS ae68_complete IMMEDIATE"))
    assert await state(db_session) == before
    identifier, _ = await insert_history(db_session, value, created_at=datetime(1900, 1, 1, tzinfo=UTC))
    created = await db_session.scalar(sa.select(AskHistory.created_at).where(AskHistory.id == identifier))
    assert created.year >= 2026


async def test_old_unmarked_rows_stay_unpinned_and_cannot_be_retrofitted(db_session):
    value = await prepared(db_session)
    identifier, row = await insert_history(db_session, value, marker=None, receipt=False)
    for command in (sa.update(AskHistory).where(AskHistory.id == identifier).values(evidence_receipt_version=VERSION),
                    Base.metadata.tables[TABLE_NAME].insert().values(**row)):
        with pytest.raises(DBAPIError, match="immutable|exact_new_history_required"):
            async with db_session.begin_nested():
                await db_session.execute(command)
    await db_session.execute(sa.update(AskHistory).where(AskHistory.id == identifier).values(answer="Legacy behavior remains"))
    assert await db_session.scalar(sa.select(AskHistory.evidence_receipt_version).where(AskHistory.id == identifier)) is None


@pytest.mark.parametrize("target,operation", [("history", "update"), ("receipt", "update"),
    ("receipt", "delete"), ("receipt", "truncate"), ("history", "truncate")])
async def test_marked_payload_cannot_change_or_silently_downgrade(db_session, target, operation):
    identifier, _ = await insert_history(db_session, await prepared(db_session))
    before = await state(db_session)
    command = {
        ("history", "update"): "UPDATE ask_history SET answer=answer WHERE id=:id",
        ("receipt", "update"): "UPDATE answer_evidence_receipts SET response_json=response_json WHERE history_id=:id",
        ("receipt", "delete"): "DELETE FROM answer_evidence_receipts WHERE history_id=:id",
        ("receipt", "truncate"): "TRUNCATE answer_evidence_receipts",
        ("history", "truncate"): "TRUNCATE ask_history CASCADE",
    }[(target, operation)]
    with pytest.raises(DBAPIError, match="immutable"):
        async with db_session.begin_nested():
            await db_session.execute(sa.text(command), {"id": identifier})
    assert await state(db_session) == before


@pytest.mark.parametrize("path", ["owner", "account", "retention"])
async def test_parent_owner_account_and_bulk_retention_deletion_remove_receipt(db_session, path):
    value = await prepared(db_session)
    identifier, _ = await insert_history(db_session, value)
    if path == "account":
        await db_session.execute(sa.text("DELETE FROM users WHERE id=:id"), {"id": value["user_id"]})
    elif path == "retention":
        await db_session.execute(sa.text("DELETE FROM ask_history WHERE user_id=:id AND created_at<=clock_timestamp()"),
                                 {"id": value["user_id"]})
    else:
        await db_session.execute(sa.delete(AskHistory).where(AskHistory.id == identifier))
    assert await db_session.scalar(sa.text("SELECT count(*) FROM answer_evidence_receipts WHERE history_id=:id"), {"id": identifier}) == 0
    await db_session.execute(sa.text("SET CONSTRAINTS ae68_complete IMMEDIATE"))


@pytest.mark.parametrize("change", [
    {"member_record_sha256": "0" * 64}, {"chunk_revision_sha256": "0" * 64},
    {"vector_sha256": "0" * 64}, {"content_sha256": "0" * 64},
    {"source_snapshot_sha256": "0" * 64}, {"evidence_revision_id": str(uuid4())},
    {"evidence_record_sha256": "0" * 64}, {"parent_result_revision_id": str(uuid4())},
    {"parent_result_sha256": "0" * 64}, {"has_evidence_pin": 1},
    {"selection_generation_pin_sha256": "0" * 64},
    {"position": True}, {"unknown": "private arbitrary input"},
])
async def test_native_generation_member_evidence_and_parent_crossbindings(db_session, change):
    value = await prepared(db_session, source=True)
    value["bindings"]["items"][0].update(change)
    before = await state(db_session)
    with pytest.raises(DBAPIError, match="answer_evidence"):
        async with db_session.begin_nested():
            await insert_history(db_session, value)
    assert await state(db_session) == before


async def test_complete_ordered_references_required_without_silent_omission(db_session):
    original = await prepared(db_session, source=True)
    for change in ("omit", "duplicate", "position", "response"):
        value = deepcopy(original)
        if change == "omit":
            value["bindings"]["items"] = []
        elif change == "duplicate":
            value["bindings"]["items"] *= 2
            value["response"]["sources"] *= 2
        elif change == "position":
            value["bindings"]["items"][0]["position"] = 2
        else:
            value["response"]["sources"][0]["paper_id"] = "different-source"
        with pytest.raises(DBAPIError, match="answer_evidence"):
            async with db_session.begin_nested():
                await insert_history(db_session, value)


async def test_historical_generation_is_not_rebound_to_new_active_pointer(db_session):
    value = await prepared(db_session, source=True)
    identifier, _ = await insert_history(db_session, value)
    generation_id = value["bindings"]["generation_id"]
    logical = await db_session.scalar(sa.text("SELECT logical_index FROM index_generations WHERE id=:id"), {"id": generation_id})
    later, _ = await staged(db_session, logical_index=logical)
    checked = await validated(db_session, later)
    await activate_generation(db_session, generation_id=later["generation_id"], validation_id=checked["validation_id"],
        expected_event_id=value["bindings"]["activation_event_id"], idempotency_key="later-active-generation", dry_run=False)
    # A new final receipt may refer to genuinely retained history; it does not
    # certify that the old generation is current, and does not consult pointer.
    await insert_history(db_session, value)
    assert await db_session.scalar(sa.text("SELECT generation_id::text FROM answer_evidence_receipts WHERE history_id=:id"),
                                   {"id": identifier}) == generation_id


async def test_wrong_checksum_size_and_noncanonical_input_are_refused(db_session):
    value = await prepared(db_session)
    for kind in ("hash", "size", "canonical"):
        async with db_session.begin_nested():
            identifier, row = await insert_history(db_session, value, receipt=False)
            if kind == "hash":
                row["response_sha256"] = "0" * 64
            elif kind == "size":
                row["response_json"] = " " * (1024 * 1024 + 1)
            else:
                row["request_json"] = " " + row["request_json"]
                row["request_sha256"] = hashlib.sha256(row["request_json"].encode()).hexdigest()
            with pytest.raises(DBAPIError, match="answer_evidence"):
                async with db_session.begin_nested():
                    await db_session.execute(Base.metadata.tables[TABLE_NAME].insert().values(**row))
            await db_session.execute(sa.delete(AskHistory).where(AskHistory.id == identifier))


async def test_new_legacy_lexical_snapshot_does_not_invent_member_or_generation(db_session):
    value = await prepared(db_session)
    from services.evidence_packing import pack_evidence, public_summary
    content = hashlib.sha256(b"Synthetic legacy lexical text").hexdigest()
    plan = pack_evidence([{"chunk_id": "synthetic-legacy-chunk", "paper_id": "synthetic-legacy-paper",
        "content_sha256": content, "chunk_kind": "legacy_unknown"}],
        cost=lambda ids: 10 + len(ids), byte_budget=64)
    source = AskSource(index=1, paper_id="synthetic-legacy-paper", arxiv_id=None, title="Legacy snapshot only",
        authors_short="Synthetic", year=None, section=None, snippet="Synthetic legacy lexical text",
        evidence_provenance={}, packing_info=plan.selected[0])
    response = AskResponse(answer=value["response"]["answer"], sources=[source], tokens_used=None,
        query_time_ms=12, evidence_packing=public_summary(plan)).model_dump(mode="json")
    value["response"] = {key: item for key, item in response.items()
                         if key not in {"remaining", "guest_remaining", "history"}}
    value["bindings"]["mode"] = "snapshot_only"
    value["bindings"]["items"] = [{"kind": "source", "position": 1,
        "paper_id": source.paper_id, "chunk_id": plan.selected[0].chunk_id,
        "content_sha256": content, "selection_input_sha256": "a" * 64,
        "member_record_sha256": None, "chunk_revision_sha256": None, "vector_sha256": None,
        "source_snapshot_sha256": None, "evidence_revision_id": None, "evidence_record_sha256": None,
        "parent_result_revision_id": None, "parent_result_sha256": None,
        "selection_generation_pin_sha256": None, "selection_grouping_sha256": None, "has_evidence_pin": False}]
    identifier, _ = await insert_history(db_session, value)
    assert await db_session.scalar(sa.text("SELECT generation_id FROM answer_evidence_receipts WHERE history_id=:id"),
                                   {"id": identifier}) is None
    value["bindings"]["items"][0]["member_record_sha256"] = "b" * 64
    with pytest.raises(DBAPIError, match="snapshot_only_no_member"):
        async with db_session.begin_nested():
            await insert_history(db_session, value)


async def test_structured_result_position_binds_exact_parent_without_scientific_authority(db_session):
    value = await prepared(db_session, source=True)
    from models.evidence_packing import EvidencePackingSummary
    from models.scientific_lookup import ScientificLookupStatus
    from services.scientific_query import interpret_scientific_query
    from services.scientific_query_results import select_record_results
    selected = value["bindings"]["items"][0]
    selected["kind"] = "scientific_result"
    member = (await load_generation_members(db_session, generation_id=value["bindings"]["generation_id"]))[0]
    question = "MgB2 Tc"
    interpretation = interpret_scientific_query(question)
    result = select_record_results(member["snapshot_json"]["materials_mentioned"], interpretation,
                                   scope_id=member["paper_id"])[0]
    binding = {"paper_id": selected["paper_id"], "vector_id": selected["chunk_id"],
        **{key: value["bindings"][key] for key in ("generation_id", "activation_event_id", "manifest_sha256")},
        **{key: selected[key] for key in ("content_sha256", "evidence_revision_id", "evidence_record_sha256",
                                          "parent_result_revision_id", "parent_result_sha256")},
        "association_scope": "derived_extraction_not_original_support"}
    value["request"]["question"] = question
    value["response"].update(sources=[], evidence_packing=EvidencePackingSummary().model_dump(mode="json"),
        scientific_query=interpretation.model_dump(mode="json"),
        scientific_lookup=ScientificLookupStatus(status="completed", returned_count=1).model_dump(mode="json"),
        scientific_results=[{"result": result.model_dump(mode="json"), "binding": binding}])
    await insert_history(db_session, value)
    for field, changed in (("generation_id", str(uuid4())), ("parent_result_sha256", "0" * 64)):
        altered = deepcopy(value)
        altered["response"]["scientific_results"][0]["binding"][field] = changed
        with pytest.raises(DBAPIError, match="result_position_binding"):
            async with db_session.begin_nested():
                await insert_history(db_session, altered)
    altered = deepcopy(value)
    altered["response"]["scientific_results"][0]["result"]["scientific_acceptance"] = True
    with pytest.raises(DBAPIError, match="result_position_binding"):
        async with db_session.begin_nested():
            await insert_history(db_session, altered)


@pytest.mark.parametrize("field,changed", [
    ("source_capture_id", str(uuid4())), ("rendering_version", "fabricated-renderer/1"),
    ("source_locator", {"page": 999}), ("chunk_kind", "original_passage"),
    ("scientific_acceptance", True), ("independent_evidence", True), ("support_eligible", True),
])
async def test_descriptor_actual_source_refs_and_no_authority_are_native(db_session, field, changed):
    value = await prepared(db_session, source=True)
    value["response"]["sources"][0]["evidence_provenance"][field] = changed
    with pytest.raises(DBAPIError, match="answer_evidence"):
        async with db_session.begin_nested():
            await insert_history(db_session, value)


async def test_selection_21_refused_before_any_truncated_receipt(db_session):
    value = await prepared(db_session, source=True)
    value["bindings"]["items"] *= 21
    value["response"]["sources"] *= 21
    before = await state(db_session)
    with pytest.raises(DBAPIError, match="complete_selection_required"):
        async with db_session.begin_nested():
            await insert_history(db_session, value)
    assert await state(db_session) == before


def test_receipt_has_real_history_cascade_and_generation_restrict_not_mutable_chunk_fk():
    foreign = {key.parent.name: (key.column.table.name, key.ondelete) for key in Base.metadata.tables[TABLE_NAME].foreign_keys}
    assert foreign == {"history_id": ("ask_history", "CASCADE"),
        "generation_id": ("index_generations", "RESTRICT"),
        "activation_event_id": ("index_activation_events", "RESTRICT")}
