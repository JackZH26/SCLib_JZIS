"""Actual disposable SQL pending import; no scientific-program execution.

Synthetic native-format bytes exercise transaction and provenance boundaries.
They are not an expert review, a completed DFT run, or scientific/ML admission.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import Base
from services import scientific_pending_import as service
from services.research_access import ResearchAccessDenied
from services.research_release_manifest import digest
from services.scientific_import_input import compiler_inventory
from tests.test_qe_force_constants_import import make_file
from tests.test_research_freeze import add, state
from tests.test_research_freeze import db_session as _serializable_db_session
from tests.test_research_publication import actors

db_session = _serializable_db_session

SYNTHETIC_INPUT = b" &input\n asr='simple', flfrc='synthetic.fc', flfrq='synthetic.freq'\n /\n 1\n 0 0 0\n"
SYNTHETIC_FREQUENCY = b" &plot nbnd=6,nks=1 /\n 0.000000 0.000000 0.000000\n -1.0000 0.0000 2.0000 3.0000 4.0000 5.0000\n"
SCIENCE_TABLES = ("material_states", "structure_records", "research_events", "event_properties", "research_runs")
UNTOUCHED_TABLES = ("materials", "material_claims", "source_snapshots", "snapshot_event_memberships",
                    "ml_dataset_snapshots", "ml_examples", "ml_example_inputs")


async def seed_import(db, *, missing_fc=False, bad_fc=False, geometry="bulk_3d", formula="AlAs", frequency=None):
    """Reusable real SQL fixture for the independent HTTP consumer tests."""
    people = await actors(db)
    material = "pending-material:" + uuid4().hex
    await add(db, "materials", id=material, formula=formula, formula_normalized=formula,
              records=[{"synthetic": True}], needs_review=True)
    binding = await service.material_binding(db, actor_user_id=people["curator"], material_id=material)
    input_bytes = SYNTHETIC_INPUT
    frequency_bytes = SYNTHETIC_FREQUENCY if frequency is None else frequency
    leaves = [("input", "synthetic.in", input_bytes), ("frequency", "synthetic.freq", frequency_bytes)]
    manifest = {
        "version": "scientific-program-package/1.0.0", "adapter_id": "qe-matdyn-flfrq",
        "files": [{"role": role, "logical_name": name, "sha256": hashlib.sha256(payload).hexdigest(),
                   "size_bytes": len(payload)} for role, name, payload in leaves],
        "context": {"material_formula": formula, "material_id": None, "geometry_scope": geometry,
                    "source_url": None, "source_revision": None, "license_spdx": None},
        "declarations": {"review_status": "unreviewed", "execution_attested": False, "ml_training_approved": False},
    }
    fc_bytes = None if missing_fc else b"malformed native force constants" if bad_fc else make_file()
    context = {
        "version": "scientific-import-context/1.0.0", "material_id": material,
        "expected_material_row_sha256": binding["material_row_sha256"],
        "force_constants": None if missing_fc else {
            "logical_name": "synthetic.fc", "sha256": hashlib.sha256(fc_bytes).hexdigest(), "size_bytes": len(fc_bytes)},
    }
    args = {"manifest": manifest, "artifact_bytes": {hashlib.sha256(data).hexdigest(): data for _, _, data in leaves},
            "expected_manifest_sha256": digest(manifest), "context": context, "force_constants_bytes": fc_bytes}
    package = service.prepare_input(**args)
    return {"actors": people, "material": material, "args": args, "package": package,
            "input_bytes": input_bytes, "frequency_bytes": frequency_bytes, "fc_bytes": fc_bytes}


async def _start(db, fixture, *, request_key=None, dry_run=False):
    return await service.start_import(db, actor_user_id=fixture["actors"]["curator"],
        request_key=request_key or "synthetic-import:" + uuid4().hex, package=fixture["package"], dry_run=dry_run)


async def _finish(db, fixture, started, *, prepared=None, dry_run=False):
    return await service.finish_import(db, actor_user_id=fixture["actors"]["curator"],
        attempt_id=started["attempt_id"], prepared=prepared or service.compile_input(fixture["package"]), dry_run=dry_run)


async def _rows(db, table_name, **equalities):
    table = Base.metadata.tables[table_name]
    query = sa.select(table)
    for key, value in equalities.items():
        if key.endswith("_id") or key == "id":
            value = UUID(value) if isinstance(value, str) and len(value) == 36 else value
        query = query.where(table.c[key] == value)
    return [dict(row) for row in (await db.execute(query)).mappings().all()]


async def _completed(db, fixture):
    started = await _start(db, fixture)
    await db.commit()
    prepared = service.compile_input(fixture["package"])
    finished = await _finish(db, fixture, started, prepared=prepared)
    await db.commit()
    return started, finished


async def test_real_source_bytes_and_exact_pending_science_rows_are_linked(db_session):
    fixture = await seed_import(db_session)
    before = await state(db_session)
    started, finished = await _completed(db_session, fixture)
    assert finished["status"] == "success_pending"
    assert set(finished["row_ids"]) == {"run", "state", "structure", "event", "property"}
    after = await state(db_session)
    for table in UNTOUCHED_TABLES:
        assert after[table] == before[table], table
    blobs = await _rows(db_session, "scientific_import_blobs", package_id=started["package_id"])
    saved = {row["bytes_sha256"]: bytes(row["payload"]) for row in blobs}
    for raw in (fixture["input_bytes"], fixture["frequency_bytes"], fixture["fc_bytes"]):
        assert saved[hashlib.sha256(raw).hexdigest()] == raw
    for blob in blobs:
        artifact = (await _rows(db_session, "evidence_artifacts", id=str(blob["artifact_id"])))[0]
        assert artifact["bytes_sha256"] == hashlib.sha256(blob["payload"]).hexdigest()
        assert artifact["access"] == "restricted"
    outcome = (await _rows(db_session, "scientific_import_outcomes", attempt_id=started["attempt_id"]))[0]
    assert outcome["outcome"] == "success_pending"
    snapshots = json.loads(outcome["row_snapshots_json"])
    assert set(snapshots) == {"run", "state", "structure", "event", "property"}
    assert outcome["row_snapshots_sha256"] == hashlib.sha256(outcome["row_snapshots_json"].encode()).hexdigest()
    pending_state = snapshots["state"]
    assert pending_state["material_id"] == fixture["material"]
    assert pending_state["pressure_gpa"] is None
    assert pending_state["pressure_status"] == "not_reported"
    assert pending_state["temperature_k"] is None
    assert pending_state["temperature_role"] == "simulation"
    assert snapshots["run"]["run_kind"] == "extraction"
    assert snapshots["run"]["status"] == "completed"
    assert snapshots["event"]["event_type"] != "calculation"
    assert snapshots["event"]["validity_status"] == "pending"
    assert snapshots["event"]["review_status"] == "pending"
    assert snapshots["event"]["decision_artifact_id"] is None
    assert snapshots["property"]["property_key"] == "phonon_min_frequency"
    assert snapshots["property"]["value"] == pytest.approx(-0.0299792458)
    assert snapshots["property"]["unit"] == "THz"


async def test_preview_restores_full_database_and_every_guard_epoch(db_session):
    fixture = await seed_import(db_session)
    prepared = service.compile_input(fixture["package"])
    before = await state(db_session)
    result = await service.preview_import(db_session, actor_user_id=fixture["actors"]["curator"],
        request_key="synthetic-preview:" + uuid4().hex, prepared=prepared)
    assert result["status"] == "success_pending"
    assert await state(db_session) == before


async def test_start_dry_run_does_not_leave_package_blobs_attempt_or_epoch(db_session):
    fixture = await seed_import(db_session)
    before = await state(db_session)
    result = await _start(db_session, fixture, dry_run=True)
    assert result["status"] == "outcome_unknown"
    assert await state(db_session) == before


async def test_finish_dry_run_preserves_only_already_durable_unfinished_attempt(db_session):
    fixture = await seed_import(db_session)
    started = await _start(db_session, fixture)
    await db_session.commit()
    before = await state(db_session)
    finished = await _finish(db_session, fixture, started, dry_run=True)
    assert finished["status"] == "success_pending"
    assert await state(db_session) == before
    inspected = await service.inspect_import(db_session, actor_user_id=fixture["actors"]["curator"], attempt_id=started["attempt_id"])
    assert inspected["status"] == "outcome_unknown"
    assert inspected["report"] is None


async def test_same_key_unfinished_replay_is_full_database_noop(db_session):
    fixture = await seed_import(db_session)
    key = "synthetic-replay:" + uuid4().hex
    started = await _start(db_session, fixture, request_key=key)
    await db_session.commit()
    before = await state(db_session)
    replay = await _start(db_session, fixture, request_key=key)
    assert replay["attempt_id"] == started["attempt_id"]
    assert replay["replayed"] is True
    assert await state(db_session) == before


async def test_terminal_replay_returns_saved_outcome_without_touching_any_row(db_session):
    fixture = await seed_import(db_session)
    key = "synthetic-replay:" + uuid4().hex
    started = await _start(db_session, fixture, request_key=key)
    await db_session.commit()
    finished = await _finish(db_session, fixture, started)
    await db_session.commit()
    before = await state(db_session)
    replay = await _start(db_session, fixture, request_key=key)
    assert replay["status"] == "success_pending"
    assert replay["outcome_id"] == finished["outcome_id"]
    assert replay["report_sha256"] == finished["report_sha256"]
    assert replay["replayed"] is True
    assert await state(db_session) == before


async def test_same_actor_key_different_request_rejected_without_mutation(db_session):
    fixture = await seed_import(db_session)
    key = "synthetic-collision:" + uuid4().hex
    await _start(db_session, fixture, request_key=key)
    await db_session.commit()
    changed_args = deepcopy(fixture["args"])
    changed_args["manifest"]["context"]["geometry_scope"] = "other"
    changed_args["expected_manifest_sha256"] = digest(changed_args["manifest"])
    changed = {**fixture, "package": service.prepare_input(**changed_args)}
    before = await state(db_session)
    with pytest.raises(ValueError):
        await _start(db_session, changed, request_key=key)
    assert await state(db_session) == before


async def test_material_row_changed_between_durable_start_and_finish_quarantines(db_session):
    fixture = await seed_import(db_session)
    started = await _start(db_session, fixture)
    await db_session.commit()
    prepared = service.compile_input(fixture["package"])
    await db_session.execute(sa.text("UPDATE materials SET family='changed after start' WHERE id=:id"), {"id": fixture["material"]})
    await db_session.commit()
    before = await state(db_session)
    finished = await _finish(db_session, fixture, started, prepared=prepared)
    assert finished["status"] == "quarantined"
    after = await state(db_session)
    for table in SCIENCE_TABLES:
        assert after[table] == before[table]


@pytest.mark.parametrize("kwargs", [{"missing_fc": True}, {"bad_fc": True}, {"geometry": "other"},
                                    {"geometry": "unknown"}, {"formula": "Al2As"}])
async def test_unresolved_sources_geometry_or_composition_only_persist_quarantine(db_session, kwargs):
    fixture = await seed_import(db_session, **kwargs)
    before = await state(db_session)
    started, finished = await _completed(db_session, fixture)
    assert finished["status"] == "quarantined"
    after = await state(db_session)
    for table in (*SCIENCE_TABLES, *UNTOUCHED_TABLES):
        assert after[table] == before[table], table
    outcome = (await _rows(db_session, "scientific_import_outcomes", attempt_id=started["attempt_id"]))[0]
    assert outcome["reason_codes"]
    assert all(outcome[name + "_id"] is None for name in ("run", "state", "structure", "event", "property"))


async def test_frequency_modes_must_match_actual_force_constant_atom_count(db_session):
    wrong = b" &plot nbnd=3,nks=1 /\n0 0 0\n1 2 3\n"
    fixture = await seed_import(db_session, frequency=wrong)
    before = await state(db_session)
    _, finished = await _completed(db_session, fixture)
    assert finished["status"] == "quarantined"
    after = await state(db_session)
    for table in SCIENCE_TABLES:
        assert after[table] == before[table]


@pytest.mark.parametrize("field", ["report_bytes", "coordinate_bytes", "signature", "import_wall_ms", "import_cpu_ms"])
async def test_changed_prepared_dataclass_cannot_bypass_process_hmac(db_session, field):
    fixture = await seed_import(db_session)
    started = await _start(db_session, fixture)
    await db_session.commit()
    prepared = service.compile_input(fixture["package"])
    original = getattr(prepared, field)
    changed = original + b" " if isinstance(original, bytes) else "0" * 64 if isinstance(original, str) else original + 1
    tampered = replace(prepared, **{field: changed})
    before = await state(db_session)
    with pytest.raises(ValueError):
        await _finish(db_session, fixture, started, prepared=tampered)
    assert await state(db_session) == before


@pytest.mark.parametrize("role", ["member", "admin", "reviewer", "publisher"])
async def test_only_explicit_live_curator_can_start_import(db_session, role):
    fixture = await seed_import(db_session)
    before = await state(db_session)
    with pytest.raises(ResearchAccessDenied):
        await service.start_import(db_session, actor_user_id=fixture["actors"][role],
            request_key="synthetic-role:" + uuid4().hex, package=fixture["package"], dry_run=False)
    assert await state(db_session) == before


async def test_outer_rollback_after_finish_leaves_no_half_scientific_result(db_session):
    fixture = await seed_import(db_session)
    started = await _start(db_session, fixture)
    await db_session.commit()
    before = await state(db_session)
    await db_session.commit()
    finished = await _finish(db_session, fixture, started)
    assert finished["status"] == "success_pending"
    await db_session.rollback()
    assert await state(db_session) == before


async def test_mid_write_failure_rolls_back_generated_artifacts_rows_and_epochs(db_session, monkeypatch):
    fixture = await seed_import(db_session)
    started = await _start(db_session, fixture)
    await db_session.commit()
    prepared = service.compile_input(fixture["package"])
    before = await state(db_session)
    original = service._add

    async def fail_property(db, name, **values):
        if name == "event_properties":
            raise RuntimeError("synthetic mid-write fault")
        return await original(db, name, **values)

    monkeypatch.setattr(service, "_add", fail_property)
    with pytest.raises(RuntimeError, match="synthetic mid-write fault"):
        await _finish(db_session, fixture, started, prepared=prepared)
    assert await state(db_session) == before
    monkeypatch.setattr(service, "_add", original)
    recovered = await _finish(db_session, fixture, started, prepared=prepared)
    assert recovered["status"] == "success_pending"


async def test_aborted_outer_sql_transaction_rolls_back_all_finish_writes(db_session):
    fixture = await seed_import(db_session)
    started = await _start(db_session, fixture)
    await db_session.commit()
    before = await state(db_session)
    await db_session.commit()
    await _finish(db_session, fixture, started)
    with pytest.raises(DBAPIError):
        await db_session.execute(sa.text("SELECT 1 / 0"))
    await db_session.rollback()
    assert await state(db_session) == before


async def test_pending_import_costs_are_parser_measurements_not_fabricated_calculation_cost(db_session):
    fixture = await seed_import(db_session)
    started, _ = await _completed(db_session, fixture)
    outcome = (await _rows(db_session, "scientific_import_outcomes", attempt_id=started["attempt_id"]))[0]
    assert outcome["cost_scope"] == "parser_worker_only"
    assert type(outcome["import_wall_ms"]) is int and outcome["import_wall_ms"] >= 0
    assert type(outcome["import_cpu_ms"]) is int and outcome["import_cpu_ms"] >= 0
    assert all(outcome[field] is None for field in ("calculation_cpu_seconds", "calculation_wall_seconds", "calculation_monetary_cost"))


async def test_explicit_failure_is_durable_no_science_rows_and_same_attempt_replay_is_noop(db_session):
    fixture = await seed_import(db_session)
    started = await _start(db_session, fixture)
    await db_session.commit()
    before = await state(db_session)
    failed = await service.fail_import(db_session, actor_user_id=fixture["actors"]["curator"],
        attempt_id=started["attempt_id"], reason_code="parser_failed")
    await db_session.commit()
    assert failed["status"] == "failed"
    assert failed["row_ids"] is None
    after = await state(db_session)
    for table in SCIENCE_TABLES:
        assert after[table] == before[table]
    replay = await service.fail_import(db_session, actor_user_id=fixture["actors"]["curator"],
        attempt_id=started["attempt_id"], reason_code="parser_failed")
    assert replay["replayed"] is True
    assert replay["outcome_id"] == failed["outcome_id"]
    assert await state(db_session) == after


async def test_new_request_after_failure_reuses_exact_sources_but_retains_failed_history(db_session):
    fixture = await seed_import(db_session)
    first = await _start(db_session, fixture)
    await db_session.commit()
    failed = await service.fail_import(db_session, actor_user_id=fixture["actors"]["curator"],
        attempt_id=first["attempt_id"], reason_code="import_timeout")
    await db_session.commit()
    files_before = await _rows(db_session, "scientific_import_files", package_id=first["package_id"])
    second = await _start(db_session, fixture)
    await db_session.commit()
    assert second["package_id"] == first["package_id"]
    assert second["attempt_id"] != first["attempt_id"]
    second_row = (await _rows(db_session, "scientific_import_attempts", id=second["attempt_id"]))[0]
    assert second_row["predecessor_id"] == UUID(first["attempt_id"])
    assert second_row["attempt_number"] == 2
    assert await _rows(db_session, "scientific_import_files", package_id=first["package_id"]) == files_before
    completed = await _finish(db_session, fixture, second)
    await db_session.commit()
    assert completed["status"] == "success_pending"
    original = await service.inspect_import(db_session, actor_user_id=fixture["actors"]["curator"], attempt_id=first["attempt_id"])
    assert original["status"] == "failed"
    assert original["outcome_id"] == failed["outcome_id"]


@pytest.mark.parametrize("field", ["request_bytes", "sources"])
async def test_input_capture_mac_rejects_dataclass_replacement_before_start(db_session, field):
    fixture = await seed_import(db_session)
    package = fixture["package"]
    if field == "request_bytes":
        changed = package.request_bytes + b" "
    else:
        first = package.sources[0]
        changed = ((first[0], first[1], first[2], first[3] + b" "), *package.sources[1:])
    fixture["package"] = replace(package, **{field: changed})
    before = await state(db_session)
    with pytest.raises(ValueError):
        await _start(db_session, fixture)
    assert await state(db_session) == before


async def test_shared_provenance_leaves_fetch_each_retained_payload_only_once(db_session, monkeypatch):
    fixture = await seed_import(db_session)
    args = deepcopy(fixture["args"])
    payload = b"Synthetic shared provenance record, not a scientific source.\n" * 1024
    checksum = hashlib.sha256(payload).hexdigest()
    args["artifact_bytes"][checksum] = payload
    for index in range(14):
        args["manifest"]["files"].append({"role": "provenance", "logical_name": f"provenance-{index}.txt",
                                           "sha256": checksum, "size_bytes": len(payload)})
    args["expected_manifest_sha256"] = digest(args["manifest"])
    fixture["package"] = service.prepare_input(**args)
    started = await _start(db_session, fixture)
    await db_session.commit()
    prepared = service.compile_input(fixture["package"])
    blobs = Base.metadata.tables["scientific_import_blobs"]
    original = db_session.execute
    observed = []

    async def observed_execute(statement, *arguments, **options):
        result = await original(statement, *arguments, **options)
        if isinstance(statement, sa.sql.Select) and any(
            getattr(column, "table", None) is blobs and getattr(column, "name", None) == "payload"
            for column in statement.selected_columns
        ):
            # Freeze/replay the actual SQL result, not a fake provider or DB row.
            frozen = result.freeze()
            rows = list(frozen().mappings())
            observed.append([(row["artifact_id"], len(row["payload"])) for row in rows])
            return frozen()
        return result

    monkeypatch.setattr(db_session, "execute", observed_execute)
    finished = await _finish(db_session, fixture, started, prepared=prepared)
    assert finished["status"] == "success_pending"
    assert len(observed) == 1
    identifiers = [identifier for identifier, _ in observed[0]]
    assert len(identifiers) == len(set(identifiers))
    unique = {sha: data for _, _, sha, data in fixture["package"].sources}
    assert len(identifiers) == len(unique) == 6
    assert sum(size for _, size in observed[0]) == sum(map(len, unique.values()))
    assert len(fixture["package"].sources) == 19


def test_compiler_identity_pins_actual_transitive_formula_and_canonical_sources():
    inventory = compiler_inventory()
    root = Path(__file__).resolve().parents[2]
    for relative in ("api/services/ml_composition.py", "api/services/_composition/formula_enrichment.py",
                     "api/services/_composition/formula_validator.py", "api/services/research_release_spec.py"):
        assert inventory[relative] == hashlib.sha256((root / relative).read_bytes()).hexdigest()


@pytest.mark.parametrize("statement", ["UPDATE scientific_import_outcomes SET report_json='{}' WHERE attempt_id=:id",
                                       "DELETE FROM scientific_import_outcomes WHERE attempt_id=:id"])
async def test_native_terminal_immutability_rejects_direct_mutation(db_session, statement):
    fixture = await seed_import(db_session)
    started, _ = await _completed(db_session, fixture)
    before = await state(db_session)
    nested = await db_session.begin_nested()
    try:
        with pytest.raises(DBAPIError):
            await db_session.execute(sa.text(statement), {"id": UUID(started["attempt_id"])})
    finally:
        await nested.rollback()
    assert await state(db_session) == before
