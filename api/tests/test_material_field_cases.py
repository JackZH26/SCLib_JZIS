"""Native PostgreSQL proof; inline scientific inputs are synthetic fixtures."""
from copy import deepcopy
from uuid import UUID, uuid4
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.db import Base, get_engine
from models.material_field_cases_v1 import TABLE_ORDER
from services.material_source_scope import VISIBILITY_VERSION
from services import material_field_cases as service
from services.material_field_case_contract import REQUEST_VERSION
from services.research_release_manifest import canonical, digest
from services.source_property_pending import SourcePropertyConflict
from tests.research_access_helpers import research_operator, research_user, revoke_research_grant
from tests.test_research_freeze import db_session, add, state, seed
from tests.test_source_expression_contract_v2 import synthetic_package, span

PREFIX = "/v1/research/material-field-cases"


def operation(kind, payload):
    return {"version": REQUEST_VERSION, "request_key": "field-case:" + uuid4().hex,
            "operation": kind, "payload": payload}


async def retained(db, *, status="published", record=None):
    token = uuid4().hex
    paper, material = "field-paper:" + token, "field-material:" + token
    await add(db, "papers", id=paper, source="arxiv", title="Synthetic field test", authors=[],
              abstract="Synthetic fixture only", status=status)
    r = record or {"paper_id": paper, "tc_kelvin": 116, "pressure_gpa": 140,
                   "knowledge_origin": "Computed", "synthetic": True}
    r["paper_id"] = paper
    await add(db, "materials", id=material, formula="YScH10", formula_normalized="YScH10", records=[r])
    return material, paper


async def target(db, operator, material, field="tc_kelvin"):
    ctx = await service.context(db, actor_user_id=operator["id"], material_id=material, record_index=0)
    req = operation("target", {"field_id": field, "target": ctx["target"]})
    before = await state(db)
    preview = await service.operate(db, actor_user_id=operator["id"], request=req)
    assert await state(db) == before
    saved = await service.operate(db, actor_user_id=operator["id"], request=req, dry_run=False,
                                   expected_preview_sha256=preview["preview_sha256"])
    assert preview["receipt_sha256"] == saved["receipt_sha256"]
    return req, saved, ctx


async def expression(db, operator, field="tc_kelvin", raw="YScH10 94.5 K at 200 GPa. Computed model X."):
    p = synthetic_package(raw)
    p["source"]["source_id"] += ":" + uuid4().hex
    if field != "tc_kelvin":
        p["expressions"][0]["field_id"] = field
    key = "expression:" + uuid4().hex
    preview = await service.expressions.import_package(db, actor_user_id=operator["id"], request_key_value=key, package=p)
    saved = await service.expressions.import_package(db, actor_user_id=operator["id"], request_key_value=key, package=p,
        dry_run=False, expected_preview_sha256=preview["preview_sha256"])
    eid = str(service.expressions._stable("revision", saved["receipt_id"], 0))
    row = await service.expressions.expression(db, actor_user_id=operator["id"], revision_id=eid)
    return p, row


def association(t, e, paper, predecessor=None):
    return operation("association", {"target_id": t["target_id"], "target_sha256": t["receipt_sha256"],
        "expression_revision_id": e["id"], "expression_record_sha256": e["record_sha256"],
        "source_identity": {"paper_id": paper, "work_id": None}, "action": "propose", "predecessor": predecessor})


def attempt(t, predecessor=None, outcome="source_unavailable"):
    return operation("attempt", {"target_id": t["target_id"], "target_sha256": t["receipt_sha256"],
        "outcome": outcome, "reason_codes": [outcome], "checked_scope": {"source_ids": [],
        "fulltext_checked": False, "supplement_checked": False, "scope_label": "Synthetic unavailable settings"},
        "expression_pins": [], "predecessor": predecessor})


async def save(db, operator, request):
    p = await service.operate(db, actor_user_id=operator["id"], request=request)
    return await service.operate(db, actor_user_id=operator["id"], request=request, dry_run=False,
                                 expected_preview_sha256=p["preview_sha256"])


@pytest.mark.asyncio
async def test_target_preview_replay_outcome_and_actual_legacy_fingerprints(db_session):
    operator = await research_operator()
    material, paper = await retained(db_session)
    req, saved, ctx = await target(db_session, operator, material)
    assert ctx["eligibility"]["eligible"]
    raw = (await db_session.execute(sa.select(Base.metadata.tables["materials"].c.records).where(
        Base.metadata.tables["materials"].c.id == material))).scalar_one()[0]
    assert ctx["closure"]["legacy_result_id"] == service.legacy_result_id(raw, scope_id=material)
    assert ctx["closure"]["retained_record_sha256"] == digest(raw)
    before = await state(db_session)
    replay = await service.operate(db_session, actor_user_id=operator["id"], request=req)
    assert replay["replayed"] and replay["pending_ledger_written"]
    # Replay rehearsal is rolled back, including all lock epoch mutations.
    assert await state(db_session) == before
    replay = await service.operate(db_session, actor_user_id=operator["id"], request=req, dry_run=False)
    assert replay["replayed"] and await state(db_session) == before
    out = await service.outcome(db_session, actor_user_id=operator["id"], request_key_value=req["request_key"],
                                expected_request_sha256=saved["request_sha256"])
    assert out["receipt_sha256"] == saved["receipt_sha256"]
    changed = deepcopy(req)
    changed["payload"]["field_id"] = "pressure_gpa"
    with pytest.raises(SourcePropertyConflict):
        await service.operate(db_session, actor_user_id=operator["id"], request=changed)


