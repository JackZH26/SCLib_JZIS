"""Small, synthetic, source-linked vector restore rehearsal.

This module has no import-time database/client initialization. Only the guarded
restore worker calls the async functions. Source seeding uses real 0060/0061/
0062 rows with *synthetic* completion response fixtures, never an embedding
provider. Target recovery reads old retained float32 bytes; it does not stage a
replacement generation or refresh an activation/validation ledger.
"""
from __future__ import annotations

import hashlib
import json
import re
from uuid import UUID, uuid4

VERSION = "research-restore-index/1.0.0"
REPORT_VERSION = "research-restore-index-check/1.0.0"
MEMBER_COUNT = 2
MAX_DESCRIPTOR_BYTES = 4096
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:+@-]{0,99}\Z")
_HASH_FIELDS = {
    "claim_record_sha256", "raw_record_sha256", "pin_sha256",
    "member_manifest_sha256", "member_inventory_sha256", "hydration_sha256",
}
_UUID_FIELDS = {"generation_id", "activation_event_id", "validation_id", "claim_id"}
_DESCRIPTOR_FIELDS = _HASH_FIELDS | _UUID_FIELDS | {
    "version", "logical_index", "paper_id", "material_id", "member_count",
}
_REPORT_COUNTS = {
    "member_count": 2, "vector_bytes": 6144, "initial_index_count": 0,
    "restored_index_count": 2, "initial_upsert_count": 2, "replay_upsert_count": 0,
    "replay_already_present_count": 2, "missing_count": 0, "mismatched_count": 0,
    "orphan_count": 0,
}
_REPORT_TRUE = {
    "exact_generation_verified", "full_inventory_observed", "declared_members_complete",
    "repeat_recovery_idempotent", "database_unchanged",
}
_REPORT_FALSE = {
    "scientific_acceptance", "ml_training_approved", "public_release_authorized",
    "provider_io_performed", "external_production_vector_restore_verified",
}
_REPORT_HASHES = {"member_manifest_sha256", "member_inventory_sha256", "hydration_sha256"}


class RestoreIndexError(ValueError):
    """Static, private-body-free refusal of an incomplete restore check."""


def _require(condition):
    if not condition:
        raise RestoreIndexError("restore_index_verification_failed")


def _canonical(value):
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise RestoreIndexError("restore_index_invalid_json") from None


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _uuid(value):
    _require(type(value) is str)
    try:
        _require(str(UUID(value)) == value)
    except (ValueError, AttributeError):
        raise RestoreIndexError("restore_index_invalid_uuid") from None


def validate_descriptor(value):
    """Closed private descriptor; pure stdlib validation, detached return value."""
    _require(type(value) is dict and set(value) == _DESCRIPTOR_FIELDS)
    _require(value["version"] == VERSION)
    for field in _UUID_FIELDS:
        _uuid(value[field])
    for field in _HASH_FIELDS:
        _require(type(value[field]) is str and _HASH.fullmatch(value[field]) is not None)
    for field in ("paper_id", "material_id"):
        _require(type(value[field]) is str and _ID.fullmatch(value[field]) is not None)
    _require(value["logical_index"] == "restore-drill-" + UUID(value["generation_id"]).hex)
    _require(type(value["member_count"]) is int and value["member_count"] == MEMBER_COUNT)
    _require(len(_canonical(value)) <= MAX_DESCRIPTOR_BYTES)
    return dict(value)


def validate_report(value):
    """Only measured successful bounded checks, never inferred zero/approval."""
    _require(type(value) is dict and set(value) == (
        {"version"} | set(_REPORT_COUNTS) | _REPORT_TRUE | _REPORT_FALSE | _REPORT_HASHES))
    _require(value["version"] == REPORT_VERSION)
    for key, expected in _REPORT_COUNTS.items():
        _require(type(value[key]) is int and value[key] == expected)
    for key in _REPORT_TRUE:
        _require(value[key] is True)
    for key in _REPORT_FALSE:
        _require(value[key] is False)
    for key in _REPORT_HASHES:
        _require(type(value[key]) is str and _HASH.fullmatch(value[key]) is not None)
    _require(len(_canonical(value)) <= MAX_DESCRIPTOR_BYTES)
    return dict(value)


def _resource(generation_id):
    """No user-supplied cloud address can reach adapter selection."""
    _uuid(generation_id)
    identifier = UUID(generation_id).hex
    prefix = "projects/synthetic-restore-rehearsal/locations/isolated-local/"
    return {"backend": "disposable", "project": "synthetic-restore-rehearsal",
            "location": "isolated-local", "index_resource": prefix + "indexes/restore-index-" + identifier,
            "endpoint_resource": prefix + "indexEndpoints/restore-endpoint-" + identifier,
            "deployed_index_id": "restore_" + identifier,
            "distance_measure": "COSINE_DISTANCE", "feature_norm": "NONE"}


