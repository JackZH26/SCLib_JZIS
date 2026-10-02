"""Native private pending closure; all retained inputs here are synthetic.

The disposable runner owns the database. This suite does not enable public
content, grant scientific approval, or change retained material results.
"""

import json
import re
from copy import deepcopy
from unittest.mock import patch
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from models import material_field_cases_v1 as frozen_case_model
from models import source_expression_intake_v2 as frozen_source_model
from models.db import Base, get_engine
from services import material_field_case_contract as old_cases
from services import material_field_case_contract_v1_1 as raw_cases
from services import material_field_cases as cases
from services import source_expression_contract_v2 as old_expressions
from services import source_expression_contract_v2_1 as raw_expressions
from services import source_expression_intake_v2 as expressions
from services.material_literal_field_contract import FIELDS, PROFILE
from services.research_release_manifest import canonical, digest
from services.source_property_pending import SourcePropertyError
from tests.research_access_helpers import research_operator, revoke_research_grant
from tests.test_material_field_cases import (
    association,
    attempt,
    expression,
    retained,
    save,
    target,
)
from tests.test_material_literal_field_contract import (
    synthetic_all_literal_fields_package,
    synthetic_literal_package,
)
from tests.test_research_freeze import db_session as frozen_db_session
from tests.test_research_freeze import state

db_session = frozen_db_session

RAW_PROJECT = "public.sclib_material_literal_project_v1(jsonb,text,jsonb)"
FROZEN_FUNCTIONS = (
    (frozen_source_model, "sclib_source_expression_project_v2", "jsonb,text,jsonb"),
    (frozen_source_model, "sclib_source_expression_quantity_v2", "text,text,text,boolean,boolean"),
    (frozen_source_model, "sclib_source_expression_insert_v2", ""),
    (frozen_case_model, "sclib_material_field_insert_v1", ""),
)
CANONICAL_TABLES = (
    "materials", "papers", "material_claims", "event_properties",
    "material_states", "structure_records", "ml_examples",
)


async def _frozen_definitions(db):
    definitions = {}
    for model, name, arguments in FROZEN_FUNCTIONS:
        signature = f"public.{name}({arguments})"
        row = (await db.execute(sa.text(
            "SELECT pg_get_functiondef(to_regprocedure(:signature)) AS definition, "
            "prosrc AS body FROM pg_proc WHERE oid=to_regprocedure(:signature)"
        ), {"signature": signature})).mappings().one()
        statement = next(sql for sql in model.guard_statements()
                         if sql.lstrip().startswith("CREATE FUNCTION public." + name + "("))
        expected = re.search(r"\bAS \$\$(.*?)\$\$", statement, re.S)
        assert expected is not None
        # This also verifies the original bodies when 0086 is already registered.
        assert row["body"] == expected.group(1)
        definitions[signature] = row["definition"]
    return definitions


@pytest_asyncio.fixture(loop_scope="function")
async def literal_bridge(db_session):
    # The separately committed grant must precede the first serializable snapshot.
    operator = await research_operator()
    before = await _frozen_definitions(db_session)
    installed = await db_session.scalar(sa.text("SELECT to_regprocedure(:signature) IS NOT NULL"),
                                        {"signature": RAW_PROJECT})
    if not installed:
        from models.material_literal_fields_v1 import upgrade_statements

        for statement in upgrade_statements():
            await db_session.execute(sa.text(statement))
    assert await _frozen_definitions(db_session) == before
    yield db_session, operator
    assert await _frozen_definitions(db_session) == before


def _authority(value):
    assert value["scientific_acceptance"] is False
    assert value["canonical_promotions"] == 0
    for key in ("public_content_release", "ml_training_approved", "sample_identity_established",
                "phase_identity_established", "field_interpretation_reviewed"):
        if key in value:
            assert value[key] is False