@pytest.mark.asyncio
async def test_three_unavailable_settings_need_no_expression(db_session):
    operator = await research_operator()
    material, _ = await retained(db_session)
    expressions_before = await db_session.scalar(sa.select(sa.func.count()).select_from(service.expressions._table(2)))
    for field in ("lambda_eph", "omega_log_k", "mu_star"):
        _, t, _ = await target(db_session, operator, material, field)
        first = await save(db_session, operator, attempt(t))
        second = await save(db_session, operator, attempt(t, {"id": first["receipt_id"], "record_sha256": first["receipt_sha256"]}, "external_reference_available"))
        detail = await service.target_detail(db_session, actor_user_id=operator["id"], target_id=t["target_id"])
        assert detail["attempt_total"] == 2 and detail["association_total"] == 0
        assert detail["attempts"][0]["id"] == second["receipt_id"]
        assert detail["attempts"][0]["is_head"] and not detail["attempts"][1]["is_head"]
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(service.expressions._table(2))) == expressions_before


@pytest.mark.asyncio
async def test_conference_expression_parallel_to_journal_no_promotion_and_stale_target(db_session):
    operator = await research_operator()
    material, paper = await retained(db_session)
    _, t, _ = await target(db_session, operator, material)
    _, e = await expression(db_session, operator)
    before_material = (await db_session.execute(sa.select(Base.metadata.tables["materials"]).where(
        Base.metadata.tables["materials"].c.id == material))).mappings().one()
    a = await save(db_session, operator, association(t, e, paper))
    panel = await service.material_adapter(db_session, actor_user_id=operator["id"], material_id=material)
    assert panel["entries"][0]["associations"][0]["expression"]["projection"]["value"]["value"] == 94.5
    assert panel["entries"][0]["associations"][0]["source_identity_status"] == "proposed"
    after_material = (await db_session.execute(sa.select(Base.metadata.tables["materials"]).where(
        Base.metadata.tables["materials"].c.id == material))).mappings().one()
    assert before_material == after_material
    await db_session.execute(sa.update(Base.metadata.tables["materials"]).where(Base.metadata.tables["materials"].c.id == material)
                             .values(records=[{"paper_id": paper, "tc_kelvin": 117, "pressure_gpa": 140, "knowledge_origin": "Computed"}]))
    panel = await service.material_adapter(db_session, actor_user_id=operator["id"], material_id=material)
    item = panel["entries"][0]["associations"][0]
    assert item["expression"] is None and "target_fingerprint_changed" in item["eligibility"]["reason_codes"]
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(service.table("association"))) == 1


@pytest.mark.asyncio
async def test_disappeared_target_record_retains_history_and_suppresses_expression(db_session):
    operator = await research_operator()
    material, paper = await retained(db_session)
    _, t, _ = await target(db_session, operator, material)
    _, e = await expression(db_session, operator)
    a = await save(db_session, operator, association(t, e, paper))
    await db_session.execute(sa.update(Base.metadata.tables["materials"]).where(
        Base.metadata.tables["materials"].c.id == material).values(records=[]))
    # Every private history path must survive the controlled missing closure.
    detail = await service.target_detail(db_session, actor_user_id=operator["id"], target_id=t["target_id"])
    page = await service.targets(db_session, actor_user_id=operator["id"], material_id=material)
    adapter = await service.material_adapter(db_session, actor_user_id=operator["id"], material_id=material)
    for row in (detail["target"], page["entries"][0], adapter["entries"][0]["target"]):
        assert not row["eligibility"]["eligible"]
        assert "target_fingerprint_changed" in row["eligibility"]["reason_codes"]
        assert row["record_sha256"] == t["receipt_sha256"]
    proposal = detail["associations"][0]
    assert proposal["id"] == a["receipt_id"] and proposal["expression"] is None
    assert "target_fingerprint_changed" in proposal["eligibility"]["reason_codes"]
    # Savepoint recovery does not mask unrelated SQL faults.
    async with db_session.begin_nested() as nested:
        with pytest.raises(DBAPIError):
            await db_session.execute(sa.text("SELECT public.sclib_intentionally_missing_function()"))
        await nested.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["disputed", "retracted"])
async def test_held_source_cannot_restore_material_or_expression(db_session, status):
    operator = await research_operator()
    material, paper = await retained(db_session, status=status)
    _, t, _ = await target(db_session, operator, material)
    _, e = await expression(db_session, operator)
    await save(db_session, operator, association(t, e, paper))
    panel = await service.material_adapter(db_session, actor_user_id=operator["id"], material_id=material)
    assert not panel["eligibility"]["eligible"]
    item = panel["entries"][0]["associations"][0]
    assert item["expression"] is None and "source_lifecycle_held" in item["eligibility"]["reason_codes"]


