"""Actual source-table bytes, with explicitly synthetic catalog targets only.

Runs exclusively in the disposable PostgreSQL runner. Passing tests establish
retention/proposal behavior, not independent review or physical sample identity.
"""
import base64
import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from config import get_settings
from models import material_literal_fields_v1 as literal_model
from models import source_expression_intake_v2 as frozen_source_model
from models.db import Base
from services import material_field_case_contract_v1_1 as passage_cases
from services import material_field_case_contract_v1_2 as table_cases
from services import material_field_cases as cases
from services import source_expression_contract_v2_2 as contract
from services import source_expression_intake_v2 as expressions
from services.material_table_field_prepare import prepare_table_package
from services.research_release_manifest import canonical, digest
from services.source_property_pending import SourcePropertyError
from tests.research_access_helpers import research_operator, revoke_research_grant
from tests.test_material_field_cases import association, retained, save
from tests.test_material_literal_field_bridge import _authority, _frozen_definitions
from tests.test_material_literal_field_bridge import (
    committed_literal_read_db as _committed_table_db,
)
from tests.test_research_freeze import db_session as _owned_db_session
from tests.test_research_freeze import state

db_session = _owned_db_session
committed_table_db = _committed_table_db
PROJECT = "public.sclib_material_table_project_v1"


def actual_table_package():
    root = Path(__file__).resolve().parents[2]
    capture = json.loads((root / "docs/data/materials-thermal-table-capture-2026-10-05.json").read_text())
    metadata = {
        "source_id": capture["id"] + ":disposable:" + uuid4().hex,
        "url": capture["source_url"], "kind": "primary_paper", "content_kind": "plain_text",
        "revision": None, "revision_status": "unresolved",
        "original_parent_sha256": capture["capture_sha256"], "parent_hash_status": "declared",
        "rights_status": "unresolved", "currentness": "unresolved", "captured_at": "2026-10-02T00:00:00Z",
    }
    return prepare_table_package(capture, formulas=["Mo5P1.1B1.9", "Mo5PB2"], source_metadata=metadata)


async def frozen_definitions(db):
    result = await _frozen_definitions(db)
    for name, args in literal_model.FUNCTION_SIGNATURES:
        signature = f"public.{name}({args})"
        row = (await db.execute(sa.text(
            "SELECT pg_get_functiondef(to_regprocedure(:signature)) AS definition, "
            "prosrc AS body FROM pg_proc WHERE oid=to_regprocedure(:signature)"
        ), {"signature": signature})).mappings().one()
        sql = next(s for s in literal_model.upgrade_statements()
                   if s.lstrip().startswith("CREATE FUNCTION public." + name + "("))
        assert row["body"] == re.search(r"\bAS \$\$(.*?)\$\$", sql, re.S).group(1)
        result[signature] = row["definition"]
    return result


async def import_table(db, actor, package=None):
    package = package or actual_table_package()
    prepared = contract.compile_package(package)
    key = "table-test:" + uuid4().hex
    before = await state(db)
    preview = await expressions.import_package(db, actor_user_id=actor["id"], request_key_value=key, package=package)
    assert await state(db) == before
    saved = await expressions.import_package(db, actor_user_id=actor["id"], request_key_value=key,
        package=package, dry_run=False, expected_preview_sha256=preview["preview_sha256"])
    assert saved["receipt_sha256"] == preview["receipt_sha256"]
    assert saved["version"] == expressions.TABLE_VERSION
    rows = [await expressions.expression(db, actor_user_id=actor["id"], profile=contract.PROFILE,
            revision_id=str(expressions._stable("revision", saved["receipt_id"], i)))
            for i in range(4)]
    assert [r["projection"] for r in rows] == list(prepared.projections)
    replay_state = await state(db)
    replay = await expressions.import_package(db, actor_user_id=actor["id"], request_key_value=key, package=package)
    assert replay["replayed"] and replay["receipt_sha256"] == saved["receipt_sha256"]
    assert await state(db) == replay_state
    return package, prepared, saved, rows