async def _raw_material(db):
    material, paper = await retained(db, record={"tc_kelvin": 16, "knowledge_origin": "Observed",
                                                "synthetic": True})
    table = Base.metadata.tables["materials"]
    # Set the fixture's identity before creating its first target or baseline.
    await db.execute(sa.update(table).where(table.c.id == material)
                     .values(formula="NbN", formula_normalized="NbN"))
    return material, paper


async def _raw_target(db, operator, material, field):
    ctx = await cases.context(db, actor_user_id=operator["id"], material_id=material, record_index=0)
    request = {"version": raw_cases.REQUEST_VERSION, "request_key": "literal-target:" + uuid4().hex,
               "operation": "target", "payload": {"field_id": field, "target": ctx["target"]}}
    before = await state(db)
    preview = await cases.operate(db, actor_user_id=operator["id"], request=request)
    assert await state(db) == before
    saved = await cases.operate(db, actor_user_id=operator["id"], request=request, dry_run=False,
                               expected_preview_sha256=preview["preview_sha256"])
    assert preview["receipt_sha256"] == saved["receipt_sha256"]
    assert saved["version"] == raw_cases.VERSION
    assert saved["request_sha256"] == digest(request)
    return request, saved, ctx


def _raw_association(t, e, paper):
    return {**association(t, e, paper), "version": raw_cases.REQUEST_VERSION}


async def _raw_import(db, operator, package):
    package = deepcopy(package)
    package["source"]["source_id"] += ":" + uuid4().hex
    prepared = raw_expressions.compile_package(package)
    key = "literal-import:" + uuid4().hex
    before = await state(db)
    preview = await expressions.import_package(db, actor_user_id=operator["id"],
        request_key_value=key, package=package)
    assert await state(db) == before
    saved = await expressions.import_package(db, actor_user_id=operator["id"],
        request_key_value=key, package=package, dry_run=False,
        expected_preview_sha256=preview["preview_sha256"])
    assert preview["receipt_sha256"] == saved["receipt_sha256"]
    assert saved["version"] == expressions.LITERAL_VERSION
    assert saved["package_sha256"] == prepared.package_sha256
    assert saved["request_sha256"] == digest({"version": expressions.LITERAL_VERSION,
                                               "package_sha256": prepared.package_sha256})
    rows = []
    for index, projection in enumerate(prepared.projections):
        revision_id = str(expressions._stable("revision", saved["receipt_id"], index))
        row = await expressions.expression(db, actor_user_id=operator["id"],
                                          revision_id=revision_id, profile=PROFILE)
        assert row["projection"] == projection
        assert row["projection_sha256"] == digest(projection)
        assert row["source_entry_sha256"] == digest(package["expressions"][index])
        rows.append(row)
    before_replay = await state(db)
    replay = await expressions.import_package(db, actor_user_id=operator["id"],
        request_key_value=key, package=package)
    assert replay["replayed"] and replay["receipt_sha256"] == saved["receipt_sha256"]
    assert await state(db) == before_replay
    outcome = await expressions.outcome(db, actor_user_id=operator["id"], request_key_value=key,
                                       expected_request_sha256=saved["request_sha256"])
    assert outcome["receipt_sha256"] == saved["receipt_sha256"]
    return package, prepared, saved, rows


