"""Native custody tests. QE output captures are real; UPF headers/actors are synthetic.

These headers are parser fixtures, not solver-valid pseudopotentials. Tests do
not establish the calculations' physical association with the synthetic design.
"""
import base64
import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from services import discovery_calculation_contract as contract
from services import discovery_calculations as service
from services import discovery_designs as designs
from services.research_release_manifest import canonical, digest
from services.source_property_pending import (
    SourcePropertyConflict,
    SourcePropertyError,
    SourcePropertyNotFound,
)
from sqlalchemy.exc import DBAPIError

from tests.research_access_helpers import research_operator
from tests.test_discovery_design_contract import operation as design_operation
from tests.test_discovery_designs import save
from tests.test_material_field_cases import retained
from tests.test_research_freeze import db_session as db_session
from tests.test_research_freeze import state

ROOT = Path(__file__).resolve().parents[2]


def originals(case="scf"):
    source = ROOT / "frontend/tests/fixtures/qe-output"
    manifest = json.loads((source / f"{case}.json").read_bytes())
    entries = [("input", "run.in", (ROOT / "api/tests/fixtures/qe-pw" / f"{case}.in").read_bytes()),
               ("xml", "data-file-schema.xml", (source / f"{case}.xml").read_bytes()),
               ("stdout", "pw.out", (source / f"{case}.out").read_bytes())]
    for pseudo in manifest["pseudopotentials"]:
        entries.append(("upf", pseudo["filename"], (
            f'<UPF version="2.0.1"><PP_HEADER element="{pseudo["element"]}" functional="PBE" '
            f'relativistic="scalar" has_so="false" is_coulomb="false" pseudo_type="PAW" '
            f'z_valence="{pseudo["valence_electrons"]}"/></UPF>').encode()))
    entries.sort(key=lambda item: item[:2])
    return [{"role": role, "name": name, "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            for role, name, raw in entries], [raw for _, _, raw in entries]


def request(reference, case="scf"):
    inventory, files = originals(case)
    return {"version": contract.REQUEST_VERSION, "request_key": "calculation-test:" + uuid4().hex,
        "design": reference, "files": inventory, "association": "researcher_linked_unverified",
        "findings": "Native files report electronic convergence; the synthetic design association is unverified.",
        "decision": "continue", "reason": "Perform a numerical convergence study before physical interpretation.",
        "unknowns": ["Basis convergence", "Physical structure and state association", "300 K stability"]}, files


async def case(db, *, anchored=False, action="calculation"):
    actor = await research_operator()
    kwargs = {}
    material = paper = None
    if anchored:
        material, paper = await retained(db, record={"tc_kelvin": 23.0, "pressure_gpa": 1.0})
        kwargs = {"kind": "retained_result", "material_id": material, "record_index": 0}
    baseline = await designs.context(db, actor_user_id=actor["id"], **kwargs)
    proposal = design_operation(baseline=baseline["baseline"])
    proposal["payload"]["design"]["next_action"]["kind"] = action
    proposal["payload"]["design"]["next_action"]["question"] = "Does this explicit structure converge in the declared PBE calculation?"
    parent = await save(db, actor, proposal)
    ctx = await service.context(db, actor_user_id=actor["id"], design_id=parent["design_id"])
    req, files = request(ctx["design"])
    return actor, parent, req, files, material, paper


async def saved(db, actor, req, files):
    prepared = contract.prepare(req, files)
    before = await state(db)
    preview = await service.operate(db, actor_user_id=actor["id"], prepared=prepared)
    assert preview["dry_run"] and not preview["private_ledger_written"]
    assert await state(db) == before
    result = await service.operate(db, actor_user_id=actor["id"], prepared=prepared,
        dry_run=False, expected_preview_sha256=preview["preview_sha256"])
    assert result["receipt_sha256"] == preview["receipt_sha256"]
    return result


def wire(req, files):
    return {"request": req, "files_base64": [base64.b64encode(raw).decode() for raw in files]}


@pytest.mark.asyncio
@pytest.mark.parametrize("anchored", [False, True])
async def test_native_preview_commit_recovery_and_reconstruction(db_session, anchored):
    actor, parent, req, files, _, _ = await case(db_session, anchored=anchored)
    prepared = contract.prepare(req, files)
    with pytest.raises(SourcePropertyConflict, match="exact_preview"):
        await service.operate(db_session, actor_user_id=actor["id"], prepared=prepared, dry_run=False)
    result = await saved(db_session, actor, req, files)
    await db_session.commit()  # Real durability, including deferred inventory constraints.
    row, eligible, retained_bytes = await service.original_files(db_session, actor_user_id=actor["id"], return_id=result["receipt_id"])
    assert eligible["eligible"] and retained_bytes == tuple(files)
    reading = service.reconstruct(row, retained_bytes)
    report = json.loads(reading.report_json)
    assert report["status"] == "scf_reported_converged"
    assert report["observations"]["total_energy"]["unit"] == "Hartree/cell"
    assert report["observations"]["total_energy"]["value"] == -31.19334546679567
    assert all(value is False for value in report["authority"].values())
    before = await state(db_session)
    replay = await service.operate(db_session, actor_user_id=actor["id"], prepared=prepared, dry_run=False)
    recovered = await service.outcome(db_session, actor_user_id=actor["id"], request_key_value=req["request_key"], expected_request_sha256=result["request_sha256"])
    assert replay["replayed"] and recovered["receipt_sha256"] == result["receipt_sha256"]
    assert await state(db_session) == before
    page = await service.returns(db_session, actor_user_id=actor["id"], design_id=parent["design_id"])
    assert page["total"] == 1 and page["entries"][0]["eligibility"]["eligible"]
    assert "-31.193" not in result["receipt_canonical_json"]
    assert "original_bytes" not in result["receipt_canonical_json"]
    assert result["canonical_promotions"] == 0 and not result["scientific_acceptance"]
    changed = deepcopy(req)
    changed["reason"] = "Different decision under a reused request key"
    with pytest.raises(SourcePropertyConflict, match="request_conflict"):
        await service.operate(db_session, actor_user_id=actor["id"], prepared=contract.prepare(changed, files))


@pytest.mark.asyncio
async def test_other_owner_cannot_resolve_return_or_design(db_session):
    actor, parent, req, files, _, _ = await case(db_session)
    result = await saved(db_session, actor, req, files)
    await db_session.commit()
    other = await research_operator()
    for call in (
        service.original_files(db_session, actor_user_id=other["id"], return_id=result["receipt_id"]),
        service.returns(db_session, actor_user_id=other["id"], design_id=parent["design_id"]),
        service.outcome(db_session, actor_user_id=other["id"], request_key_value=req["request_key"], expected_request_sha256=result["request_sha256"]),
    ):
        with pytest.raises(SourcePropertyNotFound):
            await call


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["revise", "withdraw", "source"])
async def test_changed_design_or_source_preserves_receipt_and_withholds_bytes(db_session, change):
    actor, parent, req, files, material, paper = await case(db_session, anchored=change == "source")
    result = await saved(db_session, actor, req, files)
    if change == "source":
        from models.db import Base
        papers = Base.metadata.tables["papers"]
        await db_session.execute(papers.update().where(papers.c.id == paper).values(status="withdrawn"))
    else:
        original = await designs._row(db_session, actor["id"], parent["receipt_id"])
        revision = {"version": "discovery-design-operation/1.0.0", "request_key": "change:" + uuid4().hex,
            "operation": change, "payload": {"design_id": parent["design_id"], "predecessor": {"id": parent["receipt_id"], "record_sha256": parent["receipt_sha256"]}}}
        if change == "withdraw":
            revision["payload"]["reason"] = "Withdraw the synthetic proposal"
        else:
            revision["payload"].update(baseline=original["baseline"], design=deepcopy(original["design"]), parent=original["parent"])
            revision["payload"]["design"]["hypothesis"] = "Changed synthetic research hypothesis"
        await save(db_session, actor, revision)
    _, eligible, hidden = await service.original_files(db_session, actor_user_id=actor["id"], return_id=result["receipt_id"])
    assert not eligible["eligible"] and hidden is None
    out = await service.outcome(db_session, actor_user_id=actor["id"], request_key_value=req["request_key"], expected_request_sha256=result["request_sha256"])
    assert out["receipt_sha256"] == result["receipt_sha256"]
    req["request_key"] += ":new"
    with pytest.raises(SourcePropertyConflict, match="not_currently_eligible"):
        await service.operate(db_session, actor_user_id=actor["id"], prepared=contract.prepare(req, files))


@pytest.mark.asyncio
async def test_source_review_is_not_a_calculation_action(db_session):
    actor, _, req, files, _, _ = await case(db_session, action="source_review")
    with pytest.raises(SourcePropertyConflict, match="not_currently_eligible"):
        await service.operate(db_session, actor_user_id=actor["id"], prepared=contract.prepare(req, files))


@pytest.mark.asyncio
async def test_database_immutability_and_populated_downgrade_refusal(db_session, monkeypatch):
    actor, _, req, files, _, _ = await case(db_session)
    result = await saved(db_session, actor, req, files)
    for index in (0, 1):
        table = service.table(index)
        for stmt in (table.delete(), table.update().values(**({"report_sha256": "f" * 64} if index == 0 else {"original_bytes": b"changed"})), sa.text("TRUNCATE public." + table.name)):
            async with db_session.begin_nested() as sp:
                with pytest.raises(DBAPIError):
                    await db_session.execute(stmt)
                await sp.rollback()
    spec = importlib.util.spec_from_file_location("calculation_migration", ROOT / "api/alembic/versions/0090_discovery_calculations.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    connection = await db_session.connection()
    def downgrade(sync):
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(sync)))
        with pytest.raises(RuntimeError, match="retained private calculation files"):
            module.downgrade()
    async with db_session.begin_nested():
        await connection.run_sync(downgrade)
    row, _, raw = await service.original_files(db_session, actor_user_id=actor["id"], return_id=result["receipt_id"])
    assert service.reconstruct(row, raw)


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ["missing", "changed_bytes", "extra", "forged_report", "wrong_action_pin", "wrong_actor"])
async def test_native_sql_admission_and_independent_report_replay(db_session, corruption):
    actor, _, req, files, _, _ = await case(db_session)
    preview = await service.operate(db_session, actor_user_id=actor["id"], prepared=contract.prepare(req, files))
    values = json.loads(preview["receipt_canonical_json"])
    # Re-sign deliberate corruption to test semantics independently of hashes.
    if corruption == "forged_report":
        values["report_sha256"] = "f" * 64
    elif corruption == "wrong_action_pin":
        values["design_ref"]["next_action_sha256"] = "e" * 64
    elif corruption == "wrong_actor":
        await db_session.commit()
        other = await research_operator()
        values.update(actor_user_id=str(other["id"]), actor_grant_id=str(other["grant_id"]))
    altered_request = json.loads(values["request_json"])
    altered_request["design"] = values["design_ref"]
    values["request_json"] = canonical(altered_request).decode()
    values["request_sha256"] = designs.text_sha(values["request_json"])
    p = json.loads(values["preview_json"])
    p.update(report_sha256=values["report_sha256"], design=values["design_ref"], request_sha256=values["request_sha256"],
             actor={key: values[key] for key in ("actor_user_id", "actor_grant_id", "actor_session_version")})
    values["preview_json"] = canonical(p).decode()
    values["preview_sha256"] = designs.text_sha(values["preview_json"])
    values["record_sha256"] = digest(values)
    for key in ("id", "actor_user_id", "actor_grant_id", "design_revision_id"):
        values[key] = UUID(values[key])
    before = await state(db_session)
    async with db_session.begin_nested() as sp:
        async def insert():
            await db_session.execute(service.table().insert().values(**values))
            chosen = files[:-1] if corruption == "missing" else files
            for i, raw in enumerate(chosen):
                await db_session.execute(service.table(1).insert().values(return_id=values["id"], ordinal=i,
                    original_bytes=b"changed" if corruption == "changed_bytes" and i == 0 else raw))
            if corruption == "extra":
                await db_session.execute(service.table(1).insert().values(return_id=values["id"], ordinal=len(files), original_bytes=b"extra"))
            await db_session.execute(sa.text("SET CONSTRAINTS ALL IMMEDIATE"))
        if corruption == "forged_report":
            # SQL checks custody, not PWSCF parsing. Even a re-signed fabricated
            # digest cannot produce a scientific report through the API reader.
            await insert()
            row, _, originals_saved = await service.original_files(db_session, actor_user_id=actor["id"], return_id=preview["receipt_id"])
            with pytest.raises(SourcePropertyError, match="report_integrity"):
                service.reconstruct(row, originals_saved)
        else:
            reason = "calculation_incomplete_original_inventory" if corruption == "missing" else \
                "calculation_current_design_required" if corruption in {"wrong_actor", "wrong_action_pin"} else \
                "calculation_exact_original_bytes_required"
            with pytest.raises(DBAPIError, match=reason):
                await insert()
        await sp.rollback()
    assert await state(db_session) == before


