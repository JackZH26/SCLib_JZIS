"""Synthetic source-version registry tests, only on the guarded disposable DB.

These fixtures simulate an authorized binding review; they are not a scholarly
gold set, publication metadata verification, or scientific acceptance.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError

from models.db import Base, get_session_factory
from models.source_provenance_v1 import TABLE_ORDER
from services.source_registry import (
    SOURCE_REGISTRY_VERSION,
    SourceRegistryConflict,
    import_source_provenance_bundle,
    normalize_source_provenance_bundle,
    provenance_sha256,
    resolve_claim_source_witnesses,
    source_occurrence_review_payload,
)
from services.temporal_provenance import result_temporal_provenance


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    async with get_session_factory()() as session:
        yield session


async def add(db, name, **values):
    table = Base.metadata.tables[name]
    return (await db.execute(table.insert().values(**values).returning(table))).mappings().one()


def bundle(paper=None, work=None, claim=None):
    revision, capture = str(uuid4()), str(uuid4())
    return {
        "version": SOURCE_REGISTRY_VERSION,
        "source_revisions": [{
            "id": revision, "paper_id": paper or "arxiv:test", "work_id": str(work) if work else None,
            "revision_key": "arxiv-v2", "provider_revision": "v2", "version_status": "pinned",
            "availability_status": "known_by", "availability_basis": "verified_provider_version_history",
            "source_version_public_at": "2020-02-02T10:00:00Z", "metadata_sha256": "a" * 64,
        }],
        "source_captures": [{
            "id": capture, "source_revision_id": revision, "capture_key": "source-first-capture",
            "captured_at": "2026-09-07T10:00:00Z", "bytes_sha256": "b" * 64, "representation": "arxiv_source",
        }],
        "claim_source_occurrences": ([{
            "id": str(uuid4()), "claim_id": str(claim), "work_id": str(work),
            "source_revision_id": revision, "capture_id": capture, "occurrence_key": "table-2-row-1",
            "locator": {"table": "2", "row": 1}, "binding_status": "pending",
        }] if claim else []),
    }


async def seed(db):
    paper = f"arxiv:sp52-{uuid4().hex}"
    await add(db, "papers", id=paper, source="arxiv", title="Synthetic source registry test",
              authors=[], abstract="", status="published")
    work = (await add(db, "works", canonical_title="Synthetic work"))["id"]
    await add(db, "paper_work_map", paper_id=paper, work_id=work, relation_type="preprint",
              match_method="manual", review_status="accepted")
    material = f"sp52-{uuid4().hex}"
    await add(db, "materials", id=material, formula="MgB2", formula_normalized="MgB2")
    snapshot = (await add(db, "source_snapshots", dataset_version="synthetic-sp52", schema_version="1"))["id"]
    claim = await add(db, "material_claims", material_id=material, paper_id=paper, work_id=work,
                      source_snapshot_id=snapshot, source_record_hash="c" * 64, extractor_version="synthetic",
                      result_status="observed", value_relation="exact", value_kelvin=39.0)
    return bundle(paper, work, claim["id"]), claim


async def reviewed(db, data, claim, *, overrides=None, artifact_overrides=None):
    normalized = normalize_source_provenance_bundle(data)
    review = source_occurrence_review_payload(normalized["source_revisions"][0],
        normalized["source_captures"][0], normalized["claim_source_occurrences"][0], claim)
    review.update(binding_verified=True, version_resolved=True, public_time_verified=True)
    review.update(overrides or {})
    digest = provenance_sha256(review)
    values = dict(kind="review", schema_version="source-occurrence-review/1.0.0", source="synthetic-authorized-review",
                  record_sha256=digest, hash_status="verified", bytes_sha256="d" * 64,
                  access="restricted", metadata={"source_provenance_review": review})
    values.update(artifact_overrides or {})
    artifact = await add(db, "evidence_artifacts", **values)
    data["claim_source_occurrences"][0].update(binding_status="reviewed", review_artifact_id=str(artifact["id"]),
                                             review_artifact_sha256=artifact["record_sha256"])
    return artifact


def test_schema_is_additive_and_unknown_work_not_falsely_bound():
    assert set(TABLE_ORDER) <= set(Base.metadata.tables)
    assert Base.metadata.tables["source_revisions"].c.work_id.nullable
    assert not Base.metadata.tables["claim_source_occurrences"].c.work_id.nullable
    assert Base.metadata.tables["source_revisions"].c.source_version_public_at.nullable
    assert Base.metadata.tables["material_claims"].c.available_at.type.__class__.__name__ == "Date"
    assert "source_version_public_at" not in Base.metadata.tables["source_snapshots"].c


@pytest.mark.parametrize("change", [
    {"source_version_public_at": "2020-02-02"},
    {"source_version_public_at": "2020-02-02T10:00:00"},
    {"source_version_public_at": None},
    {"availability_status": "unknown"},
    {"availability_status": "uncertain"},
    {"version_status": "unresolved"},
    {"provider_revision": None},
    {"paper_id": "x" * 101},
    {"metadata_sha256": "x" * 64},
    {"work_id": "not-a-uuid"},
    {"availability_status": "approved"},
    {"accepted": True},
])
def test_invalid_revision_metadata_fails_without_date_coercion(change):
    data = bundle()
    data["source_revisions"][0].update(change)
    with pytest.raises(ValueError):
        normalize_source_provenance_bundle(data)


def test_unknown_dates_remain_null_and_timezone_hash_is_deterministic():
    data = bundle()
    data["source_revisions"][0].update(availability_status="unknown", source_version_public_at=None)
    one = normalize_source_provenance_bundle(data)
    assert one["source_revisions"][0]["source_version_public_at"] is None
    assert one["source_captures"][0]["captured_at"].year == 2026
    equivalent = deepcopy(data)
    equivalent["source_captures"][0]["captured_at"] = "2026-09-07T18:00:00+08:00"
    assert one == normalize_source_provenance_bundle(equivalent)


@pytest.mark.parametrize("locator", [{}, {"text": "private quotation"}, {"page": True},
                                     {"span_start": 3}, {"span_start": 3, "span_end": 2},
                                     {"page": 1, "url": "https://private.invalid"}])
def test_locators_are_strict_bounded_coordinates(locator):
    data = bundle(work=uuid4(), claim=uuid4())
    data["claim_source_occurrences"][0]["locator"] = locator
    with pytest.raises(ValueError):
        normalize_source_provenance_bundle(data)


def test_bundle_bound_and_unknown_keys_fail_closed():
    data = bundle()
    data["source_revisions"] *= 1001
    with pytest.raises(ValueError, match="bounded"):
        normalize_source_provenance_bundle(data)
    with pytest.raises(ValueError):
        normalize_source_provenance_bundle({"version": SOURCE_REGISTRY_VERSION, "secret": {}})


async def test_dry_run_and_idempotent_live_insert_do_not_commit_caller(db_session):
    data, claim = await seed(db_session)
    report = await import_source_provenance_bundle(db_session, data)
    assert report["inserted"] == 3 and report["committed"] is False
    assert await resolve_claim_source_witnesses(db_session, [claim["id"]]) == {str(claim["id"]): []}
    first = await import_source_provenance_bundle(db_session, data, dry_run=False)
    again = await import_source_provenance_bundle(db_session, deepcopy(data), dry_run=False)
    assert first["inserted"] == 3 and again["verified_existing"] == 3 and again["inserted"] == 0
    witnesses = (await resolve_claim_source_witnesses(db_session, [claim["id"]]))[str(claim["id"])]
    assert result_temporal_provenance(claim_id=str(claim["id"]), witnesses=witnesses)["status"] == "uncertain"


async def test_exact_reviewed_version_is_known_by_not_work_first_public(db_session):
    data, claim = await seed(db_session)
    await reviewed(db_session, data, claim)
    await import_source_provenance_bundle(db_session, data, dry_run=False)
    witnesses = (await resolve_claim_source_witnesses(db_session, [claim["id"]]))[str(claim["id"])]
    envelope = result_temporal_provenance(claim_id=str(claim["id"]), witnesses=witnesses,
                                        paper={"date_submitted": "1900-01-01"})
    assert envelope["status"] == "known_by"
    assert envelope["result_available_at"] == "2020-02-02T10:00:00Z"
    assert envelope["captured_at"] == "2026-09-07T10:00:00Z"
    assert envelope["scientific_acceptance"] is False and envelope["first_appearance_established"] is False
    assert "review_reference" not in str(envelope) and "synthetic-authorized-review" not in str(envelope)


@pytest.mark.parametrize("overrides", [{"claim_id": str(uuid4())}, {"binding_verified": False},
                                       {"locator_sha256": "e" * 64}, {"version": "forged-policy"},
                                       {"public_time_verified": "true"}])
async def test_review_flag_does_not_verify_unlinked_or_malformed_review(db_session, overrides):
    data, claim = await seed(db_session)
    await reviewed(db_session, data, claim, overrides=overrides)
    with pytest.raises(SourceRegistryConflict, match="review artifact"):
        await import_source_provenance_bundle(db_session, data, dry_run=False)
    assert await resolve_claim_source_witnesses(db_session, [claim["id"]]) == {str(claim["id"]): []}


@pytest.mark.parametrize("overrides", [{"schema_version": "unknown-review-policy"},
                                      {"kind": "policy"},
                                      {"hash_status": "unavailable", "bytes_sha256": None}])
async def test_wrong_artifact_kind_policy_or_unverified_bytes_cannot_qualify(db_session, overrides):
    data, claim = await seed(db_session)
    await reviewed(db_session, data, claim, artifact_overrides=overrides)
    with pytest.raises(SourceRegistryConflict, match="review artifact"):
        await import_source_provenance_bundle(db_session, data, dry_run=False)


@pytest.mark.parametrize("mutation", ["review", "claim", "work_mapping"])
async def test_mutable_upstream_review_or_claim_or_work_drift_invalidates_witness(db_session, mutation):
    data, claim = await seed(db_session)
    artifact = await reviewed(db_session, data, claim)
    await import_source_provenance_bundle(db_session, data, dry_run=False)
    if mutation == "review":
        table = Base.metadata.tables["evidence_artifacts"]
        await db_session.execute(table.update().where(table.c.id == artifact["id"]).values(metadata={}))
    elif mutation == "claim":
        table = Base.metadata.tables["material_claims"]
        await db_session.execute(table.update().where(table.c.id == claim["id"]).values(value_kelvin=40))
    else:
        table = Base.metadata.tables["paper_work_map"]
        await db_session.execute(table.update().where(table.c.paper_id == claim["paper_id"]).values(review_status="rejected"))
    witnesses = (await resolve_claim_source_witnesses(db_session, [claim["id"]]))[str(claim["id"])]
    assert result_temporal_provenance(claim_id=str(claim["id"]), witnesses=witnesses)["status"] == "uncertain"


async def test_changed_immutable_content_fails_and_preserves_original(db_session):
    data, claim = await seed(db_session)
    await import_source_provenance_bundle(db_session, data, dry_run=False)
    changed = deepcopy(data)
    changed["source_revisions"][0]["metadata_sha256"] = "e" * 64
    with pytest.raises(SourceRegistryConflict, match="immutable"):
        await import_source_provenance_bundle(db_session, changed, dry_run=False)
    assert (await import_source_provenance_bundle(db_session, data, dry_run=False))["verified_existing"] == 3


async def test_same_provider_revision_cannot_be_rekeyed_to_different_identity(db_session):
    data, _ = await seed(db_session)
    await import_source_provenance_bundle(db_session, data, dry_run=False)
    changed = deepcopy(data)
    changed["source_revisions"][0].update(id=str(uuid4()), revision_key="renamed-v2")
    changed["source_captures"] = []
    changed["claim_source_occurrences"] = []
    with pytest.raises(SourceRegistryConflict):
        await import_source_provenance_bundle(db_session, changed, dry_run=False)


async def test_conflicting_capture_bytes_rejected_without_overwrite(db_session):
    data, _ = await seed(db_session)
    await import_source_provenance_bundle(db_session, data, dry_run=False)
    changed = deepcopy(data)
    changed["source_revisions"] = []
    changed["claim_source_occurrences"] = []
    changed["source_captures"][0].update(id=str(uuid4()), capture_key="second-capture", bytes_sha256="e" * 64)
    with pytest.raises(SourceRegistryConflict, match="conflicting bytes"):
        await import_source_provenance_bundle(db_session, changed, dry_run=False)


async def test_conflicting_bytes_inserted_outside_writer_invalidate_read_witness(db_session):
    data, claim = await seed(db_session)
    await reviewed(db_session, data, claim)
    await import_source_provenance_bundle(db_session, data, dry_run=False)
    changed = deepcopy(data)
    changed["source_captures"][0].update(id=str(uuid4()), capture_key="external-conflict", bytes_sha256="e" * 64)
    row = normalize_source_provenance_bundle(changed)["source_captures"][0]
    await db_session.execute(Base.metadata.tables["source_captures"].insert().values(**row))
    witnesses = (await resolve_claim_source_witnesses(db_session, [claim["id"]]))[str(claim["id"])]
    assert result_temporal_provenance(claim_id=str(claim["id"]), witnesses=witnesses)["status"] == "uncertain"


async def test_registry_resolver_bound_never_silently_accepts_first_100(db_session):
    data, claim = await seed(db_session)
    base = data["claim_source_occurrences"][0]
    data["claim_source_occurrences"] = [dict(base, id=str(uuid4()), occurrence_key=f"occurrence-{index}")
                                         for index in range(102)]
    await import_source_provenance_bundle(db_session, data, dry_run=False)
    witnesses = (await resolve_claim_source_witnesses(db_session, [claim["id"]]))[str(claim["id"])]
    assert len(witnesses) == 101
    envelope = result_temporal_provenance(claim_id=str(claim["id"]), witnesses=witnesses)
    assert envelope["status"] == "uncertain" and envelope["assessment_complete"] is False


@pytest.mark.parametrize("name", TABLE_ORDER)
@pytest.mark.parametrize("operation", ["update", "delete", "truncate"])
async def test_sql_registry_mutation_is_blocked(db_session, name, operation):
    data, _ = await seed(db_session)
    await import_source_provenance_bundle(db_session, data, dry_run=False)
    table = Base.metadata.tables[name]
    statement = {"update": table.update().values(record_sha256="e" * 64),
                 "delete": table.delete(), "truncate": sa.text(f"TRUNCATE {name} CASCADE")}[operation]
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(statement)


@pytest.mark.parametrize("field", ["work_id", "capture_id", "source_revision_id", "claim_id"])
async def test_sql_composite_association_cannot_cross_work_or_revision(db_session, field):
    data, _ = await seed(db_session)
    other, _ = await seed(db_session)
    await import_source_provenance_bundle(db_session, data, dry_run=False)
    await import_source_provenance_bundle(db_session, other, dry_run=False)
    row = normalize_source_provenance_bundle(data)["claim_source_occurrences"][0]
    row.update(id=uuid4(), occurrence_key="crossed")
    row[field] = normalize_source_provenance_bundle(other)["claim_source_occurrences"][0][field]
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(Base.metadata.tables["claim_source_occurrences"].insert().values(**row))


async def test_claim_can_have_explicit_occurrences_in_multiple_versions(db_session):
    data, claim = await seed(db_session)
    await reviewed(db_session, data, claim)
    await import_source_provenance_bundle(db_session, data, dry_run=False)
    later = bundle(claim["paper_id"], claim["work_id"], claim["id"])
    later["source_revisions"][0].update(revision_key="arxiv-v3", provider_revision="v3",
                                        source_version_public_at="2021-01-01T10:00:00Z")
    await reviewed(db_session, later, claim)
    await import_source_provenance_bundle(db_session, later, dry_run=False)
    witnesses = (await resolve_claim_source_witnesses(db_session, [claim["id"]]))[str(claim["id"])]
    assert len(witnesses) == 2 and len({item.claim_id for item in witnesses}) == 1
    assert result_temporal_provenance(claim_id=str(claim["id"]), witnesses=witnesses)["result_available_at"].startswith("2020-")


async def test_two_reviewed_locations_same_capture_remain_known_by(db_session):
    data, claim = await seed(db_session)
    await reviewed(db_session, data, claim)
    await import_source_provenance_bundle(db_session, data, dry_run=False)
    another = deepcopy(data)
    another["claim_source_occurrences"][0].update(
        id=str(uuid4()), occurrence_key="figure-3", locator={"figure": "3"}, binding_status="pending",
        review_artifact_id=None, review_artifact_sha256=None,
    )
    await reviewed(db_session, another, claim)
    await import_source_provenance_bundle(db_session, another, dry_run=False)
    witnesses = (await resolve_claim_source_witnesses(db_session, [claim["id"]]))[str(claim["id"])]
    envelope = result_temporal_provenance(claim_id=str(claim["id"]), witnesses=witnesses)
    reversed_envelope = result_temporal_provenance(claim_id=str(claim["id"]), witnesses=list(reversed(witnesses)))
    assert envelope == reversed_envelope and envelope["status"] == "known_by"
    assert len(envelope["witnesses"]) == 2
    assert len({item["capture_id"] for item in envelope["witnesses"]}) == 1


async def test_missing_and_malformed_resolver_ids(db_session):
    missing = str(uuid4())
    assert await resolve_claim_source_witnesses(db_session, [missing]) == {missing: []}
    assert await resolve_claim_source_witnesses(db_session, []) == {}
    for ids in (["invalid"], [missing] * 501, "not-an-array"):
        with pytest.raises(ValueError):
            await resolve_claim_source_witnesses(db_session, ids)


async def test_unknown_work_capture_is_retained_without_result_binding(db_session):
    data, _ = await seed(db_session)
    data["source_revisions"][0].update(work_id=None, provider_revision=None, version_status="unresolved",
                                     availability_status="unknown", source_version_public_at=None)
    data["claim_source_occurrences"] = []
    assert (await import_source_provenance_bundle(db_session, data, dry_run=False))["inserted"] == 2


async def test_unaccepted_work_mapping_and_capture_before_public_time_fail(db_session):
    data, claim = await seed(db_session)
    table = Base.metadata.tables["paper_work_map"]
    await db_session.execute(table.update().where(table.c.paper_id == claim["paper_id"]).values(review_status="pending"))
    with pytest.raises(SourceRegistryConflict, match="accepted bibliographic"):
        await import_source_provenance_bundle(db_session, data, dry_run=False)
    await db_session.execute(table.update().where(table.c.paper_id == claim["paper_id"]).values(review_status="accepted"))
    data["source_captures"][0]["captured_at"] = datetime(1900, 1, 1, tzinfo=UTC)
    with pytest.raises(SourceRegistryConflict, match="precedes"):
        await import_source_provenance_bundle(db_session, data, dry_run=False)
