"""Bounded private index staging/CAS, never source permission or science approval.

No provider I/O or outer commit. Immutable members retain exact historical
hydration and float32 vector bytes; current source holds remain independent.
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
from copy import deepcopy
from datetime import datetime
from uuid import UUID, uuid5

import sqlalchemy as sa

from models.db import Base
from models.index_generations_v1 import PROFILE
from services.embedding_contract import (
    LOCAL_DOCUMENT_COUNT_METHOD,
    validate_embedding_provenance,
    validate_vector,
)
from services.embedding_receipts import _document_encoder, _document_token_count
from services.source_lifecycle import resolve_paper_lifecycle
from services.source_visibility import source_visibility

MAX_MEMBERS = 1000
MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
NAMESPACE = UUID("12cff404-58fc-4ef4-9926-e7f14f16af62")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_VECTOR_ID = re.compile(r"[A-Za-z0-9_-]{1,200}\Z")
_PARSER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}\Z")
_RESOURCE_KEYS = {"backend", "project", "location", "index_resource", "endpoint_resource", "deployed_index_id",
                  "distance_measure", "feature_norm"}


class IndexGenerationError(ValueError):
    """The bounded, exactly identified operation cannot be admitted."""


def _string(value, maximum):
    if type(value) is not str or not value.strip() or len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise IndexGenerationError("A bounded nonempty identifier is required")
    return value


def _resource(value):
    if type(value) is not dict or set(value) != _RESOURCE_KEYS:
        raise IndexGenerationError("An exact closed index resource is required")
    for item in value.values():
        _string(item, 500)
    if value["backend"] not in {"vertex-public", "disposable"} or value["distance_measure"] != "COSINE_DISTANCE" or value["feature_norm"] != "NONE":
        raise IndexGenerationError("Unsupported index backend/distance/normalization")
    return dict(value)


def vector_id_for(generation_id, chunk_revision_sha256):
    if type(chunk_revision_sha256) is not str or not _SHA.fullmatch(chunk_revision_sha256):
        raise IndexGenerationError("An exact chunk revision hash is required")
    return "ig62_" + UUID(str(generation_id)).hex + "_" + chunk_revision_sha256


def manifest_sha256(members):
    """Portable ASCII TSV manifest, exact IDs plus complete text/vector hashes."""
    if type(members) not in {list, tuple} or len(members) > MAX_MEMBERS:
        raise IndexGenerationError("Index inventory exceeds the bounded pilot scope")
    rows, identifiers = [], set()
    for member in members:
        identifier = member.get("vector_id") if type(member) is dict else None
        if type(identifier) is not str or not _VECTOR_ID.fullmatch(identifier) or identifier in identifiers:
            raise IndexGenerationError("Invalid or repeated vector identity")
        identifiers.add(identifier)
        if any(type(member.get(key)) is not str or not _SHA.fullmatch(member[key]) for key in ("content_sha256", "vector_sha256")):
            raise IndexGenerationError("Exact inventory text/vector hashes are required")
        rows.append((identifier, member["content_sha256"], member["vector_sha256"]))
    return hashlib.sha256("".join("\t".join(row) + "\n" for row in sorted(rows)).encode("ascii")).hexdigest()


def _clean(db, dry_run):
    if type(dry_run) is not bool or db.new or db.dirty or db.deleted:
        raise IndexGenerationError("A clean caller-owned session and boolean dry_run are required")


def _table(name):
    return Base.metadata.tables[name]


async def _verified_rows(db, name, *conditions):
    table = _table(name)
    digest = sa.func.sclib_index_record_hash_v1(sa.func.to_jsonb(table.table_valued()))
    rows = (await db.execute(sa.select(table, (digest == table.c.record_sha256).label("_valid")).where(*conditions))).mappings().all()
    if any(not row["_valid"] for row in rows):
        raise IndexGenerationError("Immutable index record hash mismatch")
    return [{key: value for key, value in row.items() if key != "_valid"} for row in rows]


async def _generation(db, identifier):
    rows = await _verified_rows(db, "index_generations", _table("index_generations").c.id == UUID(str(identifier)))
    return rows[0] if rows else None


def _pin(generation, event=None):
    return {"generation_id": str(generation["id"]), "activation_event_id": str(event) if event else None,
            "profile": deepcopy(generation["profile"]), "resource": deepcopy(generation["resource"]),
            "manifest_sha256": generation["manifest_sha256"]}


def _public_member(row):
    return {key: str(value) if isinstance(value, UUID) else bytes(value) if isinstance(value, (bytes, memoryview)) else deepcopy(value)
            for key, value in row.items() if key != "created_at"}


async def load_generation_members(db, *, generation_id, vector_ids=None, paper_id=None):
    """Read retained bytes, independent of current Chunk. No policy approval."""
    identifier = UUID(str(generation_id))
    table = _table("index_generation_members")
    conditions = [table.c.generation_id == identifier]
    if vector_ids is not None:
        if type(vector_ids) not in {list, tuple} or len(vector_ids) > MAX_MEMBERS or len(set(vector_ids)) != len(vector_ids):
            raise IndexGenerationError("Invalid bounded vector selection")
        for value in vector_ids:
            _string(value, 200)
        conditions.append(table.c.vector_id.in_(vector_ids))
    if paper_id is not None:
        conditions.append(table.c.paper_id == _string(paper_id, 100))
    count, size = (await db.execute(sa.select(sa.func.count(), sa.func.coalesce(sa.func.sum(
        sa.func.octet_length(sa.cast(table.c.snapshot_json, sa.Text)) + sa.func.octet_length(sa.cast(table.c.paper_snapshot_json, sa.Text))), 0))
        .where(*conditions))).one()
    if count > MAX_MEMBERS or size > MAX_SNAPSHOT_BYTES:
        raise IndexGenerationError("Index snapshot exceeds the bounded pilot scope")
    rows = await _verified_rows(db, "index_generation_members", *conditions)
    for row in rows:
        if row["vector_id"] != vector_id_for(identifier, row["chunk_revision_sha256"]) or len(row["vector_bytes"]) != 3072:
            raise IndexGenerationError("Retained member identity/bytes mismatch")
        if hashlib.sha256(row["vector_bytes"]).hexdigest() != row["vector_sha256"] or hashlib.sha256(
                row["snapshot_json"]["text"].encode("utf-8")).hexdigest() != row["content_sha256"]:
            raise IndexGenerationError("Retained member content/vector hash mismatch")
    return [_public_member(row) for row in sorted(rows, key=lambda row: row["vector_id"])]


async def load_active_generation(db, *, logical_index="sclib-main"):
    logical_index = _string(logical_index, 128)
    pointer = (await db.execute(sa.select(_table("index_active_pointer")).where(
        _table("index_active_pointer").c.logical_index == logical_index))).mappings().one_or_none()
    if pointer is None:
        return None
    events = await _verified_rows(db, "index_activation_events", _table("index_activation_events").c.id == pointer["activation_event_id"])
    generation = await _generation(db, pointer["generation_id"])
    if len(events) != 1 or generation is None or events[0]["generation_id"] != generation["id"] or generation["logical_index"] != logical_index:
        raise IndexGenerationError("Active generation pointer is unavailable")
    return _pin(generation, pointer["activation_event_id"])


async def load_generation(db, *, generation_id):
    """Read a sanitized staged/historical resource pin, never member payloads."""
    generation = await _generation(db, generation_id)
    return _pin(generation) if generation is not None else None


async def inspect_generation(db, *, generation_id):
    """Sanitized operational recovery view; no private snapshots or vectors."""
    generation = await _generation(db, generation_id)
    if generation is None:
        return None
    active = await load_active_generation(db, logical_index=generation["logical_index"])
    return {"pin": _pin(generation), "logical_index": generation["logical_index"], "current_active_pin": active,
            "is_current": active is not None and active["generation_id"] == str(generation["id"])}


async def _hashes(db, bodies, function="sclib_index_revision_hash_v1"):
    # Function names are internal constants, never caller-supplied SQL.
    rows = (await db.execute(sa.text(f"SELECT public.{function}(value) FROM jsonb_array_elements(CAST(:body AS jsonb)) WITH ORDINALITY AS x(value,n) ORDER BY n"),
        {"body": json.dumps(bodies, allow_nan=False, default=str)})).scalars().all()
    return rows


async def stage_generation(db, *, generation_id, items, resource, logical_index="sclib-main", dry_run=True):
    """Retain a <=1000-member immutable pilot in one caller-owned transaction."""
    _clean(db, dry_run)
    generation_id = UUID(str(generation_id))
    logical_index, resource = _string(logical_index, 128), _resource(resource)
    if type(items) is not list or not 1 <= len(items) <= MAX_MEMBERS:
        raise IndexGenerationError("Index staging requires 1..1000 members")
    inputs = {}
    for item in items:
        if type(item) is not dict or set(item) != {"chunk_id", "receipt_id", "vector", "parser_version"}:
            raise IndexGenerationError("Exact staging item fields are required")
        key = _string(item["chunk_id"], 200)
        if key in inputs:
            raise IndexGenerationError("Duplicate staging chunk")
        vector = validate_vector(item["vector"])
        if type(item["parser_version"]) is not str or not _PARSER.fullmatch(item["parser_version"]) or item["parser_version"].lower() in {"unknown", "legacy_unknown", "unrecorded"}:
            raise IndexGenerationError("An actual explicit parser version label is required")
        inputs[key] = {"receipt_id": UUID(str(item["receipt_id"])), "parser_version": _string(item["parser_version"], 160),
                       "vector": vector, "vector_bytes": struct.pack(">768f", *vector)}
    # Receipt rows are append-only (0061). This bounded scalar preflight can
    # select the actual count method before taking the private SQL fence, without
    # hydrating provider metadata. UTF-8-only stages must not download/load an
    # unrelated tokenizer; cl100k recounts still use a prepared real encoder.
    receipts = _table("embedding_completion_receipts")
    needs_encoder = await db.scalar(sa.select(sa.exists().where(
        receipts.c.id.in_([item["receipt_id"] for item in inputs.values()]),
        receipts.c.metadata_json["local_count_method"].astext == LOCAL_DOCUMENT_COUNT_METHOD,
    )))
    encoder = _document_encoder() if needs_encoder else None
    transaction = await db.begin_nested()
    try:
        await db.execute(sa.text("SELECT public.sclib_index_lock_v1()"))
        existing = await _generation(db, generation_id)
        if existing is not None:
            members = await load_generation_members(db, generation_id=generation_id)
            if existing["logical_index"] != logical_index or existing["resource"] != resource or len(members) != len(inputs):
                raise IndexGenerationError("Immutable generation identity/content conflict")
            for member in members:
                value = inputs.get(member["chunk_key"])
                if value is None or str(value["receipt_id"]) != member["receipt_id"] or value["parser_version"] != member["parser_version"] or value["vector_bytes"] != member["vector_bytes"]:
                    raise IndexGenerationError("Immutable generation identity/content conflict")
            if manifest_sha256(members) != existing["manifest_sha256"]:
                raise IndexGenerationError("Incomplete immutable generation staging")
            result = {**_pin(existing), "member_count": len(members), "dry_run": dry_run, "committed": False}
            await transaction.rollback()
            return result
        joins = """FROM chunks c JOIN papers p ON p.id=c.paper_id
            JOIN chunk_evidence_current link ON link.chunk_id=c.id
            JOIN rag_evidence_revisions e ON e.id=link.evidence_revision_id
            JOIN embedding_completion_receipts r ON r.chunk_key=c.id AND r.evidence_revision_id=e.id
            WHERE c.id IN :chunks AND r.id IN :receipts"""
        parameters = {"chunks": list(inputs), "receipts": [item["receipt_id"] for item in inputs.values()]}
        preflight = sa.text("SELECT count(*),COALESCE(sum(octet_length(to_jsonb(c)::text)+octet_length(public.sclib_index_paper_snapshot_v1(to_jsonb(p))::text)),0) " + joins).bindparams(
            sa.bindparam("chunks", expanding=True), sa.bindparam("receipts", expanding=True))
        count, size = (await db.execute(preflight, parameters)).one()
        if count != len(inputs) or size > MAX_SNAPSHOT_BYTES:
            raise IndexGenerationError("Current exact receipt inventory unavailable or pilot scope exceeded")
        query = sa.text("""SELECT c.id AS chunk_key,c.paper_id,to_jsonb(c) AS snapshot_json,
            public.sclib_index_paper_snapshot_v1(to_jsonb(p)) AS paper_snapshot_json,
            public.sclib_index_hash_v1(jsonb_build_object('chunk',to_jsonb(c),'paper',public.sclib_index_paper_snapshot_v1(to_jsonb(p)))) AS snapshot_sha256,
            e.id AS evidence_revision_id,e.record_sha256 AS evidence_record_sha256,e.source_snapshot_sha256,
            e.rendering_version AS chunker_version,r.id AS receipt_id,r.record_sha256 AS receipt_record_sha256,
            r.content_sha256,r.vector_sha256,r.metadata_json,
            octet_length(to_jsonb(c)::text)+octet_length(public.sclib_index_paper_snapshot_v1(to_jsonb(p))::text) AS snapshot_bytes
            """ + joins).bindparams(sa.bindparam("chunks", expanding=True), sa.bindparam("receipts", expanding=True))
        captured = (await db.execute(query, parameters)).mappings().all()
        if len(captured) != len(inputs) or sum(row["snapshot_bytes"] for row in captured) > MAX_SNAPSHOT_BYTES:
            raise IndexGenerationError("Current exact receipt inventory unavailable or pilot scope exceeded")
        members = []
        for source in captured:
            row = dict(source)
            value = inputs[row["chunk_key"]]
            if row["receipt_id"] != value["receipt_id"]:
                raise IndexGenerationError("Receipt does not match its actual chunk")
            _string(row["chunker_version"], 160)
            metadata = row.pop("metadata_json")
            validate_embedding_provenance(metadata, text=row["snapshot_json"]["text"], vector=value["vector"], expected_task="RETRIEVAL_DOCUMENT")
            if metadata["local_count_method"] == "tiktoken-cl100k_base/1" and _document_token_count(row["snapshot_json"]["text"], encoder) != metadata["local_count"]:
                raise IndexGenerationError("Current receipt local token count mismatch")
            row.pop("snapshot_bytes")
            row.update(generation_id=generation_id, parser_version=value["parser_version"])
            members.append(row)
        hashes = await _hashes(db, members)
        for member, digest in zip(members, hashes, strict=True):
            member.update(chunk_revision_sha256=digest, vector_id=vector_id_for(generation_id, digest), vector_bytes=inputs[member["chunk_key"]]["vector_bytes"])
        manifest = manifest_sha256(members)
        generation = {"id": generation_id, "logical_index": logical_index, "profile": deepcopy(PROFILE), "resource": resource,
                      "expected_member_count": len(members), "manifest_sha256": manifest}
        await db.execute(_table("index_generations").insert().values(**generation))
        for member in members:
            await db.execute(_table("index_generation_members").insert().values(**member))
        result = {**_pin(generation), "member_count": len(members), "dry_run": dry_run, "committed": False}
        await (transaction.rollback() if dry_run else transaction.commit())
        return result
    except BaseException:
        if transaction.is_active:
            await transaction.rollback()
        raise


async def record_validation(db, *, generation_id, observation, dry_run=True):
    """Validate all declared members, without claiming remote orphan absence."""
    _clean(db, dry_run)
    generation_id = UUID(str(generation_id))
    if type(observation) is not dict or set(observation) != {"version", "observation_id", "observed_at", "resource", "profile", "adapter_version", "full_inventory_observed", "vectors"}:
        raise IndexGenerationError("Exact observation fields are required")
    observation = deepcopy(observation)
    if observation["version"] != "sclib-index-observation/1.0.0" or type(observation["full_inventory_observed"]) is not bool:
        raise IndexGenerationError("Invalid inventory observation version/scope")
    if type(observation["observation_id"]) is not str or str(UUID(observation["observation_id"])) != observation["observation_id"]:
        raise IndexGenerationError("A canonical observation UUID is required")
    timestamp = observation["observed_at"]
    if type(timestamp) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z", timestamp):
        raise IndexGenerationError("A canonical UTC observation timestamp is required")
    datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%fZ")
    _string(observation["adapter_version"], 160)
    _resource(observation["resource"])
    manifest_sha256(observation["vectors"])
    if any(type(row) is not dict or set(row) != {"vector_id", "content_sha256", "vector_sha256"} for row in observation["vectors"]):
        raise IndexGenerationError("Exact observed inventory fields are required")
    observation["vectors"].sort(key=lambda row: row["vector_id"])
    encoded = json.dumps(observation, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    if len(encoded.encode()) > 1024 * 1024:
        raise IndexGenerationError("Observation byte limit")
    identifier = uuid5(NAMESPACE, "validation:" + observation["observation_id"])
    transaction = await db.begin_nested()
    try:
        await db.execute(sa.text("SELECT public.sclib_index_lock_v1()"))
        table = _table("index_generation_validations")
        rows = await _verified_rows(db, table.name, table.c.id == identifier)
        if rows:
            row = rows[0]
            if row["generation_id"] != generation_id or row["observation"] != observation:
                raise IndexGenerationError("Immutable validation identity/content conflict")
        else:
            row = dict((await db.execute(table.insert().values(id=identifier, generation_id=generation_id, observation=observation).returning(table))).mappings().one())
        result = {"validation_id": str(identifier), "generation_id": str(generation_id), "outcome": row["outcome"],
                  "validation_scope": row["validation_scope"],
                  "observed_manifest_sha256": row["observed_manifest_sha256"], "dry_run": dry_run, "committed": False}
        await (transaction.rollback() if dry_run or rows else transaction.commit())
        return result
    except BaseException:
        if transaction.is_active:
            await transaction.rollback()
        raise


async def activate_generation(db, *, generation_id, validation_id, expected_event_id, idempotency_key, action="promote", dry_run=True):
    """Internal operational CAS; never adds scientific curator authority."""
    _clean(db, dry_run)
    generation_id, validation_id = UUID(str(generation_id)), UUID(str(validation_id))
    predecessor = UUID(str(expected_event_id)) if expected_event_id is not None else None
    key = _string(idempotency_key, 160)
    if action not in {"promote", "rollback"}:
        raise IndexGenerationError("Unsupported activation action")
    transaction = await db.begin_nested()
    try:
        await db.execute(sa.text("SELECT public.sclib_index_lock_v1()"))
        generation = await _generation(db, generation_id)
        if generation is None:
            raise IndexGenerationError("Generation is unavailable")
        logical_index = generation["logical_index"]
        identifier = uuid5(NAMESPACE, "activation:" + logical_index + ":" + key)
        table = _table("index_activation_events")
        rows = await _verified_rows(db, table.name, table.c.id == identifier)
        values = {"id": identifier, "logical_index": logical_index, "generation_id": generation_id, "validation_id": validation_id,
                  "predecessor_id": predecessor, "idempotency_key": key, "action": action}
        if rows:
            if any(rows[0][field] != value for field, value in values.items()):
                raise IndexGenerationError("Immutable activation idempotency conflict")
        else:
            members = await load_generation_members(db, generation_id=generation_id)
            statuses = await resolve_paper_lifecycle(db, {member["paper_id"] for member in members})
            if any(not source_visibility(statuses.get(member["paper_id"]))["reported_claim_filter_eligible"] for member in members):
                raise IndexGenerationError("Current source lifecycle hold prevents activation")
            number = await db.scalar(sa.select(sa.func.coalesce(sa.func.max(table.c.event_number), 0)).where(table.c.logical_index == logical_index))
            await db.execute(table.insert().values(**values, event_number=number + 1))
        result = {**_pin(generation, identifier), "dry_run": dry_run, "committed": False}
        await (transaction.rollback() if dry_run or rows else transaction.commit())
        return result
    except BaseException:
        if transaction.is_active:
            await transaction.rollback()
        raise
