"""Native append-only, exact-source and saved-child SQL counterexamples.

The real 0089 triggers admit reconstructed owned test records. Resealing an
insert is not source verification or scientific approval; admission must still
check live roles, current heads and actual captured source bytes independently.
"""
import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import Base
from models.discovery_feedback_v1 import TABLE_ORDER
from services import discovery_designs as designs
from services import discovery_feedback as service
from services import discovery_feedback_contract as contract
from services.research_release_manifest import canonical, digest
from tests.research_access_helpers import research_operator
from tests.test_discovery_design_contract import operation as design_operation
from tests.test_discovery_designs import save
from tests.test_discovery_feedback import feedback_case, return_request, return_saved
from tests.test_research_freeze import db_session as db_session
from tests.test_research_freeze import state


def reseal(values):
    """Independently rebuild proofs, preserving deliberately altered facts."""
    request = json.loads(values["request_json"])
    values["payload"] = request["payload"]
    values["request_sha256"] = designs.text_sha(values["request_json"])
    preview = {"version": contract.VERSION, "actor": {
        key: str(values[key]) if isinstance(values[key], UUID) else values[key]
        for key in ("actor_user_id", "actor_grant_id", "actor_session_version")},
        "request_sha256": values["request_sha256"], "receipt_id": str(values["id"])}
    if values["operation"] == "return_evidence":
        preview.update(feedback_id=str(values["id"]), design=values["design_ref"],
                       context_sha256=values["context_sha256"], projection_sha256=values["projection_sha256"])
    else:
        preview.update(feedback_id=str(values["feedback_id"]),
                       feedback_record_sha256=values["feedback_record_sha256"], child=values["child"])
    values["preview_json"] = canonical(preview).decode()
    values["preview_sha256"] = designs.text_sha(values["preview_json"])
    body = {str(key): str(value) if isinstance(value, UUID) else value for key, value in values.items()
            if key not in {"created_at", "record_sha256", "context_json", "projection"}}
    values["record_sha256"] = digest(body)
    return values


def fresh_clone(row):
    values = deepcopy({str(key): value for key, value in row.items() if key != "created_at"})
    values["id"] = uuid4()
    values["request_key"] = "feedback-sql:" + uuid4().hex
    request = json.loads(values["request_json"])
    request["request_key"] = values["request_key"]
    values["request_json"] = canonical(request).decode()
    return reseal(values)


def request_change(values, change):
    request = json.loads(values["request_json"])
    change(request)
    values["request_json"] = canonical(request).decode()


async def reject_insert(db, name, values, expected):
    before = await state(db)
    with pytest.raises(DBAPIError, match=expected):
        async with db.begin_nested():
            await db.execute(Base.metadata.tables[name].insert().values(**values))
    assert await state(db) == before


async def saved_return(db, *, actor=None):
    actor, material, paper, parent, ctx = await feedback_case(db, actor=actor)
    returned = await return_saved(db, actor, return_request(ctx))
    row = (await db.execute(sa.select(service.table()).where(
        service.table().c.id == UUID(returned["receipt_id"])))).mappings().one()
    return actor, parent, ctx, row


async def saved_link(db):
    actor, parent, ctx, returned = await saved_return(db)
    parent_row = await designs._row(db, actor["id"], parent["receipt_id"])
    parent_pin = {key: ctx["design"][key] for key in ("design_id", "revision_id", "record_sha256")}
    child = await save(db, actor, design_operation(baseline=parent_row["baseline"], parent=parent_pin))
    request = {"version": contract.REQUEST_VERSION, "request_key": "feedback-sql-link:" + uuid4().hex,
        "operation": "link_follow_up", "payload": {
            "feedback": {"id": str(returned["id"]), "record_sha256": returned["record_sha256"]},
            "child": {"design_id": child["design_id"], "revision_id": child["receipt_id"],
                      "record_sha256": child["receipt_sha256"]}}}
    receipt = await return_saved(db, actor, request)
    table = Base.metadata.tables[TABLE_ORDER[1]]
    linked = (await db.execute(sa.select(table).where(table.c.id == UUID(receipt["receipt_id"])))).mappings().one()
    return actor, parent_row, ctx, returned, child, linked


