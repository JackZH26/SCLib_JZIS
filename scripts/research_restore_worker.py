"""Fixed synthetic research-recovery stages; never a general restore command.

Each fresh process requires the parent's exact disposable capability before
importing any application, database, Redis or provider client. It never imports
pytest/conftest, recreates a restored schema, accepts a DSN/path from the CLI,
or changes production backup retention. All generated evidence is synthetic.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from uuid import UUID, uuid4

REPO = Path(__file__).resolve().parents[1]
API_ROOT = REPO / "api"
VERSION = "research-restore-stage/1.0.0"
DESCRIPTOR_VERSION = "synthetic-research-restore-source/1.0.0"
FIXTURE_VERSION = "sclib-research-restore-fixture/1.0.0"
AUTHORITY = {"scientific_acceptance": False, "ml_training_approved": False,
             "public_release_authorized": False}
_INVALID_SCHEMA_OBJECTS = """SELECT
    (SELECT count(*) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace
      WHERE n.nspname='public' AND NOT c.convalidated) +
    (SELECT count(*) FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
      JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname='public' AND (NOT i.indisvalid OR NOT i.indisready))"""
CHECKS = {
    "migrate": ["capability_verified", "guard_identity_verified", "alembic_head_applied", "schema_head_verified"],
    "seed": ["capability_verified", "guard_identity_verified", "synthetic_rows_seeded", "release_and_pins_verified",
             "complete_artifact_bytes_verified", "restricted_access_verified", "metadata_publication_verified",
             "index_generation_seeded", "sql_snapshot_recorded", "source_descriptor_written"],
    "verify": ["capability_verified", "guard_identity_verified", "restored_sql_snapshot_matches",
               "release_and_pins_verified", "complete_artifact_bytes_verified", "restricted_access_verified",
               "metadata_publication_verified", "index_rebuild_verified", "index_rebuild_idempotent",
               "exact_index_hydration_verified", "sql_snapshot_unchanged"],
    "source-check": ["capability_verified", "guard_identity_verified", "source_sql_snapshot_unchanged",
                     "release_and_pins_verified", "complete_artifact_bytes_verified", "source_bundle_unchanged"],
}


class WorkerError(ValueError):
    """No input, private row, credential or driver text belongs in an error."""


def require(condition):
    if not condition:
        raise WorkerError("research_restore_worker_rejected")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha(value):
    return hashlib.sha256(value).hexdigest()


class SafeParser(argparse.ArgumentParser):
    def error(self, _message):
        raise WorkerError("research_restore_worker_arguments")


def _runtime():
    # Keep this above every application/client import. The existing gate checks
    # DSNs, file identity, process/container ownership, expiry and both services.
    from test_safety import validate_test_environment
    capability = validate_test_environment()
    sys.path.insert(0, str(API_ROOT))
    from config import Settings, get_settings
    Settings.model_config = {**Settings.model_config, "env_file": None}
    get_settings.cache_clear()
    settings = get_settings()
    validate_test_environment(database_url=settings.database_url, redis_url=settings.redis_url)
    # A capability is necessary, not authority to access any other endpoint.
    allowed = {("127.0.0.1", capability.manifest[name]["port"]) for name in ("postgres", "redis")}
    def audit(event, args):
        if event == "socket.connect":
            address = args[1]
            if not isinstance(address, tuple) or tuple(address[:2]) not in allowed:
                raise WorkerError("external_network_forbidden")
    sys.addaudithook(audit)
    asyncio.run(_redis_identity(capability))
    return capability


async def _redis_identity(capability):
    # The capability/runtime gate precedes this first Redis client. Check the
    # actual instance marker too; an endpoint string alone is not identity.
    from redis.asyncio import Redis
    from test_safety import verify_redis_identity
    client = Redis.from_url(capability.redis_url, decode_responses=True,
                            socket_connect_timeout=5, socket_timeout=5)
    try:
        await verify_redis_identity(client, capability)
    finally:
        await client.aclose()


async def _engine(capability):
    from models import db as database
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool
    from test_safety import validate_test_environment, verify_postgres_identity
    # Do not use a cached engine connected under another stage's environment.
    validate_test_environment(database_url=capability.database_url, redis_url=capability.redis_url)
    engine = create_async_engine(database._to_async_dsn(capability.database_url), poolclass=NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(verify_postgres_identity, capability)
    return engine


def _migrate(capability):
    import sqlalchemy as sa
    from alembic import command
    from alembic.config import Config
    from test_safety import validate_test_environment, verify_postgres_identity
    validate_test_environment()
    engine = sa.create_engine(capability.database_url, poolclass=sa.pool.NullPool)
    try:
        with engine.connect() as connection:
            verify_postgres_identity(connection, capability)
            require(connection.scalar(sa.text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")) == 0)
        config = Config(str(API_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(API_ROOT / "alembic"))
        config.config_file_name = None  # No incidental host logger/path configuration.
        command.upgrade(config, "head")
        with engine.connect() as connection:
            verify_postgres_identity(connection, capability)
            revisions = connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalars().all()
            invalid = connection.scalar(sa.text(_INVALID_SCHEMA_OBJECTS))
            require(type(invalid) is int and invalid == 0)
        require(revisions == [_expected_revision()])
        return revisions[0]
    finally:
        engine.dispose()


def _expected_revision():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    config = Config()
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()
    require(len(heads) == 1)
    return heads[0]


async def _revision(db):
    import sqlalchemy as sa
    rows = (await db.execute(sa.text("SELECT version_num FROM alembic_version"))).scalars().all()
    require(rows == [_expected_revision()])
    await _schema_validity(db)
    return rows[0]


async def _schema_validity(db):
    """Reject invalid catalogue objects, without claiming full DDL equality."""
    import sqlalchemy as sa
    invalid = await db.scalar(sa.text(_INVALID_SCHEMA_OBJECTS))
    require(type(invalid) is int and invalid == 0)


async def sql_snapshot(db):
    """Bound full public table bytes before aggregating; no guard-schema rows."""
    import sqlalchemy as sa
    names = (await db.execute(sa.text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"))).scalars().all()
    require(0 < len(names) <= 512 and all(re.fullmatch(r"[a-z][a-z0-9_]{0,62}", name) for name in names))
    reservations = []
    total_rows = total_bytes = 0
    for name in names:
        count, size = (await db.execute(sa.text(f'SELECT count(*),coalesce(sum(octet_length(to_jsonb(t)::text)),0) FROM public."{name}" t'))).one()
        total_rows += count
        total_bytes += size
        require(total_rows <= 20000 and total_bytes <= 32 * 1024 * 1024)
        reservations.append((name, count, size))
    rows = []
    for name, count, size in reservations:
        value = await db.scalar(sa.text(f"""SELECT encode(digest(coalesce(
            jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text COLLATE "C")::text,'[]'),'sha256'),'hex')
            FROM public."{name}" t"""))
        rows.append({"table": name, "row_count": count, "bytes": size, "sha256": value})
    return {"version": "research-restore-sql-snapshot/1.0.0", "tables": rows, "sha256": _sha(_canonical(rows))}


async def _add(db, table_name, **values):
    from models.db import Base
    table = Base.metadata.tables[table_name]
    return (await db.execute(table.insert().values(**values).returning(table))).mappings().one()


async def _actors(db):
    from services import research_publication as publication
    actors, grants = {}, {}
    for role in ("admin", "curator", "reviewer", "publisher", "member", "revoked"):
        actor = uuid4()
        await _add(db, "users", id=actor, email=f"restore-{role}-{actor}@example.test",
                   name="Synthetic restore fixture account", is_active=True, email_verified=True,
                   is_admin=role == "admin", profile={"synthetic": True})
        actors[role] = str(actor)
    for role in ("curator", "reviewer", "publisher", "revoked"):
        receipt = await publication.grant_role(db, actor_user_id=actors["admin"], user_id=actors[role],
            role=role if role != "revoked" else "curator", reason_code="synthetic_restore_role", dry_run=False)
        grants[role] = receipt["id"]
    await publication.revoke_role(db, actor_user_id=actors["admin"], grant_id=grants["revoked"],
                                  reason_code="synthetic_restore_revocation", dry_run=False)
    return actors


async def seed_rows(db, source_run_id):
    """Real typed rows and exact files; deliberately not a scientific dataset."""
    from research_restore_index import seed_index
    from services import research_freeze as freeze
    from services import research_publication as publication
    from services.research_release_manifest import (
        REVIEW_VERSION,
        canonical,
        digest,
        processing_review_payload,
    )
    actors = await _actors(db)
    material_id, paper_id = "restore-material:" + source_run_id, "restore-paper:" + source_run_id
    raw = {"formula": "MgB2", "tc_kelvin": "39 K", "knowledge_origin": "Observed", "source_role": "primary",
           "result_status": "observed", "validity_status": "pending", "synthetic": True}
    await _add(db, "materials", id=material_id, formula="MgB2", formula_normalized="MgB2",
               records=[{"paper_id": paper_id, "tc_kelvin": 39, "synthetic": True}], total_papers=1, needs_review=False)
    await _add(db, "papers", id=paper_id, source="arxiv", title="Synthetic recovery fixture; not a scientific publication",
               authors=["Synthetic Fixture"], abstract="Public synthetic bibliographic fixture; not a scientific finding.",
               status="published", materials_extracted=[raw])
    work = (await _add(db, "works", canonical_title="Synthetic recovery fixture", publication_status="active"))["id"]
    await _add(db, "paper_work_map", paper_id=paper_id, work_id=work, review_status="accepted", match_method="manual")
    artifact_bytes = {}
    async def artifact(kind, document, *, schema="restore-synthetic/1", metadata=None):
        payload = canonical(document)
        sha = _sha(payload)
        artifact_bytes[sha] = payload
        return (await _add(db, "evidence_artifacts", kind=kind, schema_version=schema,
            source="synthetic-recovery-fixture", source_version=FIXTURE_VERSION,
            record_sha256=digest(document), bytes_sha256=sha, hash_status="verified", access="restricted",
            metadata={"synthetic": True, **(metadata or {})}))["id"]
    source = await artifact("literature_locator", {"synthetic": True, "raw_text": "PRIVATE_RESTORE_SYNTHETIC_SOURCE", "page": 1})
    coords = {"version": "sclib-coordinate/1.0.0", "boundary_conditions": "bulk_3d_periodic",
        "cell_angstrom": [[3.0, 0.0, 0.0], [0.0, 3.0, 0.0], [0.0, 0.0, 3.0]],
        "sites": [{"element": "Mg", "fractional": [0.0, 0.0, 0.0], "occupancy": 1.0},
                  {"element": "B", "fractional": [0.3, 0.3, 0.3], "occupancy": 1.0},
                  {"element": "B", "fractional": [0.6, 0.6, 0.6], "occupancy": 1.0}]}
    coordinate_artifact = await artifact("structure", coords, schema="sclib-coordinate/1.0.0")
    run_input = await artifact("run_manifest", {"synthetic": True, "stage": "input", "formula": "MgB2",
        "coordinate_sha256": _sha(canonical(coords)), "upstream_execution_attested": False})
    run_output = await artifact("run_manifest", {"synthetic": True, "stage": "output",
        "sampled_phonon_minimum": {"value": -0.0299792458, "unit": "THz"}, "upstream_execution_attested": False})
    policies = [await artifact("policy", {"synthetic": True, "role": role, "version": FIXTURE_VERSION})
                for role in ("task", "property_registry")]
    sample = (await _add(db, "research_samples", material_id=material_id, work_id=work,
        sample_label="Synthetic recovery sample", source_artifact_id=source, preparation={"synthetic": True}))["id"]
    state = (await _add(db, "material_states", material_id=material_id, sample_id=sample, resolution="source_scoped",
        condition_schema_version="restore-synthetic/1", pressure_status="not_reported", temperature_role="unknown",
        conditions={"synthetic": True}, context_sha256=digest({"synthetic": True, "pressure": None, "temperature": None}),
        source_artifact_id=source))["id"]
    structure = (await _add(db, "structure_records", material_id=material_id, artifact_id=coordinate_artifact,
        coordinate_artifact_kind="structure", structure_kind="coordinates", source_version=FIXTURE_VERSION,
        occupancy_context={"synthetic": True}, record_sha256=digest(coords)))["id"]
    run = (await _add(db, "research_runs", run_kind="dfpt", status="planned", code_version="synthetic-not-executed/1",
        settings_schema_version="restore-synthetic/1", settings={"synthetic": True, "actual_calculation_executed": False},
        input_manifest_id=run_input, output_manifest_id=run_output,
        record_sha256=digest({"synthetic": True, "fixture_run": source_run_id})))["id"]
    measurement = (await _add(db, "research_events", material_id=material_id, state_id=state,
        event_type="measurement", knowledge_origin="Observed", record_sha256=digest({"synthetic": True, "event": "measurement"})))["id"]
    calculation = (await _add(db, "research_events", material_id=material_id, state_id=state,
        structure_id=structure, producer_run_id=run, event_type="calculation", knowledge_origin="Computed",
        record_sha256=digest({"synthetic": True, "event": "calculation_not_executed"})))["id"]
    prop = (await _add(db, "event_properties", event_id=calculation, property_key="phonon_min_frequency",
        relation="exact", value=-0.0299792458, unit="THz", raw={"synthetic": True},
        record_sha256=digest({"synthetic": True, "minimum": -0.0299792458})))["id"]
    await _add(db, "event_evidence", event_id=measurement, link_type="source", artifact_id=source, locator={"page": 1})
    await _add(db, "event_evidence", event_id=calculation, link_type="source", artifact_id=run_output, locator={"stage": "synthetic_output"})
    snapshot = (await _add(db, "source_snapshots", dataset_version="synthetic-" + source_run_id,
        schema_version="restore-synthetic/1", material_count=1, paper_count=1))["id"]
    claim = (await _add(db, "material_claims", material_id=material_id, paper_id=paper_id, work_id=work,
        source_snapshot_id=snapshot, event_id=measurement, result_key="synthetic-tc", interpretation_revision=1,
        source_record_hash=digest(raw), value_relation="exact", value_kelvin=39, result_status="observed",
        source_kind="table", extractor_version="restore-synthetic/1", raw_record=raw))["id"]
    member = (await _add(db, "snapshot_event_memberships", snapshot_id=snapshot, event_id=measurement,
        event_revision=1, source_occurrence_key="synthetic:table:1", locator={"table": 1},
        source_record_sha256=digest(raw), result_manifest_sha256=digest({"synthetic": True, "claim": str(claim)})))["id"]
    dataset = (await _add(db, "ml_dataset_snapshots", source_snapshot_id=snapshot, name="Synthetic restore capsule",
        version=source_run_id, label_policy_version="restore-synthetic/1", feature_schema_version="restore-synthetic/1",
        split_ruleset_version="restore-synthetic/1", row_count=1))["id"]
    example = (await _add(db, "ml_examples", dataset_snapshot_id=dataset, example_key="synthetic-one",
        claim_id=claim, material_id=material_id, work_id=work, split="train", task_type="tc_regression",
        label_data={"synthetic_pending": True}, work_group=str(work), material_group=material_id,
        duplicate_group=source_run_id, assignment_hash=digest({"synthetic": True, "split": "train"})))["id"]
    await _add(db, "ml_example_inputs", example_id=example, input_kind="property", input_event_id=calculation,
        input_property_id=prop, feature_key="synthetic_phonon_minimum", matching_policy_version="restore-synthetic/1",
        record_sha256=digest({"synthetic": True, "property": str(prop)}))
    index = await seed_index(db, paper_id=paper_id, material_id=material_id, claim_id=claim, raw_record=raw)
    args = {"dataset_id": dataset, "policy_artifact_ids": policies,
            "source_roots": [{"table": "snapshot_event_memberships", "row_id": str(member)}], "artifact_bytes": artifact_bytes}
    preview = await freeze.preview_research_release(db, **args)
    review_document = processing_review_payload(preview["manifest"])
    review_id = await artifact("review", review_document, schema=REVIEW_VERSION,
                               metadata={"shadow_freeze_review": review_document})
    release = await freeze.freeze_research_release(db, **{**args, "artifact_bytes": artifact_bytes},
                                                   review_artifact_id=review_id, dry_run=False)
    for row in release["manifest"]["rows"]:
        await publication.decide_permission(db, actor_user_id=actors["reviewer"], release_id=release["release_id"],
            table_name=row["table"], row_id=row["row_id"], row_sha256=row["row_sha256"], decision="allow",
            license_code="permission-on-file", basis_code="synthetic_metadata_only",
            reason_code="synthetic_recovery_disclosure", dry_run=False)
    proposal = await publication.propose_publication(db, actor_user_id=actors["curator"], release_id=release["release_id"],
        expected_capsule_sha256=release["manifest_sha256"], artifact_bytes=artifact_bytes, dry_run=False)
    disclosure = await publication.review_publication(db, actor_user_id=actors["reviewer"], proposal_id=proposal["id"],
        expected_payload_sha256=proposal["payload_sha256"], disclosure_approved=True,
        reason_code="synthetic_metadata_review", dry_run=False)
    await publication.publication_action(db, actor_user_id=actors["publisher"], proposal_id=proposal["id"],
        review_id=disclosure["id"], expected_payload_sha256=proposal["payload_sha256"], kind="publish",
        reason_code="synthetic_metadata_publication", dry_run=False)
    return {"release": release, "artifact_bytes": artifact_bytes, "actors": actors, "index": index,
            "access_targets": {"claim_id": str(claim), "work_id": str(work), "dataset_id": str(dataset),
                               "publication_proposal_id": str(proposal["id"])}}


async def verify_access(db, descriptor):
    """Exercise actual authenticated API and live grants, no dependency mocks."""
    from httpx import ASGITransport, AsyncClient
    from main import app
    from services.auth_service import create_access_token
    from services.research_access import ResearchAccessDenied, require_research_operator
    from services.research_publication import admitted_publication
    actors, targets = descriptor["actors"], descriptor["access_targets"]
    for role in ("admin", "member", "revoked"):
        try:
            await require_research_operator(db, UUID(actors[role]))
        except ResearchAccessDenied:
            pass
        else:
            raise WorkerError("synthetic_role_denial_missing")
    for role in ("curator", "reviewer", "publisher"):
        await require_research_operator(db, UUID(actors[role]))
    paths = [f"/v1/claims/{targets['claim_id']}", f"/v1/works/{targets['work_id']}",
             f"/v1/ml/snapshots/{targets['dataset_id']}/manifest"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://restore.invalid") as client:
        for role in (None, "admin", "member", "revoked", "curator", "reviewer", "publisher"):
            headers = {}
            if role is not None:
                token, _ = create_access_token(UUID(actors[role]), 0)
                headers = {"Authorization": "Bearer " + token}
            for path in paths:
                response = await client.get(path, headers=headers)
                expected = 401 if role is None else 403 if role in {"admin", "member", "revoked"} else 200
                require(response.status_code == expected)
                require(response.headers.get("cache-control") == "private, no-store")
                if expected != 200:
                    require(b"PRIVATE_RESTORE_SYNTHETIC_SOURCE" not in response.content)
        proposal = await admitted_publication(db, targets["publication_proposal_id"])
        public = await client.get(f"/v1/ml/releases/{targets['publication_proposal_id']}/manifest")
        require(public.status_code == 200 and public.json() == proposal["public_payload"])
        require(public.json()["scientific_acceptance"] is False and public.json()["ml_training_approved"] is False)
        require(all(value not in public.content for value in (b"PRIVATE_RESTORE_SYNTHETIC_SOURCE", b"MgB2", b"39 K")))


def _measurements(descriptor=None):
    rows = descriptor["sql_snapshot"]["tables"] if descriptor else []
    files = descriptor["artifact_files"] if descriptor else []
    return {"sql_tables": len(rows), "sql_rows": sum(row["row_count"] for row in rows),
            "artifact_count": len(files), "artifact_bytes": sum(row["size_bytes"] for row in files),
            "index_members": descriptor["index"]["member_count"] if descriptor else 0}


async def _seed(capability):
    from research_restore_contract import (
        capture_bundle,
        safe_write_new,
        validate_descriptor,
    )
    from services.research_freeze import inspect_research_release
    from sqlalchemy.ext.asyncio import AsyncSession
    engine = await _engine(capability)
    root = Path(capability.manifest["root"])
    try:
        async with AsyncSession(engine.execution_options(isolation_level="SERIALIZABLE")) as db:
            async with db.begin():
                import sqlalchemy as sa
                await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
                await db.execute(sa.text("SET LOCAL statement_timeout='10000ms'"))
                revision = await _revision(db)
                require(await db.scalar(sa.text("SELECT count(*) FROM research_releases")) == 0)
                seeded = await seed_rows(db, capability.run_id)
                release = seeded["release"]
                await inspect_research_release(db, release_id=release["release_id"],
                    expected_manifest_sha256=release["manifest_sha256"], artifact_bytes=seeded["artifact_bytes"])
            # Separate fresh read snapshot and real HTTP sessions after commit.
            async with db.begin():
                await db.execute(sa.text("SET TRANSACTION READ ONLY"))
                await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
                await db.execute(sa.text("SET LOCAL statement_timeout='10000ms'"))
                await verify_access(db, seeded)
                snapshot = await sql_snapshot(db)
        safe_write_new(root, "research-bundle/manifest.json", _canonical(release["manifest"]))
        for sha, payload in sorted(seeded["artifact_bytes"].items()):
            safe_write_new(root, "research-bundle/artifacts/" + sha, payload)
        bundle = capture_bundle(root, expected_manifest_sha256=release["manifest_sha256"])
        descriptor = {"version": DESCRIPTOR_VERSION, "fixture_version": FIXTURE_VERSION,
            "source_run_id": capability.run_id, "schema_revision": revision,
            "release_id": release["release_id"], "manifest_sha256": release["manifest_sha256"],
            "bundle_sha256": bundle["bundle_sha256"],
            "artifact_files": [{"sha256": sha, "size_bytes": len(value)} for sha, value in sorted(seeded["artifact_bytes"].items())],
            "sql_snapshot": snapshot, "actors": seeded["actors"], "access_targets": seeded["access_targets"],
            "index": seeded["index"], "authority": dict(AUTHORITY)}
        validate_descriptor(descriptor)
        safe_write_new(root, "source-descriptor.json", _canonical(descriptor))
        return revision, descriptor
    finally:
        await engine.dispose()


async def _verify(capability, *, source_check=False):
    import sqlalchemy as sa
    from research_restore_contract import capture_bundle, read_source_descriptor
    from research_restore_index import verify_index
    from services.research_freeze import inspect_research_release
    from sqlalchemy.ext.asyncio import AsyncSession
    root = Path(capability.manifest["root"])
    expected_descriptor = os.environ.get("SCLIB_RESTORE_EXPECTED_DESCRIPTOR_SHA256")
    require(type(expected_descriptor) is str and re.fullmatch(r"[0-9a-f]{64}", expected_descriptor))
    descriptor = read_source_descriptor(root, expected_descriptor_sha256=expected_descriptor)
    require((descriptor["source_run_id"] == capability.run_id) is source_check)
    bundle = capture_bundle(root, expected_manifest_sha256=descriptor["manifest_sha256"])
    require(bundle["bundle_sha256"] == descriptor["bundle_sha256"])
    # The descriptor reader has already checked fixed safe leaf names/inventory.
    # Actual artifact payload capture uses the contract's retained byte API.
    from research_restore_contract import read_artifact_bytes
    artifact_bytes = read_artifact_bytes(root, expected_manifest_sha256=descriptor["manifest_sha256"])
    engine = await _engine(capability)
    try:
        async with AsyncSession(engine.execution_options(isolation_level="REPEATABLE READ")) as db:
            async with db.begin():
                await db.execute(sa.text("SET TRANSACTION READ ONLY"))
                await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
                await db.execute(sa.text("SET LOCAL statement_timeout='10000ms'"))
                revision = await _revision(db)
                require(revision == descriptor["schema_revision"])
                before = await sql_snapshot(db)
                require(before == descriptor["sql_snapshot"])
                inspected = await inspect_research_release(db, release_id=descriptor["release_id"],
                    expected_manifest_sha256=descriptor["manifest_sha256"], artifact_bytes=artifact_bytes)
                require(inspected["manifest_sha256"] == descriptor["manifest_sha256"])
                if not source_check:
                    await verify_access(db, descriptor)
                    index_check = await verify_index(db, descriptor["index"])
                else:
                    index_check = None
                require(await sql_snapshot(db) == before)
        final = capture_bundle(root, expected_manifest_sha256=descriptor["manifest_sha256"])
        require(final == bundle)
        return revision, descriptor, index_check
    finally:
        await engine.dispose()


def main(argv=None):
    try:
        capability = _runtime()
        parser = SafeParser(description="Fixed disposable synthetic research-recovery worker", allow_abbrev=False)
        parser.add_argument("--stage", choices=tuple(CHECKS), required=True)
        args = parser.parse_args(argv)
        index_check = None
        if args.stage == "migrate":
            revision, descriptor = _migrate(capability), None
        elif args.stage == "seed":
            revision, descriptor = asyncio.run(_seed(capability))
        else:
            revision, descriptor, index_check = asyncio.run(_verify(capability, source_check=args.stage == "source-check"))
        from research_restore_contract import safe_write_new, validate_stage
        result = {"version": VERSION, "stage": args.stage, "run_id": capability.run_id, "status": "passed",
            "schema_revision": revision, "descriptor_sha256": _sha(_canonical(descriptor)) if descriptor else None,
            "checks": list(CHECKS[args.stage]), "measurements": _measurements(descriptor),
            "index_check": index_check,
            "sql_snapshot_sha256": descriptor["sql_snapshot"]["sha256"] if descriptor else None}
        validate_stage(result, args.stage)
        safe_write_new(Path(capability.manifest["root"]), "stage-" + args.stage + ".json", _canonical(result))
        print(_canonical(result).decode("utf-8"))
        return 0
    except Exception:
        print("Research restore worker refused: stage_failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