@pytest.mark.asyncio
@pytest.mark.parametrize("held_status", ["disputed", "retracted", "corrected"])
async def test_source_scoped_field_targets_use_exact_current_records_and_keep_holds(db_session, held_status):
    operator = await research_operator()
    material, active_paper = await retained(db_session)
    held_paper = "field-held:" + uuid4().hex
    await add(db_session, "papers", id=held_paper, source="arxiv", title="Synthetic held source",
              authors=[], abstract="Synthetic fixture only", status=held_status)
    materials = Base.metadata.tables["materials"]
    active_raw = (await db_session.scalar(sa.select(materials.c.records).where(materials.c.id == material)))[0]
    # Equal Tc must not grant a held occurrence the other source's membership.
    held_raw = {**active_raw, "paper_id": held_paper}
    original_records = [active_raw, held_raw]
    await db_session.execute(sa.update(materials).where(materials.c.id == material).values(records=original_records))

    contexts, receipts = [], []
    for index in (0, 1):
        ctx = await service.context(db_session, actor_user_id=operator["id"], material_id=material, record_index=index)
        contexts.append(ctx)
        req = operation("target", {"field_id": "tc_kelvin", "target": ctx["target"]})
        receipts.append(await save(db_session, operator, req))
    assert contexts[0]["eligibility"] == {"eligible": True, "reason_codes": []}
    assert contexts[1]["eligibility"] == {"eligible": False, "reason_codes": ["material_not_currently_eligible"]}
    assert contexts[0]["closure"]["legacy_result_id"] != contexts[1]["closure"]["legacy_result_id"]
    for index in (0, 1):
        assert contexts[index]["closure"]["retained_record_sha256"] == digest(original_records[index])
        assert contexts[index]["closure"]["legacy_result_id"] == service.legacy_result_id(original_records[index], scope_id=material)

    material_view = await service.material_view(db_session, await db_session.get(service.Material, material))
    assert material_view.visibility["version"] == VISIBILITY_VERSION
    assert material_view.source_scope.eligible_indices == (0,)
    assert material_view.current_records() == [active_raw]
    _, evidence = await expression(db_session, operator)
    for receipt, paper in zip(receipts, (active_paper, held_paper)):
        await save(db_session, operator, association(receipt, evidence, paper))

    panel = await service.material_adapter(db_session, actor_user_id=operator["id"], material_id=material)
    assert panel["eligibility"] == {"eligible": True, "reason_codes": []}
    assert panel["expressions_returned"] == 1
    entries = {entry["target"]["id"]: entry for entry in panel["entries"]}
    assert entries[receipts[0]["target_id"]]["associations"][0]["expression"] is not None
    held = entries[receipts[1]["target_id"]]["associations"][0]
    assert held["expression"] is None
    assert set(held["eligibility"]["reason_codes"]) == {"material_not_currently_eligible", "source_lifecycle_held"}
    assert await db_session.scalar(sa.select(materials.c.records).where(materials.c.id == material)) == original_records

    # An authoritative source-only change leaves target bytes intact but removes
    # its eligible triple. No other record or pending expression clears that hold.
    papers = Base.metadata.tables["papers"]
    await db_session.execute(sa.update(papers).where(papers.c.id == active_paper).values(status="withdrawn"))
    assert await service.sql_context(db_session, contexts[0]["target"]) == contexts[0]["context_canonical_json"]
    panel = await service.material_adapter(db_session, actor_user_id=operator["id"], material_id=material)
    assert not panel["eligibility"]["eligible"] and panel["expressions_returned"] == 0
    for entry in panel["entries"]:
        assert not entry["target"]["eligibility"]["eligible"]
        assert entry["associations"][0]["expression"] is None
        assert "source_lifecycle_held" in entry["associations"][0]["eligibility"]["reason_codes"]
    assert await db_session.scalar(sa.select(materials.c.records).where(materials.c.id == material)) == original_records


@pytest.mark.asyncio
async def test_field_condition_mismatch_and_direct_sql_receipt_tampering(db_session):
    operator = await research_operator()
    material, paper = await retained(db_session)
    _, t, _ = await target(db_session, operator, material)
    _, e = await expression(db_session, operator, field="measurement_temperature_k")
    with pytest.raises(DBAPIError) as rejected:
        await save(db_session, operator, association(t, e, paper))
    assert "field_case_expression_field_mismatch" in str(rejected.value)
    a = await save(db_session, operator, attempt(t))
    row = await service.row_by_id(db_session, "attempt", a["receipt_id"])
    forged = {k: v for k, v in row.items() if k != "created_at"}
    forged["id"] = uuid4()
    forged["record_sha256"] = "f" * 64
    async with db_session.begin_nested() as nested:
        with pytest.raises(DBAPIError):
            await db_session.execute(service.table("attempt").insert().values(**forged))
        await nested.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation_kind", ["UPDATE", "DELETE", "TRUNCATE"])