def member_inventory_sha256(members):
    """Bind full retained snapshots and every identity, plus actual vector bytes."""
    _require(type(members) is list and len(members) == MEMBER_COUNT)
    copied = []
    for member in members:
        _require(type(member) is dict and type(member.get("vector_id")) is str)
        vector = member.get("vector_bytes")
        _require(type(vector) is bytes and len(vector) == 3072)
        row = {key: value for key, value in member.items() if key != "vector_bytes"}
        row["retained_vector_bytes_sha256"] = hashlib.sha256(vector).hexdigest()
        _require(row["retained_vector_bytes_sha256"] == row.get("vector_sha256"))
        copied.append(row)
    _require(len({row["vector_id"] for row in copied}) == MEMBER_COUNT)
    payload = sorted(copied, key=lambda row: row["vector_id"])
    _require(len(_canonical(payload)) <= 256 * 1024)
    return _digest(payload)


async def _session(db, *, readonly):
    import sqlalchemy as sa

    _require(not (db.new or db.dirty or db.deleted))
    _require(await db.scalar(sa.text("SHOW transaction_isolation")) in {"repeatable read", "serializable"})
    _require(await db.scalar(sa.text("SHOW transaction_read_only")) == ("on" if readonly else "off"))
    _require(await db.scalar(sa.text("SHOW TimeZone")) == "UTC")
    timeout = await db.scalar(sa.text("SELECT current_setting('statement_timeout')::interval <= interval '10 seconds' "
                                      "AND current_setting('statement_timeout')::interval > interval '0 seconds'"))
    _require(timeout is True)


async def _claim(db, *, paper_id, material_id, claim_id, raw_record=None):
    import sqlalchemy as sa

    params = {"claim": UUID(claim_id), "paper": paper_id, "material": material_id}
    bounded = await db.scalar(sa.text("""SELECT octet_length(to_jsonb(c)::text)+
        octet_length(p.materials_extracted::text) FROM material_claims c JOIN papers p ON p.id=c.paper_id
        WHERE c.id=:claim AND c.paper_id=:paper AND c.material_id=:material"""), params)
    _require(type(bounded) is int and bounded <= 65536)
    row = (await db.execute(sa.text("""SELECT to_jsonb(c)::text AS row_text,c.raw_record,
        c.validity_status,p.materials_extracted FROM material_claims c JOIN papers p ON p.id=c.paper_id
        WHERE c.id=:claim AND c.paper_id=:paper AND c.material_id=:material"""), params)).mappings().one()
    actual = row["raw_record"]
    _require(type(actual) is dict and actual.get("synthetic") is True and row["validity_status"] == "pending")
    _require(type(row["materials_extracted"]) is list and any(
        _canonical(item) == _canonical(actual) for item in row["materials_extracted"]))
    if raw_record is not None:
        _require(_canonical(actual) == _canonical(raw_record))
    _require(len(_canonical(actual)) <= 2048)
    return actual, hashlib.sha256(row["row_text"].encode("utf-8")).hexdigest()


async def _hydration_sha256(db, pin, members, *, paper_id, raw_record):
    from services.index_retrieval import hydrate, resolve_evidence

    identifiers = [member["vector_id"] for member in members]
    hydrated = await hydrate(db, pin, identifiers)
    _require(set(hydrated) == set(identifiers))
    evidence = await resolve_evidence(db, list(hydrated.values()))
    summaries = []
    for identifier in sorted(hydrated):
        chunk = hydrated[identifier]
        descriptor = evidence[identifier]
        _require(chunk.id == identifier and chunk.paper_id == paper_id and chunk.paper.id == paper_id)
        _require(chunk.generation_pin == pin and chunk.member["generation_id"] == pin["generation_id"])
        _require(_canonical(chunk.materials_mentioned) == _canonical([raw_record]))
        _require(descriptor["currentness"] == "current" and descriptor["chunk_kind"] == "derived_fact")
        _require(descriptor["support_eligible"] is False and descriptor["scientific_acceptance"] is False)
        summaries.append({"vector_id": identifier, "paper_id": chunk.paper_id,
            "text_sha256": hashlib.sha256(chunk.text.encode("utf-8")).hexdigest(),
            "title": chunk.title, "section": chunk.section, "chunk_index": chunk.chunk_index,
            "materials_mentioned": chunk.materials_mentioned, "has_equation": chunk.has_equation,
            "has_table": chunk.has_table, "evidence": descriptor})
    return _digest(summaries)