@pytest.mark.asyncio
async def test_independent_resealed_sql_return_is_admitted_without_source_or_authority_changes(db_session):
    _, parent, ctx, original = await saved_return(db_session)
    values = fresh_clone(original)
    inserted = (await db_session.execute(service.table().insert().values(**values).returning(service.table()))).mappings().one()
    assert inserted["projection"] == original["projection"] == ctx["projection"]
    assert inserted["context_json"] == original["context_json"]
    assert inserted["design_ref"]["design_id"] == parent["design_id"]
    assert inserted["record_sha256"] == values["record_sha256"]
    assert all(inserted[key] == value for key, value in contract.AUTHORITY.items() if key != "scope")


@pytest.mark.asyncio
@pytest.mark.parametrize("attack", ["extra_request", "extra_payload", "authority", "request_hash", "preview_hash",
    "record_hash", "forged_projection", "forged_context", "evidence_pin", "action_pin", "wrong_session",
    "wrong_grant", "wrong_owner"])
async def test_resealed_sql_return_rejects_closed_proof_source_and_live_owner_forgery(db_session, attack):
    # Independently committed grants must predate publication/source locks.
    other = await research_operator() if attack in {"wrong_grant", "wrong_owner"} else None
    actor, _, _, original = await saved_return(db_session)
    values = fresh_clone(original)
    expected = "feedback_"
    if attack == "extra_request":
        request_change(values, lambda q: q.update(experiment_executed=True))
        expected = "feedback_exact_request_required"
    elif attack == "extra_payload":
        request_change(values, lambda q: q["payload"].update(scientific_acceptance=True))
        expected = "feedback_return_shape_required"
    elif attack == "authority":
        values["scientific_acceptance"] = True
        expected = "feedback_exact_no_authority_receipt_required"
    elif attack == "forged_projection":
        values["projection"]["record"].update(tc_kelvin=99, hc2_conditions="invented WHH method")
        values["projection_sha256"] = digest(values["projection"])
        expected = "feedback_exact_source_return_required"
    elif attack == "forged_context":
        captured = json.loads(values["context_json"])
        captured["base"]["result"]["measurement"] = "invented measurement"
        values["context_json"] = canonical(captured).decode()
        values["context_sha256"] = designs.text_sha(values["context_json"])
        expected = "feedback_exact_source_return_required"
    elif attack == "evidence_pin":
        values["evidence"]["expected_context_sha256"] = "c" * 64
        request_change(values, lambda q: q["payload"].update(evidence=values["evidence"]))
        expected = "feedback_evidence_source_pin_changed"
    elif attack == "action_pin":
        values["design_ref"]["next_action_sha256"] = "d" * 64
        request_change(values, lambda q: q["payload"].update(design=values["design_ref"]))
        expected = "feedback_design_pin_conflict"
    elif attack == "wrong_session":
        values["actor_session_version"] += 1
        expected = "feedback_live_actor_required"
    elif attack == "wrong_grant":
        values["actor_grant_id"] = other["grant_id"]
        expected = "feedback_live_actor_required"
    elif attack == "wrong_owner":
        values.update(actor_user_id=other["id"], actor_grant_id=other["grant_id"])
        # Both synthetic users begin with the same actual session version.
        values["actor_session_version"] = await db_session.scalar(sa.select(Base.metadata.tables["users"].c.session_version)
            .where(Base.metadata.tables["users"].c.id == other["id"]))
        expected = "condition_batch_"
    reseal(values)
    if attack in {"request_hash", "preview_hash", "record_hash"}:
        values[{"request_hash": "request_sha256", "preview_hash": "preview_sha256",
                "record_hash": "record_sha256"}[attack]] = "e" * 64
        expected = "feedback_exact_request_required" if attack == "request_hash" else "feedback_exact_no_authority_receipt_required"
    await reject_insert(db_session, TABLE_ORDER[0], values, expected)


@pytest.mark.asyncio
@pytest.mark.parametrize("attack", ["extra_request", "extra_payload", "authority", "request_hash", "preview_hash",
                                   "record_hash", "feedback_pin", "child_pin"])
