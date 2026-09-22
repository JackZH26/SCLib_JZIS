"""RG02 text-free immutable lineage, exclusively synthetic disposable data."""
from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import Base, Chunk, get_session_factory
from services import rag_evidence as service
from services.rag_evidence_contract import (
    VERSION,
    extraction_projection,
    validate_candidate,
    validate_evidence_descriptor,
)
from tests.test_research_freeze import add


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    async with get_session_factory()() as session:
        yield session


async def seed(db, *, record=None, text="Synthetic derived quantity Tc < 100 K."):
    token = uuid4().hex
    paper, chunk = "rag-evidence:" + token, "rag-evidence-chunk:" + token
    record = record or {"formula": "MgB2", "tc_kelvin": "<100 K", "evidence_role": "primary_theoretical", "source_quote": "PRIVATE ORIGINAL WORDING"}
    await add(db, "papers", id=paper, source="arxiv", title="Synthetic lineage fixture", authors=[],
              abstract="", materials_extracted=[record])
    await add(db, "chunks", id=chunk, paper_id=paper, text=text, materials_mentioned=[record])
    return chunk, {"version": VERSION, "chunk_kind": "derived_fact", "parent_record": record,
                   "extraction_version": "synthetic-extraction/1", "rendering_version": service.CURRENT_FACT_RENDERER_VERSION}


async def chunk_row(db, identifier):
    return (await db.execute(sa.select(Chunk).where(Chunk.id == identifier))).scalar_one()


async def counts(db):
    return [await db.scalar(sa.select(sa.func.count()).select_from(Base.metadata.tables[name]))
            for name in ("rag_extraction_revisions", "rag_evidence_revisions", "chunk_evidence_current")]


def test_projection_keeps_raw_bounds_negative_and_removes_all_prose():
    value = extraction_projection({"tc_kelvin": 100, "source_context": "PRIVATE", "raw_extraction": {
        "tc_kelvin": "< 100 K", "outcome": "not_detected", "source_quote": "SECRET"}})
    assert value["quantities"]["tc_kelvin"]["relation"] == "lt"
    assert value["quantities"]["tc_kelvin"]["value"] is None
    assert value["positive_interpretation_blocked"] is True
    assert all(text not in str(value) for text in ("PRIVATE", "SECRET", "source_context", "raw_value", "source_quote"))


def test_projection_conflicting_origin_and_malformed_outcomes_fail_closed():
    value = extraction_projection({"evidence_role": "primary_experimental", "outcome": 1,
        "raw_extraction": {"evidence_role": "primary_theoretical"}})
    assert value["knowledge_origin"] == "Unknown" and value["classification_status"] == "conflicted"
    assert value["positive_interpretation_blocked"] is True


def test_projection_keeps_malformed_origin_validation_flags_without_raw_record():
    value = extraction_projection({"method": "resistivity", "validation_flags": ["knowledge_origin:invalid_type"]})
    assert value["knowledge_origin"] == "Unknown" and value["classification_status"] == "conflicted"


@pytest.mark.parametrize("change", [{"permission_status": "allowed"}, {"root_status": "resolved"},
    {"parent_result_id": str(uuid4())}, {"source_locator": {"source_quote": "private"}},
    {"source_locator": {"page": True}}, {"source_locator": {"span_start": 1}}, {"parent_record": None}])
def test_candidate_cannot_assert_authority_or_unknown_fields(change):
    candidate = {"version": VERSION, "chunk_kind": "derived_fact", "parent_record": {"tc_kelvin": 39},
                 "extraction_version": "synthetic/1", "rendering_version": "synthetic/1", **change}
    with pytest.raises(ValueError):
        validate_candidate(candidate)


async def test_dry_run_idempotence_no_hidden_commit_and_sanitized_descriptor(db_session):
    chunk, candidate = await seed(db_session)
    before = await counts(db_session)
    rehearsal = await service.register_chunk_evidence(db_session, chunk_id=chunk, candidate=candidate)
    assert rehearsal["committed"] is False and await counts(db_session) == before
    first = await service.register_chunk_evidence(db_session, chunk_id=chunk, candidate=candidate, dry_run=False)
    epoch = await db_session.scalar(sa.text("SELECT epoch FROM research_integrity_epoch WHERE id=1"))
    again = await service.register_chunk_evidence(db_session, chunk_id=chunk, candidate=deepcopy(candidate), dry_run=False)
    assert first == again and first["evidence_revision_id"] == rehearsal["evidence_revision_id"]
    assert await db_session.scalar(sa.text("SELECT epoch FROM research_integrity_epoch WHERE id=1")) == epoch
    await service.bind_chunk_evidence(db_session, chunk_id=chunk, evidence_revision_id=first["evidence_revision_id"], dry_run=False)
    assert await db_session.scalar(sa.text("SELECT epoch FROM research_integrity_epoch WHERE id=1")) == epoch
    assert await counts(db_session) == [before[0] + 1, before[1] + 1, before[2] + 1]
    descriptor = (await service.resolve_chunk_evidence(db_session, [await chunk_row(db_session, chunk)]))[chunk]
    assert descriptor["currentness"] == "current" and descriptor["chunk_kind"] == "derived_fact"
    assert descriptor["support_eligible"] is descriptor["scientific_acceptance"] is False
    assert "PRIVATE" not in str(descriptor) and "projection_json" not in str(descriptor)
    assert validate_evidence_descriptor(descriptor) == descriptor
    await db_session.rollback()
    assert await db_session.scalar(sa.select(Chunk.id).where(Chunk.id == chunk)) is None