async def test_append_only_sql(db_session, operation_kind):
    if operation_kind != "TRUNCATE":
        operator = await research_operator()
        material, _ = await retained(db_session)
        await target(db_session, operator, material)
    async with db_session.begin_nested() as nested:
        with pytest.raises(DBAPIError) as rejected:
            name = TABLE_ORDER[0]
            # TRUNCATE statement guards run on empty tables too; row mutations
            # require a real retained row.
            sql = f"TRUNCATE public.{name}" if operation_kind == "TRUNCATE" else f"DELETE FROM public.{name}" if operation_kind == "DELETE" else f"UPDATE public.{name} SET field_id='pressure_gpa'"
            await db_session.execute(sa.text(sql))
        await nested.rollback()


@pytest.mark.asyncio
async def test_native_claim_closure_and_unavailable_property_source_fail_closed(db_session):
    operator = await research_operator()
    seeded = await seed(db_session)
    claim = (await db_session.execute(sa.select(Base.metadata.tables["material_claims"]).where(
        Base.metadata.tables["material_claims"].c.material_id == seeded["material"]))).mappings().first()
    ctx = await service.context(db_session, actor_user_id=operator["id"], material_id=seeded["material"],
                                kind="tc_claim", entity_id=str(claim["id"]))
    assert ctx["closure"]["event_id"] is not None and ctx["closure"]["state_id"] is not None
    assert not ctx["eligibility"]["eligible"]
    prop = (await db_session.execute(sa.select(Base.metadata.tables["event_properties"]).where(
        Base.metadata.tables["event_properties"].c.event_id == claim["event_id"]))).mappings().first()
    ctx = await service.context(db_session, actor_user_id=operator["id"], material_id=seeded["material"],
                                kind="event_property", entity_id=str(prop["id"]))
    assert "native_source_binding_unavailable" in ctx["eligibility"]["reason_codes"]


@pytest.mark.asyncio
async def test_http_disabled_auth_grants_private_recovery_and_bounds(client, db_session, monkeypatch):
    assert (await client.get(PREFIX + "/capabilities")).status_code == 404
    monkeypatch.setenv("SOURCE_PROPERTY_PENDING_ENABLED", "true")
    get_settings.cache_clear()
    try:
        operator = await research_operator()
        reviewer = await research_operator(role="reviewer")
        admin = await research_user(is_admin=True)
        for headers, expected in (({}, 401), (admin["headers"], 403), (operator["headers"], 200), (reviewer["headers"], 200)):
            response = await client.get(PREFIX + "/capabilities", headers=headers)
            assert response.status_code == expected, response.text
            assert response.headers["cache-control"] == "private, no-store"
        response = await client.get(PREFIX + "/targets?limit=9", headers=operator["headers"])
        assert response.status_code == 400
        material, _ = await retained(db_session)
        await db_session.commit()
        ctx = (await client.get(PREFIX + "/context", params={"material_id": material, "record_index": 0}, headers=operator["headers"])).json()
        req = operation("target", {"field_id": "tc_kelvin", "target": ctx["target"]})
        denied = await client.post(PREFIX + "/operations/preview", headers=reviewer["headers"], json={"request": req})
        assert denied.status_code == 403
        preview = await client.post(PREFIX + "/operations/preview", headers=operator["headers"], json={"request": req})
        assert preview.status_code == 200, preview.text
        result = await client.post(PREFIX + "/operations/commit", headers=operator["headers"], json={"request": req,
                                   "expected_preview_sha256": preview.json()["preview_sha256"]})
        assert result.status_code == 200, result.text
        result = await client.get(PREFIX + "/operations/outcome", headers=operator["headers"], params={
            "request_key": req["request_key"], "expected_request_sha256": result.json()["request_sha256"]})
        assert result.status_code == 200 and result.json()["replayed"]
        await revoke_research_grant(grant_id=operator["grant_id"], revoked_by=operator["grantor_id"])
        assert (await client.get(PREFIX + "/capabilities", headers=operator["headers"])).status_code == 403
    finally:
        get_settings.cache_clear()


