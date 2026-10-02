"""New owned SQL ledger proof; source expressions stay pending and unbound.

The metadata bytes are the existing published snapshots. Test accounts/grants
and reviewer notes are synthetic; they do not claim human scientific review.
"""
from __future__ import annotations

import asyncio
import base64
import importlib.util
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import DBAPIError

from alembic import command
from config import get_settings
from models.db import Base
from models.source_property_pending_v1 import TABLE_ORDER, guard_statements
from services import source_property_contract as contract
from services import source_property_pending as service
from services.research_audit_retention import has_research_audit_references
from services.research_release_manifest import canonical, digest
from services.session_config import build_browser_session_config
from tests.research_access_helpers import research_operator, research_user, revoke_research_grant
from tests.test_research_freeze import db_session as _serializable_db_session
from tests.test_research_freeze import state

db_session = _serializable_db_session
PUBLIC = Path(__file__).resolve().parents[2] / "frontend/public/research-pilots"
SNAPSHOTS = ("materials-source-observations-2026-10-02.json", "materials-source-followup-2026-10-02.json")
PREFIX = "/v1/research/source-properties"


def private(response):
    assert response.headers["cache-control"] == "private, no-store"
    assert "etag" not in response.headers


def test_frozen_v1_sql_replay_rejects_registry_expansion(monkeypatch):
    monkeypatch.setattr(contract, "REGISTRY_SHA256", "f" * 64)
    with pytest.raises(RuntimeError, match="Frozen 0082"):
        guard_statements()


