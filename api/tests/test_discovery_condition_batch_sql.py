"""Independent native SQL reconstruction and forgery counterexamples.

All parents/source properties are synthetic owned fixtures. No result or source
is imported, promoted, calculated or accepted by retaining a condition batch.
Direct SQL checks prove exact source/governance/ancestry guards, not parity with
the complete catalogue parser/anomaly policy applied separately by HTTP.
"""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import Base
from models.discovery_condition_batch_v1 import TABLE_ORDER
from services import discovery_condition_batch_contract as contract
from services import discovery_designs as designs
from services.research_release_manifest import canonical, digest
from tests.research_access_helpers import research_operator
from tests.test_discovery_design_contract import operation
from tests.test_discovery_designs import request, save
from tests.test_research_freeze import db_session, seed, state


AXES = {"pressures": [{"kind": "ambient", "raw_gpa": None},
    *[{"kind": "specified", "raw_gpa": raw} for raw in ("0", "0.0", "10", "20")]],
    "temperatures_k": [None, "250", "300"]}


def json_row(row):
    return {key: str(value) if isinstance(value, UUID) else value
            for key, value in row.items() if key != "created_at"}


async def native_parent(db):
    actor = await research_operator()
    fixture = await seed(db)
    req, _ = await request(db, actor, kind="native_property", material_id=fixture["material"],
                           property_id=str(fixture["children"]["property"]))
    receipt = await save(db, actor, req)
    row = (await db.execute(sa.select(designs.table()).where(
        designs.table().c.id == UUID(receipt["receipt_id"])))).mappings().one()
    session = await db.scalar(sa.select(Base.metadata.tables["users"].c.session_version).where(
        Base.metadata.tables["users"].c.id == actor["id"]))
    actor["session_version"] = session
    return actor, row, fixture


def actor_pins(actor):
    return {"actor_user_id": str(actor["id"]), "curator_grant_id": str(actor["grant_id"]),
            "session_version": actor["session_version"]}


async def sql_manifest(db, row, actor, axes):
    parent = {"design_id": str(row["design_id"]), "revision_id": str(row["id"]),
              "revision": row["revision"], "record_sha256": row["record_sha256"]}
    return await db.scalar(sa.text("""SELECT public.sclib_discovery_condition_batch_manifest_v1(
        CAST(:parent AS jsonb),CAST(:axes AS jsonb),CAST(:actor AS uuid),CAST(:grant AS uuid),CAST(:session AS bigint))"""),
        {"parent": canonical(parent).decode(), "axes": canonical(axes).decode(),
         "actor": str(actor["id"]), "grant": str(actor["grant_id"]), "session": actor["session_version"]})


def reseal(values, *, batch):
    q = json.loads(values["request_json"])
    values["payload"] = q["payload"]
    values["request_sha256"] = designs.text_sha(values["request_json"])
    preview = json.loads(values["preview_json"])
    preview["request_sha256"] = values["request_sha256"]
    preview["actor"] = {key: str(values[key]) if isinstance(values[key], UUID) else values[key]
                        for key in ("actor_user_id", "actor_grant_id", "actor_session_version")}
    if batch:
        preview.update(parent=values["parent"], input_sha256=values["input_sha256"],
                       manifest_sha256=values["manifest_sha256"], scenario_total=values["scenario_total"])
    else:
        preview.update(batch_id=str(values["batch_id"]), batch_record_sha256=values["batch_record_sha256"],
            manifest_sha256=values["manifest_sha256"], candidate_sha256=values["candidate_sha256"],
            child={"design_id": str(values["child_design_id"]), "revision_id": str(values["child_revision_id"]),
                   "record_sha256": values["child_record_sha256"]})
    values["preview_json"] = canonical(preview).decode()
    values["preview_sha256"] = designs.text_sha(values["preview_json"])
    body = {key: value for key, value in json_row(values).items()
            if key not in {"record_sha256", *({"manifest_json"} if batch else set())}}
    values["record_sha256"] = digest(body)
    return values


