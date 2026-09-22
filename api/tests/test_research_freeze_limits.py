"""Guarded ML04 wire-budget and historical-inspection adversaries.

Large rows are synthetic compressible strings. Malformed assembly fixtures are
never committed and never disable triggers or deferred checks. SQL spies fail
before an unbounded JSON body can reach the driver.
"""
from __future__ import annotations

import hashlib
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from models.db import Base
from services import research_freeze as freeze
from services import research_release_manifest as contract
from tests.test_research_freeze import approved, notice_approved, release_pair, seed
from tests.test_research_freeze import db_session as _serializable_db_session

db_session = _serializable_db_session
_MIB = 1024 * 1024


async def epoch(db):
    return (await db.execute(sa.text("SELECT epoch FROM research_integrity_epoch WHERE id=1"))).scalar_one()


def forbid_body(monkeypatch, db, table, *, stored=False):
    original = db.execute
    observed = []

    async def execute(statement, *args, **kwargs):
        sql = str(statement)
        if f"FROM {table}" in sql:
            observed.append(sql)
            if "octet_length" not in sql:
                if stored or f"SELECT to_jsonb({table})" in sql:
                    pytest.fail(f"{table} JSON body was requested before rejecting its expanded size")
        return await original(statement, *args, **kwargs)

    monkeypatch.setattr(db, "execute", execute)
    return observed


async def test_expanded_oversized_catalogue_row_rejected_before_json_body_fetch(db_session, monkeypatch):
    fixture = await seed(db_session)
    materials = Base.metadata.tables["materials"]
    await db_session.execute(materials.update().where(materials.c.id == fixture["material"]).values(
        anomaly_context={"synthetic_padding": "x" * (8 * _MIB)}))
    before_epoch = await epoch(db_session)
    with monkeypatch.context() as context:
        queries = forbid_body(context, db_session, "materials")
        with pytest.raises(freeze.ResearchFreezeError, match="closure row byte limit"):
            await freeze.preview_research_release(db_session, **fixture["args"])
    assert queries and all("octet_length" in query for query in queries)
    assert await epoch(db_session) == before_epoch


async def test_aggregate_wire_budget_spans_catalogue_tables_before_next_body_fetch(db_session, monkeypatch):
    fixture = await seed(db_session)
    materials, papers = Base.metadata.tables["materials"], Base.metadata.tables["papers"]
    await db_session.execute(materials.update().where(materials.c.id == fixture["material"]).values(
        anomaly_context={"synthetic_padding": "m" * (5 * _MIB)}))
    await db_session.execute(papers.update().where(papers.c.id == fixture["paper"]).values(
        abstract="p" * (4 * _MIB)))
    before_epoch = await epoch(db_session)
    with monkeypatch.context() as context:
        queries = forbid_body(context, db_session, "papers")
        with pytest.raises(freeze.ResearchFreezeError, match="combined closure row byte limit"):
            await freeze.preview_research_release(db_session, **fixture["args"])
    assert queries and all("octet_length" in query for query in queries)
    assert await epoch(db_session) == before_epoch


async def test_repeated_reference_does_not_double_count_same_row_budget(db_session):
    fixture = await seed(db_session)
    materials = Base.metadata.tables["materials"]
    await db_session.execute(materials.update().where(materials.c.id == fixture["material"]).values(
        anomaly_context={"synthetic_padding": "m" * (5 * _MIB)}))
    budget = {}
    first = await freeze._fetch(db_session, "materials", identifiers=[fixture["material"]], byte_budget=budget)
    before = dict(budget)
    second = await freeze._fetch(db_session, "materials", identifiers=[fixture["material"]], byte_budget=budget)
    assert first == second and budget == before and len(budget) == 1


async def test_oversized_uncommitted_manifest_rejected_before_stored_payload_read(db_session, monkeypatch):
    fixture = await seed(db_session)
    identifier = uuid4()
    # This intentionally incomplete assembly is rolled back by the fixture;
    # it never reaches its mandatory deferred completeness check at commit.
    await db_session.execute(Base.metadata.tables["research_releases"].insert().values(
        id=identifier, dataset_snapshot_id=fixture["args"]["dataset_id"],
        manifest={"rows": [], "synthetic_padding": "x" * (9 * _MIB)},
        manifest_sha256=hashlib.sha256(identifier.bytes).hexdigest(), bundle_sha256="a" * 64,
        closure_policy_version=contract.CLOSURE_POLICY_VERSION))
    with monkeypatch.context() as context:
        queries = forbid_body(context, db_session, "research_releases", stored=True)
        with pytest.raises(freeze.ResearchFreezeError, match="stored release row byte limit"):
            await freeze._stored(db_session, "research_releases", identifier)
    assert queries and all("octet_length" in query for query in queries)


async def test_oversized_uncommitted_pin_rejected_before_pin_payload_read(db_session, monkeypatch):
    fixture = await seed(db_session)
    await db_session.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
    materials = Base.metadata.tables["materials"]
    await db_session.execute(materials.update().where(materials.c.id == fixture["material"]).values(
        anomaly_context={"synthetic_padding": "x" * (8 * _MIB)}))
    identifier = uuid4()
    # Build this deliberately incomplete, never-committed assembly entirely in
    # SQL, so even test setup does not request the oversized JSON from PostgreSQL.
    await db_session.execute(sa.text("""
        INSERT INTO research_releases(id,dataset_snapshot_id,manifest,manifest_sha256,bundle_sha256,closure_policy_version)
        SELECT :release,:dataset,jsonb_build_object('rows',jsonb_build_array(jsonb_build_object(
            'table','materials','row_id',m.id,'data',to_jsonb(m),'row_sha256',repeat('a',64)))),
            :manifest_hash,repeat('b',64),:policy FROM materials m WHERE m.id=:material
    """), {"release": identifier, "dataset": fixture["args"]["dataset_id"],
           "material": fixture["material"], "manifest_hash": hashlib.sha256(identifier.bytes).hexdigest(),
           "policy": contract.CLOSURE_POLICY_VERSION})
    await db_session.execute(sa.text("""
        INSERT INTO research_release_pins(id,release_id,table_name,row_id,row_data,row_sha256)
        SELECT :pin,:release,'materials',m.id,to_jsonb(m),repeat('a',64) FROM materials m WHERE m.id=:material
    """), {"pin": uuid4(), "release": identifier, "material": fixture["material"]})
    with monkeypatch.context() as context:
        queries = forbid_body(context, db_session, "research_release_pins", stored=True)
        with pytest.raises(freeze.ResearchFreezeError, match="stored release pin budget"):
            await freeze._verify_pins(db_session, {"id": identifier})
    assert queries and all("octet_length" in query for query in queries)