@pytest.mark.asyncio
async def test_fourteen_raw_fields_close_as_actual_pending_expressions_targets_and_associations(literal_bridge):
    db, operator = literal_bridge
    material, paper = await _raw_material(db)
    before = await state(db)
    package, prepared, receipt, rows = await _raw_import(db, operator, synthetic_all_literal_fields_package())
    assert receipt["expression_count"] == len(rows) == 14
    by_target = {}
    for index, row in enumerate(rows):
        field = row["projection"]["field_id"]
        actual = await db.scalar(sa.text(
            "SELECT public.sclib_material_literal_project_v1(CAST(:source AS jsonb),:raw,CAST(:entry AS jsonb))::text"
        ), {"source": canonical(package["source"]).decode(), "raw": prepared.source_text,
            "entry": canonical(package["expressions"][index]).decode()})
        assert json.loads(actual) == prepared.projections[index]
        req, t, ctx = await _raw_target(db, operator, material, field)
        assert ctx["closure"]["paper_id"] == paper
        assert ctx["eligibility"]["eligible"]
        proposal = await save(db, operator, _raw_association(t, row, paper))
        assert proposal["version"] == raw_cases.VERSION
        _authority(proposal)
        outcome = await cases.outcome(db, actor_user_id=operator["id"],
            request_key_value=req["request_key"], expected_request_sha256=t["request_sha256"])
        assert outcome["receipt_sha256"] == t["receipt_sha256"]
        by_target[t["target_id"]] = row

    pages = [await cases.material_adapter(db, actor_user_id=operator["id"], material_id=material,
                                         offset=offset, limit=8, profile=PROFILE) for offset in (0, 8)]
    assert [page["expressions_returned"] for page in pages] == [8, 6]
    assert [page["entries_returned"] for page in pages] == [8, 6]
    assert [page["next_offset"] for page in pages] == [8, None]
    observed = set()
    for page in pages:
        assert page["total"] == 14 and page["expressions_omitted"] == 0
        assert page["eligibility"]["eligible"]
        _authority(page)
        for detail in page["entries"]:
            assert detail["association_total"] == detail["association_returned"] == 1
            item = detail["associations"][0]
            assert item["eligibility"]["eligible"] and item["source_identity_status"] == "proposed"
            actual = item["expression"]
            assert actual is not None
            expected = by_target[detail["target"]["id"]]
            assert actual["id"] == expected["id"]
            assert actual["projection"] == expected["projection"]
            p, value = actual["projection"], actual["projection"]["value"]
            observed.add(p["field_id"])
            assert p["profile"] == PROFILE and p["subject"]["formula"] == "NbN"
            assert p["field_role"] == value["role"] == FIELDS[p["field_id"]]
            assert p["conditions"] == [] and value["quantity"] is None
            assert value["normalization"] == "none" and value["status"] == "raw_literal"
            for key in ("value_span", "unit_span", "cue_span", "uncertainty_span"):
                selection = value[key]
                if selection is not None:
                    original = prepared.source_text[selection["char_start"]:selection["char_end"]]
                    assert digest_text(original) == selection["text_sha256"]
            _authority(p)
            capture = actual["capture"]
            assert capture["source_content_sha256"] == package["source_content_sha256"]
            assert capture["rights_verified"] is False
            assert capture["publication_revision_verified"] is False
            assert capture["publication_currentness_verified"] is False
            # Captures retain the unchanged 2.0 DTO; authority is explicit
            # on the pending expression and association, never inferred here.
            assert capture.get("scientific_acceptance") is not True
    assert observed == set(FIELDS)
    after = await state(db)
    assert {name: before[name] for name in CANONICAL_TABLES} == {name: after[name] for name in CANONICAL_TABLES}

    # The default legacy reader and UUID paths do not expand their old profile.
    old_page = await cases.targets(db, actor_user_id=operator["id"], material_id=material)
    assert old_page["version"] == old_cases.VERSION and old_page["total"] == 0
    old_source_page = await expressions.expressions(db, actor_user_id=operator["id"],
                                                   source_id=package["source"]["source_id"])
    assert old_source_page["version"] == expressions.VERSION and old_source_page["total"] == 0
    with pytest.raises(SourcePropertyError, match="profile_mismatch"):
        await expressions.expression(db, actor_user_id=operator["id"], revision_id=rows[0]["id"])
    with pytest.raises(SourcePropertyError, match="profile_mismatch"):
        await cases.target_detail(db, actor_user_id=operator["id"], target_id=next(iter(by_target)))


def digest_text(value):
    from hashlib import sha256

    return sha256(value.encode()).hexdigest()