async def batch_values(db, row, actor, axes=AXES):
    body = await sql_manifest(db, row, actor, axes)
    manifest = {**json.loads(body), "manifest_sha256": designs.text_sha(body)}
    receipt_id = uuid4()
    req = {"version": contract.REQUEST_VERSION, "request_key": "batch-sql:"+uuid4().hex,
           "operation": "retain_batch", "payload": {"parent": manifest["parent"], "axes": deepcopy(axes),
           "expected_input_sha256": manifest["input_sha256"], "expected_manifest_sha256": manifest["manifest_sha256"]}}
    values = {"id": receipt_id, "actor_user_id": actor["id"], "actor_grant_id": actor["grant_id"],
        "actor_session_version": actor["session_version"], "operation": req["operation"], "request_key": req["request_key"],
        "request_json": canonical(req).decode(), "parent": manifest["parent"], "source_pins": manifest["source_pins"],
        "input_json": manifest["input_canonical_json"], "input_sha256": manifest["input_sha256"],
        "manifest_json": canonical(manifest).decode(), "manifest_sha256": manifest["manifest_sha256"],
        "scenario_total": len(manifest["scenarios"]), "scientific_acceptance": False, "canonical_promotions": 0,
        "ml_training_approved": False, "public_release": False, "calculation_executed": False,
        "preview_json": canonical({"version": contract.VERSION, "actor": {}, "request_sha256": "",
            "receipt_id": str(receipt_id), "batch_id": str(receipt_id), "parent": {}, "input_sha256": "",
            "manifest_sha256": "", "scenario_total": 0}).decode()}
    return reseal(values, batch=True)


async def child_values(db, batch, actor, *, proposal=None, request_key=None):
    manifest = json.loads(batch["manifest_json"])
    candidate = manifest["scenarios"][0]
    parent = {key: batch["parent"][key] for key in ("design_id", "revision_id", "record_sha256")}
    req = operation(baseline=deepcopy(batch["source_pins"]["baseline"]), parent=parent)
    req["payload"]["design"] = deepcopy(proposal or candidate["proposal"])
    child = await save(db, actor, req)
    receipt_id = uuid4()
    request_json = canonical({"version": contract.REQUEST_VERSION,
        "request_key": request_key or "child-link-sql:"+uuid4().hex, "operation": "propose_candidate_child",
        "payload": {"batch": {"id": str(batch["id"]), "record_sha256": batch["record_sha256"],
            "manifest_sha256": batch["manifest_sha256"]}, "candidate_sha256": candidate["candidate_sha256"]}}).decode()
    values = {"id": receipt_id, "actor_user_id": actor["id"], "actor_grant_id": actor["grant_id"],
        "actor_session_version": actor["session_version"], "operation": "propose_candidate_child",
        "request_key": json.loads(request_json)["request_key"], "request_json": request_json,
        "batch_id": batch["id"], "batch_record_sha256": batch["record_sha256"], "manifest_sha256": batch["manifest_sha256"],
        "candidate_sha256": candidate["candidate_sha256"], "child_revision_id": UUID(child["receipt_id"]),
        "child_design_id": UUID(child["design_id"]), "child_record_sha256": child["receipt_sha256"],
        "scientific_acceptance": False, "canonical_promotions": 0, "ml_training_approved": False,
        "public_release": False, "calculation_executed": False,
        "preview_json": canonical({"version": contract.VERSION, "actor": {}, "request_sha256": "",
                                  "receipt_id": str(receipt_id)}).decode()}
    return reseal(values, batch=False)


@pytest.mark.asyncio
async def test_native_manifest_and_exact_alias_identity_match_python_and_literal_ts_fixture(db_session):
    # Seed independently committed operator grants before taking this
    # SERIALIZABLE transaction's first snapshot.
    actor, row, _ = await native_parent(db_session)
    # This pure builder independently checks the already-rendered TS artifact's
    # literal SHA. The next check uses an actual new SQL parent, not fixture IDs.
    wire = json.loads((Path(__file__).resolve().parents[2] /
        "frontend/tests/fixtures/discovery-designs-native.synthetic.json").read_text())
    entry = wire["page"]["entries"][0]
    fixture_row = json.loads(entry["receipt"]["receipt_canonical_json"])
    fixture_row.update(record_sha256=entry["record_sha256"], projection=entry["projection"])
    cap = wire["capabilities"]
    body = await db_session.scalar(sa.text("""SELECT public.sclib_discovery_condition_batch_body_v1(
        CAST(:row AS jsonb),CAST(:axes AS jsonb),CAST(:actor AS uuid),CAST(:grant AS uuid),CAST(:session AS bigint))"""),
        {"row": canonical(fixture_row).decode(), "axes": canonical(AXES).decode(), "actor": cap["actor_user_id"],
         "grant": cap["curator_grant_id"], "session": cap["session_version"]})
    assert designs.text_sha(body) == "17de1ff390afbb508d53a7eb553711129f898229eab33f792fede0148bd9c2af"
    assert json.loads(body)["input_sha256"] == "47844ecbc764400a52c199bf28b5f98b880161cd031399f6cd9cd920b90f1740"
    body = await sql_manifest(db_session, row, actor, AXES)
    expected = contract.build_manifest(row, row["projection"], actor_pins(actor), AXES)
    sha = expected.pop("manifest_sha256")
    assert body == canonical(expected).decode() and designs.text_sha(body) == sha
    assert expected["estimate"]["raw_cartesian_count"] == 15
    assert expected["estimate"]["unique_cartesian_count"] == 12
    assert expected["source_pins"]["baseline"] == row["baseline"]
    assert "values" not in expected["source_pins"] and expected["batch_saved"] is False
    largest = {"pressures": [{"kind": "specified", "raw_gpa": str(i)} for i in range(8)],
               "temperatures_k": [str(i) for i in range(8)]}
    full = json.loads(await sql_manifest(db_session, row, actor, largest))
    assert len(full["scenarios"]) == 64


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["0", "0e999999999999999999", "00.000", "10.0", "1e1", "9007199254740992",
    "9007199254740993", "5e-324", "2.5e-324", "1.7976931348623158e308", "1e-323", "0e-1999999999999999997"])
