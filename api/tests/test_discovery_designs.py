"""Owned native PostgreSQL ledger proof; scientific fixtures are synthetic."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import Base
from services import discovery_designs as service
from services import discovery_design_contract as contract
from services.research_access import ResearchAccessDenied
from services.research_release_manifest import canonical, digest
from services.source_property_pending import SourcePropertyConflict, SourcePropertyNotFound
from tests.research_access_helpers import research_operator, research_user, revoke_research_grant
from tests.test_discovery_design_contract import operation
from tests.test_material_field_cases import retained
from tests.test_research_freeze import db_session, add, seed, state


async def request(db, actor, *, kind="unanchored", material_id=None, record_index=None, property_id=None):
    ctx = await service.context(db, actor_user_id=actor["id"], kind=kind, material_id=material_id,
                                record_index=record_index, property_id=property_id)
    return operation(baseline=ctx["baseline"]), ctx


async def save(db, actor, req):
    before = await state(db)
    preview = await service.operate(db, actor_user_id=actor["id"], request=req)
    assert await state(db) == before
    saved = await service.operate(db, actor_user_id=actor["id"], request=req, dry_run=False,
                                  expected_preview_sha256=preview["preview_sha256"])
    assert preview["receipt_sha256"] == saved["receipt_sha256"]
    assert preview["preview_sha256"] == saved["preview_sha256"]
    return saved


@pytest.mark.asyncio
async def test_native_context_exact_property_scope_zero_and_no_source_http(db_session):
    actor = await research_operator()
    fixture = await seed(db_session)
    ctx = await service.context(db_session, actor_user_id=actor["id"], kind="native_property",
        material_id=fixture["material"], property_id=str(fixture["children"]["property"]))
    assert ctx["eligibility"]["eligible"]
    assert ctx["projection"]["values"] == [{"field_id": "band_gap", "value": 0, "unit": "eV", "relation": "exact"}]
    assert ctx["projection"]["event_id"] == str(fixture["event"])
    assert ctx["projection"]["state_id"] == str(fixture["state"])
    assert ctx["projection"]["pressure_gpa"] is None
    assert json.loads(ctx["projection_canonical_json"]) == ctx["projection"]
    assert service.text_sha(ctx["projection_canonical_json"]) == ctx["projection_sha256"]
    assert "context_canonical_json" not in ctx and "subject" not in ctx
    saved = await save(db_session, actor, operation(baseline=ctx["baseline"]))
    proof = json.loads(saved["receipt_canonical_json"])
    assert "context_json" not in proof and "projection" not in proof
    assert proof["projection_sha256"] and proof["context_sha256"] == ctx["context_sha256"]
    assert digest(proof) == saved["receipt_sha256"]
    detail = await service.design_detail(db_session, actor_user_id=actor["id"], design_id=saved["design_id"])
    wire = canonical(detail).decode()
    assert "literature_locator" not in wire and "Synthetic freeze integration" not in wire
    assert detail["entries"][0]["projection"]["values"][0]["value"] == 0
    entry = detail["entries"][0]
    assert service.text_sha(entry["projection_canonical_json"]) == proof["projection_sha256"]
    assert saved["scientific_acceptance"] is saved["calculation_executed"] is saved["ml_training_approved"] is False
    assert saved["canonical_promotions"] == 0


@pytest.mark.asyncio
async def test_propose_revise_withdraw_preview_rollback_and_uncertain_outcome(db_session):
    actor = await research_operator()
    req, ctx = await request(db_session, actor)
    with pytest.raises(SourcePropertyConflict, match="exact_preview"):
        await service.operate(db_session, actor_user_id=actor["id"], request=req, dry_run=False)
    first = await save(db_session, actor, req)
    before = await state(db_session)
    replay = await service.operate(db_session, actor_user_id=actor["id"], request=req, dry_run=False)
    assert replay["replayed"] and await state(db_session) == before
    out = await service.outcome(db_session, actor_user_id=actor["id"], request_key_value=req["request_key"], expected_request_sha256=first["request_sha256"])
    assert out["receipt_sha256"] == first["receipt_sha256"]
    missing = operation()
    with pytest.raises(SourcePropertyNotFound, match="not_proof_of_failure"):
        await service.outcome(db_session, actor_user_id=actor["id"], request_key_value=missing["request_key"], expected_request_sha256="a" * 64)
    revision = operation("revise", baseline=ctx["baseline"])
    revision["payload"].update(design_id=first["design_id"], predecessor={"id": first["receipt_id"], "record_sha256": first["receipt_sha256"]})
    revision["payload"]["design"]["hypothesis"] = "A revised synthetic source-review question"
    second = await save(db_session, actor, revision)
    assert second["revision"] == 2
    stale = deepcopy(revision)
    stale["request_key"] += ":stale"
    with pytest.raises(SourcePropertyConflict, match="exact_owner_head"):
        await service.operate(db_session, actor_user_id=actor["id"], request=stale)
    withdraw = {"version": contract.REQUEST_VERSION, "request_key": "withdraw:" + uuid4().hex, "operation": "withdraw",
        "payload": {"design_id": second["design_id"], "predecessor": {"id": second["receipt_id"], "record_sha256": second["receipt_sha256"]}, "reason": "Synthetic scope now needs independent reassessment"}}
    third = await save(db_session, actor, withdraw)
    assert third["revision"] == 3 and third["status"] == "withdrawn"
    detail = await service.design_detail(db_session, actor_user_id=actor["id"], design_id=first["design_id"])
    assert detail["revision_total"] == 3 and [item["revision"] for item in detail["entries"]] == [3, 2, 1]
    assert [item["is_head"] for item in detail["entries"]] == [True, False, False]
    after_withdraw = deepcopy(revision)
    after_withdraw["request_key"] += ":after-withdraw"
    after_withdraw["payload"]["predecessor"] = {"id": third["receipt_id"], "record_sha256": third["receipt_sha256"]}
    with pytest.raises(SourcePropertyConflict):
        await service.operate(db_session, actor_user_id=actor["id"], request=after_withdraw)


@pytest.mark.asyncio
async def test_retained_source_drift_suppresses_values_but_proofs_and_history_survive(db_session):
    actor = await research_operator()
    material, paper = await retained(db_session, record={"tc_kelvin": 39.5, "pressure_gpa": 0.0, "knowledge_origin": "Observed", "private_source_text": "DO NOT RETURN SOURCE", "work_id": "unreviewed-legacy-work-label"})
    req, ctx = await request(db_session, actor, kind="retained_result", material_id=material, record_index=0)
    assert ctx["projection"]["values"][0]["value"] == 39.5 and ctx["projection"]["pressure_gpa"] == 0
    first = await save(db_session, actor, req)
    papers = Base.metadata.tables["papers"]
    await db_session.execute(papers.update().where(papers.c.id == paper).values(status="withdrawn"))
    detail = await service.design_detail(db_session, actor_user_id=actor["id"], design_id=first["design_id"])
    row = detail["entries"][0]
    assert not row["eligibility"]["eligible"] and row["projection"] is None
    assert row["projection_canonical_json"] is None
    assert "source_context_changed" in row["eligibility"]["reason_codes"]
    assert "DO NOT RETURN SOURCE" not in canonical(detail).decode()
    assert "39.5" not in row["receipt"]["receipt_canonical_json"]
    fresh = await service.context(db_session, actor_user_id=actor["id"], kind="retained_result", material_id=material, record_index=0)
    assert fresh["projection"] is None and not fresh["eligibility"]["eligible"]
    assert fresh["projection_canonical_json"] is None
    revised = operation("revise", baseline=ctx["baseline"])
    revised["payload"].update(design_id=first["design_id"], predecessor={"id": first["receipt_id"], "record_sha256": first["receipt_sha256"]})
    with pytest.raises(SourcePropertyConflict, match="source_pin_changed"):
        await service.operate(db_session, actor_user_id=actor["id"], request=revised)
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(service.table())) == 1


@pytest.mark.asyncio
async def test_native_exact_state_or_run_change_holds_and_wrong_material_rejected(db_session):
    actor = await research_operator()
    fixture = await seed(db_session)
    req, _ = await request(db_session, actor, kind="native_property", material_id=fixture["material"], property_id=str(fixture["children"]["property"]))
    first = await save(db_session, actor, req)
    relation = Base.metadata.tables["material_states"]
    await db_session.execute(relation.update().where(relation.c.id == fixture["state"]).values(context_sha256="d" * 64))
    detail = await service.design_detail(db_session, actor_user_id=actor["id"], design_id=first["design_id"])
    assert detail["entries"][0]["projection"] is None
    assert detail["entries"][0]["eligibility"]["reason_codes"] == ["source_context_changed"]
    other, _ = await retained(db_session)
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await service.context(db_session, actor_user_id=actor["id"], kind="native_property", material_id=other, property_id=str(fixture["children"]["property"]))


@pytest.mark.asyncio
async def test_owner_scope_parent_pin_and_current_grant_not_admin_flag(db_session):
    actor = await research_operator()
    other = await research_operator()
    first = await save(db_session, actor, (await request(db_session, actor))[0])
    assert (await service.designs(db_session, actor_user_id=other["id"]))["total"] == 0
    with pytest.raises(SourcePropertyNotFound):
        await service.design_detail(db_session, actor_user_id=other["id"], design_id=first["design_id"])
    child, _ = await request(db_session, actor)
    child["payload"]["parent"] = {"design_id": first["design_id"], "revision_id": first["receipt_id"], "record_sha256": first["receipt_sha256"]}
    second = await save(db_session, actor, child)
    assert second["design_id"] != first["design_id"]
    child["request_key"] += ":wrong-owner"
    with pytest.raises(SourcePropertyNotFound):
        await service.operate(db_session, actor_user_id=other["id"], request=child)
    ungranted = await research_user(is_admin=True)
    with pytest.raises(ResearchAccessDenied):
        await service.capabilities(db_session, actor_user_id=ungranted["id"])
    await db_session.commit()
    await revoke_research_grant(grant_id=actor["grant_id"], revoked_by=actor["grantor_id"])
    with pytest.raises(ResearchAccessDenied):
        await service.outcome(db_session, actor_user_id=actor["id"], request_key_value=child["request_key"], expected_request_sha256=first["request_sha256"])


async def sql_candidate(db, actor):
    req, ctx = await request(db, actor)
    preview = await service.operate(db, actor_user_id=actor["id"], request=req)
    values = json.loads(preview["receipt_canonical_json"])
    for key in ("id", "design_id", "actor_user_id", "actor_grant_id"):
        values[key] = UUID(values[key])
    values["context_json"] = await service.sql_context(db, ctx["baseline"])
    values["projection"], _ = await service.sql_projection(db, values["context_json"])
    values["record_sha256"] = preview["receipt_sha256"]
    return values


@pytest.mark.asyncio
@pytest.mark.parametrize("attack", ["authority", "extra_request", "one_outcome", "unknown_cost_zero", "wrong_session", "wrong_owner_grant", "source_pin"])
async def test_direct_sql_guards_reject_resealed_authority_or_semantic_attacks(db_session, attack):
    actor = await research_operator()
    values = await sql_candidate(db_session, actor)
    if attack == "authority":
        values["scientific_acceptance"] = True
    elif attack == "wrong_session":
        values["actor_session_version"] += 1
    elif attack == "wrong_owner_grant":
        values["actor_user_id"] = (await research_operator())["id"]
    elif attack == "source_pin":
        values["context_json"] = values["context_json"].replace("unanchored", "retained_result")
        values["context_sha256"] = service.text_sha(values["context_json"])
    else:
        req = json.loads(values["request_json"])
        if attack == "extra_request":
            req["scientific_acceptance"] = True
        elif attack == "one_outcome":
            req["payload"]["design"]["next_action"]["outcomes"] = req["payload"]["design"]["next_action"]["outcomes"][:1]
        else:
            req["payload"]["design"]["next_action"]["budget"][0]["raw_upper"] = "0"
        values["request_json"] = canonical(req).decode()
        values["request_sha256"] = service.text_sha(values["request_json"])
        values["payload"] = req["payload"]
        values["design"] = req["payload"]["design"]
    preview = json.loads(values["preview_json"])
    preview["request_sha256"] = values["request_sha256"]
    preview["context_sha256"] = values["context_sha256"]
    preview["actor"]["actor_user_id"] = str(values["actor_user_id"])
    preview["actor"]["actor_session_version"] = values["actor_session_version"]
    values["preview_json"] = canonical(preview).decode()
    values["preview_sha256"] = service.text_sha(values["preview_json"])
    values["record_sha256"] = digest(service._body(values))
    before = await state(db_session)
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(service.table().insert().values(**values))
    assert await state(db_session) == before


@pytest.mark.asyncio
async def test_direct_sql_append_only_update_delete_truncate_and_downgrade_refusal(db_session):
    actor = await research_operator()
    await save(db_session, actor, (await request(db_session, actor))[0])
    before = await state(db_session)
    for mutation in (service.table().update().values(scientific_acceptance=False), service.table().delete(), sa.text("TRUNCATE public.discovery_design_revisions_v1")):
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                await db_session.execute(mutation)
        assert await state(db_session) == before
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0087_discovery_designs.py"
    spec = importlib.util.spec_from_file_location("discovery_migration_test", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    class SyncOps:
        def __init__(self, connection): self.connection = connection
        def get_bind(self): return self.connection
        def execute(self, sql): return self.connection.execute(sa.text(sql))
    def downgrade(connection):
        connection = connection.connection()
        migration.op = SyncOps(connection)
        with pytest.raises(RuntimeError, match="retained private Discovery"):
            migration.downgrade()
    await db_session.run_sync(downgrade)
    assert await state(db_session) == before


@pytest.mark.asyncio
async def test_preview_session_drift_requires_new_preview_and_request_snapshot_survives_caller_mutation(db_session, monkeypatch):
    actor = await research_operator()
    req, _ = await request(db_session, actor)
    snapshot = deepcopy(req)
    original_session = service._session
    async def mutate_caller(db, *, write):
        req["payload"]["design"]["host_label"] = "Caller changed after async request pinning"
        await original_session(db, write=write)
    with monkeypatch.context() as patch:
        patch.setattr(service, "_session", mutate_caller)
        preview = await service.operate(db_session, actor_user_id=actor["id"], request=req)
    assert json.loads(preview["request_canonical_json"]) == snapshot
    users = Base.metadata.tables["users"]
    await db_session.execute(users.update().where(users.c.id == actor["id"]).values(session_version=1))
    before = await state(db_session)
    with pytest.raises(SourcePropertyConflict, match="exact_preview"):
        await service.operate(db_session, actor_user_id=actor["id"], request=snapshot, dry_run=False,
                              expected_preview_sha256=preview["preview_sha256"])
    assert await state(db_session) == before
    saved = await save(db_session, actor, snapshot)
    assert saved["actor_session_version"] == 1


@pytest.mark.asyncio
async def test_native_sibling_not_transplanted_and_unit_mismatch_fails_closed(db_session):
    actor = await research_operator()
    fixture = await seed(db_session)
    first = await service.context(db_session, actor_user_id=actor["id"], kind="native_property",
        material_id=fixture["material"], property_id=str(fixture["children"]["property"]))
    omega = await add(db_session, "event_properties", event_id=fixture["event"], property_key="omega_log",
        relation="exact", value=300, unit="K", record_sha256="a" * 64)
    second = await service.context(db_session, actor_user_id=actor["id"], kind="native_property",
        material_id=fixture["material"], property_id=str(fixture["children"]["property"]))
    assert first["context_sha256"] == second["context_sha256"]
    assert second["projection"]["values"] == first["projection"]["values"]
    properties = Base.metadata.tables["event_properties"]
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(properties.update().where(properties.c.id == omega["id"]).values(unit="THz"))
    valid = await service.context(db_session, actor_user_id=actor["id"], kind="native_property",
        material_id=fixture["material"], property_id=str(omega["id"]))
    assert valid["projection"]["values"] == [{"field_id": "omega_log", "value": 300, "unit": "K", "relation": "exact"}]


@pytest.mark.asyncio
async def test_retained_record_disappears_history_survives_without_fallback(db_session):
    actor = await research_operator()
    material, _ = await retained(db_session)
    req, _ = await request(db_session, actor, kind="retained_result", material_id=material, record_index=0)
    first = await save(db_session, actor, req)
    materials = Base.metadata.tables["materials"]
    await db_session.execute(materials.update().where(materials.c.id == material).values(records=[]))
    detail = await service.design_detail(db_session, actor_user_id=actor["id"], design_id=first["design_id"])
    entry = detail["entries"][0]
    assert entry["projection"] is None and not entry["eligibility"]["eligible"]
    assert entry["baseline"]["kind"] == "retained_result"
    assert entry["baseline"]["record_index"] == 0 and entry["receipt"]["receipt_sha256"] == first["receipt_sha256"]


@pytest.mark.asyncio
async def test_sql_resealed_fresh_withdrawn_source_still_cannot_be_proposed(db_session):
    actor = await research_operator()
    material, paper = await retained(db_session)
    req, ctx = await request(db_session, actor, kind="retained_result", material_id=material, record_index=0)
    preview = await service.operate(db_session, actor_user_id=actor["id"], request=req)
    values = json.loads(preview["receipt_canonical_json"])
    for key in ("id", "design_id", "actor_user_id", "actor_grant_id"):
        values[key] = UUID(values[key])
    papers = Base.metadata.tables["papers"]
    await db_session.execute(papers.update().where(papers.c.id == paper).values(status="withdrawn"))
    values["context_json"] = await service.sql_context(db_session, ctx["baseline"])
    values["context_sha256"] = service.text_sha(values["context_json"])
    values["projection"], values["projection_sha256"] = await service.sql_projection(db_session, values["context_json"])
    req["payload"]["baseline"]["expected_context_sha256"] = values["context_sha256"]
    values["baseline"] = req["payload"]["baseline"]
    values["payload"] = req["payload"]
    values["request_json"] = canonical(req).decode()
    values["request_sha256"] = service.text_sha(values["request_json"])
    proof = json.loads(values["preview_json"])
    proof.update(context_sha256=values["context_sha256"], request_sha256=values["request_sha256"])
    values["preview_json"] = canonical(proof).decode()
    values["preview_sha256"] = service.text_sha(values["preview_json"])
    values["record_sha256"] = digest(service._body(values))
    before = await state(db_session)
    with pytest.raises(DBAPIError, match="current_source_hold"):
        async with db_session.begin_nested():
            await db_session.execute(service.table().insert().values(**values))
    assert await state(db_session) == before


@pytest.mark.asyncio
async def test_native_pending_is_not_approval_and_local_negative_event_holds_projection(db_session):
    actor = await research_operator()
    fixture = await seed(db_session)
    req, ctx = await request(db_session, actor, kind="native_property", material_id=fixture["material"], property_id=str(fixture["children"]["property"]))
    first = await save(db_session, actor, req)
    assert ctx["eligibility"]["eligible"] and ctx["scientific_acceptance"] is False
    events = Base.metadata.tables["research_events"]
    await db_session.execute(events.update().where(events.c.id == fixture["event"]).values(validity_status="disputed"))
    detail = await service.design_detail(db_session, actor_user_id=actor["id"], design_id=first["design_id"])
    assert detail["entries"][0]["projection"] is None
    assert "native_event_held" in detail["entries"][0]["eligibility"]["reason_codes"]
    fresh = await service.context(db_session, actor_user_id=actor["id"], kind="native_property", material_id=fixture["material"], property_id=str(fixture["children"]["property"]))
    assert fresh["projection"] is None and fresh["eligibility"]["reason_codes"] == ["native_event_held"]
    with pytest.raises(SourcePropertyConflict, match="not_currently_eligible"):
        await service.operate(db_session, actor_user_id=actor["id"], request=operation(baseline=fresh["baseline"]))


@pytest.mark.asyncio
async def test_empty_migration_roundtrip_uses_actual_metadata_guards(db_session):
    # The repository fixture is session-wide. Never erase committed audit
    # history just to manufacture an empty downgrade; also run this case alone
    # against a fresh disposable harness to exercise the actual empty branch.
    if await db_session.scalar(sa.select(sa.func.count()).select_from(service.table())):
        pytest.skip("Empty migration roundtrip requires a fresh owned disposable database")
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0087_discovery_designs.py"
    spec = importlib.util.spec_from_file_location("discovery_empty_migration_test", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    class SyncOps:
        def __init__(self, connection): self.connection = connection
        def get_bind(self): return self.connection
        def execute(self, sql): return self.connection.execute(sa.text(sql))
    def roundtrip(connection):
        connection = connection.connection()
        migration.op = SyncOps(connection)
        migration.downgrade()
        assert connection.execute(sa.text("SELECT to_regclass('public.discovery_design_revisions_v1')")).scalar_one() is None
        migration.upgrade()
        assert connection.execute(sa.text("SELECT to_regclass('public.discovery_design_revisions_v1')")).scalar_one()
        assert connection.execute(sa.text("SELECT count(*) FROM pg_trigger WHERE tgrelid='public.discovery_design_revisions_v1'::regclass AND NOT tgisinternal")).scalar_one() == 3
    await db_session.run_sync(roundtrip)
