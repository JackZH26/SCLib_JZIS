"""Owned SQL/auth proof for private new fragments; inline sources synthetic."""

from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError

from config import get_settings
from models.source_expression_intake_v2 import TABLE_ORDER
from services import source_expression_contract_v2 as contract
from services import source_expression_intake_v2 as service
from services.research_release_manifest import canonical, digest
from services.session_config import build_browser_session_config
from tests.research_access_helpers import research_operator, research_user, revoke_research_grant
from tests.test_research_freeze import db_session as _serializable_db_session
from tests.test_research_freeze import state
from tests.test_source_expression_contract_v2 import synthetic_package

db_session = _serializable_db_session
PREFIX = "/v1/research/source-expressions"


def private(response):
    assert response.headers["cache-control"] == "private, no-store"
    assert "etag" not in response.headers


def package():
    p = synthetic_package()
    p["source"]["source_id"] += ":" + uuid4().hex
    return p


async def save(client, operator, p):
    body = {"request_key": "synthetic-v2:" + uuid4().hex, "package": p}
    preview = await client.post(PREFIX + "/imports/preview", headers=operator["headers"], json=body)
    assert preview.status_code == 200, preview.text
    result = await client.post(
        PREFIX + "/imports/commit",
        headers=operator["headers"],
        json={**body, "expected_preview_sha256": preview.json()["preview_sha256"]},
    )
    assert result.status_code == 200, result.text
    return body, result.json()


def _migration(connection, action):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = Path(__file__).resolve().parents[1] / "alembic/versions/0083_source_expression_intake.py"
    spec = importlib.util.spec_from_file_location("source_expression_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(connection)):
        getattr(module, action)()


@pytest.mark.asyncio
async def test_empty_0083_roundtrip_preserves_all_0082_rows(db_session):
    # The additive 0084 field-case namespace has restrictive foreign keys to
    # 0083. Its own empty-only downgrade refuses retained audit history.
    from tests.test_material_field_cases import migration as field_case_migration
    before = await state(db_session)
    connection = await db_session.connection()
    await connection.run_sync(lambda conn: field_case_migration(conn, "downgrade"))
    await connection.run_sync(lambda conn: _migration(conn, "downgrade"))
    await connection.run_sync(lambda conn: _migration(conn, "upgrade"))
    await connection.run_sync(lambda conn: field_case_migration(conn, "upgrade"))
    assert await state(db_session) == before
    await db_session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "printed,selected,unit",
    [
        ("94.5 K", "94.5 K", None),
        ("-2.8 ± 0.2 K", "-2.8 ± 0.2 K", None),
        ("66 mK", "66 mK", None),
        ("1e-999 K", "1e-999 K", None),
        ("~66 ± 2 K", "~66 ± 2 K", None),
        ("66 unusual", "66 unusual", None),
        ("94.5 K", "94", "K"),
        ("≤66 K", "66", "K"),
        ("66 mK", "66", "K"),
        ("66 K/GPa", "66 K", None),
        ("66 K^2", "66 K", None),
        ("6.6 ×10^3 K", "6.6", "K"),
        ("66", "66", None),
        ("<t>-</t><t>2.8</t><t> K</t>", "2.8", "K"),
        ("<t>66 </t><t>m</t><t>K</t>", "66", "K"),
        ("<t>-2.8</t><t> K</t>", "-2.8", "K"),
    ],
)
async def test_independent_sql_projection_preserves_grammar_and_token_semantics(
    db_session, printed, selected, unit
):
    import json

    import sqlalchemy as sa

    from tests.test_source_expression_contract_v2 import span

    raw = "YScH10 94.5 K at 200 GPa. Computed model X. " + printed
    p = synthetic_package(raw)
    if printed.startswith("<t>"):
        p["source"]["content_kind"] = "xml_text"
    start = len(raw) - len(printed)
    e = p["expressions"][0]
    e["value_spans"] = [span(raw, selected, start)]
    e["unit_spans"] = [] if unit is None else [span(raw, unit, start)]
    prepared = contract.compile_package(p)
    actual = await db_session.scalar(
        sa.text(
            "SELECT public.sclib_source_expression_project_v2(CAST(:source AS jsonb),:raw,CAST(:entry AS jsonb))::text"
        ),
        {"source": canonical(p["source"]).decode(), "raw": raw, "entry": canonical(e).decode()},
    )
    assert json.loads(actual) == prepared.projections[0]