def migration(connection, action):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0084_material_field_cases.py"
    spec = importlib.util.spec_from_file_location("material_field_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(connection)):
        getattr(module, action)()


@pytest.mark.asyncio
async def test_0084_nonempty_downgrade_refusal(db_session):
    operator = await research_operator()
    material, _ = await retained(db_session)
    await target(db_session, operator, material)
    connection = await db_session.connection()
    before = await state(db_session)
    with pytest.raises(RuntimeError, match="Refusing downgrade"):
        await connection.run_sync(lambda conn: migration(conn, "downgrade"))
    assert await state(db_session) == before


@pytest.mark.asyncio
async def test_actual_conference_four_expressions_are_historical_pending(db_session):
    import hashlib
    import json
    path = Path("/private/tmp/sclib-source-expression-v2-20261002/genuine_conference_private_package.json")
    if not path.is_file():
        pytest.skip("Private inspected conference package is not available on this host")
    source_bytes = path.read_bytes()
    assert hashlib.sha256(source_bytes).hexdigest() == "3885751def7c56a3a7a8316aa9bebe2599d8fb41f68c44116c4b0b945fbd9636"
    package = json.loads(source_bytes)
    operator = await research_operator()
    key = "actual-conference:" + uuid4().hex
    preview = await service.expressions.import_package(db_session, actor_user_id=operator["id"], request_key_value=key, package=package)
    saved = await service.expressions.import_package(db_session, actor_user_id=operator["id"], request_key_value=key, package=package,
        dry_run=False, expected_preview_sha256=preview["preview_sha256"])
    values = {}
    for index in range(4):
        eid = str(service.expressions._stable("revision", saved["receipt_id"], index))
        e = await service.expressions.expression(db_session, actor_user_id=operator["id"], revision_id=eid)
        values[e["projection"]["subject"]["formula"]] = e["projection"]["value"]["value"]
        assert e["capture"]["source_content_sha256"] == "0dacb0f6181d97155c13c741258c23d9065c12a560a5d033f16f58022de0a129"
        assert e["capture"]["source"]["currentness"] == "historical"
        assert not e["capture"]["publication_currentness_verified"]
        if e["projection"]["subject"]["formula"] == "YScH10":
            material, paper = await retained(db_session)
            _, t, _ = await target(db_session, operator, material)
            await save(db_session, operator, association(t, e, paper))
            panel = await service.material_adapter(db_session, actor_user_id=operator["id"], material_id=material)
            proposal = panel["entries"][0]["associations"][0]
            assert proposal["expression"] is None and "source_lifecycle_held" in proposal["eligibility"]["reason_codes"]
            assert json.loads(panel["entries"][0]["target"]["context_canonical_json"])["result"]["tc_kelvin"] == 116
    assert values == {"YScH6": 66, "YScH8": 89, "YScH10": 94.5, "YScH12": 142.7}


@pytest.mark.asyncio
async def test_actual_pt_onset_zero_and_crystallography_stay_separate_pending(db_session):
    import hashlib
    import json
    root = Path("/private/tmp/sclib-field-cases-genuine-pt-packages-r2-20261002")
    files = (("pt_resistivity_onset_zero.json", "4620f292957f04f6fbf7e7009f80205e2fdb707cc3ec548a20fae7954b3c1994", 2),
             ("pt_crystallography_temperature.json", "d8ca842aa37186228c573d09c4cb05077d896018570ffb83cb26c833edb0b596", 1))
    if not all((root / name).is_file() for name, _, _ in files):
        pytest.skip("Private inspected Pt fragments are not available on this host")
    operator = await research_operator()
    rows = []
    for name, pin, count in files:
        source_bytes = (root / name).read_bytes()
        assert hashlib.sha256(source_bytes).hexdigest() == pin
        package = json.loads(source_bytes)
        key = "actual-pt:" + uuid4().hex
        preview = await service.expressions.import_package(db_session, actor_user_id=operator["id"], request_key_value=key, package=package)
        saved = await service.expressions.import_package(db_session, actor_user_id=operator["id"], request_key_value=key,
            package=package, dry_run=False, expected_preview_sha256=preview["preview_sha256"])
        for index in range(count):
            eid = str(service.expressions._stable("revision", saved["receipt_id"], index))
            rows.append(await service.expressions.expression(db_session, actor_user_id=operator["id"], revision_id=eid))
    onset, zero, temperature = rows
    assert onset["projection"]["value"]["value"] == 23
    assert zero["projection"]["value"]["value"] == 21.5
    assert onset["expression_key"] != zero["expression_key"]
    assert onset["projection"]["window"]["id"] == "resistivity:onset"
    assert zero["projection"]["window"]["id"] == "resistivity:zero"
    for expression_row, criterion in ((onset, "onsets"), (zero, "zero resistance")):
        conditions = expression_row["projection"]["conditions"]
        criterion_row = next(c for c in conditions if c["field_id"] == "criterion_statement")
        field_row = next(c for c in conditions if c["field_id"] == "magnetic_field_t")
        assert criterion_row["value"]["raw_value"] == criterion
        assert criterion_row["role"] == "reported_result_condition"
        assert field_row["value"]["raw_value"] == "zero applied magnetic field"
        assert field_row["value"]["value"] is None
        assert not any(c["field_id"] == "pressure_gpa" for c in conditions)
    assert temperature["projection"]["field_id"] == "measurement_temperature_k"
    assert temperature["projection"]["value"]["value"] == 250
    assert temperature["projection"]["window"]["id"] == "crystallography:table1"
    assert temperature["projection"]["subject"]["formula"] == "BaFe1.90Pt0.10As2"
    assert all(e["capture"]["source"]["currentness"] == "historical" for e in rows)
    # These existing target pins are explicitly synthetic; the unchanged
    # historical fragments prove transcription, never physical association.
    material, paper = await retained(db_session, record={"tc_kelvin": 23, "knowledge_origin": "Observed", "synthetic": True})
    _, tc, _ = await target(db_session, operator, material)
    _, criterion_target, _ = await target(db_session, operator, material, "tc_criterion")
    _, temperature_target, _ = await target(db_session, operator, material, "measurement_temperature_k")
    for e in (onset, zero):
        await save(db_session, operator, association(tc, e, paper))
        await save(db_session, operator, association(criterion_target, e, paper))
    with pytest.raises(DBAPIError) as rejected:
        await save(db_session, operator, association(tc, temperature, paper))
    assert "field_case_expression_field_mismatch" in str(rejected.value)
    await save(db_session, operator, association(temperature_target, temperature, paper))
    detail = await service.target_detail(db_session, actor_user_id=operator["id"], target_id=tc["target_id"])
    assert detail["association_total"] == 2 and all(a["is_head"] for a in detail["associations"])
    assert all(a["expression"] is None and "source_lifecycle_held" in a["eligibility"]["reason_codes"] for a in detail["associations"])
    assert json.loads(detail["target"]["context_canonical_json"])["result"]["tc_kelvin"] == 23


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["catalogue", "grant", "session", "expression"])
async def test_fresh_read_fence_rejects_concurrent_changes(client, db_session, monkeypatch, change):
    monkeypatch.setenv("SOURCE_PROPERTY_PENDING_ENABLED", "true")
    get_settings.cache_clear()
    operator = await research_operator()
    material, _ = await retained(db_session)
    await db_session.commit()
    original = service.material_adapter
    async def racing(*args, **kwargs):
        result = await original(*args, **kwargs)
        if change == "grant":
            await revoke_research_grant(grant_id=operator["grant_id"], revoked_by=operator["grantor_id"])
        else:
            async with AsyncSession(get_engine().execution_options(isolation_level="SERIALIZABLE")) as fresh:
                if change == "catalogue":
                    await fresh.execute(sa.update(Base.metadata.tables["materials"]).where(Base.metadata.tables["materials"].c.id == material).values(needs_review=True))
                elif change == "session":
                    await fresh.execute(sa.update(Base.metadata.tables["users"]).where(Base.metadata.tables["users"].c.id == operator["id"]).values(session_version=1))
                else:
                    await expression(fresh, operator)
                await fresh.commit()
        return result
    monkeypatch.setattr(service, "material_adapter", racing)
    try:
        result = await client.get(PREFIX + "/materials/" + material, headers=operator["headers"])
        assert result.status_code in {403, 409}, result.text
        assert result.headers["cache-control"] == "private, no-store"
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_sql_closed_attempt_guard_rejects_coordinated_payload_hash_rewrite(db_session):
    operator = await research_operator()
    material, _ = await retained(db_session)
    _, t, _ = await target(db_session, operator, material)
    saved = await save(db_session, operator, attempt(t))
    original = await service.row_by_id(db_session, "attempt", saved["receipt_id"])
    row = {k: v for k, v in original.items() if k != "created_at"}
    row["id"] = uuid4()
    row["request_key"] = "forged:" + uuid4().hex
    row["payload"] = deepcopy(row["payload"])
    row["payload"]["checked_scope"]["fulltext_checked"] = True
    row["predecessor_id"], row["predecessor_sha256"] = original["id"], original["record_sha256"]
    row["payload"]["predecessor"] = {"id": str(original["id"]), "record_sha256": original["record_sha256"]}
    req = operation("attempt", row["payload"])
    req["request_key"] = row["request_key"]
    row["request_json"] = canonical(req).decode()
    row["request_sha256"] = service.text_sha(row["request_json"])
    row["preview_json"] = canonical({"version": service.VERSION,
        "actor": {"actor_user_id": str(row["actor_user_id"]), "actor_grant_id": str(row["actor_grant_id"]), "actor_session_version": row["actor_session_version"]},
        "request_sha256": row["request_sha256"], "receipt_id": str(row["id"]), "context_sha256": row["context_sha256"]}).decode()
    row["preview_sha256"] = service.text_sha(row["preview_json"])
    row["record_sha256"] = digest(service._body(row))
    async with db_session.begin_nested() as nested:
        with pytest.raises(DBAPIError) as rejected:
            await db_session.execute(service.table("attempt").insert().values(**row))
        assert "field_case_attempt_shape" in str(rejected.value)
        await nested.rollback()


