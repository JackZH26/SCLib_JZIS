"""Native SQL guards for synthetic imports, not scientific review fixtures."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import Base
from models.scientific_import_v1 import TABLE_ORDER
from services import scientific_pending_import as service
from services.research_release_manifest import canonical, digest
from tests.test_research_freeze import add, state
from tests.test_research_freeze import db_session as db_session
from tests.test_scientific_pending_import import _completed, _rows, _start, seed_import


def _copy(row, **changes):
    return {**{key: value for key, value in row.items()
               if key not in {"id", "created_at", "record_sha256", "assembly_xid"}}, "id": uuid4(), **changes}


async def _reject(db, table, values, match):
    before = await state(db)
    with pytest.raises(DBAPIError, match=match):
        async with db.begin_nested():
            await add(db, table, **values)
            await db.execute(sa.text("SET CONSTRAINTS si65_complete IMMEDIATE"))
    assert await state(db) == before


def test_additive_tables_do_not_expand_frozen_release_spec():
    from services.research_release_spec import SPEC
    assert not set(TABLE_ORDER) & set(SPEC)
    assert all(fk.ondelete == "RESTRICT" and fk.onupdate == "RESTRICT"
               for name in TABLE_ORDER for fk in Base.metadata.tables[name].foreign_keys)
    assert Base.metadata.tables["scientific_import_blobs"].c.payload.type.__class__ is sa.LargeBinary


@pytest.mark.parametrize("table", TABLE_ORDER)
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
async def test_all_five_histories_are_immutable_even_noop(db_session, table, operation):
    fixture = await seed_import(db_session)
    started, _ = await _completed(db_session, fixture)
    row = (await _rows(db_session, table, **({"attempt_id": started["attempt_id"]}
        if table == "scientific_import_outcomes" else {"id": started["package_id"]}
        if table == "scientific_import_packages" else {"package_id": started["package_id"]})))[0]
    # TRUNCATE without foreign-key cascade can be refused before the trigger;
    # CASCADE includes only this synthetic test's retained FK graph and rolls back.
    query = (f"UPDATE {table} SET record_sha256=record_sha256 WHERE id=:id" if operation == "UPDATE"
        else f"DELETE FROM {table} WHERE id=:id" if operation == "DELETE" else f"TRUNCATE {table} CASCADE")
    before = await state(db_session)
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(sa.text(query), {"id": row["id"]})
    assert await state(db_session) == before


async def test_lock_requires_serializable_not_repeatable_read(db_session):
    await db_session.execute(sa.text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
    with pytest.raises(DBAPIError, match="scientific_import_serializable_required"):
        async with db_session.begin_nested():
            await db_session.execute(sa.text("SELECT sclib_scientific_import_lock_v1()"))


@pytest.mark.parametrize("change", ["manifest_hash", "request_extra", "context_null_hash", "noncanonical", "duplicate_name"])
async def test_raw_sql_request_requires_exact_hashes_closed_types_and_inventory(db_session, change):
    fixture = await seed_import(db_session)
    started = await _start(db_session, fixture)
    package = (await _rows(db_session, "scientific_import_packages", id=started["package_id"]))[0]
    values = _copy(package)
    request = json.loads(values["request_json"])
    request["compiler_sha256"] = "b" * 64
    values["compiler_sha256"] = request["compiler_sha256"]
    if change == "manifest_hash": values["manifest_sha256"] = "f" * 64
    elif change == "request_extra": request["private_extra"] = "synthetic"
    elif change == "context_null_hash":
        context = deepcopy(request["context"])
        context["expected_material_row_sha256"] = None
        request["context"] = context
        values["context_json"] = canonical(context).decode()
        values["context_sha256"] = request["context_sha256"] = digest(context)
    elif change == "duplicate_name": request["files"].append(request["files"][0])
    values["request_json"] = canonical(request).decode()
    if change == "noncanonical": values["request_json"] = " " + values["request_json"]
    values["package_key"] = hashlib.sha256(values["request_json"].encode()).hexdigest()
    await _reject(db_session, "scientific_import_packages", values, "scientific_import_")


async def test_package_cannot_commit_without_all_declared_original_bytes(db_session):
    fixture = await seed_import(db_session)
    started = await _start(db_session, fixture)
    old = (await _rows(db_session, "scientific_import_packages", id=started["package_id"]))[0]
    request = json.loads(old["request_json"])
    request["compiler_sha256"] = "e" * 64
    values = _copy(old, compiler_sha256="e" * 64, request_json=canonical(request).decode(), package_key=digest(request))
    await _reject(db_session, "scientific_import_packages", values, "complete_source_inventory_required")


@pytest.mark.parametrize("change", ["number", "predecessor", "actor", "grant"])
async def test_exact_attempt_head_and_explicit_actor_grant_are_required(db_session, change):
    fixture = await seed_import(db_session)
    started = await _start(db_session, fixture)
    old = (await _rows(db_session, "scientific_import_attempts", id=started["attempt_id"]))[0]
    values = _copy(old, attempt_number=2, predecessor_id=old["id"], request_key="raw:" + uuid4().hex)
    if change == "number": values["attempt_number"] = 3
    elif change == "predecessor": values["predecessor_id"] = None
    elif change == "actor": values["actor_user_id"] = fixture["actors"]["reviewer"]
    else: values["actor_grant_id"] = fixture["actors"]["grants"]["reviewer"]
    await _reject(db_session, "scientific_import_attempts", values,
                  "exact_attempt_chain_required|current_curator_required")


@pytest.mark.parametrize("change", ["payload", "projection_hash", "projection", "size"])
async def test_retained_bytes_and_artifact_projection_are_independently_verified(db_session, change):
    fixture = await seed_import(db_session)
    started = await _start(db_session, fixture)
    old = (await _rows(db_session, "scientific_import_blobs", package_id=started["package_id"]))[0]
    values = _copy(old)
    if change == "payload": values["payload"] = b"different synthetic bytes"
    elif change == "projection_hash": values["artifact_row_sha256"] = "f" * 64
    elif change == "projection": values["artifact_projection_json"] = "{}"
    else: values["size_bytes"] += 1
    await _reject(db_session, "scientific_import_blobs", values, "exact_bounded_artifact_bytes_required")


async def test_source_artifact_currentness_is_rechecked_before_a_new_attempt(db_session):
    fixture = await seed_import(db_session)
    started = await _start(db_session, fixture)
    await db_session.commit()
    blob = (await _rows(db_session, "scientific_import_blobs", package_id=started["package_id"]))[0]
    await db_session.execute(sa.text("UPDATE evidence_artifacts SET source='synthetic changed source' WHERE id=:id"),
                             {"id": blob["artifact_id"]})
    attempt = (await _rows(db_session, "scientific_import_attempts", id=started["attempt_id"]))[0]
    await _reject(db_session, "scientific_import_attempts", _copy(attempt, attempt_number=2,
        predecessor_id=attempt["id"], request_key="changed:" + uuid4().hex), "exact_source_bytes_required")
    # Negative recovery remains possible even though positive source closure fails.
    failed = await service.fail_import(db_session, actor_user_id=fixture["actors"]["curator"],
                                      attempt_id=started["attempt_id"], reason_code="import_failed")
    assert failed["status"] == "failed"


@pytest.mark.parametrize("change", ["status", "authority", "execution", "authority_extra", "cost", "report_hash", "snapshot_hash", "snapshot"])
async def test_terminal_report_cannot_launder_science_cost_or_row_snapshots(db_session, change):
    fixture = await seed_import(db_session)
    started, _ = await _completed(db_session, fixture)
    old = (await _rows(db_session, "scientific_import_outcomes", attempt_id=started["attempt_id"]))[0]
    values = _copy(old)
    report = json.loads(values["report_json"])
    if change == "status": report["status"] = "failed"
    elif change == "authority": report["authority"]["ml_training_approved"] = True
    elif change == "execution": report["authority"]["execution_attested"] = True
    elif change == "authority_extra": report["authority"]["synthetic_new_approval"] = True
    elif change == "cost": values["calculation_cpu_seconds"] = 1.0
    elif change == "snapshot_hash": values["row_snapshots_sha256"] = "f" * 64
    elif change == "snapshot":
        snapshots = json.loads(values["row_snapshots_json"])
        snapshots["event"]["review_status"] = "accepted"
        values["row_snapshots_json"] = canonical(snapshots).decode()
        values["row_snapshots_sha256"] = digest(snapshots)
    values["report_json"] = canonical(report).decode()
    values["report_sha256"] = digest(report) if change != "report_hash" else "f" * 64
    # The unique terminal constraint may fire first for a scalar cost change;
    # either native path rejects it without mutating the retained success.
    await _reject(db_session, "scientific_import_outcomes", values,
                  "scientific_import_|ck_si65_costs|uq_si65_attempt_outcome")


async def test_db_generated_record_hash_overwrites_caller_claim(db_session):
    fixture = await seed_import(db_session)
    started = await _start(db_session, fixture)
    old = (await _rows(db_session, "scientific_import_attempts", id=started["attempt_id"]))[0]
    new = await add(db_session, "scientific_import_attempts", **_copy(old, attempt_number=2,
        predecessor_id=old["id"], request_key="generated:" + uuid4().hex, record_sha256="f" * 64))
    assert new["record_sha256"] != "f" * 64
    actual = (await db_session.execute(sa.text("SELECT sclib_scientific_import_record_hash_v1(to_jsonb(a)) "
        "FROM scientific_import_attempts a WHERE id=:id"), {"id": new["id"]})).scalar_one()
    assert new["record_sha256"] == actual


@pytest.mark.parametrize("field", ["calculation_cpu_seconds", "calculation_wall_seconds", "calculation_monetary_cost",
                                  "import_wall_ms", "import_cpu_ms"])
async def test_fresh_negative_terminal_cannot_invent_calculation_cost_or_negative_measurements(db_session, field):
    fixture = await seed_import(db_session)
    started = await _start(db_session, fixture)
    report = {"version": "scientific-pending-import-report/1.0.0", "status": "failed",
              "reason_codes": ["import_failed"], "cost_scope": "parser_worker_only",
              "actual_calculation_costs": None, "authority": dict(service.AUTHORITY)}
    values = {"attempt_id": started["attempt_id"], "actor_user_id": fixture["actors"]["curator"],
              "actor_grant_id": fixture["actors"]["grants"]["curator"], "outcome": "failed",
              "reason_codes": ["import_failed"], "report_json": canonical(report).decode(), "report_sha256": digest(report),
              field: -1 if field.startswith("import_") else 1.0}
    await _reject(db_session, "scientific_import_outcomes", values, "ck_si65_costs")


async def test_success_rows_from_another_package_are_not_a_result_witness(db_session):
    first = await seed_import(db_session)
    started, _ = await _completed(db_session, first)
    outcome = (await _rows(db_session, "scientific_import_outcomes", attempt_id=started["attempt_id"]))[0]
    other = await seed_import(db_session)
    other_started = await _start(db_session, other)
    await _reject(db_session, "scientific_import_outcomes", _copy(outcome, attempt_id=other_started["attempt_id"],
        actor_user_id=other["actors"]["curator"], actor_grant_id=other["actors"]["grants"]["curator"]),
        "pending_exact_result_required")


async def test_successful_package_cannot_start_another_attempt(db_session):
    fixture = await seed_import(db_session)
    started, _ = await _completed(db_session, fixture)
    old = (await _rows(db_session, "scientific_import_attempts", id=started["attempt_id"]))[0]
    await _reject(db_session, "scientific_import_attempts", _copy(old, attempt_number=2,
        predecessor_id=old["id"], request_key="after-success:" + uuid4().hex), "exact_attempt_chain_required")