@pytest.mark.asyncio
async def test_private_flag_authority_preview_atomic_successor_and_outcome(
    client, db_session, monkeypatch
):
    get_settings.cache_clear()
    response = await client.get(PREFIX + "/capabilities")
    assert response.status_code == 404
    private(response)
    monkeypatch.setenv("SOURCE_PROPERTY_PENDING_ENABLED", "true")
    get_settings.cache_clear()
    try:
        operator = await research_operator(role="curator")
        reviewer = await research_operator(role="reviewer")
        admin = await research_user(is_admin=True, is_reviewer=True)
        for headers, expected in (({}, 401), (admin["headers"], 403)):
            result = await client.get(PREFIX + "/capabilities", headers=headers)
            assert result.status_code == expected
            private(result)
        caps = await client.get(PREFIX + "/capabilities", headers=operator["headers"])
        assert caps.status_code == 200 and caps.json()["can_import"]
        assert caps.json()["actor_user_id"] == str(operator["id"])
        p = package()
        second = deepcopy(p["expressions"][0])
        second["window"]["id"] = "other-window"
        p["expressions"].append(second)
        body = {"request_key": "synthetic-v2:" + uuid4().hex, "package": p}
        denied = await client.post(
            PREFIX + "/imports/preview", headers=reviewer["headers"], json=body
        )
        assert denied.status_code == 403
        before = await state(db_session)
        await db_session.rollback()
        preview = await client.post(
            PREFIX + "/imports/preview", headers=operator["headers"], json=body
        )
        if preview.status_code != 200:
            await service.import_package(
                db_session,
                actor_user_id=str(operator["id"]),
                request_key_value=body["request_key"],
                package=p,
            )
        assert preview.status_code == 200, preview.text
        private(preview)
        assert preview.json()["dry_run"] and not preview.json()["pending_ledger_written"]
        assert await state(db_session) == before
        await db_session.rollback()
        committed = await client.post(
            PREFIX + "/imports/commit",
            headers=operator["headers"],
            json={**body, "expected_preview_sha256": preview.json()["preview_sha256"]},
        )
        assert committed.status_code == 200, committed.text
        assert (
            committed.json()["pending_ledger_written"]
            and not committed.json()["scientific_acceptance"]
        )
        after = await state(db_session)
        for name in (
            "materials",
            "material_claims",
            "event_properties",
            "material_states",
            "structure_records",
            "source_lifecycle_reviews",
            "source_property_import_receipts",
        ):
            assert after[name] == before[name]
        connection = await db_session.connection()
        nested = await db_session.begin_nested()
        with pytest.raises(RuntimeError, match="Refusing downgrade"):
            await connection.run_sync(lambda conn: _migration(conn, "downgrade"))
        await nested.rollback()
        assert await state(db_session) == after
        await db_session.rollback()
        replay = await client.post(
            PREFIX + "/imports/commit",
            headers=operator["headers"],
            json={**body, "expected_preview_sha256": preview.json()["preview_sha256"]},
        )
        assert replay.status_code == 200 and replay.json()["replayed"]
        assert await state(db_session) == after
        await db_session.rollback()
        outcome = await client.get(
            PREFIX + "/imports/outcome",
            headers=operator["headers"],
            params={
                "request_key": body["request_key"],
                "expected_request_sha256": committed.json()["request_sha256"],
            },
        )
        assert (
            outcome.status_code == 200
            and outcome.json()["receipt_id"] == committed.json()["receipt_id"]
        )
        listed = await client.get(
            PREFIX + "/expressions",
            headers=reviewer["headers"],
            params={"source_id": p["source"]["source_id"]},
        )
        assert listed.status_code == 200 and listed.json()["total"] == 2
        original = listed.json()["expressions"][0]
        assert (
            digest(__import__("json").loads(original["projection_canonical_json"]))
            == original["projection_sha256"]
        )
        assert original["capture"]["fragment_integrity"] == "server_verified_retained_bytes"
        assert original["capture"]["parent_integrity"] == "declared_not_verified"
        detail = await client.get(
            PREFIX + "/expressions/" + original["id"], headers=reviewer["headers"]
        )
        assert detail.status_code == 200
        proof = detail.json()
        revision_body = __import__("json").loads(proof["revision_canonical_json"])
        assert digest(revision_body) == proof["record_sha256"]
        assert (
            revision_body["import_receipt_sha256"]
            == proof["import_receipt_sha256"]
            == proof["import_receipt"]["receipt_sha256"]
        )
        successor = deepcopy(p)
        successor["expressions"] = [
            next(
                e
                for e, projected in zip(
                    p["expressions"], contract.compile_package(p).projections, strict=True
                )
                if projected["expression_key"] == original["expression_key"]
            )
        ]
        successor["expressions"][0]["predecessor"] = {
            "revision_id": original["id"],
            "record_sha256": original["record_sha256"],
            "revision_number": 1,
        }
        successor["expressions"][0]["knowledge_origin"] = "unknown"
        _, saved = await save(client, operator, successor)
        assert saved["expression_manifest"][0]["revision_number"] == 2
        old = await client.get(
            PREFIX + "/expressions/" + original["id"], headers=reviewer["headers"]
        )
        assert (
            old.status_code == 200
            and old.json()["projection_sha256"] == original["projection_sha256"]
        )
        assert old.json()["is_expression_head"] is False
        stale = await client.post(
            PREFIX + "/imports/preview",
            headers=operator["headers"],
            json={"request_key": "synthetic-stale:" + uuid4().hex, "package": successor},
        )
        assert stale.status_code == 409
        # Current browser-session Origin guard is inherited, not bypassed.
        cookie = build_browser_session_config(get_settings().environment, 3600)
        client.cookies.set(cookie.cookie_name, operator["token"])
        try:
            denied = await client.post(PREFIX + "/imports/preview", json=body)
            assert denied.status_code == 403
        finally:
            client.cookies.delete(cookie.cookie_name)
        await revoke_research_grant(
            grant_id=operator["grant_id"], revoked_by=operator["grantor_id"]
        )
        revoked = await client.get(
            PREFIX + "/imports/outcome",
            headers=operator["headers"],
            params={
                "request_key": body["request_key"],
                "expected_request_sha256": committed.json()["request_sha256"],
            },
        )
        assert revoked.status_code == 403
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "alter",
    [
        "quantity",
        "origin_null",
        "span_null",
        "condition_null",
        "incomplete",
        "duplicate",
        "reverse",
        "overlap",
        "separated",
        "unit_assembly",
        "condition_assembly",
        "receipt_pin",
    ],
)
async def test_sql_rebuild_rejects_self_hashed_tamper_and_partial_inventory(db_session, alter):
    operator = await research_operator(role="curator")
    p = package()
    prepared = contract.compile_package(p)
    # Run the real service within a rollback savepoint, mutating just before INSERT.
    original = service._insert

    async def tampered(db, name, values):
        values = deepcopy(values)
        if name == TABLE_ORDER[1] and alter in {
            "origin_null",
            "span_null",
            "condition_null",
            "duplicate",
            "reverse",
            "overlap",
            "separated",
            "unit_assembly",
            "condition_assembly",
        }:
            document = __import__("json").loads(values["package_json"])
            e = document["expressions"][0]
            if alter == "origin_null":
                e["knowledge_origin"] = None
            elif alter == "span_null":
                e["value_spans"][0]["sha256"] = None
            elif alter == "condition_null":
                e["conditions"][0]["role"] = None
            else:
                from tests.test_source_expression_contract_v2 import span

                raw = prepared.source_text
                if alter == "duplicate":
                    e["value_spans"] = [span(raw, "9"), span(raw, "9")]
                elif alter == "reverse":
                    e["subject"]["formula_spans"] = [span(raw, "10"), span(raw, "YScH")]
                elif alter == "overlap":
                    e["subject"]["formula_spans"] = [span(raw, "YScH"), span(raw, "ScH10")]
                elif alter == "separated":
                    e["value_spans"] = [span(raw, "9"), span(raw, "4.5")]
                elif alter == "unit_assembly":
                    e["unit_spans"] = [span(raw, "K"), span(raw, "GPa")]
                else:
                    e["conditions"][0]["value_spans"] *= 2
            values["package_json"] = canonical(document).decode()
            values["package_sha256"] = digest(document)
            values["request_sha256"] = digest(
                {"version": service.VERSION, "package_sha256": values["package_sha256"]}
            )
            actor = {
                k: values[k] for k in ("actor_user_id", "actor_grant_id", "actor_session_version")
            }
            values["preview_sha256"] = digest(
                {
                    "version": service.VERSION,
                    "request_key": values["request_key"],
                    "request_sha256": values["request_sha256"],
                    "actor": service._body(actor),
                    "manifest": values["expression_manifest"],
                }
            )
        if name == TABLE_ORDER[2] and alter == "quantity":
            projection = __import__("json").loads(values["projection_json"])
            projection["value"]["value"] = 999.0
            values["projection_json"], values["projection_sha256"] = (
                canonical(projection).decode(),
                digest(projection),
            )
        if name == TABLE_ORDER[2] and alter == "incomplete":
            return values
        if name == TABLE_ORDER[2] and alter == "receipt_pin":
            values["import_receipt_sha256"] = "a" * 64
        return await original(db, name, values)

    from unittest.mock import patch

    before = await state(db_session)
    with patch.object(service, "_insert", tampered), pytest.raises(DBAPIError) as rejected:
        await service.import_package(
            db_session,
            actor_user_id=str(operator["id"]),
            request_key_value="synthetic-direct:" + uuid4().hex,
            package=p,
            dry_run=True,
        )
    assert rejected.value.orig.sqlstate == "23514"
    assert await state(db_session) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "printed,selected,unit",
    [
        ("94.5 K", "94", "K"),
        ("-2.8 K", "2.8", "K"),
        ("≤66 K", "66", "K"),
        ("1e3 K", "3", "K"),
        ("66 ± 2 K", "66", "K"),
        ("66(5) K", "66", "K"),
        ("66 mK", "66", "K"),
        ("66 K/GPa", "66 K", None),
        ("66 K^2", "66 K", None),
        ("6.6 ×10^3 K", "6.6", "K"),
        ("<t>-</t><t>2.8</t><t> K</t>", "2.8", "K"),
        ("<t>66 </t><t>m</t><t>K</t>", "66", "K"),
    ],
)
async def test_sql_partial_token_cannot_be_self_hashed_into_normalized_value(
    db_session, printed, selected, unit
):
    from unittest.mock import patch

    from tests.test_source_expression_contract_v2 import span

    operator = await research_operator(role="curator")
    raw = "YScH10 94.5 K at 200 GPa. Computed model X. " + printed
    p = synthetic_package(raw)
    if printed.startswith("<t>"):
        p["source"]["content_kind"] = "xml_text"
    p["source"]["source_id"] += ":" + uuid4().hex
    e = p["expressions"][0]
    e["value_spans"] = [span(raw, selected, len(raw) - len(printed))]
    e["unit_spans"] = [] if unit is None else [span(raw, unit, len(raw) - len(printed))]
    prepared = contract.compile_package(p)
    assert prepared.projections[0]["value"]["value"] is None
    forged = deepcopy(prepared.projections[0])
    forged["value"] = contract.quantity(selected, unit, e["field_id"])
    assert forged["value"]["status"] == "parsed"
    original = service._insert

    async def forged_scalar(db, name, values):
        values = deepcopy(values)
        if name == TABLE_ORDER[1]:
            values["expression_manifest"][0]["projection_sha256"] = digest(forged)
            values["preview_sha256"] = digest(
                {
                    "version": service.VERSION,
                    "request_key": values["request_key"],
                    "request_sha256": values["request_sha256"],
                    "actor": service._body(
                        {
                            key: values[key]
                            for key in ("actor_user_id", "actor_grant_id", "actor_session_version")
                        }
                    ),
                    "manifest": values["expression_manifest"],
                }
            )
        if name == TABLE_ORDER[2]:
            values["projection_json"] = canonical(forged).decode()
            values["projection_sha256"] = digest(forged)
        return await original(db, name, values)

    before = await state(db_session)
    with patch.object(service, "_insert", forged_scalar), pytest.raises(DBAPIError) as rejected:
        await service.import_package(
            db_session,
            actor_user_id=str(operator["id"]),
            request_key_value="synthetic-token:" + uuid4().hex,
            package=p,
            dry_run=True,
        )
    assert rejected.value.orig.sqlstate == "23514"
    assert "source_expression_exact_projection" in str(rejected.value.orig)
    assert await state(db_session) == before