async def _ledger(db, generation_id):
    """Measured bounded SQL ledger bytes, not a claim that all DB tables were scanned."""
    import sqlalchemy as sa

    result = {}
    conditions = {
        "index_generations": "id=:generation",
        "index_generation_members": "generation_id=:generation",
        "index_generation_validations": "generation_id=:generation",
        "index_activation_events": "generation_id=:generation",
        "index_active_pointer": "generation_id=:generation",
        "index_generation_epoch": "true",
        "research_integrity_epoch": "true",
        "source_lifecycle_epoch": "true",
    }
    for table, condition in conditions.items():
        params = {"generation": UUID(generation_id)}
        count, size = (await db.execute(sa.text(f"SELECT count(*),coalesce(sum(octet_length(to_jsonb(r)::text)),0) "
            f"FROM {table} r WHERE {condition}"), params)).one()
        _require(count <= 20 and size <= 256 * 1024)
        rows = (await db.execute(sa.text(f"SELECT to_jsonb(r)::text FROM {table} r WHERE {condition} "
                                        "ORDER BY to_jsonb(r)::text COLLATE \"C\""), params)).scalars().all()
        result[table] = {"count": count, "sha256": _digest(rows)}
    return result


async def seed_index(db, *, paper_id, material_id, claim_id, raw_record):
    """Actual synthetic SQL+disposable publication; caller alone commits source DB."""
    import sqlalchemy as sa
    from models.db import Base
    from services.embedding_contract import validate_embedding_response
    from services.embedding_receipts import append_embedding_receipt
    from services.index_generations import (
        load_active_generation,
        load_generation_members,
    )
    from services.index_operations import run_operation
    from services.index_vector_adapter import register_disposable
    from services.rag_evidence import (
        CURRENT_FACT_RENDERER_VERSION,
        register_chunk_evidence,
    )

    claim_id = str(claim_id)
    _uuid(claim_id)
    _require(all(type(value) is str and _ID.fullmatch(value) for value in (paper_id, material_id)))
    await _session(db, readonly=False)
    raw, claim_sha = await _claim(db, paper_id=paper_id, material_id=material_id, claim_id=claim_id, raw_record=raw_record)
    generation_id = str(uuid4())
    logical_index = "restore-drill-" + UUID(generation_id).hex
    resource = _resource(generation_id)
    register_disposable(resource)
    items = []
    for number in range(MEMBER_COUNT):
        chunk_id = "restore-chunk-" + UUID(generation_id).hex + "-" + str(number)
        text = "Synthetic pending restore fixture, fragment " + str(number + 1) + ": " + _canonical(raw).decode("utf-8")
        await db.execute(sa.insert(Base.metadata.tables["chunks"]).values(id=chunk_id, paper_id=paper_id,
            title="Synthetic pending restore result", section="Synthetic results", chunk_index=number,
            text=text, materials_mentioned=[raw], has_equation=False, has_table=False))
        await register_chunk_evidence(db, chunk_id=chunk_id, candidate={
            "version": "rag-evidence/1.0.0", "chunk_kind": "derived_fact", "parent_record": raw,
            "extraction_version": "synthetic-restore/1.0.0", "rendering_version": CURRENT_FACT_RENDERER_VERSION,
        }, dry_run=False)
        # Explicit synthetic completion fixture. No provider was invoked; this
        # exercises retained transport bytes, not embedding quality or billing.
        vector, metadata = validate_embedding_response([text], {"embeddings": [{
            "values": [0.125 + number / 1024] * 768,
            "statistics": {"truncated": False, "token_count": 1},
        }]}, model="text-embedding-005", dimension=768, task_type="RETRIEVAL_DOCUMENT",
            local_counts=[len(text.encode("utf-8"))], local_count_method="utf8-bytes/1",
            local_input_limit=8192, local_request_limit=8192)[0]
        receipt = await append_embedding_receipt(db, chunk_id=chunk_id, vector=vector, receipt=metadata, dry_run=False)
        items.append({"chunk_id": chunk_id, "receipt_id": receipt["receipt_id"], "vector": vector,
                      "parser_version": "synthetic-restore/1.0.0"})
    await run_operation(db, {"command": "stage", "generation_id": generation_id,
        "logical_index": logical_index, "resource": resource, "items": items}, apply=True)
    publication = await run_operation(db, {"command": "publish", "generation_id": generation_id}, apply=True)
    _require(publication["provider_io_performed"] is False and publication["publication"]["acknowledged_count"] == MEMBER_COUNT)
    observed = await run_operation(db, {"command": "observe", "generation_id": generation_id}, apply=True, read_remote=True)
    _require(observed["provider_io_performed"] is False and observed["validation"]["outcome"] == "validated")
    validation_id = observed["validation"]["validation_id"]
    await run_operation(db, {"command": "activate", "generation_id": generation_id, "validation_id": validation_id,
        "expected_event_id": None, "idempotency_key": "synthetic-restore-bootstrap", "action": "promote"}, apply=True)
    pin = await load_active_generation(db, logical_index=logical_index)
    _require(pin is not None and pin["resource"] == resource)
    members = await load_generation_members(db, generation_id=generation_id)
    hydration = await _hydration_sha256(db, pin, members, paper_id=paper_id, raw_record=raw)
    return validate_descriptor({"version": VERSION, "logical_index": logical_index, "generation_id": generation_id,
        "activation_event_id": pin["activation_event_id"], "validation_id": validation_id,
        "paper_id": paper_id, "material_id": material_id, "claim_id": claim_id,
        "claim_record_sha256": claim_sha, "raw_record_sha256": _digest(raw), "pin_sha256": _digest(pin),
        "member_manifest_sha256": pin["manifest_sha256"], "member_inventory_sha256": member_inventory_sha256(members),
        "hydration_sha256": hydration, "member_count": MEMBER_COUNT})