def _migration(connection, operation):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0082_source_property_pending.py"
    spec = importlib.util.spec_from_file_location("pending_source_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(connection)):
        getattr(module, operation)()


@pytest.mark.asyncio
async def test_empty_new_migration_roundtrip_preserves_existing_schema(db_session):
    before = await state(db_session)
    connection = await db_session.connection()
    await connection.run_sync(lambda conn: _migration(conn, "downgrade"))
    await connection.run_sync(lambda conn: _migration(conn, "upgrade"))
    assert await state(db_session) == before
    await db_session.commit()


@pytest.mark.asyncio
async def test_actual_pending_import_preview_replay_notes_and_guards(client, db_session, monkeypatch):
    monkeypatch.setenv("SOURCE_PROPERTY_PENDING_ENABLED", "true")
    get_settings.cache_clear()
    try:
        curator, reviewer = await research_operator(role="curator"), await research_operator(role="reviewer")
        admin = await research_user(is_admin=True, is_reviewer=True)
        for headers, code in (({}, 401), (admin["headers"], 403)):
            response = await client.get(PREFIX + "/capabilities", headers=headers)
            assert response.status_code == code
            private(response)
        caps = await client.get(PREFIX + "/capabilities", headers=curator["headers"])
        assert caps.json()["can_import"] is True and caps.json()["can_append_source_note"] is False
        assert caps.json()["actor_user_id"] == str(curator["id"])
        private(caps)
        # No privilege can be supplied by JSON, and compressed input is refused.
        for body, headers, status in (({"actor_user_id": str(admin["id"])}, {}, 400),
                                     ({}, {"Content-Encoding": "gzip"}, 415)):
            response = await client.post(PREFIX + "/imports/preview", headers={**curator["headers"], **headers}, json=body)
            assert response.status_code == status, response.text
            private(response)
        before = await state(db_session)
        raw = (PUBLIC / SNAPSHOTS[0]).read_bytes()
        body = {"request_key": "synthetic-source-import:" + uuid4().hex,
                "source_bytes_base64": base64.b64encode(raw).decode("ascii")}
        preview = await client.post(PREFIX + "/imports/preview", headers=curator["headers"], json=body)
        assert preview.status_code == 200, preview.text
        private(preview)
        assert preview.json()["dry_run"] is True
        assert preview.json()["pending_ledger_written"] is False
        assert preview.json()["summary"]["source_task_count"] == 15
        # Close our reader snapshot before taking a fresh inventory.
        await db_session.rollback()
        assert await state(db_session) == before
        await db_session.rollback()
        commit = await client.post(PREFIX + "/imports/commit", headers=curator["headers"],
            json={**body, "expected_preview_sha256": preview.json()["preview_sha256"]})
        assert commit.status_code == 200, commit.text
        assert commit.json()["pending_ledger_written"] is True
        private(commit)
        after = await state(db_session)
        for table in ("materials", "material_claims", "event_properties", "material_states", "structure_records", "source_lifecycle_reviews"):
            assert after[table] == before[table]
        assert len(after[TABLE_ORDER[0]]) == 1 and len(after[TABLE_ORDER[1]]) == 15
        await db_session.rollback()
        replay = await client.post(PREFIX + "/imports/commit", headers=curator["headers"],
            json={**body, "expected_preview_sha256": preview.json()["preview_sha256"]})
        assert replay.status_code == 200 and replay.json()["replayed"] is True
        assert replay.json()["pending_ledger_written"] is True
        assert await state(db_session) == after
        await db_session.rollback()
        outcome = await client.get(PREFIX + "/imports/outcome", headers=curator["headers"],
            params={"request_key": body["request_key"], "expected_request_sha256": commit.json()["request_sha256"]})
        assert outcome.status_code == 200 and outcome.json()["receipt_id"] == commit.json()["receipt_id"]
        conflict = await client.post(PREFIX + "/imports/commit", headers=curator["headers"],
            json={**body, "source_bytes_base64": base64.b64encode((PUBLIC / SNAPSHOTS[1]).read_bytes()).decode("ascii"),
                  "expected_preview_sha256": preview.json()["preview_sha256"]})
        assert conflict.status_code == 409
        listed = await client.get(PREFIX + "/observations", headers=reviewer["headers"])
        if listed.status_code != 200:
            # Native diagnostics expose a static validation code, never source text.
            table = Base.metadata.tables[TABLE_ORDER[1]]
            native_row = (await db_session.execute(sa.select(table).limit(1))).mappings().one()
            service._observation_dto(native_row)
        assert listed.status_code == 200 and listed.json()["total"] == 15
        assert listed.json()["count_scope"] == "pending_source_task_observations_not_independent_experiments"
        obs = listed.json()["observations"][0]
        assert obs["projection"]["status"] == "pending"
        assert obs["projection"]["authority"]["scientific_acceptance"] is False
        assert obs["projection"]["authority"]["scope"] == "source_preparation"
        assert obs["projection"]["display_context_material_id"] is None
        download = await client.get(PREFIX + f"/observations/{obs['id']}/download", headers=curator["headers"])
        assert download.status_code == 200 and download.json()["projection_sha256"] == obs["projection_sha256"]
        assert "attachment" in download.headers["content-disposition"]
        private(download)
        filtered = await client.get(PREFIX + "/observations", headers=curator["headers"],
            params={"field_id": obs["projection"]["field_id"], "source_role": obs["projection"]["source_role"]})
        assert filtered.status_code == 200 and filtered.json()["total"] == 1
        # Browser sessions retain the same existing Origin guard as bearer auth.
        settings = get_settings()
        cookie = build_browser_session_config(settings.environment, settings.jwt_expiry_hours * 3600)
        client.cookies.set(cookie.cookie_name, curator["token"])
        try:
            cookie_get = await client.get(PREFIX + "/capabilities")
            assert cookie_get.status_code == 200
            no_origin = await client.post(PREFIX + "/imports/preview", json=body)
            assert no_origin.status_code == 403
            with_origin = await client.post(PREFIX + "/imports/preview", headers={"Origin": str(settings.frontend_url).rstrip("/")}, json=body)
            assert with_origin.status_code == 200
        finally:
            client.cookies.delete(cookie.cookie_name)
        request = {"request_key": "synthetic-source-note:" + uuid4().hex,
            "observation_id": obs["id"], "observation_sha256": obs["record_sha256"],
            "expected_previous_review_id": None, "expected_previous_review_sha256": None,
            "scope": "source_expression_fidelity_note", "action": "requires_clarification",
            "checks": ["source_subject", "source_window"],
            "note": "Synthetic access and transaction test; no scientific or human review claimed.",
            "source_inspection_attested": True}
        first_withdrawal = {**request, "request_key": "synthetic-first-withdraw:" + uuid4().hex, "action": "withdraw_note"}
        rejected_first = await client.post(PREFIX + "/reviews/preview", headers=reviewer["headers"], json={"request": first_withdrawal})
        assert rejected_first.status_code == 409
        denied = await client.post(PREFIX + "/reviews/preview", headers=curator["headers"], json={"request": request})
        assert denied.status_code == 403
        for bad in ({**request, "action": "scientific_accept"},
                    {**request, "scope": "scientific_result"},
                    {**request, "source_inspection_attested": False},
                    {**request, "actor_user_id": str(reviewer["id"])}):
            rejected = await client.post(PREFIX + "/reviews/preview", headers=reviewer["headers"], json={"request": bad})
            assert rejected.status_code == 400
            private(rejected)
        review_preview = await client.post(PREFIX + "/reviews/preview", headers=reviewer["headers"], json={"request": request})
        assert review_preview.status_code == 200, review_preview.text
        assert review_preview.json()["pending_ledger_written"] is False
        assert await state(db_session) == after
        await db_session.rollback()
        note = await client.post(PREFIX + "/reviews/commit", headers=reviewer["headers"],
            json={"request": request, "expected_preview_sha256": review_preview.json()["preview_sha256"]})
        assert note.status_code == 200, note.text
        assert note.json()["pending_ledger_written"] is True
        assert note.json()["status"] == "pending" and note.json()["scientific_acceptance"] is False
        assert await has_research_audit_references(db_session, reviewer["id"]) is True
        await db_session.rollback()
        note_replay = await client.post(PREFIX + "/reviews/commit", headers=reviewer["headers"],
            json={"request": request, "expected_preview_sha256": review_preview.json()["preview_sha256"]})
        assert note_replay.status_code == 200 and note_replay.json()["replayed"] is True
        assert note_replay.json()["pending_ledger_written"] is True
        note_outcome = await client.get(PREFIX + "/reviews/outcome", headers=reviewer["headers"],
            params={"request_key": request["request_key"], "expected_request_sha256": note.json()["request_sha256"]})
        assert note_outcome.status_code == 200 and note_outcome.json()["review_id"] == note.json()["review_id"]
        other = await research_operator(role="reviewer")
        withdrawal = {**request, "request_key": "synthetic-withdraw-note:" + uuid4().hex,
            "expected_previous_review_id": note.json()["review_id"],
            "expected_previous_review_sha256": note.json()["review_sha256"], "action": "withdraw_note"}
        other_withdraw = await client.post(PREFIX + "/reviews/preview", headers=other["headers"], json={"request": withdrawal})
        assert other_withdraw.status_code == 409
        withdrawal_preview = await client.post(PREFIX + "/reviews/preview", headers=reviewer["headers"], json={"request": withdrawal})
        assert withdrawal_preview.status_code == 200
        withdrawn = await client.post(PREFIX + "/reviews/commit", headers=reviewer["headers"],
            json={"request": withdrawal, "expected_preview_sha256": withdrawal_preview.json()["preview_sha256"]})
        assert withdrawn.status_code == 200 and withdrawn.json()["review_number"] == 2
        double_withdrawal = {**withdrawal, "request_key": "synthetic-double-withdraw:" + uuid4().hex,
            "expected_previous_review_id": withdrawn.json()["review_id"],
            "expected_previous_review_sha256": withdrawn.json()["review_sha256"]}
        rejected_double = await client.post(PREFIX + "/reviews/preview", headers=reviewer["headers"], json={"request": double_withdrawal})
        assert rejected_double.status_code == 409
        source_detail = await client.get(PREFIX + f"/observations/{obs['id']}", headers=reviewer["headers"])
        assert source_detail.json()["source_notes_total"] == 2
        assert source_detail.json()["projection"]["status"] == "pending"
        assert source_detail.json()["record_sha256"] == obs["record_sha256"]
        bad_request = {**request, "request_key": "synthetic-note-fork:" + uuid4().hex}
        stale = await client.post(PREFIX + "/reviews/preview", headers=reviewer["headers"], json={"request": bad_request})
        assert stale.status_code == 409
        for table_name in TABLE_ORDER:
            table = Base.metadata.tables[table_name]
            for query in (table.update().values(record_sha256="a" * 64), table.delete(), sa.text(f"TRUNCATE public.{table_name}")):
                with pytest.raises(DBAPIError):
                    async with db_session.begin_nested():
                        await db_session.execute(query)
        await db_session.rollback()
        await revoke_research_grant(grant_id=reviewer["grant_id"], revoked_by=reviewer["grantor_id"])
        revoked = await client.get(PREFIX + f"/observations/{obs['id']}", headers=reviewer["headers"])
        assert revoked.status_code == 403
        private(revoked)
        monkeypatch.setenv("SOURCE_PROPERTY_PENDING_ENABLED", "false")
        get_settings.cache_clear()
        closed = await client.get(PREFIX + "/capabilities", headers=curator["headers"])
        assert closed.status_code == 404
        private(closed)
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", ["quantity_value", "component_role", "range_unit", "omit_statement", "provenance"])
async def test_sql_rejects_forged_typed_value_even_with_consistent_manifest(db_session, monkeypatch, tamper):
    curator = await research_operator(role="curator")
    raw = (PUBLIC / SNAPSHOTS[1]).read_bytes()
    prepared = contract.compile_public_snapshot(raw)
    observations = deepcopy(prepared.observations)
    if tamper == "range_unit":
        target = next(row for row in observations if row["values"]["ranges"])
        target["values"]["ranges"][0]["unit"] = "K"
    else:
        target = next(row for row in observations if row["values"]["quantities"])
        if tamper == "quantity_value":
            target["values"]["quantities"][0]["quantity"]["value"] = 987654.0
        elif tamper == "component_role":
            target["values"]["quantities"][0]["component_role"] = "electron_phonon_coupling"
        elif tamper == "omit_statement":
            target["values"]["statements"].pop()
        else:
            target["provenance"]["sources"] = []
    # Deliberately bypass app-only checks: the SQL pointer guard must still fail.
    monkeypatch.setattr(contract, "compile_public_snapshot", lambda _: replace(prepared, observations=observations))
    monkeypatch.setattr(contract, "validate_observation", lambda value: value)
    before = await state(db_session)
    with pytest.raises(DBAPIError):
        await service.import_snapshot(db_session, actor_user_id=curator["id"],
            request_key_value="synthetic-forged-projection:" + uuid4().hex, source_bytes=raw, dry_run=True)
    assert await state(db_session) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("forgery", ["reviewer_as_curator", "session_version"])
async def test_sql_rechecks_actor_role_and_session_independent_of_service(db_session, monkeypatch, forgery):
    operator = await research_operator(role="reviewer" if forgery == "reviewer_as_curator" else "curator")
    grants = Base.metadata.tables["research_role_grants"]
    grant = (await db_session.execute(sa.select(grants).where(grants.c.id == operator["grant_id"]))).mappings().one()

    async def fake_grant(*_args, **_kwargs):
        return grant, 1 if forgery == "session_version" else 0

    monkeypatch.setattr(service, "_grant", fake_grant)
    before = await state(db_session)
    with pytest.raises(DBAPIError):
        await service.import_snapshot(db_session, actor_user_id=operator["id"],
            request_key_value="synthetic-sql-actor-forgery:" + uuid4().hex,
            source_bytes=(PUBLIC / SNAPSHOTS[1]).read_bytes(), dry_run=True)
    assert await state(db_session) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing_head", "other_actor", "double_withdraw"])
async def test_sql_withdrawal_requires_own_preceding_nonwithdraw_note(db_session, case):
    actor, other = await research_operator(role="reviewer"), await research_operator(role="reviewer")
    obs_table, reviews = Base.metadata.tables[TABLE_ORDER[1]], Base.metadata.tables[TABLE_ORDER[2]]
    obs = (await db_session.execute(sa.select(obs_table).where(~sa.exists(sa.select(reviews.c.id)
        .where(reviews.c.observation_id == obs_table.c.id))).limit(1))).mappings().one()
    note_request = {"request_key": "synthetic-sql-note:" + uuid4().hex, "observation_id": str(obs["id"]),
        "observation_sha256": obs["record_sha256"], "expected_previous_review_id": None,
        "expected_previous_review_sha256": None, "scope": "source_expression_fidelity_note",
        "action": "requires_clarification", "checks": ["source_expression"],
        "note": "Synthetic SQL ownership boundary test; no human scientific inspection claimed.",
        "source_inspection_attested": True}
    head = None
    if case != "missing_head":
        owner = other if case == "other_actor" else actor
        preview = await service.append_review(db_session, actor_user_id=owner["id"], request=note_request)
        head = await service.append_review(db_session, actor_user_id=owner["id"], request=note_request,
            dry_run=False, expected_preview_sha256=preview["preview_sha256"])
        if case == "double_withdraw":
            request = {**note_request, "request_key": "synthetic-sql-own-withdraw:" + uuid4().hex,
                "action": "withdraw_note", "expected_previous_review_id": head["review_id"],
                "expected_previous_review_sha256": head["review_sha256"]}
            preview = await service.append_review(db_session, actor_user_id=actor["id"], request=request)
            head = await service.append_review(db_session, actor_user_id=actor["id"], request=request,
                dry_run=False, expected_preview_sha256=preview["preview_sha256"])
    request = {**note_request, "request_key": "synthetic-sql-illegal-withdraw:" + uuid4().hex, "action": "withdraw_note",
        "expected_previous_review_id": None if head is None else head["review_id"],
        "expected_previous_review_sha256": None if head is None else head["review_sha256"]}
    actor_binding = {"actor_user_id": actor["id"], "actor_grant_id": actor["grant_id"], "actor_session_version": 0}
    note = {key: request[key] for key in ("scope", "action", "observation_id", "observation_sha256",
        "source_inspection_attested", "checks", "note")}
    request_sha = digest(request)
    preview_sha = digest({"version": service.VERSION, "actor": service._body(actor_binding),
        "request_sha256": request_sha, "observation_sha256": obs["record_sha256"],
        "previous_review_sha256": request["expected_previous_review_sha256"]})
    before = await state(db_session)
    # Bypass the service's own-withdraw check and supply otherwise self-consistent
    # request/preview/record hashes. PostgreSQL must reject the action itself.
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await service._insert(db_session, TABLE_ORDER[2], {"id": uuid4(), **actor_binding,
                "observation_id": obs["id"], "observation_sha256": obs["record_sha256"],
                "request_key": request["request_key"], "request_sha256": request_sha, "preview_sha256": preview_sha,
                "review_number": 1 if head is None else head["review_number"] + 1,
                "predecessor_id": None if head is None else service.identifier(head["review_id"]),
                "predecessor_sha256": request["expected_previous_review_sha256"], "action": "withdraw_note",
                "review_json": canonical(note).decode("utf-8"), "review_sha256": digest(note)})
    assert await state(db_session) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_check", [None, 0, True, {}, ["source_expression"]])
async def test_sql_review_check_items_require_enum_strings(db_session, invalid_check):
    actor = await research_operator(role="reviewer")
    obs_table, reviews = Base.metadata.tables[TABLE_ORDER[1]], Base.metadata.tables[TABLE_ORDER[2]]
    obs = (await db_session.execute(sa.select(obs_table).where(~sa.exists(sa.select(reviews.c.id)
        .where(reviews.c.observation_id == obs_table.c.id))).limit(1))).mappings().one()
    request = {"request_key": "synthetic-sql-invalid-check:" + uuid4().hex, "observation_id": str(obs["id"]),
        "observation_sha256": obs["record_sha256"], "expected_previous_review_id": None,
        "expected_previous_review_sha256": None, "scope": "source_expression_fidelity_note",
        "action": "matches_inspected_source", "checks": [invalid_check],
        "note": "Synthetic SQL type boundary test; no human scientific inspection claimed.",
        "source_inspection_attested": True}
    actor_binding = {"actor_user_id": actor["id"], "actor_grant_id": actor["grant_id"], "actor_session_version": 0}
    note = {key: request[key] for key in ("scope", "action", "observation_id", "observation_sha256",
        "source_inspection_attested", "checks", "note")}
    request_sha = digest(request)
    preview_sha = digest({"version": service.VERSION, "actor": service._body(actor_binding),
        "request_sha256": request_sha, "observation_sha256": obs["record_sha256"], "previous_review_sha256": None})
    before = await state(db_session)
    # The service rejects these inputs. Prove the independent SQL guard also
    # rejects malformed check items when every submitted hash agrees.
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await service._insert(db_session, TABLE_ORDER[2], {"id": uuid4(), **actor_binding,
                "observation_id": obs["id"], "observation_sha256": obs["record_sha256"],
                "request_key": request["request_key"], "request_sha256": request_sha, "preview_sha256": preview_sha,
                "review_number": 1, "predecessor_id": None, "predecessor_sha256": None,
                "action": request["action"], "review_json": canonical(note).decode("utf-8"), "review_sha256": digest(note)})
    assert await state(db_session) == before


@pytest.mark.asyncio
async def test_actual_second_batch_retains_unavailable_without_material_binding(db_session):
    curator = await research_operator(role="curator")
    raw = (PUBLIC / SNAPSHOTS[1]).read_bytes()
    key = "synthetic-second-batch:" + uuid4().hex
    before = await state(db_session)
    preview = await service.import_snapshot(db_session, actor_user_id=curator["id"], request_key_value=key, source_bytes=raw)
    assert preview["summary"]["source_task_count"] == 34
    assert preview["summary"]["source_unavailable_count"] == 3
    assert await state(db_session) == before
    receipt = await service.import_snapshot(db_session, actor_user_id=curator["id"], request_key_value=key,
        source_bytes=raw, dry_run=False, expected_preview_sha256=preview["preview_sha256"])
    assert receipt["summary"]["source_expression_count"] == 31
    after = await state(db_session)
    assert all(after[name] == before[name] for name in ("materials", "material_claims", "event_properties", "source_lifecycle_reviews"))
    rows = [row for row in after[TABLE_ORDER[1]] if row["source_json_sha256"] == receipt["source_json_sha256"]]
    assert len(rows) == 34 and all(row["status"] == "pending" and row["display_context_material_id"] is None for row in rows)
    with pytest.raises(RuntimeError, match="Refusing downgrade"):
        connection = await db_session.connection()
        await connection.run_sync(lambda conn: _migration(conn, "downgrade"))
    assert await state(db_session) == after
    await db_session.commit()
    # The fixture creates the current metadata rather than upgrading historical
    # schemas. Stamp that test setup explicitly, then invoke real Alembic online
    # downgrade in its own migration session; refusal must retain its marker.
    # The separate complete owned migration runner proves historical replay.
    api = Path(__file__).resolve().parents[1]
    config = Config(str(api / "alembic.ini"))
    config.set_main_option("script_location", str(api / "alembic"))
    await asyncio.to_thread(command.stamp, config, "0082_source_property_pending")
    marker_before = (await db_session.execute(sa.text("SELECT version_num FROM alembic_version"))).scalars().all()
    assert marker_before == ["0082_source_property_pending"]
    await db_session.rollback()
    with pytest.raises(RuntimeError, match="Refusing downgrade"):
        await asyncio.to_thread(command.downgrade, config, "0081_index_search")
    assert (await db_session.execute(sa.text("SELECT version_num FROM alembic_version"))).scalars().all() == marker_before
    assert await state(db_session) == after
    await db_session.rollback()