@pytest.mark.asyncio
async def test_default_capabilities_and_actual_legacy_numeric_case_keep_old_versions_shapes_and_hashes(literal_bridge):
    db, operator = literal_bridge
    source_caps = await expressions.capabilities(db, actor_user_id=operator["id"])
    assert set(source_caps) == {
        "version", "package_version", "actor_user_id", "session_version", "can_import",
        "curator_grant_id", "registry_sha256", "field_profiles", "max_source_bytes", "max_expressions",
        "max_package_bytes", "max_projection_bytes", "max_expression_page_size", "scope",
        "scientific_acceptance", "canonical_promotions", "public_content_release",
    }
    assert source_caps["version"] == "source-expression-intake/2.0.0"
    assert source_caps["package_version"] == old_expressions.VERSION
    assert source_caps["field_profiles"] == old_expressions.FIELDS and len(source_caps["field_profiles"]) == 16
    assert source_caps["registry_sha256"] == old_expressions.REGISTRY_SHA256
    old_caps = await cases.capabilities(db, actor_user_id=operator["id"])
    assert set(old_caps) == {
        "version", "request_version", "actor_user_id", "session_version", "curator_grant_id", "can_write",
        "field_ids", "outcomes", "reason_codes", "expression_field_map", "max_page_size", "max_operation_bytes",
        *old_cases.AUTHORITY,
    }
    assert old_caps["field_ids"] == list(old_cases.FIELDS) and len(old_caps["field_ids"]) == 24
    assert old_caps["version"] == old_cases.VERSION and old_caps["request_version"] == old_cases.REQUEST_VERSION
    caps = await cases.capabilities(db, actor_user_id=operator["id"], profile=PROFILE)
    assert "read_hold_reason_codes" not in old_caps
    assert caps["reason_codes"] == old_caps["reason_codes"]
    assert caps["read_hold_reason_codes"] == list(cases.LITERAL_READ_HOLDS)
    assert len(caps["field_ids"]) == 38 and set(caps["field_ids"]) == set(raw_cases.ALL_FIELDS)
    assert caps["field_request_versions"] == {
        field: old_cases.REQUEST_VERSION if field in old_cases.FIELDS else raw_cases.REQUEST_VERSION
        for field in raw_cases.ALL_FIELDS
    }
    assert all(caps["expression_field_map"][field] == field for field in FIELDS)
    _authority(caps)
    raw_source_caps = await expressions.capabilities(db, actor_user_id=operator["id"], profile=PROFILE)
    assert raw_source_caps["field_profiles"] == FIELDS
    assert raw_source_caps["registry_sha256"] == raw_expressions.REGISTRY_SHA256

    material, paper = await retained(db)
    req, t, _ = await target(db, operator, material)
    package, e = await expression(db, operator)
    receipt = e["import_receipt"]
    prepared = old_expressions.compile_package(package)
    assert receipt["version"] == expressions.VERSION
    assert receipt["request_sha256"] == digest({"version": expressions.VERSION,
                                                "package_sha256": prepared.package_sha256})
    assert e["projection"] == prepared.projections[0]
    assert e["projection"]["value"]["value"] == 94.5
    assert e["projection"]["conditions"][0]["value"]["value"] == 200
    assert "profile" not in e["projection"]
    proposal = await save(db, operator, association(t, e, paper))
    assert t["request_sha256"] == digest(req)
    assert t["version"] == proposal["version"] == old_cases.VERSION
    assert digest(json.loads(t["receipt_canonical_json"])) == t["receipt_sha256"]
    panel = await cases.material_adapter(db, actor_user_id=operator["id"], material_id=material)
    assert panel["version"] == old_cases.VERSION and panel["expressions_returned"] == 1
    assert panel["entries"][0]["associations"][0]["expression"]["id"] == e["id"]
    _authority(panel)