@pytest.mark.parametrize("kind", ["original_passage", "abstract"])
async def test_original_kinds_have_no_fabricated_parent_or_permission(db_session, kind):
    chunk, _ = await seed(db_session)
    candidate = {"version": VERSION, "chunk_kind": kind, "source_locator": {"page": 2, "section": "Methods"},
                 "permission_status": "restricted"}
    result = await service.register_chunk_evidence(db_session, chunk_id=chunk, candidate=candidate, dry_run=False)
    assert result["parent_result_revision_id"] is None
    descriptor = (await service.resolve_chunk_evidence(db_session, [await chunk_row(db_session, chunk)]))[chunk]
    assert descriptor["permission_status"] == "restricted" and descriptor["root_status"] == "unresolved"


async def test_parent_must_match_real_current_chunk_record(db_session):
    chunk, candidate = await seed(db_session)
    candidate["parent_record"] = {"tc_kelvin": 999}
    with pytest.raises(service.RagEvidenceError, match="actual current"):
        await service.register_chunk_evidence(db_session, chunk_id=chunk, candidate=candidate, dry_run=False)


@pytest.mark.parametrize("change", [{"chunk_kind": []}, {"permission_status": {}}, {"currentness": []},
    {"support_eligible": True}, {"parent_result_revision_id": None}, {"source_quote": "PRIVATE"}])
async def test_descriptor_malformed_shapes_and_false_authority_raise_value_error(db_session, change):
    chunk, candidate = await seed(db_session)
    await service.register_chunk_evidence(db_session, chunk_id=chunk, candidate=candidate, dry_run=False)
    descriptor = (await service.resolve_chunk_evidence(db_session, [await chunk_row(db_session, chunk)]))[chunk]
    with pytest.raises(ValueError):
        validate_evidence_descriptor({**descriptor, **change})


@pytest.mark.parametrize("raw", ["<100 K", "100 ± 2 K", [90, 100]])
async def test_valid_bounds_uncertainty_intervals_and_dimensionless_project_to_sql(db_session, raw):
    chunk, candidate = await seed(db_session, record={"tc_kelvin": 100, "lambda_eph": 2.3,
        "raw_extraction": {"tc_kelvin": raw, "not_detected": True}})
    receipt = await service.register_chunk_evidence(db_session, chunk_id=chunk, candidate=candidate, dry_run=False)
    table = Base.metadata.tables["rag_extraction_revisions"]
    projection = await db_session.scalar(sa.select(table.c.projection_json).where(table.c.id == receipt["parent_result_revision_id"]))
    assert projection["positive_interpretation_blocked"] is True
    assert projection["quantities"]["lambda_eph"]["unit_basis"] == "dimensionless"


async def test_optional_capture_must_belong_to_exact_paper_without_granting_a_root(db_session):
    from services.source_registry import import_source_provenance_bundle
    from tests.test_source_registry import bundle

    chunk, _ = await seed(db_session)
    paper = (await chunk_row(db_session, chunk)).paper_id
    data = bundle(paper=paper)
    await import_source_provenance_bundle(db_session, data, dry_run=False)
    capture = data["source_captures"][0]["id"]
    candidate = {"version": VERSION, "chunk_kind": "original_passage", "source_capture_id": capture}
    await service.register_chunk_evidence(db_session, chunk_id=chunk, candidate=candidate, dry_run=False)
    descriptor = (await service.resolve_chunk_evidence(db_session, [await chunk_row(db_session, chunk)]))[chunk]
    assert descriptor["source_capture_id"] == capture and descriptor["root_status"] == "unresolved"
    wrong_chunk, _ = await seed(db_session)
    with pytest.raises(DBAPIError, match="capture_paper_mismatch"):
        async with db_session.begin_nested():
            await service.register_chunk_evidence(db_session, chunk_id=wrong_chunk, candidate=candidate, dry_run=False)


@pytest.mark.parametrize("operation", ["update", "delete", "truncate"])
@pytest.mark.parametrize("name", ["rag_extraction_revisions", "rag_evidence_revisions"])
async def test_history_rejects_mutation_and_truncate(db_session, name, operation):
    chunk, candidate = await seed(db_session)
    await service.register_chunk_evidence(db_session, chunk_id=chunk, candidate=candidate, dry_run=False)
    command = {"update": f"UPDATE {name} SET record_sha256=record_sha256", "delete": f"DELETE FROM {name}", "truncate": f"TRUNCATE {name} CASCADE"}[operation]
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(sa.text(command))