async def test_inspection_artifact_container_captured_before_first_await(db_session, monkeypatch):
    fixture = await seed(db_session)
    _, arguments = await approved(db_session, fixture)
    report = await freeze.freeze_research_release(db_session, **arguments, dry_run=False)
    await db_session.commit()
    original = freeze._stored
    payloads = dict(arguments["artifact_bytes"])
    called = False

    async def mutate_caller_then_read(*args, **kwargs):
        nonlocal called
        if not called:
            called = True
            payloads.clear()
        return await original(*args, **kwargs)

    monkeypatch.setattr(freeze, "_stored", mutate_caller_then_read)
    historical = await freeze.inspect_research_release(db_session, release_id=report["release_id"],
        expected_manifest_sha256=report["manifest_sha256"], artifact_bytes=payloads)
    assert called and payloads == {}
    assert historical["manifest"] == report["manifest"]


async def test_freeze_uses_captured_dataset_identity_after_first_await(db_session, monkeypatch):
    fixture = await seed(db_session)
    _, arguments = await approved(db_session, fixture)

    class MutableIdentifier:
        value = fixture["args"]["dataset_id"]

        def __str__(self):
            return str(self.value)

    identifier = MutableIdentifier()
    original = freeze._session

    async def mutate_identifier_then_check(db):
        identifier.value = uuid4()
        await original(db)

    monkeypatch.setattr(freeze, "_session", mutate_identifier_then_check)
    result = await freeze.freeze_research_release(db_session, **{**arguments, "dataset_id": identifier})
    assert result["manifest"]["dataset_id"] == str(fixture["args"]["dataset_id"])
    assert result["dry_run"] is True


async def test_retained_valid_notice_has_precisely_limited_verification_flags(db_session):
    old, new, arguments = await release_pair(db_session)
    notice_arguments = await notice_approved(db_session, old, new)
    notice = await freeze.append_release_notice(db_session, **notice_arguments, dry_run=False)
    await db_session.commit()
    before_epoch = await epoch(db_session)
    historical = await freeze.inspect_research_release(db_session, release_id=old["release_id"],
        expected_manifest_sha256=old["manifest_sha256"], artifact_bytes=arguments["artifact_bytes"])
    retained = next(item for item in historical["notices"] if str(item["id"]) == notice["notice_id"])
    assert retained["review_document_binding_verified"] is True
    assert retained["external_review_bytes_rechecked"] is False
    assert retained["reviewer_authority_authenticated"] is False
    assert historical["current_eligibility_reassessed"] is historical["scientific_acceptance"] is False
    assert await epoch(db_session) == before_epoch


@pytest.mark.parametrize("corruption", ["record_hash", "review_hash", "reason", "review_flag", "review_bytes_hash"])
async def test_direct_sql_forged_retained_notice_is_not_reported_as_valid(db_session, corruption):
    old, new, arguments = await release_pair(db_session)
    notice_arguments = await notice_approved(db_session, old, new, mutate_review=(
        (lambda document: document.update(restricted_internal_notice_approved=1))
        if corruption == "review_flag" else None))
    artifact_table = Base.metadata.tables["evidence_artifacts"]
    if corruption == "review_bytes_hash":
        await db_session.execute(artifact_table.update().where(
            artifact_table.c.id == notice_arguments["review_artifact_id"]).values(bytes_sha256="f" * 64))
    artifact = (await db_session.execute(sa.select(artifact_table).where(
        artifact_table.c.id == notice_arguments["review_artifact_id"]))).mappings().one()
    body = {"release_id": old["release_id"], "kind": "superseded", "successor_release_id": new["release_id"],
            "review_artifact_id": str(notice_arguments["review_artifact_id"]), "review_artifact_kind": "review",
            "review_sha256": "e" * 64 if corruption == "review_hash" else artifact["record_sha256"],
            "reason_code": "changed_reason" if corruption == "reason" else notice_arguments["reason_code"]}
    values = {**body, "id": uuid4(), "record_sha256": "d" * 64 if corruption == "record_hash" else contract.digest(body)}
    for field in ("release_id", "successor_release_id", "review_artifact_id"):
        values[field] = UUID(values[field])
    # Ordinary direct INSERT uses all normal FK/immutability guards, proving
    # retained inspection independently checks content beyond row shape.
    await db_session.execute(Base.metadata.tables["research_release_notices"].insert().values(**values))
    await db_session.commit()
    before_epoch = await epoch(db_session)
    with pytest.raises(freeze.ResearchFreezeError, match="retained notice review binding invalid"):
        await freeze.inspect_research_release(db_session, release_id=old["release_id"],
            expected_manifest_sha256=old["manifest_sha256"], artifact_bytes=arguments["artifact_bytes"])
    assert await epoch(db_session) == before_epoch