@pytest.mark.asyncio
@pytest.mark.parametrize("alter", ("unknown_field", "wrong_role", "span_hash", "outside_window"))
async def test_native_raw_projection_rejects_untrusted_field_role_and_spans(literal_bridge, alter):
    db, _ = literal_bridge
    package = synthetic_literal_package()
    prepared = raw_expressions.compile_package(package)
    entry = deepcopy(package["expressions"][0])
    if alter == "unknown_field":
        entry["field_id"] = "hc2_tesla"
    elif alter == "wrong_role":
        entry["field_role"] = "reported_result_condition"
    elif alter == "span_hash":
        entry["cue_spans"][0]["sha256"] = "a" * 64
    else:
        entry["window"]["label_spans"] = entry["value_spans"]
    async with db.begin_nested() as nested:
        with pytest.raises(DBAPIError) as rejected:
            await db.execute(sa.text(
                "SELECT public.sclib_material_literal_project_v1(CAST(:source AS jsonb),:raw,CAST(:entry AS jsonb))"
            ), {"source": canonical(package["source"]).decode(), "raw": prepared.source_text,
                "entry": canonical(entry).decode()})
        assert rejected.value.orig.sqlstate == "23514"
        await nested.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("alter", ("unknown_profile", "wrong_role", "span_hash", "normalized_quantity", "wrong_projection_hash"))