async def test_sql_decimal_exact_identity_matches_independent_python_boundary_admission(db_session, raw):
    actual = await db_session.scalar(sa.text("SELECT public.sclib_discovery_condition_batch_decimal_v1(CAST(:v AS jsonb))"),
                                     {"v": canonical(raw).decode()})
    assert actual == contract.decimal_identity(raw)


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["1e-999", "2e-324", "1.7976931348623159e308", "0e1000000000000000000",
    "0e-1999999999999999998", "NaN", "٣٠٠", "+1", "1"*65])
async def test_sql_decimal_rejects_invalid_whole_axis(db_session, raw):
    with pytest.raises(contract.DiscoveryConditionBatchError):
        contract.decimal_identity(raw)
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(sa.text("SELECT public.sclib_discovery_condition_batch_decimal_v1(CAST(:v AS jsonb))"),
                                     {"v": canonical(raw).decode()})


@pytest.mark.asyncio
@pytest.mark.parametrize("attack", ["authority", "extra_request", "forged_manifest", "forged_pins", "wrong_session", "wrong_grant", "wrong_parent"])
async def test_resealed_direct_sql_batch_insert_refuses_forgery(db_session, attack):
    other = await research_operator() if attack == "wrong_grant" else None
    actor, row, _ = await native_parent(db_session)
    values = await batch_values(db_session, row, actor)
    if attack == "authority": values["scientific_acceptance"] = True
    elif attack == "extra_request":
        q = json.loads(values["request_json"]); q["uploaded_proposal"] = row["design"]
        values["request_json"] = canonical(q).decode()
    elif attack == "forged_manifest":
        manifest = json.loads(values["manifest_json"])
        manifest["scenarios"][0]["proposal"]["hypothesis"] = "Forged but resealed hypothesis"
        manifest.pop("manifest_sha256")
        values["manifest_sha256"] = digest(manifest)
        values["manifest_json"] = canonical({**manifest, "manifest_sha256": values["manifest_sha256"]}).decode()
        q = json.loads(values["request_json"]); q["payload"]["expected_manifest_sha256"] = values["manifest_sha256"]
        values["request_json"] = canonical(q).decode()
    elif attack == "forged_pins": values["source_pins"]["state_id"] = str(uuid4())
    elif attack == "wrong_session": values["actor_session_version"] += 1
    elif attack == "wrong_grant": values["actor_grant_id"] = other["grant_id"]
    else:
        values["parent"]["revision"] += 1
        q = json.loads(values["request_json"]); q["payload"]["parent"] = values["parent"]
        values["request_json"] = canonical(q).decode()
    reseal(values, batch=True)
    before = await state(db_session)
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(Base.metadata.tables[TABLE_ORDER[0]].insert().values(**values))
    assert await state(db_session) == before


@pytest.mark.asyncio
async def test_native_batch_preview_rollback_append_only_and_nonempty_downgrade(db_session):
    actor, row, _ = await native_parent(db_session)
    values = await batch_values(db_session, row, actor)
    table = Base.metadata.tables[TABLE_ORDER[0]]
    before = await state(db_session)
    nested = await db_session.begin_nested()
    await db_session.execute(table.insert().values(**values))
    await nested.rollback()
    assert await state(db_session) == before
    await db_session.execute(table.insert().values(**values))
    committed = await state(db_session)
    for name in TABLE_ORDER:
        ledger = Base.metadata.tables[name]
        for mutation in (ledger.update().values(scientific_acceptance=False), ledger.delete(), sa.text("TRUNCATE public."+name)):
            if name == TABLE_ORDER[1] and not isinstance(mutation, sa.sql.elements.TextClause):
                # Empty row-level operations fire no trigger; TRUNCATE still must fail.
                continue
            with pytest.raises(DBAPIError):
                async with db_session.begin_nested(): await db_session.execute(mutation)
            assert await state(db_session) == committed
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0088_discovery_condition_batches.py"
    spec = importlib.util.spec_from_file_location("condition_batch_migration_test", path)
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    class SyncOps:
        def __init__(self, connection): self.connection = connection
        def get_bind(self): return self.connection
        def execute(self, sql): return self.connection.execute(sa.text(sql))
    def downgrade(session):
        migration.op = SyncOps(session.connection())
        with pytest.raises(RuntimeError, match="retained private Discovery condition-batch"):
            migration.downgrade()
    await db_session.run_sync(downgrade)
    assert await state(db_session) == committed