@pytest.mark.asyncio
async def test_actor_preview_binding_and_declared_currentness_never_verify_publication(
    client, db_session, monkeypatch
):
    monkeypatch.setenv("SOURCE_PROPERTY_PENDING_ENABLED", "true")
    get_settings.cache_clear()
    try:
        first = await research_operator(role="curator")
        other = await research_operator(role="curator")
        p = package()
        body = {"request_key": "synthetic-actor:" + uuid4().hex, "package": p}
        preview = await client.post(
            PREFIX + "/imports/preview", headers=first["headers"], json=body
        )
        assert preview.status_code == 200
        before = await state(db_session)
        await db_session.rollback()
        denied = await client.post(
            PREFIX + "/imports/commit",
            headers=other["headers"],
            json={**body, "expected_preview_sha256": preview.json()["preview_sha256"]},
        )
        assert denied.status_code == 409
        private(denied)
        assert await state(db_session) == before
        await db_session.rollback()
        _, committed = await save(client, first, p)
        revision = committed["expression_manifest"][0]
        listed = (
            await client.get(
                PREFIX + "/expressions",
                headers=first["headers"],
                params={"source_id": p["source"]["source_id"]},
            )
        ).json()["expressions"][0]
        p["source"]["currentness"] = "declared_current"
        p["expressions"][0]["predecessor"] = {
            "revision_id": listed["id"],
            "record_sha256": listed["record_sha256"],
            "revision_number": revision["revision_number"],
        }
        _, new = await save(client, first, p)
        response = await client.get(
            PREFIX + "/captures",
            headers=first["headers"],
            params={"currentness": "declared_current"},
        )
        assert response.status_code == 200
        capture = next(c for c in response.json()["captures"] if c["id"] == new["capture_id"])
        assert capture["latest_retained_capture_for_source"]
        assert capture["source"]["currentness"] == "declared_current"
        assert (
            capture["publication_currentness_verified"] is False
            and capture["rights_verified"] is False
        )
        wrong = await client.get(
            PREFIX + "/imports/outcome",
            headers=other["headers"],
            params={
                "request_key": body["request_key"],
                "expected_request_sha256": committed["request_sha256"],
            },
        )
        assert wrong.status_code == 404
        private(wrong)
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_actual_maximum_escape_page_is_bounded_and_pagination_omits_no_heads(
    client, monkeypatch
):
    from routers.source_properties import MAX_RESPONSE_BYTES
    from tests.test_source_expression_contract_v2 import escaping_package

    monkeypatch.setenv("SOURCE_PROPERTY_PENDING_ENABLED", "true")
    get_settings.cache_clear()
    try:
        actor = await research_operator(role="curator")
        p = escaping_package()
        p["source"]["source_id"] += ":" + uuid4().hex
        prepared = contract.compile_package(p)
        assert 30000 < len(canonical(prepared.projections[0])) <= contract.MAX_PROJECTION_BYTES
        await save(client, actor, p)
        params = {"source_id": p["source"]["source_id"]}
        first = await client.get(PREFIX + "/expressions", headers=actor["headers"], params=params)
        assert first.status_code == 200, first.text[:200]
        assert len(first.content) < MAX_RESPONSE_BYTES
        assert (
            first.json()["total"] == 9
            and first.json()["limit"] == 8
            and len(first.json()["expressions"]) == 8
        )
        second = await client.get(
            PREFIX + "/expressions", headers=actor["headers"], params={**params, "offset": 8}
        )
        assert second.status_code == 200 and len(second.json()["expressions"]) == 1
        ids = {row["id"] for page in (first, second) for row in page.json()["expressions"]}
        assert len(ids) == 9
        too_many = await client.get(
            PREFIX + "/expressions", headers=actor["headers"], params={**params, "limit": 9}
        )
        assert too_many.status_code == 400
        private(too_many)
    finally:
        get_settings.cache_clear()