async def test_native_insert_rejects_self_hashed_literal_package_and_projection_forgeries(literal_bridge, alter):
    db, operator = literal_bridge
    package = synthetic_literal_package()
    package["source"]["source_id"] += ":" + uuid4().hex
    original = expressions._insert
    forged = deepcopy(raw_expressions.compile_package(package).projections[0])
    forged["value"]["quantity"] = {"status": "parsed", "value": 4.2, "unit": "meV"}

    async def tampered(session, name, values):
        values = deepcopy(values)
        if name == frozen_source_model.TABLE_ORDER[1]:
            document = json.loads(values["package_json"])
            entry = document["expressions"][0]
            if alter == "unknown_profile":
                document["profile"] = "material-literal-field/9.0.0"
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
            values["request_sha256"] = digest({"version": expressions.LITERAL_VERSION,
                                               "package_sha256": values["package_sha256"]})
            values["preview_sha256"] = digest({
                "version": expressions.LITERAL_VERSION, "request_key": values["request_key"],
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
            request_key_value="literal-forged:" + uuid4().hex, package=package, dry_run=True)
    assert rejected.value.orig.sqlstate == "23514"
    assert await state(db) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("target_profile", ("legacy", "literal"))
@pytest.mark.parametrize("kind", ("association", "attempt"))
async def test_cross_version_target_operations_rejected_in_service_and_independent_sql(literal_bridge, target_profile, kind):
    db, operator = literal_bridge
    material, paper = await (_raw_material(db) if target_profile == "literal" else retained(db))
    if target_profile == "literal":
        _, t, _ = await _raw_target(db, operator, material, "gap_energy_source_value")
        _, _, _, rows = await _raw_import(db, operator, synthetic_literal_package())
        e = rows[0]
        valid_version, bad_version = raw_cases.REQUEST_VERSION, old_cases.REQUEST_VERSION
        bad_preview_version = old_cases.VERSION
    else:
        _, t, _ = await target(db, operator, material)
        _, e = await expression(db, operator)
        valid_version, bad_version = old_cases.REQUEST_VERSION, raw_cases.REQUEST_VERSION
        bad_preview_version = raw_cases.VERSION
    request = association(t, e, paper) if kind == "association" else attempt(t)
    request["version"] = valid_version
    wrong = {**request, "version": bad_version}
    before = await state(db)
    with pytest.raises(SourcePropertyError, match="target_profile_mismatch"):
        await cases.operate(db, actor_user_id=operator["id"], request=wrong)
    assert await state(db) == before
    original = cases._insert

    async def tampered(session, name, values):
        values = deepcopy(values)
        document = json.loads(values["request_json"])
        document["version"] = bad_version
        values["request_json"] = canonical(document).decode()
        values["request_sha256"] = digest(document)
        preview = json.loads(values["preview_json"])
        preview.update(version=bad_preview_version, request_sha256=values["request_sha256"])
        values["preview_json"] = canonical(preview).decode()
        values["preview_sha256"] = digest(preview)
        return await original(session, name, values)

    with patch.object(cases, "_insert", tampered), pytest.raises(DBAPIError) as rejected:
        await cases.operate(db, actor_user_id=operator["id"], request=request)
    assert rejected.value.orig.sqlstate == "23514"
    assert await state(db) == before


async def _distinct_pending_literal(db):
    # Each actor is committed before the first serializable snapshot. Capture,
    # import, association and current reader/target identities are independent.
    capture_actor, importer, proposer, current_reader = [await research_operator() for _ in range(4)]
    assert len({actor["id"] for actor in (capture_actor, importer, proposer, current_reader)}) == 4
    before = await _frozen_definitions(db)
    assert await db.scalar(sa.text("SELECT to_regprocedure(:signature) IS NOT NULL"), {"signature": RAW_PROJECT})
    material, paper = await _raw_material(db)
    package, _, first, first_rows = await _raw_import(db, capture_actor, synthetic_literal_package())
    parent = first_rows[0]
    package["expressions"][0]["predecessor"] = {
        "revision_id": parent["id"], "record_sha256": parent["record_sha256"],
        "revision_number": parent["revision_number"],
    }
    key = "literal-independent-import:" + uuid4().hex
    preview = await expressions.import_package(db, actor_user_id=importer["id"], request_key_value=key, package=package)
    saved = await expressions.import_package(db, actor_user_id=importer["id"], request_key_value=key, package=package,
                                           dry_run=False, expected_preview_sha256=preview["preview_sha256"])
    assert saved["capture_id"] == first["capture_id"]
    revision_id = str(expressions._stable("revision", saved["receipt_id"], 0))
    expression_row = await expressions.expression(db, actor_user_id=current_reader["id"], revision_id=revision_id, profile=PROFILE)
    _, fixed_target, _ = await _raw_target(db, current_reader, material, expression_row["projection"]["field_id"])
    proposal = await save(db, proposer, _raw_association(fixed_target, expression_row, paper))
    baseline = await cases.target_detail(db, actor_user_id=current_reader["id"], target_id=fixed_target["target_id"], profile=PROFILE)
    assert baseline["associations"][0]["expression"] is not None
    assert baseline["associations"][0]["eligibility"] == {"eligible": True, "reason_codes": []}
    await db.commit()
    return {"capture": capture_actor, "import": importer, "association": proposer, "reader": current_reader,
            "material": material, "target": fixed_target, "proposal": proposal, "baseline": baseline,
            "expression": expression_row, "source_id": package["source"]["source_id"], "frozen": before}


@pytest_asyncio.fixture(loop_scope="function")
async def committed_literal_read_db():
    # These reads need committed records and an actual read-only transaction.
    # Isolate their complete schema on the verified disposable database so
    # committed synthetic ledgers cannot change another test's inventory.
    from test_safety import validate_test_environment, verify_postgres_identity

    capability = validate_test_environment()
    engine = get_engine().execution_options(isolation_level="SERIALIZABLE")

    async def reset_owned_schema():
        async with engine.begin() as connection:
            await connection.run_sync(verify_postgres_identity, capability)
            # Metadata drop_all leaves standalone frozen lock functions behind.
            # Reset only this verified disposable database's application schema;
            # its separately owned sclib_test_guard identity is preserved.
            await connection.execute(sa.text("DROP SCHEMA public CASCADE"))
            await connection.execute(sa.text("CREATE SCHEMA public"))
            await connection.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
            await connection.run_sync(Base.metadata.create_all)

    await reset_owned_schema()
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session
    finally:
        await reset_owned_schema()
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("role,change,reason", [
    ("capture", "grant", "literal_capture_authority_held"),
    ("capture", "session", "literal_capture_authority_held"),
    ("import", "grant", "literal_import_authority_held"),
    ("import", "session", "literal_import_authority_held"),
    ("association", "grant", "literal_association_authority_held"),
    ("association", "session", "literal_association_authority_held"),
])
async def test_raw_pending_read_isolates_upstream_authority_loss_and_preserves_history(committed_literal_read_db, role, change, reason):
    db_session = committed_literal_read_db
    fixed = await _distinct_pending_literal(db_session)
    actor = fixed[role]
    if change == "grant":
        await revoke_research_grant(grant_id=actor["grant_id"], revoked_by=actor["grantor_id"])
    else:
        users = Base.metadata.tables["users"]
        await db_session.execute(sa.update(users).where(users.c.id == actor["id"])
                                 .values(session_version=users.c.session_version+1))
        await db_session.commit()
    # The existing authority predicate must work in an actual read-only GET
    # transaction; no frozen FOR SHARE writer role guard is used here.
    await db_session.execute(sa.text("SET TRANSACTION READ ONLY"))
    detail = await cases.target_detail(db_session, actor_user_id=fixed["reader"]["id"],
                                     target_id=fixed["target"]["target_id"], profile=PROFILE)
    item = detail["associations"][0]
    original = fixed["baseline"]["associations"][0]
    assert item["eligibility"] == {"eligible": False, "reason_codes": [reason]}
    assert item["expression"] is None
    assert detail["association_total"] == detail["association_returned"] == 1
    assert item["id"] == original["id"] and item["record_sha256"] == original["record_sha256"]
    assert item["record_canonical_json"] == original["record_canonical_json"] and item["payload"] == original["payload"]
    _authority(item)
    adapter = await cases.material_adapter(db_session, actor_user_id=fixed["reader"]["id"],
                                         material_id=fixed["material"], profile=PROFILE)
    assert adapter["expressions_returned"] == 0
    assert adapter["entries"][0]["associations"][0]["expression"] is None
    assert await _frozen_definitions(db_session) == fixed["frozen"]


@pytest.mark.asyncio
async def test_raw_capture_replacement_withholds_old_current_expression_without_erasing_history(committed_literal_read_db):
    db_session = committed_literal_read_db
    fixed = await _distinct_pending_literal(db_session)
    newer = synthetic_literal_package("debye_temperature_source_value")
    newer["source"]["source_id"] = fixed["source_id"]
    key = "literal-new-capture:" + uuid4().hex
    preview = await expressions.import_package(db_session, actor_user_id=fixed["import"]["id"], request_key_value=key, package=newer)
    saved = await expressions.import_package(db_session, actor_user_id=fixed["import"]["id"], request_key_value=key, package=newer,
                                           dry_run=False, expected_preview_sha256=preview["preview_sha256"])
    assert saved["capture_id"] != fixed["expression"]["capture"]["id"]
    await db_session.commit()
    await db_session.execute(sa.text("SET TRANSACTION READ ONLY"))
    original = await expressions.expression(db_session, actor_user_id=fixed["reader"]["id"],
                                          revision_id=fixed["expression"]["id"], profile=PROFILE)
    assert original["is_expression_head"]
    assert original["capture"]["latest_retained_capture_for_source"] is False
    detail = await cases.target_detail(db_session, actor_user_id=fixed["reader"]["id"],
                                     target_id=fixed["target"]["target_id"], profile=PROFILE)
    item = detail["associations"][0]
    assert item["eligibility"] == {"eligible": False, "reason_codes": ["literal_capture_superseded"]}
    assert item["expression"] is None and item["is_head"]
    assert item["record_canonical_json"] == fixed["baseline"]["associations"][0]["record_canonical_json"]
    assert detail["association_total"] == detail["association_returned"] == 1
    _authority(item)
    assert await _frozen_definitions(db_session) == fixed["frozen"]