async def test_chunk_update_delete_preserve_history_but_clear_current_pointer(db_session):
    chunk, candidate = await seed(db_session)
    first = await service.register_chunk_evidence(db_session, chunk_id=chunk, candidate=candidate, dry_run=False)
    history = await counts(db_session)
    await db_session.execute(sa.update(Chunk).where(Chunk.id == chunk).values(text="Synthetic revised text"))
    assert await counts(db_session) == [history[0], history[1], history[2] - 1]
    with pytest.raises(DBAPIError, match="exact_live_chunk"):
        async with db_session.begin_nested():
            await service.bind_chunk_evidence(db_session, chunk_id=chunk, evidence_revision_id=first["evidence_revision_id"], dry_run=False)
    second = await service.register_chunk_evidence(db_session, chunk_id=chunk, candidate=candidate, dry_run=False)
    assert first["evidence_revision_id"] != second["evidence_revision_id"]
    await db_session.execute(sa.delete(Chunk).where(Chunk.id == chunk))
    assert (await counts(db_session))[:2] == [history[0], history[1] + 1]


async def test_restricted_history_survives_pointer_update_delete_and_same_identity_reinsert(db_session):
    chunk, _ = await seed(db_session)
    candidate = {"version": VERSION, "chunk_kind": "original_passage", "permission_status": "restricted"}
    first = await service.register_chunk_evidence(db_session, chunk_id=chunk, candidate=candidate, dry_run=False)
    current = await chunk_row(db_session, chunk)
    paper = current.paper_id
    await db_session.execute(sa.update(Chunk).where(Chunk.id == chunk).values(text="Changed restricted source"))
    await db_session.refresh(current)
    stale = (await service.resolve_chunk_evidence(db_session, [current]))[chunk]
    assert stale["currentness"] == "stale" and stale["permission_status"] == "restricted"
    assert stale["evidence_revision_id"] == first["evidence_revision_id"]
    assert "current_pointer_invalidated" in stale["warning_codes"]
    await db_session.execute(sa.delete(Chunk).where(Chunk.id == chunk))
    db_session.expunge(current)
    await add(db_session, "chunks", id=chunk, paper_id=paper, text="Reinserted restricted source", materials_mentioned=[])
    restored = await chunk_row(db_session, chunk)
    stale = (await service.resolve_chunk_evidence(db_session, [restored]))[chunk]
    assert stale["currentness"] == "stale" and stale["permission_status"] == "restricted"
    # An automatic unreviewed rebuild has no authority to clear a restriction.
    await service.register_chunk_evidence(db_session, chunk_id=chunk,
        candidate={"version": VERSION, "chunk_kind": "abstract"}, dry_run=False)
    rebuilt = (await service.resolve_chunk_evidence(db_session, [restored]))[chunk]
    assert rebuilt["currentness"] == "current" and rebuilt["permission_status"] == "restricted"


async def test_source_correction_and_renderer_change_mark_immutable_lineage_stale(db_session):
    chunk, candidate = await seed(db_session)
    await service.register_chunk_evidence(db_session, chunk_id=chunk, candidate=candidate, dry_run=False)
    row = await chunk_row(db_session, chunk)
    stale = (await service.resolve_chunk_evidence(db_session, [row], rendering_version="new/1"))[chunk]
    assert stale["currentness"] == "stale" and "renderer_version_changed" in stale["warning_codes"]
    await db_session.execute(sa.text("UPDATE papers SET status='corrected' WHERE id=:id"), {"id": row.paper_id})
    stale = (await service.resolve_chunk_evidence(db_session, [row]))[chunk]
    assert stale["currentness"] == "stale" and "source_snapshot_changed" in stale["warning_codes"]


async def test_missing_or_oversized_current_chunk_does_not_become_unrestricted_legacy(db_session):
    chunk, _ = await seed(db_session, text="x" * (1024 * 1024 + 1))
    result = (await service.resolve_chunk_evidence(db_session, [await chunk_row(db_session, chunk)]))[chunk]
    assert result["currentness"] == "stale" and result["warning_codes"] == ["current_chunk_unavailable"]


@pytest.mark.parametrize("field,value", [("knowledge_origin", None), ("source_context", "PRIVATE"),
    ("quantities", {"tc_kelvin": {"raw_value": "PRIVATE"}})])
async def test_direct_sql_cannot_persist_arbitrary_prose_or_missing_controlled_projection(db_session, field, value):
    chunk, candidate = await seed(db_session)
    await service.register_chunk_evidence(db_session, chunk_id=chunk, candidate=candidate, dry_run=False)
    table = Base.metadata.tables["rag_extraction_revisions"]
    row = dict((await db_session.execute(sa.select(table))).mappings().first())
    row["id"] = uuid4()
    row["projection_json"] = {**row["projection_json"], field: value}
    with pytest.raises(DBAPIError, match="closed_projection"):
        async with db_session.begin_nested():
            await db_session.execute(table.insert().values(**row))


def test_no_historical_foreign_key_targets_mutable_chunks_or_old_capsule_expansion():
    from services.research_release_spec import SPEC
    for name in ("rag_extraction_revisions", "rag_evidence_revisions"):
        assert all(fk.column.table.name != "chunks" for fk in Base.metadata.tables[name].foreign_keys)
        assert name not in SPEC
    assert "evidence_candidate" not in Base.metadata.tables["chunks"].c