async def table_target(db, actor, material, field):
    ctx = await cases.context(db, actor_user_id=actor["id"], material_id=material, record_index=0)
    request = {"version": table_cases.REQUEST_VERSION, "request_key": "table-target:" + uuid4().hex,
               "operation": "target", "payload": {"field_id": field, "target": ctx["target"]}}
    before = await state(db)
    preview = await cases.operate(db, actor_user_id=actor["id"], request=request)
    assert await state(db) == before
    saved = await cases.operate(db, actor_user_id=actor["id"], request=request, dry_run=False,
                               expected_preview_sha256=preview["preview_sha256"])
    assert saved["receipt_sha256"] == preview["receipt_sha256"]
    return saved


@pytest.mark.asyncio
async def test_actual_four_readings_sql_parity_pending_cases_and_isolated_profiles(db_session):
    db = db_session
    actor = await research_operator()
    frozen = await frozen_definitions(db)
    material, paper = await retained(db, record={"tc_kelvin": 9.2, "knowledge_origin": "Observed", "synthetic": True})
    catalog = Base.metadata.tables["materials"]
    # Fixture target is explicitly synthetic; equal formula does not certify identity.
    await db.execute(sa.update(catalog).where(catalog.c.id == material)
                     .values(formula="Mo5P1.1B1.9", formula_normalized="Mo5P1.1B1.9"))
    before = await state(db)
    package, prepared, receipt, rows = await import_table(db, actor)
    assert receipt["expression_count"] == 4
    for i, row in enumerate(rows):
        actual = await db.scalar(sa.text(f"SELECT {PROJECT}(CAST(:source AS jsonb),:raw,CAST(:entry AS jsonb))::text"),
            {"source": canonical(package["source"]).decode(), "raw": prepared.source_text,
             "entry": canonical(package["expressions"][i]).decode()})
        assert json.loads(actual) == row["projection"]
        t = await table_target(db, actor, material, row["projection"]["field_id"])
        a = await save(db, actor, {**association(t, row, paper), "version": table_cases.REQUEST_VERSION})
        assert a["version"] == table_cases.VERSION
        _authority(a)
    panel = await cases.material_adapter(db, actor_user_id=actor["id"], material_id=material, profile=contract.PROFILE)
    assert panel["expressions_returned"] == 4 and panel["expressions_omitted"] == 0
    assert sorted(e["associations"][0]["expression"]["projection"]["value"]["raw_value"]
                  for e in panel["entries"]) == ["3.07", "3.16", "492", "501"]
    for profile in (None, expressions.literal_contract.PROFILE):
        assert (await expressions.expressions(db, actor_user_id=actor["id"], source_id=package["source"]["source_id"], profile=profile))["total"] == 0
        assert (await cases.targets(db, actor_user_id=actor["id"], material_id=material, profile=profile))["total"] == 0
        with pytest.raises(SourcePropertyError, match="profile_mismatch"):
            await expressions.expression(db, actor_user_id=actor["id"], revision_id=rows[0]["id"], profile=profile)
    assert await frozen_definitions(db) == frozen
    after = await state(db)
    for name in ("materials", "papers", "material_claims", "event_properties", "material_states", "structure_records", "ml_examples"):
        assert before[name] == after[name]


@pytest.mark.asyncio
async def test_same_field_passage_and_table_versions_cannot_cross_associate(db_session):
    db = db_session
    actor = await research_operator()
    material, paper = await retained(db)
    _, _, _, rows = await import_table(db, actor)
    t = await table_target(db, actor, material, rows[0]["projection"]["field_id"])
    wrong = {**association(t, rows[0], paper), "version": passage_cases.REQUEST_VERSION}
    with pytest.raises(SourcePropertyError, match="target_profile_mismatch"):
        await cases.operate(db, actor_user_id=actor["id"], request=wrong)
    caps = await cases.capabilities(db, actor_user_id=actor["id"], profile=contract.PROFILE)
    assert caps["field_ids"] == list(table_cases.FIELDS)
    assert caps["expression_field_map"] == {f: f for f in table_cases.FIELDS}
    assert caps["profile"] == contract.PROFILE
    assert (await expressions.capabilities(db, actor_user_id=actor["id"], profile=contract.PROFILE))["package_version"] == contract.VERSION


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", ["formula", "value", "unit", "grid_order", "locator", "null_grid", "bool_index", "extra_authority"])
async def test_database_rejects_rehashed_or_rebound_table_cells(db_session, tamper):
    package = actual_table_package()
    prepared = contract.compile_package(package)
    entry = deepcopy(package["expressions"][0])
    grid = entry["table_binding"]
    if tamper == "formula":
        entry["subject"]["formula_spans"] = [grid["header_spans"][2]]
    elif tamper == "value":
        entry["value_spans"] = [grid["rows"][1][2]]
    elif tamper == "unit":
        entry["unit_spans"] = package["expressions"][1]["unit_spans"]
    elif tamper == "grid_order":
        grid["header_spans"][1:3] = reversed(grid["header_spans"][1:3])
    elif tamper == "locator":
        entry["locator"]["column"] = 3
    elif tamper == "null_grid":
        entry["table_binding"] = None
    elif tamper == "bool_index":
        grid["row_index"] = True
    else:
        entry["scientific_acceptance"] = True
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(sa.text(f"SELECT {PROJECT}(CAST(:source AS jsonb),:raw,CAST(:entry AS jsonb))"),
                {"source": canonical(package["source"]).decode(), "raw": prepared.source_text, "entry": canonical(entry).decode()})