@pytest.mark.asyncio
async def test_native_child_link_exact_proposal_current_session_and_candidate_uniqueness(db_session):
    actor, row, _ = await native_parent(db_session)
    batch = await batch_values(db_session, row, actor)
    await db_session.execute(Base.metadata.tables[TABLE_ORDER[0]].insert().values(**batch))
    # A session refresh leaves original manifest actor and bytes unchanged.
    users = Base.metadata.tables["users"]
    await db_session.execute(users.update().where(users.c.id == actor["id"]).values(session_version=1))
    actor["session_version"] = 1
    values = await child_values(db_session, batch, actor)
    table = Base.metadata.tables[TABLE_ORDER[1]]
    await db_session.execute(table.insert().values(**values))
    child = (await db_session.execute(sa.select(designs.table()).where(
        designs.table().c.id == values["child_revision_id"]))).mappings().one()
    assert child["design"] == json.loads(batch["manifest_json"])["scenarios"][0]["proposal"]
    assert child["context_sha256"] == row["context_sha256"] and child["parent"]["revision_id"] == str(row["id"])
    native_parent_row = (await db_session.execute(sa.select(designs.table()).where(designs.table().c.id == row["id"]))).mappings().one()
    assert dict(native_parent_row) == dict(row)
    retained = (await db_session.execute(sa.select(Base.metadata.tables[TABLE_ORDER[0]]).where(
        Base.metadata.tables[TABLE_ORDER[0]].c.id == batch["id"]))).mappings().one()
    assert retained["manifest_json"] == batch["manifest_json"] and retained["actor_session_version"] == 0
    before = await state(db_session)
    # Even a new child/operation key cannot create a second initial link for a
    # candidate in this exact batch; an outer savepoint rolls the child back.
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            duplicate = await child_values(db_session, batch, actor)
            await db_session.execute(table.insert().values(**duplicate))
    assert await state(db_session) == before
    for mutation in (table.update().values(scientific_acceptance=False), table.delete(), sa.text("TRUNCATE public."+TABLE_ORDER[1])):
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested(): await db_session.execute(mutation)
        assert await state(db_session) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("attack", ["wrong_proposal", "wrong_candidate", "cross_table_request", "wrong_child_sha"])
async def test_native_failed_initial_link_rolls_back_child_and_refuses_resealed_forgery(db_session, attack):
    actor, row, _ = await native_parent(db_session)
    batch = await batch_values(db_session, row, actor)
    await db_session.execute(Base.metadata.tables[TABLE_ORDER[0]].insert().values(**batch))
    before = await state(db_session)
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            proposal = None
            if attack == "wrong_proposal":
                proposal = deepcopy(json.loads(batch["manifest_json"])["scenarios"][0]["proposal"])
                proposal["hypothesis"] = "Different legitimately saved hypothesis is not this batch candidate"
            values = await child_values(db_session, batch, actor, proposal=proposal,
                request_key=batch["request_key"] if attack == "cross_table_request" else None)
            if attack == "wrong_candidate":
                values["candidate_sha256"] = json.loads(batch["manifest_json"])["scenarios"][1]["candidate_sha256"]
                q = json.loads(values["request_json"]); q["payload"]["candidate_sha256"] = values["candidate_sha256"]
                values["request_json"] = canonical(q).decode()
            elif attack == "wrong_child_sha": values["child_record_sha256"] = "0"*64
            reseal(values, batch=False)
            await db_session.execute(Base.metadata.tables[TABLE_ORDER[1]].insert().values(**values))
    assert await state(db_session) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("hold", ["parent_revision", "source_drift", "owner"])
async def test_sql_manifest_rechecks_current_parent_source_and_owner(db_session, hold):
    other = await research_operator() if hold == "owner" else None
    actor, row, fixture = await native_parent(db_session)
    if hold == "parent_revision":
        req = operation("revise", baseline=row["baseline"], parent=row["parent"])
        req["payload"].update(design_id=str(row["design_id"]),
            predecessor={"id": str(row["id"]), "record_sha256": row["record_sha256"]})
        req["payload"]["design"]["hypothesis"] = "Revised parent requires a fresh batch"
        await save(db_session, actor, req)
    elif hold == "source_drift":
        states = Base.metadata.tables["material_states"]
        await db_session.execute(states.update().where(states.c.id == fixture["state"]).values(context_sha256="a"*64))
    else:
        actor = {**other, "session_version": 0}
    before = await state(db_session)
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested(): await sql_manifest(db_session, row, actor, AXES)
    assert await state(db_session) == before