@pytest.mark.asyncio
async def test_worst_escaped_target_page_is_bounded_with_omission_counts(client, db_session, monkeypatch):
    monkeypatch.setenv("SOURCE_PROPERTY_PENDING_ENABLED", "true")
    get_settings.cache_clear()
    operator = await research_operator()
    material, _ = await retained(db_session, record={"tc_kelvin": 116, "pressure_gpa": 140,
        "knowledge_origin": "Computed", "synthetic": True, "private_proof_padding": '\\"' * 16000})
    for field in ("lambda_eph", "omega_log_k", "mu_star", "hc2_tesla", "lattice_a", "lattice_b", "lattice_c", "sample_form"):
        await target(db_session, operator, material, field)
    await db_session.commit()
    try:
        result = await client.get(PREFIX + "/materials/" + material, headers=operator["headers"])
        assert result.status_code == 200, result.text[:500]
        body = result.json()
        assert len(result.content) < 2 * 1024 * 1024
        assert body["total"] == 8 and body["entries_returned"] + body["entries_omitted"] == 8
        assert body["next_offset"] == body["entries_returned"]
        next_page = await client.get(PREFIX + "/materials/" + material, params={"offset": body["next_offset"]}, headers=operator["headers"])
        assert next_page.status_code == 200
        all_ids = [d["target"]["id"] for d in body["entries"] + next_page.json()["entries"]]
        assert len(all_ids) == len(set(all_ids)) == 8
        assert all(detail["target"]["context_canonical_json"] is not None for detail in body["entries"])
    finally:
        get_settings.cache_clear()


