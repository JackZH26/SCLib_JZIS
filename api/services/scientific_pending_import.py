"""Private pending-row import with separately durable start/terminal receipts.

Trusted callers own clean transactions and final commits. Services use only
their savepoints. A start without a terminal is outcome_unknown, not failure.
The completed producer run is the actual extraction, never a fabricated DFPT
execution. All scientific/public/ML review gates remain independent and false.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from contextlib import asynccontextmanager
from uuid import UUID, uuid5

import sqlalchemy as sa

from models.db import Base
from models.scientific_import_v1 import LOCK_FUNCTION
from services.ml_composition import ELEMENTS, composition_features
from services.research_access import active_grant
from services.research_release_manifest import canonical, digest
from services.scientific_import_input import (  # re-exported public worker API
    AUTHORITY,
    InputPackage,
    PreparedImport,
    ScientificImportError,
    compile_input,
    compiler_inventory,
    prepare_input,
    require,
    sha,
    verify_input,
    verify_prepared,
)

__all__ = ["InputPackage", "PreparedImport", "ScientificImportError", "compile_input", "prepare_input",
           "start_import", "finish_import", "fail_import", "preview_import", "inspect_import", "material_binding",
           "scientific_import_capabilities", "lookup_import_outcome"]
_NAMESPACE = UUID("ba0b4b73-15bf-46fa-aafb-c02de4c28d78")
_PREFIX = "scientific_import_"
_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$")
_FAILURES = {"parser_failed", "import_failed", "import_timeout", "import_cancelled"}


def _table(name):
    return Base.metadata.tables[name]


def _id(value):
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise ScientificImportError("invalid_import_identifier") from None


def _stable(*parts):
    return uuid5(_NAMESPACE, digest(list(map(str, parts))))


def _record_hash(value):
    def document(item):
        if isinstance(item, UUID):
            return str(item)
        if type(item) is dict:
            return {key: document(child) for key, child in item.items()}
        if type(item) is list:
            return [document(child) for child in item]
        return item
    return digest(document(value))


async def _session(db, *, write):
    require(not (db.new or db.dirty or db.deleted), "clean_import_session_required")
    isolation = await db.scalar(sa.text("SHOW transaction_isolation"))
    require(isolation == "serializable" if write else isolation in {"serializable", "repeatable read"},
            "stable_import_session_required")
    await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))


@asynccontextmanager
async def _write(db, dry_run):
    require(type(dry_run) is bool, "boolean_preview_required")
    await _session(db, write=True)
    nested = await db.begin_nested()
    operation = {"changed": False}
    try:
        await db.execute(sa.text(f"SELECT public.{LOCK_FUNCTION}()"))
        yield operation
        await db.execute(sa.text("SET CONSTRAINTS si65_complete IMMEDIATE"))
        await db.execute(sa.text("SET CONSTRAINTS si65_complete DEFERRED"))
        if dry_run or not operation["changed"]:
            await nested.rollback()
        else:
            await nested.commit()
    except BaseException:
        if nested.is_active:
            await nested.rollback()
        raise


async def _row(db, name, identifier):
    relation = _table(name)
    return (await db.execute(sa.select(relation).where(relation.c.id == _id(identifier)))).mappings().one_or_none()


async def _projection(db, name, identifier):
    relation = _table(name)
    key = _id(identifier) if isinstance(relation.c.id.type, sa.UUID) else identifier
    body = sa.func.to_jsonb(relation.table_valued())
    size = await db.scalar(sa.select(sa.func.octet_length(sa.cast(body, sa.Text))).where(relation.c.id == key))
    require(size is not None and size <= 2 * 1024 * 1024, "import_row_unavailable_or_oversized")
    return await db.scalar(sa.select(body).where(relation.c.id == key))


async def _add(db, name, **values):
    relation = _table(name)
    return (await db.execute(relation.insert().values(**values).returning(relation))).mappings().one()


async def material_binding(db, *, actor_user_id, material_id):
    await _session(db, write=False)
    await active_grant(db, actor_user_id, role="curator")
    require(type(material_id) is str and 0 < len(material_id) <= 100, "import_material_id")
    material = await _projection(db, "materials", material_id)
    return {"material_id": material_id, "material_row_sha256": digest(material), "material_formula": material["formula"]}


async def _material(db, context):
    material = await _projection(db, "materials", context["material_id"])
    require(digest(material) == context["expected_material_row_sha256"], "stale_material_binding")
    return material


async def _terminal(db, attempt):
    relation = _table(_PREFIX + "outcomes")
    return (await db.execute(sa.select(relation).where(relation.c.attempt_id == attempt["id"]))).mappings().one_or_none()


async def _dto(db, attempt, *, replayed=False):
    package = await _row(db, _PREFIX + "packages", attempt["package_id"])
    require(package is not None, "import_package_unavailable")
    terminal = await _terminal(db, attempt)
    return {"attempt_id": str(attempt["id"]), "package_id": str(package["id"]),
        "request_sha256": package["package_key"], "actor_grant_id": str(attempt["actor_grant_id"]),
        "status": "outcome_unknown" if terminal is None else terminal["outcome"],
        "outcome_id": None if terminal is None else str(terminal["id"]),
        "report_sha256": None if terminal is None else terminal["report_sha256"],
        "report": None if terminal is None else json.loads(terminal["report_json"]),
        "row_ids": None if terminal is None or terminal["outcome"] != "success_pending" else {
            key: str(terminal[key + "_id"]) for key in ("run", "state", "structure", "event", "property")},
        "costs": None if terminal is None else {key: terminal[key] for key in (
            "cost_scope", "import_wall_ms", "import_cpu_ms", "calculation_cpu_seconds",
            "calculation_wall_seconds", "calculation_monetary_cost")},
        "replayed": replayed, "authority": dict(AUTHORITY)}


async def inspect_import(db, *, actor_user_id, attempt_id):
    await _session(db, write=False)
    await active_grant(db, actor_user_id, role="curator")
    attempt = await _row(db, _PREFIX + "attempts", attempt_id)
    require(attempt is not None, "import_attempt_unavailable")
    return await _dto(db, attempt)


async def scientific_import_capabilities(db, *, actor_user_id):
    """Current operator admission only; not approval of any package or result."""
    await _session(db, write=False)
    grant = await active_grant(db, actor_user_id, role="curator")
    return {"version": "scientific-import-capabilities/1.0.0",
        "actor_user_id": str(_id(actor_user_id)), "actor_grant_id": str(grant["id"]),
        "can_read": True, "can_import": True,
        "compiler_sha256": digest(compiler_inventory()), "authority": dict(AUTHORITY)}


async def lookup_import_outcome(db, *, actor_user_id, request_key, expected_request_sha256):
    """Observe one original actor/key without starting, resuming or failing it.

    The independent pin is the augmented package key returned by preview, not
    a hash of the HTTP body. A replacement current curator grant admits the
    original actor to their historical receipt; its stored grant is unchanged.
    Absence is not evidence that an earlier submission rolled back.
    """
    await _session(db, write=False)
    await active_grant(db, actor_user_id, role="curator")
    require(type(request_key) is str and _KEY.fullmatch(request_key), "invalid_import_request_key")
    require(type(expected_request_sha256) is str
            and re.fullmatch(r"[0-9a-f]{64}", expected_request_sha256), "invalid_import_request_pin")
    attempts = _table(_PREFIX + "attempts")
    attempt = (await db.execute(sa.select(attempts).where(
        attempts.c.actor_user_id == _id(actor_user_id), attempts.c.request_key == request_key,
    ))).mappings().one_or_none()
    require(attempt is not None, "import_outcome_unavailable")
    package = await _row(db, _PREFIX + "packages", attempt["package_id"])
    require(package is not None, "import_package_unavailable")
    require(package["package_key"] == expected_request_sha256, "import_request_pin_conflict")
    return await _dto(db, attempt, replayed=True)


async def _artifact(db, *, package_id, package_key, actor_user_id, actor_grant_id, payload,
                    role, kind="other", schema="scientific-import-source/1.0.0", attempt_id=None):
    checksum = sha(payload)
    identifier = _stable(package_key, attempt_id or "source", role, checksum)
    artifact = await _add(db, "evidence_artifacts", id=identifier, kind=kind,
        schema_version=schema, source="private-scientific-import", source_version=package_key,
        bytes_sha256=checksum, hash_status="verified", access="restricted", available_at=None,
        record_sha256=digest({"package_key": package_key, "role": role, "bytes_sha256": checksum}),
        metadata={"scientific_import": {"package_key": package_key, "role": role, **AUTHORITY}})
    projection = await _projection(db, "evidence_artifacts", artifact["id"])
    await _add(db, _PREFIX + "blobs", id=_stable(identifier, "blob"), package_id=package_id,
        attempt_id=attempt_id, artifact_id=identifier, artifact_kind=kind,
        artifact_row_sha256=digest(projection), artifact_projection_json=canonical(projection).decode(),
        bytes_sha256=checksum, size_bytes=len(payload), payload=payload,
        actor_user_id=_id(actor_user_id), actor_grant_id=actor_grant_id)
    return identifier


async def start_import(db, *, actor_user_id, request_key, package, dry_run=True):
    verify_input(package)
    require(type(request_key) is str and _KEY.fullmatch(request_key), "invalid_import_request_key")
    request = package.request
    async with _write(db, dry_run) as operation:
        grant = await active_grant(db, actor_user_id, role="curator")
        attempts, packages = _table(_PREFIX + "attempts"), _table(_PREFIX + "packages")
        existing = (await db.execute(sa.select(attempts).where(attempts.c.actor_user_id == _id(actor_user_id),
            attempts.c.request_key == request_key))).mappings().one_or_none()
        if existing is not None:
            stored = await _row(db, _PREFIX + "packages", existing["package_id"])
            require(stored["package_key"] == package.package_key and stored["request_json"].encode() == package.request_bytes,
                    "import_request_key_conflict")
            result = await _dto(db, existing, replayed=True)
        else:
            await _material(db, request["context"])
            stored = (await db.execute(sa.select(packages).where(packages.c.package_key == package.package_key))).mappings().one_or_none()
            if stored is None:
                stored = await _add(db, _PREFIX + "packages", id=_stable(package.package_key, "package"),
                    package_key=package.package_key, manifest_sha256=request["manifest_sha256"],
                    context_sha256=request["context_sha256"], compiler_sha256=request["compiler_sha256"],
                    manifest_json=canonical(request["manifest"]).decode(), context_json=canonical(request["context"]).decode(),
                    request_json=package.request_bytes.decode(), actor_user_id=_id(actor_user_id), actor_grant_id=grant["id"])
                artifacts = {}
                for role, name, checksum, payload in package.sources:
                    if checksum not in artifacts:
                        artifacts[checksum] = await _artifact(db, package_id=stored["id"], package_key=package.package_key,
                            actor_user_id=actor_user_id, actor_grant_id=grant["id"], payload=payload, role="source:" + checksum)
                    await _add(db, _PREFIX + "files", id=_stable(package.package_key, "source-file", name),
                        package_id=stored["id"], role=role, logical_name=name, sha256=checksum,
                        size_bytes=len(payload), artifact_id=artifacts[checksum])
            head = (await db.execute(sa.select(attempts).where(attempts.c.package_id == stored["id"])
                                    .order_by(attempts.c.attempt_number.desc()).limit(1))).mappings().one_or_none()
            require(head is None or (await _terminal(db, head) or {}).get("outcome") != "success_pending",
                    "successful_import_package_already_exists")
            attempt = await _add(db, _PREFIX + "attempts", id=_stable(actor_user_id, request_key),
                package_id=stored["id"], attempt_number=1 if head is None else head["attempt_number"] + 1,
                predecessor_id=None if head is None else head["id"], actor_user_id=_id(actor_user_id),
                actor_grant_id=grant["id"], request_key=request_key)
            operation["changed"] = True
            result = await _dto(db, attempt)
    return result


async def _source_inventory(db, package, stored):
    """Recheck actual retained bytes/artifact snapshots, not merely their IDs."""
    blobs, files = _table(_PREFIX + "blobs"), _table(_PREFIX + "files")
    rows = (await db.execute(sa.select(files.c.role, files.c.logical_name, files.c.sha256, files.c.size_bytes,
        files.c.artifact_id)
        .where(files.c.package_id == stored["id"]))).mappings().all()
    require(len(rows) == len(package.sources), "retained_import_inventory_changed")
    # Shared logical leaves must not duplicate a multi-megabyte BYTEA in the
    # driver result. Check physical unique-source size before fetching it once.
    source_filter = sa.and_(blobs.c.package_id == stored["id"], blobs.c.attempt_id.is_(None))
    count, size = (await db.execute(sa.select(sa.func.count(),
        sa.func.coalesce(sa.func.sum(sa.func.octet_length(blobs.c.payload)), 0)).where(source_filter))).one()
    require(count <= 19 and size <= 16 * 1024 * 1024 + 131072, "retained_import_source_byte_limit")
    retained = {row["artifact_id"]: row for row in (await db.execute(sa.select(
        blobs.c.artifact_id, blobs.c.payload, blobs.c.artifact_projection_json).where(source_filter))).mappings()}
    require(set(retained) == {row["artifact_id"] for row in rows}, "retained_import_inventory_changed")
    for identifier, blob in retained.items():
        current = await _projection(db, "evidence_artifacts", identifier)
        require(current == json.loads(blob["artifact_projection_json"]), "retained_import_artifact_changed")
    expected = {name: (role, checksum, payload) for role, name, checksum, payload in package.sources}
    for row in rows:
        require(row["logical_name"] in expected, "retained_import_inventory_changed")
        role, checksum, payload = expected[row["logical_name"]]
        require(row["role"] == role and row["sha256"] == checksum and row["size_bytes"] == len(payload)
                and bytes(retained[row["artifact_id"]]["payload"]) == payload, "retained_import_bytes_changed")
    return rows


def _actual_composition(coordinate_bytes, formula):
    composition = composition_features({"formula_raw": formula})
    if composition["status"] != "computed":
        return False
    sites = json.loads(coordinate_bytes)["sites"]
    counts = Counter(site["element"] for site in sites)
    return all(abs(counts.get(element, 0) / len(sites) - value) <= 1e-10
               for element, value in zip(ELEMENTS, composition["values"][:len(ELEMENTS)], strict=True))


async def _pending_rows(db, *, attempt, stored, prepared, grant, actor_user_id, sources, report_bytes):
    key, attempt_id = stored["package_key"], attempt["id"]
    material_id = prepared.package.request["context"]["material_id"]
    async def artifact(role, payload, kind, schema):
        return await _artifact(db, package_id=stored["id"], package_key=key, actor_user_id=actor_user_id,
            actor_grant_id=grant["id"], payload=payload, role=role, kind=kind, schema=schema, attempt_id=attempt_id)
    coordinate_id = await artifact("coordinates", prepared.coordinate_bytes, "structure", "sclib-coordinate/1.0.0")
    report_id = await artifact("report", report_bytes, "other", "scientific-import-report/1.0.0")
    input_id = await artifact("input_manifest", canonical({"version": "scientific-import-run/1.0.0", "phase": "input",
        "request_sha256": key, "source_artifacts": [{"id": str(row["artifact_id"]), "sha256": row["sha256"],
            "role": row["role"], "logical_name": row["logical_name"]} for row in sorted(sources, key=lambda row: row["logical_name"])],
        "authority": AUTHORITY}), "run_manifest", "scientific-import-run/1.0.0")
    output_id = await artifact("output_manifest", canonical({"version": "scientific-import-run/1.0.0", "phase": "output",
        "request_sha256": key, "coordinate_artifact_id": str(coordinate_id), "report_artifact_id": str(report_id),
        "coordinate_sha256": sha(prepared.coordinate_bytes), "report_sha256": sha(report_bytes),
        "authority": AUTHORITY}), "run_manifest", "scientific-import-run/1.0.0")
    run_data = {"id": _stable(attempt_id, "run"), "run_kind": "extraction", "status": "completed",
        "code_version": stored["compiler_sha256"], "settings_schema_version": "scientific-import-run/1.0.0",
        "settings": {"request_sha256": key, "native_program_hint": "QE matdyn/q2r", "upstream_run_unresolved": True,
                     "cost_scope": "parser_worker_only", **AUTHORITY},
        "input_manifest_id": input_id, "output_manifest_id": output_id}
    run = await _add(db, "research_runs", **run_data, record_sha256=_record_hash(run_data))
    source_id = next(row["artifact_id"] for row in sources if row["role"] == "force_constants")
    conditions = {"request_sha256": key, "pressure": "not_reported", "temperature": "not_reported",
                  "magnetic_field": "not_reported", "phase": "not_reported", "phonon_treatment": "unknown",
                  "bulk_geometry_reviewed": False, "upstream_execution_attested": False}
    state = await _add(db, "material_states", id=_stable(attempt_id, "state"), material_id=material_id,
        resolution="source_scoped", condition_schema_version="scientific-import-state/1.0.0",
        pressure_status="not_reported", pressure_gpa=None, temperature_role="simulation", temperature_k=None,
        conditions=conditions, context_sha256=digest(conditions), source_artifact_id=source_id)
    structure_data = {"id": _stable(attempt_id, "structure"), "material_id": material_id, "artifact_id": coordinate_id,
        "coordinate_artifact_kind": "structure", "structure_kind": "coordinates", "source_version": key,
        "occupancy_context": {"basis": "explicit_QE_site_inventory", "occupancy": 1,
            "geometry_reviewed": False, "formula_match_basis": "atomic_fractions_only_not_phase_identity"}}
    structure = await _add(db, "structure_records", **structure_data, record_sha256=_record_hash(structure_data))
    event_data = {"id": _stable(attempt_id, "event"), "material_id": material_id, "state_id": state["id"],
        "structure_id": structure["id"], "producer_run_id": run["id"], "event_type": "extraction",
        "knowledge_origin": "Computed", "review_status": "pending", "validity_status": "pending",
        "context": {"request_sha256": key, "computed_origin_basis": "retained_native_program_file",
                    "producer_is_import_not_upstream_calculation": True, **AUTHORITY}}
    event = await _add(db, "research_events", **event_data, record_sha256=_record_hash(event_data))
    candidate = prepared.report["preflight"]["parse_result"]["property_candidates"][0]
    property_data = {"id": _stable(attempt_id, "property"), "event_id": event["id"], "property_key": "phonon_min_frequency",
        "registry_version": "rv2/1", "component_key": "bulk", "relation": "exact", "value": candidate["value"],
        "unit": "THz", "uncertainty": {"reported_uncertainty": None, "precision_basis": candidate["precision_basis"]},
        "raw": {"request_sha256": key, "source": candidate, "scope": candidate["scope"],
                "phonon_treatment": "unknown", "scientific_review": "pending"}}
    prop = await _add(db, "event_properties", **property_data, record_sha256=_record_hash(property_data))
    for row in sources:
        await _add(db, "event_evidence", id=_stable(attempt_id, "evidence", row["logical_name"]),
            event_id=event["id"], link_type="source", artifact_id=row["artifact_id"],
            locator={"logical_name": row["logical_name"], "role": row["role"], "bytes_sha256": row["sha256"],
                     "source_locator": candidate["source_locator"] if row["role"] == "frequency" else {"scope": "complete_file"}})
    for role, identifier in (("coordinates", coordinate_id), ("import_report", report_id)):
        await _add(db, "event_evidence", id=_stable(attempt_id, "evidence", role), event_id=event["id"],
            link_type="source", artifact_id=identifier, locator={"role": role, "scope": "complete_file"})
    ids = {"run": run["id"], "state": state["id"], "structure": structure["id"], "event": event["id"], "property": prop["id"]}
    tables = {"run": "research_runs", "state": "material_states", "structure": "structure_records",
              "event": "research_events", "property": "event_properties"}
    snapshots = {key: await _projection(db, tables[key], identifier) for key, identifier in ids.items()}
    return {**{key + "_id": identifier for key, identifier in ids.items()},
            "row_snapshots_json": canonical(snapshots).decode(), "row_snapshots_sha256": digest(snapshots)}


async def finish_import(db, *, actor_user_id, attempt_id, prepared, dry_run=True):
    verify_prepared(prepared)
    async with _write(db, dry_run) as operation:
        grant = await active_grant(db, actor_user_id, role="curator")
        attempt = await _row(db, _PREFIX + "attempts", attempt_id)
        require(attempt is not None, "import_attempt_unavailable")
        stored = await _row(db, _PREFIX + "packages", attempt["package_id"])
        require(stored["package_key"] == prepared.package.package_key
                and stored["request_json"].encode() == prepared.package.request_bytes, "import_attempt_input_mismatch")
        if await _terminal(db, attempt) is not None:
            result = await _dto(db, attempt, replayed=True)
        else:
            sources = await _source_inventory(db, prepared.package, stored)
            report = prepared.report
            reasons = list(report["reason_codes"])
            try:
                material = await _material(db, prepared.package.request["context"])
            except ScientificImportError:
                reasons.append("stale_material_binding")
            else:
                if prepared.coordinate_bytes is not None and not _actual_composition(prepared.coordinate_bytes, material["formula"]):
                    reasons.append("actual_material_composition_mismatch")
            reasons = sorted(set(reasons))
            report.update(status="quarantined" if reasons else "success_pending", reason_codes=reasons)
            report_bytes = canonical(report)
            links = {} if reasons else await _pending_rows(db, attempt=attempt, stored=stored,
                prepared=prepared, grant=grant, actor_user_id=actor_user_id, sources=sources, report_bytes=report_bytes)
            await _add(db, _PREFIX + "outcomes", id=_stable(attempt["id"], "outcome"), attempt_id=attempt["id"],
                actor_user_id=_id(actor_user_id), actor_grant_id=grant["id"], outcome=report["status"],
                reason_codes=reasons, import_wall_ms=prepared.import_wall_ms, import_cpu_ms=prepared.import_cpu_ms,
                report_json=report_bytes.decode(), report_sha256=sha(report_bytes), **links)
            operation["changed"] = True
            result = await _dto(db, attempt)
    return result


async def fail_import(db, *, actor_user_id, attempt_id, reason_code):
    require(type(reason_code) is str and reason_code in _FAILURES, "invalid_import_failure_code")
    async with _write(db, False) as operation:
        grant = await active_grant(db, actor_user_id, role="curator")
        attempt = await _row(db, _PREFIX + "attempts", attempt_id)
        require(attempt is not None, "import_attempt_unavailable")
        if await _terminal(db, attempt) is None:
            report = {"version": "scientific-pending-import-report/1.0.0", "status": "failed",
                "reason_codes": [reason_code], "cost_scope": "parser_worker_only",
                "actual_calculation_costs": None, "authority": AUTHORITY}
            await _add(db, _PREFIX + "outcomes", id=_stable(attempt["id"], "outcome"), attempt_id=attempt["id"],
                actor_user_id=_id(actor_user_id), actor_grant_id=grant["id"], outcome="failed", reason_codes=[reason_code],
                report_json=canonical(report).decode(), report_sha256=digest(report))
            operation["changed"] = True
        result = await _dto(db, attempt, replayed=not operation["changed"])
    return result


async def preview_import(db, *, actor_user_id, request_key, prepared):
    verify_prepared(prepared)
    async with _write(db, True):
        start = await start_import(db, actor_user_id=actor_user_id, request_key=request_key,
                                   package=prepared.package, dry_run=False)
        if start["status"] != "outcome_unknown":
            return start
        return await finish_import(db, actor_user_id=actor_user_id, attempt_id=start["attempt_id"],
                                   prepared=prepared, dry_run=False)