@pytest.mark.asyncio
async def test_new_capture_withholds_old_table_association_without_changing_history(committed_table_db):
    db, actor = committed_table_db, await research_operator()
    material, paper = await retained(db)
    package, _, _, rows = await import_table(db, actor)
    t = await table_target(db, actor, material, rows[0]["projection"]["field_id"])
    a = await save(db, actor, {**association(t, rows[0], paper), "version": table_cases.REQUEST_VERSION})
    older = await cases.row_by_id(db, "association", a["receipt_id"])
    await db.commit()
    # Synthetic later capture changes only an unselected trailing newline.
    # Metadata-only declarations do not create a new retained byte capture.
    new_bytes = base64.b64decode(package["source_text_base64"]) + b"\n"
    package["source_text_base64"] = base64.b64encode(new_bytes).decode()
    package["source_content_sha256"] = hashlib.sha256(new_bytes).hexdigest()
    package["source"]["captured_at"] = "2026-10-05T00:00:00Z"
    for e in package["expressions"]:
        e["window"]["id"] += ":new-capture"
    await import_table(db, actor, package)
    detail = await cases.target_detail(db, actor_user_id=actor["id"], target_id=t["target_id"], profile=contract.PROFILE)
    assert detail["associations"][0]["expression"] is None
    assert "literal_capture_superseded" in detail["associations"][0]["eligibility"]["reason_codes"]
    assert await cases.row_by_id(db, "association", a["receipt_id"]) == older
    with pytest.raises(DBAPIError):
        async with db.begin_nested():
            await db.execute(cases.table("association").delete().where(cases.table("association").c.id == older["id"]))