@pytest.mark.parametrize("case_name,expected", [("scf", "scf_reported_converged"), ("relax", "relaxation_reported_converged"),
    ("initialization", "initialization_only"), ("relax-initialization", "initialization_only")])
def test_prepared_native_outputs_do_not_infer_target_conditions(case_name, expected):
    req, raw = request({"design_id": str(uuid4()), "revision_id": str(uuid4()), "record_sha256": "a" * 64, "next_action_sha256": "b" * 64}, case_name)
    parsed = contract.prepare(req, raw)
    req["reason"] = "later caller mutation"
    assert parsed.request["reason"] != req["reason"]
    report = json.loads(parsed.report_json)
    assert report["status"] == expected and report["scientific_scope"]["target_temperature_k"] is None
    if expected == "initialization_only":
        assert all(value is None for value in report["observations"].values())


@pytest.mark.parametrize("corruption", ["missing", "extra", "changed", "mutable", "report", "path", "oversize", "scientific_claim"])
def test_untrusted_manifest_does_not_supply_scientific_quantities(corruption):
    req, files = request({"design_id": str(uuid4()), "revision_id": str(uuid4()), "record_sha256": "a" * 64, "next_action_sha256": "b" * 64})
    if corruption == "missing":
        files.pop()
    elif corruption == "extra":
        files.append(b"extra")
    elif corruption == "changed":
        files[0] += b"changed"
    elif corruption == "mutable":
        files[0] = bytearray(files[0])
    elif corruption == "report":
        req["report"] = {"tc": 300}
    elif corruption == "path":
        req["files"][0]["name"] = "../run.in"
    elif corruption == "oversize":
        req["files"][0]["size_bytes"] = 1024 * 1024 + 1
    else:
        req["association"] = "candidate_verified"
    with pytest.raises(SourcePropertyError):
        contract.prepare(req, files)