def rehash_forged(row, request):
    """Rebuild every submitted proof; only independent SQL can reject this."""
    row["request_json"] = canonical(request).decode()
    row["request_key"], row["payload"] = request["request_key"], request["payload"]
    row["request_sha256"] = service.text_sha(row["request_json"])
    row["preview_json"] = canonical({"version": service.VERSION,
        "actor": {"actor_user_id": str(row["actor_user_id"]), "actor_grant_id": str(row["actor_grant_id"]),
                  "actor_session_version": row["actor_session_version"]},
        "request_sha256": row["request_sha256"], "receipt_id": str(row["id"]), "context_sha256": row["context_sha256"]}).decode()
    row["preview_sha256"] = service.text_sha(row["preview_json"])
    row["record_sha256"] = digest(service._body(row))
    return row


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["version", "operation", "outcome", "reason_codes", "predecessor", "kind", "field_id",
                                  "material_id", "expected_context_sha256", "scope_label", "fulltext_checked"])
async def test_rehashed_sql_null_discriminators_and_wrong_predecessor_rejected(db_session, field):
    import json
    operator = await research_operator()
    material, _ = await retained(db_session)
    _, t, _ = await target(db_session, operator, material)
    op = "target" if field in {"kind", "field_id", "material_id", "expected_context_sha256"} else "attempt"
    saved = t if op == "target" else await save(db_session, operator, attempt(t))
    original = await service.row_by_id(db_session, op, saved["receipt_id"])
    row = {k: deepcopy(v) for k, v in original.items() if k != "created_at"}
    row["id"] = uuid4()
    req = json.loads(row["request_json"])
    req["request_key"] = "null-rewrite:" + uuid4().hex
    if op == "attempt":
        row["predecessor_id"], row["predecessor_sha256"] = original["id"], original["record_sha256"]
        req["payload"]["predecessor"] = {"id": str(original["id"]), "record_sha256": original["record_sha256"]}
    if field in {"version", "operation"}:
        req[field] = None
    elif field in {"kind", "material_id", "expected_context_sha256"}:
        req["payload"]["target"][field] = None
    elif field in {"scope_label", "fulltext_checked"}:
        req["payload"]["checked_scope"][field] = None
    else:
        req["payload"][field] = "pretend-null-predecessor" if field == "predecessor" else [None] if field == "reason_codes" else None
    rehash_forged(row, req)
    async with db_session.begin_nested() as nested:
        with pytest.raises(DBAPIError) as rejected:
            await db_session.execute(service.table(op).insert().values(**row))
        assert any(reason in str(rejected.value) for reason in ("field_case_exact_request_required", "field_case_attempt_shape", "field_case_target_shape", "field_case_target_selector", "field_case_exact_predecessor_required"))
        await nested.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("key", [123456789, True])
async def test_rehashed_sql_coerced_request_key_rejected(db_session, key):
    import json
    operator = await research_operator()
    material, _ = await retained(db_session)
    _, saved, _ = await target(db_session, operator, material)
    original = await service.row_by_id(db_session, "target", saved["receipt_id"])
    row = {k: deepcopy(v) for k, v in original.items() if k != "created_at"}
    row["id"] = uuid4()
    request = json.loads(row["request_json"])
    request["request_key"] = key
    rehash_forged(row, request)
    # Model the text column and JSON ->> coercion independently; both are
    # otherwise legal existing request-key grammar and all proofs are rebuilt.
    row["request_key"] = str(key).lower()
    row["record_sha256"] = digest(service._body(row))
    async with db_session.begin_nested() as nested:
        with pytest.raises(DBAPIError) as rejected:
            await db_session.execute(service.table("target").insert().values(**row))
        assert "field_case_exact_request_required" in str(rejected.value)
        await nested.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("op", ["association", "attempt"])