@pytest.mark.asyncio
async def test_http_table_profile_private_gate_preview_save_and_legacy_isolation(client, monkeypatch, committed_table_db):
    prefix = "/v1/research/source-expressions"
    params = {"profile": contract.PROFILE}
    get_settings.cache_clear()
    assert (await client.get(prefix + "/capabilities", params=params)).status_code == 404
    monkeypatch.setenv("SOURCE_PROPERTY_PENDING_ENABLED", "true")
    get_settings.cache_clear()
    try:
        assert (await client.get(prefix + "/capabilities", params=params)).status_code == 401
        actor = await research_operator()
        reviewer = await research_operator(role="reviewer")
        caps = await client.get(prefix + "/capabilities", params=params, headers=actor["headers"])
        assert caps.status_code == 200 and caps.json()["package_version"] == contract.VERSION
        request = {"request_key": "table-http:" + uuid4().hex, "package": actual_table_package()}
        assert (await client.post(prefix + "/imports/preview", json=request, headers=reviewer["headers"])).status_code == 403
        preview = await client.post(prefix + "/imports/preview", json=request, headers=actor["headers"])
        assert preview.status_code == 200, preview.text
        assert preview.json()["dry_run"] and preview.json()["expression_count"] == 4
        filters = {**params, "source_id": request["package"]["source"]["source_id"]}
        assert (await client.get(prefix + "/expressions", params=filters, headers=actor["headers"])).json()["total"] == 0
        saved = await client.post(prefix + "/imports/commit", json={**request, "expected_preview_sha256": preview.json()["preview_sha256"]}, headers=actor["headers"])
        assert saved.status_code == 200 and saved.json()["pending_ledger_written"]
        page = await client.get(prefix + "/expressions", params=filters, headers=actor["headers"])
        assert page.status_code == 200 and page.json()["total"] == 4
        assert page.headers["cache-control"] == "private, no-store"
        filters["profile"] = expressions.literal_contract.PROFILE
        assert (await client.get(prefix + "/expressions", params=filters, headers=actor["headers"])).json()["total"] == 0
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_table_source_authority_loss_withholds_value_for_a_current_reader(committed_table_db):
    db = committed_table_db
    actor, viewer = await research_operator(), await research_operator(role="reviewer")
    material, paper = await retained(db)
    _, _, _, rows = await import_table(db, actor)
    t = await table_target(db, actor, material, rows[0]["projection"]["field_id"])
    a = await save(db, actor, {**association(t, rows[0], paper), "version": table_cases.REQUEST_VERSION})
    original = await cases.row_by_id(db, "association", a["receipt_id"])
    await db.commit()
    await revoke_research_grant(grant_id=actor["grant_id"], revoked_by=actor["grantor_id"])
    detail = await cases.target_detail(db, actor_user_id=viewer["id"], target_id=t["target_id"], profile=contract.PROFILE)
    assert detail["associations"][0]["expression"] is None
    assert set(detail["associations"][0]["eligibility"]["reason_codes"]) == {
        "literal_capture_authority_held", "literal_import_authority_held", "literal_association_authority_held"}
    assert await cases.row_by_id(db, "association", a["receipt_id"]) == original


@pytest.mark.asyncio
@pytest.mark.parametrize("alter", ("unknown_profile", "wrong_role", "span_hash", "normalized_quantity", "wrong_projection_hash"))
async def test_native_table_insert_rejects_self_hashed_package_and_projection_forgeries(db_session, alter):
    db, operator = db_session, await research_operator()
    package = actual_table_package()
    package["source"]["source_id"] += ":" + uuid4().hex
    original = expressions._insert
    forged = deepcopy(contract.compile_package(package).projections[0])
    forged["value"]["quantity"] = {"status": "parsed", "value": 4.2, "unit": "meV"}

    async def tampered(session, name, values):
        values = deepcopy(values)
        if name == frozen_source_model.TABLE_ORDER[1]:
            document = json.loads(values["package_json"])
            entry = document["expressions"][0]
            if alter == "unknown_profile":
                document["profile"] = "material-table-field/9.0.0"
            elif alter == "wrong_role":
                entry["field_role"] = "reported_result_condition"
            elif alter == "span_hash":
                entry["cue_spans"][0]["sha256"] = "a" * 64
            values["package_json"] = canonical(document).decode()
            values["package_sha256"] = digest(document)
            values["expression_manifest"][0]["entry_sha256"] = digest(entry)
            if alter == "normalized_quantity":
                values["expression_manifest"][0]["projection_sha256"] = digest(forged)
            elif alter == "wrong_projection_hash":
                values["expression_manifest"][0]["projection_sha256"] = "b" * 64
            values["request_sha256"] = digest({"version": expressions.TABLE_VERSION,
                                               "package_sha256": values["package_sha256"]})
            values["preview_sha256"] = digest({
                "version": expressions.TABLE_VERSION, "request_key": values["request_key"],
                "request_sha256": values["request_sha256"],
                "actor": expressions._body({key: values[key] for key in
                    ("actor_user_id", "actor_grant_id", "actor_session_version")}),
                "manifest": values["expression_manifest"],
            })
        elif name == frozen_source_model.TABLE_ORDER[2]:
            if alter == "normalized_quantity":
                values["projection_json"] = canonical(forged).decode()
                values["projection_sha256"] = digest(forged)
            elif alter == "wrong_projection_hash":
                values["projection_sha256"] = "b" * 64
        return await original(session, name, values)

    before = await state(db)
    with patch.object(expressions, "_insert", tampered), pytest.raises(DBAPIError) as rejected:
        await expressions.import_package(db, actor_user_id=operator["id"],
            request_key_value="table-forged:" + uuid4().hex, package=package, dry_run=True)
    assert rejected.value.orig.sqlstate == "23514"
    assert await state(db) == before