async def test_resealed_sql_follow_up_rejects_closed_authority_and_hash_corruption(db_session, attack):
    _, _, _, _, _, original = await saved_link(db_session)
    values = fresh_clone(original)
    expected = "feedback_"
    if attack == "extra_request":
        request_change(values, lambda q: q.update(public_release=True))
        expected = "feedback_exact_request_required"
    elif attack == "extra_payload":
        request_change(values, lambda q: q["payload"].update(physical_association_established=True))
        expected = "feedback_follow_up_shape_required"
    elif attack == "authority":
        values["experiment_executed"] = True
        expected = "feedback_exact_no_authority_receipt_required"
    elif attack == "feedback_pin":
        values["feedback_record_sha256"] = "f" * 64
        request_change(values, lambda q: q["payload"]["feedback"].update(record_sha256=values["feedback_record_sha256"]))
        expected = "feedback_exact_owner_return_required"
    elif attack == "child_pin":
        values["child"]["record_sha256"] = "d" * 64
        request_change(values, lambda q: q["payload"].update(child=values["child"]))
        expected = "feedback_initial_linked_child_required"
    reseal(values)
    if attack in {"request_hash", "preview_hash", "record_hash"}:
        values[{"request_hash": "request_sha256", "preview_hash": "preview_sha256",
                "record_hash": "record_sha256"}[attack]] = "e" * 64
        expected = "feedback_exact_request_required" if attack == "request_hash" else "feedback_exact_no_authority_receipt_required"
    await reject_insert(db_session, TABLE_ORDER[1], values, expected)


@pytest.mark.asyncio
@pytest.mark.parametrize("attack", ["different_parent", "revised_child"])
async def test_sql_follow_up_requires_exact_initial_current_child_and_feedback_parent(db_session, attack):
    actor, parent, ctx, _, child, original = await saved_link(db_session)
    if attack == "different_parent":
        unrelated = await save(db_session, actor, design_operation(baseline=parent["baseline"]))
        wrong = await save(db_session, actor, design_operation(baseline=parent["baseline"], parent={
            "design_id": unrelated["design_id"], "revision_id": unrelated["receipt_id"],
            "record_sha256": unrelated["receipt_sha256"]}))
    else:
        child_row = await designs._row(db_session, actor["id"], child["receipt_id"])
        request = design_operation("revise", baseline=child_row["baseline"], parent=child_row["parent"])
        request["payload"].update(design_id=child["design_id"], predecessor={
            "id": child["receipt_id"], "record_sha256": child["receipt_sha256"]})
        wrong = await save(db_session, actor, request)
    values = fresh_clone(original)
    values["child_revision_id"] = UUID(wrong["receipt_id"])
    values["child"] = {"design_id": wrong["design_id"], "revision_id": wrong["receipt_id"],
                       "record_sha256": wrong["receipt_sha256"]}
    request_change(values, lambda q: q["payload"].update(child=values["child"]))
    reseal(values)
    await reject_insert(db_session, TABLE_ORDER[1], values, "feedback_initial_linked_child_required")
    assert original["child"]["revision_id"] == child["receipt_id"]
    assert parent["id"] == UUID(ctx["design"]["revision_id"])


@pytest.mark.asyncio
async def test_both_populated_ledgers_refuse_update_delete_truncate_and_actual_nonempty_0089_downgrade(db_session):
    await saved_link(db_session)
    retained = await state(db_session)
    for name in TABLE_ORDER:
        table = Base.metadata.tables[name]
        assert await db_session.scalar(sa.select(sa.func.count()).select_from(table)) > 0
        for mutation in (table.update().values(scientific_acceptance=False), table.delete(),
                             sa.text("TRUNCATE public." + name + " CASCADE")):
            with pytest.raises(DBAPIError, match="append-only"):
                async with db_session.begin_nested():
                    await db_session.execute(mutation)
            assert await state(db_session) == retained
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0089_discovery_feedback.py"
    spec = importlib.util.spec_from_file_location("discovery_feedback_migration_guard_test", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    class SyncOps:
        def __init__(self, connection):
            self.connection = connection

        def get_bind(self):
            return self.connection

        def execute(self, sql):
            return self.connection.execute(sa.text(sql))

    def downgrade(session):
        migration.op = SyncOps(session.connection())
        with pytest.raises(RuntimeError, match="retained private Discovery evidence return history"):
            migration.downgrade()

    # Invoke the actual migration function against populated native tables;
    # this is a refusal proof, not a claim that these fixtures were Alembic-created.
    await db_session.run_sync(downgrade)
    assert await state(db_session) == retained