async def test_sql_chain_head_follows_predecessors_with_out_of_order_timestamps(db_session, op):
    import json
    from datetime import datetime, timezone
    operator = await research_operator()
    material, paper = await retained(db_session)
    _, t, _ = await target(db_session, operator, material)
    _, e = await expression(db_session, operator)
    request = association(t, e, paper) if op == "association" else attempt(t)
    preview = await service.operate(db_session, actor_user_id=operator["id"], request=request)
    root = json.loads(preview["receipt_canonical_json"])
    for column in service.table(op).columns:
        if isinstance(column.type, sa.UUID) and root[column.name] is not None:
            root[column.name] = UUID(root[column.name])
    root["record_sha256"] = preview["receipt_sha256"]
    # SQL supports an independently supplied finite receipt clock. That clock
    # is deliberately outside the stable proof and cannot determine a head.
    root["created_at"] = datetime(2099, 1, 1, tzinfo=timezone.utc)
    await db_session.execute(service.table(op).insert().values(**root))
    previous = {"id": str(root["id"]), "record_sha256": root["record_sha256"]}
    for _ in range(2):
        request = association(t, e, paper, previous) if op == "association" else attempt(t, previous)
        saved = await save(db_session, operator, request)
        previous = {"id": saved["receipt_id"], "record_sha256": saved["receipt_sha256"]}
    detail = await service.target_detail(db_session, actor_user_id=operator["id"], target_id=t["target_id"])
    entries = detail["associations" if op == "association" else "attempts"]
    assert len(entries) == 3
    assert {row["id"] for row in entries if row["is_head"]} == {previous["id"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("op", ["association", "attempt"])
async def test_bounded_detail_shows_head_before_more_than_eight_future_clock_rows(db_session, op):
    import json
    from datetime import datetime, timedelta, timezone
    operator = await research_operator()
    material, paper = await retained(db_session)
    _, t, _ = await target(db_session, operator, material)
    _, e = await expression(db_session, operator)
    previous = None
    for index in range(9):
        request = association(t, e, paper, previous) if op == "association" else attempt(t, previous)
        preview = await service.operate(db_session, actor_user_id=operator["id"], request=request)
        row = json.loads(preview["receipt_canonical_json"])
        for column in service.table(op).columns:
            if isinstance(column.type, sa.UUID) and row[column.name] is not None:
                row[column.name] = UUID(row[column.name])
        row["record_sha256"] = preview["receipt_sha256"]
        row["created_at"] = datetime(2099, 1, 1, tzinfo=timezone.utc) + timedelta(days=index)
        await db_session.execute(service.table(op).insert().values(**row))
        previous = {"id": str(row["id"]), "record_sha256": row["record_sha256"]}
    request = association(t, e, paper, previous) if op == "association" else attempt(t, previous)
    saved = await save(db_session, operator, request)
    detail = await service.target_detail(db_session, actor_user_id=operator["id"], target_id=t["target_id"])
    entries = detail["associations" if op == "association" else "attempts"]
    assert len(entries) == detail[op + "_returned"] == 8
    assert detail[op + "_total"] == 10 and detail[op + "_omitted"] == 2
    assert entries[0]["id"] == saved["receipt_id"] and entries[0]["is_head"]
    assert sum(row["is_head"] for row in entries) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("action", [None, "propose"])
async def test_rehashed_sql_action_cannot_bypass_superseded_expression(db_session, action):
    import json
    operator = await research_operator()
    material, paper = await retained(db_session)
    _, t, _ = await target(db_session, operator, material)
    package, e = await expression(db_session, operator)
    a = await save(db_session, operator, association(t, e, paper))
    package["expressions"][0]["predecessor"] = {"revision_id": e["id"], "record_sha256": e["record_sha256"], "revision_number": 1}
    key = "successor:" + uuid4().hex
    preview = await service.expressions.import_package(db_session, actor_user_id=operator["id"], request_key_value=key, package=package)
    await service.expressions.import_package(db_session, actor_user_id=operator["id"], request_key_value=key, package=package,
        dry_run=False, expected_preview_sha256=preview["preview_sha256"])
    original = await service.row_by_id(db_session, "association", a["receipt_id"])
    row = {k: deepcopy(v) for k, v in original.items() if k != "created_at"}
    row["id"], row["predecessor_id"], row["predecessor_sha256"] = uuid4(), original["id"], original["record_sha256"]
    req = json.loads(row["request_json"])
    req["request_key"] = "stale-action:" + uuid4().hex
    req["payload"].update(action=action, predecessor={"id": str(original["id"]), "record_sha256": original["record_sha256"]})
    rehash_forged(row, req)
    async with db_session.begin_nested() as nested:
        with pytest.raises(DBAPIError) as rejected:
            await db_session.execute(service.table("association").insert().values(**row))
        assert ("field_case_association_shape" if action is None else "field_case_current_inputs_required") in str(rejected.value)
        await nested.rollback()
    detail = await service.target_detail(db_session, actor_user_id=operator["id"], target_id=t["target_id"])
    assert detail["associations"][0]["expression"] is None
    assert "expression_superseded" in detail["associations"][0]["eligibility"]["reason_codes"]


@pytest.mark.asyncio
@pytest.mark.parametrize("action", [None, "withdraw"])
async def test_rehashed_sql_action_cannot_bypass_proposal_owner(db_session, action):
    import json
    operator, other = await research_operator(), await research_operator()
    material, paper = await retained(db_session)
    _, t, _ = await target(db_session, operator, material)
    _, e = await expression(db_session, operator)
    a = await save(db_session, operator, association(t, e, paper))
    original = await service.row_by_id(db_session, "association", a["receipt_id"])
    row = {k: deepcopy(v) for k, v in original.items() if k != "created_at"}
    row.update(id=uuid4(), actor_user_id=other["id"], actor_grant_id=other["grant_id"],
               predecessor_id=original["id"], predecessor_sha256=original["record_sha256"])
    req = json.loads(row["request_json"])
    req["request_key"] = "owner-action:" + uuid4().hex
    req["payload"].update(action=action, predecessor={"id": str(original["id"]), "record_sha256": original["record_sha256"]})
    rehash_forged(row, req)
    async with db_session.begin_nested() as nested:
        with pytest.raises(DBAPIError) as rejected:
            await db_session.execute(service.table("association").insert().values(**row))
        assert ("field_case_association_shape" if action is None else "field_case_own_proposal_withdrawal_required") in str(rejected.value)
        await nested.rollback()
