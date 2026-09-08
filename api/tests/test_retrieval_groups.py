"""Private diversity mapping witnesses on guarded actual PostgreSQL."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Chunk, Paper, PaperWorkMap, Work, get_engine
from services import retrieval_currentness as currentness
from services import retrieval_groups as grouping
from services.source_lifecycle import resolve_paper_lifecycle
from services.source_visibility import project_source_occurrences, source_visibility


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    async with AsyncSession(get_engine(), expire_on_commit=False) as session:
        yield session


async def seed(db, status=None):
    paper = Paper(id="group-fixture-" + uuid4().hex, source="arxiv", title="Synthetic grouping fixture",
                  authors=[], abstract="Synthetic only.", status="published", materials_extracted=[])
    chunk = Chunk(id=paper.id + "-chunk", paper=paper, title=paper.title, section="Methods",
                  text="Synthetic unchanged original method.", materials_mentioned=[])
    work = Work(canonical_title="Synthetic Work", publication_status="active")
    db.add_all([paper, chunk, work])
    await db.flush()
    if status is not None:
        db.add(PaperWorkMap(paper_id=paper.id, work_id=work.id, relation_type="preprint",
                           match_method="manual", match_score=0.5, review_status=status))
    await db.commit()
    return paper, chunk, work


async def pin(db, chunk, binding):
    status = (await resolve_paper_lifecycle(db, [chunk.paper_id]))[chunk.paper_id]
    occurrences, summary = project_source_occurrences(chunk.materials_mentioned, paper_status=status, linked_materials={})
    visibility = source_visibility(status)
    visibility["warning_codes"] = sorted(set(visibility["warning_codes"] + summary["warning_codes"]))
    return currentness.selection_pin(chunk, material_evidence=occurrences, source_review=visibility, grouping_binding=binding)


@pytest.mark.parametrize("status", [None, "pending", "accepted", "rejected"])
async def test_full_current_mapping_binding_never_promotes_pending_work_to_diversity(db_session, status):
    paper, _, work = await seed(db_session, status)
    bindings = await grouping.resolve_grouping_bindings(db_session, [paper.id, paper.id])
    assert set(bindings) == {paper.id}
    value = bindings[paper.id]
    assert value.paper_id == paper.id and len(value.mapping_sha256) == 64
    assert value.accepted_work_id == (str(work.id) if status == "accepted" else None)
    assert not hasattr(value, "scientific_acceptance") and not hasattr(value, "independent_support_count")
    assert str(work.id) not in repr(value)
    assert await grouping.resolve_grouping_bindings(db_session, {paper.id}) == bindings


async def test_missing_mapping_is_a_source_specific_hash_not_an_unbound_null(db_session):
    paper, _, _ = await seed(db_session)
    other, _, _ = await seed(db_session)
    bindings = await grouping.resolve_grouping_bindings(db_session, [paper.id, other.id])
    assert bindings[paper.id].accepted_work_id is bindings[other.id].accepted_work_id is None
    assert bindings[paper.id].mapping_sha256 != bindings[other.id].mapping_sha256


async def test_digest_is_independent_of_connection_timezone(db_session):
    paper, _, _ = await seed(db_session, "accepted")
    await db_session.execute(text("SET LOCAL TIME ZONE 'UTC'"))
    before = await grouping.resolve_grouping_bindings(db_session, [paper.id])
    await db_session.execute(text("SET LOCAL TIME ZONE 'Asia/Singapore'"))
    assert await grouping.resolve_grouping_bindings(db_session, [paper.id]) == before


@pytest.mark.parametrize("column,new_value", [
    ("relation_type", "published_version"), ("match_method", "metadata"), ("match_score", 0.75),
    ("review_status", "rejected"), ("created_at", datetime(2000, 1, 1, tzinfo=UTC)),
])
async def test_every_current_mapping_field_change_withholds_prepared_grouping(db_session, column, new_value):
    paper, chunk, _ = await seed(db_session, "accepted")
    before = (await grouping.resolve_grouping_bindings(db_session, [paper.id]))[paper.id]
    selected = await pin(db_session, chunk, before)
    assert selected.grouping_sha256 == before.mapping_sha256
    assert (await currentness.check_selected_sources([selected])).status == "unchanged"
    async with AsyncSession(get_engine()) as writer:
        await writer.execute(update(PaperWorkMap).where(PaperWorkMap.paper_id == paper.id).values(**{column: new_value}))
        await writer.commit()
    result = await currentness.check_selected_sources([selected])
    assert result.status == "changed" and result.reason_code == "retrieval_grouping_changed"
    assert (await grouping.resolve_grouping_bindings(db_session, [paper.id]))[paper.id].mapping_sha256 != before.mapping_sha256


async def test_changed_accepted_work_id_with_same_source_text_withholds(db_session):
    paper, chunk, _ = await seed(db_session, "accepted")
    selected = await pin(db_session, chunk, (await grouping.resolve_grouping_bindings(db_session, [paper.id]))[paper.id])
    async with AsyncSession(get_engine()) as writer:
        other = Work(canonical_title="Another synthetic Work", publication_status="active")
        writer.add(other)
        await writer.flush()
        await writer.execute(update(PaperWorkMap).where(PaperWorkMap.paper_id == paper.id).values(work_id=other.id))
        await writer.commit()
    assert (await currentness.check_selected_sources([selected])).reason_code == "retrieval_grouping_changed"


@pytest.mark.parametrize("before_status,after_status", [(None, "accepted"), (None, "pending"), ("pending", "accepted"), ("pending", "rejected")])
async def test_no_map_or_pending_transitions_are_detected_even_without_old_accepted_work(db_session, before_status, after_status):
    paper, chunk, work = await seed(db_session, before_status)
    binding = (await grouping.resolve_grouping_bindings(db_session, [paper.id]))[paper.id]
    assert binding.accepted_work_id is None
    selected = await pin(db_session, chunk, binding)
    async with AsyncSession(get_engine()) as writer:
        if before_status is None:
            writer.add(PaperWorkMap(paper_id=paper.id, work_id=work.id, match_method="manual", review_status=after_status))
        else:
            await writer.execute(update(PaperWorkMap).where(PaperWorkMap.paper_id == paper.id).values(review_status=after_status))
        await writer.commit()
    result = await currentness.check_selected_sources([selected])
    assert result.status == "changed" and result.reason_code == "retrieval_grouping_changed"


async def test_deleted_or_reassigned_paper_mapping_withholds(db_session):
    paper, chunk, _ = await seed(db_session, "accepted")
    selected = await pin(db_session, chunk, (await grouping.resolve_grouping_bindings(db_session, [paper.id]))[paper.id])
    async with AsyncSession(get_engine()) as writer:
        await writer.execute(delete(PaperWorkMap).where(PaperWorkMap.paper_id == paper.id))
        await writer.commit()
    assert (await currentness.check_selected_sources([selected])).reason_code == "retrieval_grouping_changed"


async def test_grouping_recheck_shares_fresh_readonly_repeatable_snapshot(db_session, monkeypatch):
    paper, chunk, _ = await seed(db_session, "accepted")
    selected = await pin(db_session, chunk, (await grouping.resolve_grouping_bindings(db_session, [paper.id]))[paper.id])
    original = grouping.resolve_grouping_bindings
    observed = []
    async def checked(db, paper_ids):
        observed.append({name: (await db.execute(text("SHOW " + name))).scalar_one() for name in
                         ("transaction_isolation", "transaction_read_only", "statement_timeout")})
        return await original(db, paper_ids)
    monkeypatch.setattr(currentness, "resolve_grouping_bindings", checked)
    assert (await currentness.check_selected_sources([selected])).status == "unchanged"
    assert observed == [{"transaction_isolation": "repeatable read", "transaction_read_only": "on", "statement_timeout": "5s"}]


async def test_unchanged_multi_chunk_same_source_pins_are_all_retained(db_session):
    paper, first, _ = await seed(db_session, "accepted")
    second = Chunk(id=paper.id + "-results", paper=paper, title=paper.title, section="Results", text="Synthetic unchanged result.", materials_mentioned=[])
    db_session.add(second)
    await db_session.commit()
    binding = (await grouping.resolve_grouping_bindings(db_session, [paper.id]))[paper.id]
    selected = [await pin(db_session, first, binding), await pin(db_session, second, binding)]
    assert (await currentness.check_selected_sources(selected)).status == "unchanged"
    assert selected[0].grouping_sha256 == selected[1].grouping_sha256
    assert selected[0].input_sha256 != selected[1].input_sha256


async def test_optional_grouping_keeps_legacy_callers_unchanged_and_checks_binding_identity(db_session):
    paper, chunk, _ = await seed(db_session)
    old = await pin(db_session, chunk, None)
    assert old.grouping_sha256 is None and (await currentness.check_selected_sources([old])).status == "unchanged"
    with pytest.raises(currentness.CurrentnessUnavailable):
        await pin(db_session, chunk, grouping.GroupBinding("other-paper", None, "a" * 64))
    with pytest.raises(currentness.CurrentnessUnavailable):
        await pin(db_session, chunk, {"paper_id": paper.id})


async def test_size_preflight_fails_before_mapping_payload_hydration(db_session, monkeypatch):
    paper, _, _ = await seed(db_session, "accepted")
    monkeypatch.setattr(grouping, "MAX_ROW_BYTES", 1)
    statements = []
    original = db_session.execute
    async def record(statement, *args, **kwargs):
        statements.append(str(statement))
        return await original(statement, *args, **kwargs)
    monkeypatch.setattr(db_session, "execute", record)
    with pytest.raises(grouping.RetrievalGroupingError):
        await grouping.resolve_grouping_bindings(db_session, [paper.id])
    assert len(statements) == 1 and "octet_length" in statements[0]


async def test_grouping_failure_never_returns_an_eligible_subset(db_session, monkeypatch):
    paper, chunk, _ = await seed(db_session, "accepted")
    selected = await pin(db_session, chunk, (await grouping.resolve_grouping_bindings(db_session, [paper.id]))[paper.id])
    async def unavailable(*_):
        raise grouping.RetrievalGroupingError("Private raw Work identity must not escape")
    monkeypatch.setattr(currentness, "resolve_grouping_bindings", unavailable)
    result = await currentness.check_selected_sources([selected])
    assert result.status == "unavailable" and result.reason_code == "retrieval_currentness_unavailable"
    assert "Private" not in repr(result)


@pytest.mark.parametrize("identifiers", ["paper", {"paper": True}, [True], [" "], ["x" * 101], ["paper"] * 301])
async def test_malformed_inventory_rejected_before_database_access(identifiers):
    with pytest.raises(grouping.RetrievalGroupingError):
        await grouping.resolve_grouping_bindings(None, identifiers)


async def test_empty_inventory_performs_no_database_access():
    assert await grouping.resolve_grouping_bindings(None, []) == {}


@pytest.mark.parametrize("changes", [{"accepted_work_id": "invalid"}, {"paper_id": " "},
    {"mapping_sha256": "A" * 64}, {"mapping_sha256": True}])
def test_group_binding_is_strict_private_typed_metadata(changes):
    values = {"paper_id": "paper", "accepted_work_id": None, "mapping_sha256": "a" * 64, **changes}
    with pytest.raises(grouping.RetrievalGroupingError):
        grouping.GroupBinding(**values)


async def test_grouping_does_not_override_accepted_work_lifecycle_hold(db_session):
    paper, chunk, work = await seed(db_session, "accepted")
    selected = await pin(db_session, chunk, (await grouping.resolve_grouping_bindings(db_session, [paper.id]))[paper.id])
    async with AsyncSession(get_engine()) as writer:
        await writer.execute(update(Work).where(Work.id == work.id).values(publication_status="corrected"))
        await writer.commit()
    result = await currentness.check_selected_sources([selected])
    assert result.status == "changed" and result.reason_code == "retrieval_source_no_longer_eligible"