async def verify_index(db, descriptor):
    """Rebuild *only* an independent local index, twice; restored SQL is read-only.

    The second publication tests exact upsert idempotency within this recovery.
    A later call starts another empty isolated index, but never replaces SQL
    generations or appends new validation/activation observations.
    """
    descriptor = validate_descriptor(descriptor)  # before DB/adapter imports
    import sqlalchemy as sa
    from services import index_vector_adapter as vectors
    from services.index_generations import (
        load_active_generation,
        load_generation_members,
        manifest_sha256,
    )

    await _session(db, readonly=True)
    before = await _ledger(db, descriptor["generation_id"])
    pin = await load_active_generation(db, logical_index=descriptor["logical_index"])
    _require(pin is not None and pin["resource"] == _resource(descriptor["generation_id"]))
    _require(pin["generation_id"] == descriptor["generation_id"] and
             pin["activation_event_id"] == descriptor["activation_event_id"] and _digest(pin) == descriptor["pin_sha256"])
    validation = await db.scalar(sa.text("""SELECT v.outcome='validated' AND
        v.record_sha256=public.sclib_index_record_hash_v1(to_jsonb(v))
        FROM index_activation_events e JOIN index_generation_validations v ON v.id=e.validation_id
        WHERE e.id=:event AND v.id=:validation AND v.generation_id=:generation"""), {
            "event": UUID(descriptor["activation_event_id"]), "validation": UUID(descriptor["validation_id"]),
            "generation": UUID(descriptor["generation_id"])})
    _require(validation is True)  # Historical validation, not fresh availability.
    raw, claim_sha = await _claim(db, **{key: descriptor[key] for key in ("paper_id", "material_id", "claim_id")})
    _require(claim_sha == descriptor["claim_record_sha256"] and _digest(raw) == descriptor["raw_record_sha256"])
    members = await load_generation_members(db, generation_id=descriptor["generation_id"])
    _require(member_inventory_sha256(members) == descriptor["member_inventory_sha256"])
    _require(manifest_sha256(members) == descriptor["member_manifest_sha256"] == pin["manifest_sha256"])
    adapter = vectors.register_disposable(pin["resource"], vectors.DisposableIndex())
    initial_count = len(adapter.points)
    _require(initial_count == 0)
    first = vectors.publish(pin, members)
    observation = vectors.observe(pin, members)
    reconciliation = vectors.repair_plan(pin, members, observation)
    second = vectors.publish(pin, members)
    repeated = vectors.observe(pin, members)
    _require(observation["vectors"] == repeated["vectors"])
    hydration = await _hydration_sha256(db, pin, members, paper_id=descriptor["paper_id"], raw_record=raw)
    _require(hydration == descriptor["hydration_sha256"])
    _require(await _ledger(db, descriptor["generation_id"]) == before)
    return validate_report({"version": REPORT_VERSION, "member_count": len(members),
        "vector_bytes": sum(len(member["vector_bytes"]) for member in members),
        "initial_index_count": initial_count, "restored_index_count": len(adapter.points),
        "initial_upsert_count": first["acknowledged_count"], "replay_upsert_count": second["acknowledged_count"],
        "replay_already_present_count": second["already_present_count"],
        "missing_count": len(reconciliation["missing_ids"]), "mismatched_count": len(reconciliation["hash_mismatch_ids"]),
        "orphan_count": len(reconciliation["observed_orphan_ids"]),
        "member_manifest_sha256": pin["manifest_sha256"], "member_inventory_sha256": member_inventory_sha256(members),
        "hydration_sha256": hydration, "exact_generation_verified": True,
        "full_inventory_observed": observation["full_inventory_observed"],
        "declared_members_complete": reconciliation["declared_members_complete"],
        "repeat_recovery_idempotent": True, "database_unchanged": True,
        **{key: False for key in _REPORT_FALSE}})
