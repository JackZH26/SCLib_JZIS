"""Observe retained input files and capture native revisions, never activation.

The caller owns the outer transaction. Defaults roll back the complete preview.
No provider client, provider-resource record or original-root/rights grant is
created. File observations prove the retained parser input bytes, not delivery
of an entire publisher work or correctness of a scientific extraction.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import struct
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid5

import sqlalchemy as sa

from models.db import Base
from services.embedding_contract import (
    LOCAL_DOCUMENT_COUNT_METHOD,
    validate_embedding_provenance,
    validate_vector,
)
from services.embedding_receipts import _document_encoder, _document_token_count

NAMESPACE = UUID("c6b85586-63b5-4495-9d26-f75ab863042a")
MAX_FILE_BYTES = 128 * 1024**2
MAX_SNAPSHOT_BYTES = 16 * 1024**2
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}\Z")


class RetrievalNativeError(ValueError):
    """The actual bounded input/revision binding cannot be established."""


@dataclass(frozen=True, slots=True)
class FileObservation:
    relative_path: str
    sha256: str
    bytes: int
    observed_at: datetime


def _text(value, maximum):
    if (type(value) is not str or not value.strip() or len(value) > maximum
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise RetrievalNativeError("A bounded nonempty field is required")
    return value


def _label(value):
    if (type(value) is not str or not _LABEL.fullmatch(value)
            or value.lower() in {"unknown", "legacy_unknown", "unrecorded"}):
        raise RetrievalNativeError("An actual parser/chunker version is required")
    return value


def observe_archive_file(root: Path, relative_path: str, *, expected_bytes=None, provider_sha256=None):
    """Read a stable regular file entirely, without changing or copying it.

    The configured archive root is operator-owned. Neither absolute paths nor
    symlink escapes are accepted. The observation does not authenticate a
    publisher or change the original-root status of existing evidence.
    """
    _text(relative_path, 2048)
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise RetrievalNativeError("A path inside the configured archive is required")
    if expected_bytes is not None and (type(expected_bytes) is not int or not 1 <= expected_bytes <= MAX_FILE_BYTES):
        raise RetrievalNativeError("Invalid expected input byte count")
    if provider_sha256 is not None and (type(provider_sha256) is not str or not _SHA.fullmatch(provider_sha256)):
        raise RetrievalNativeError("Invalid provider input checksum")
    try:
        archive = Path(root).resolve(strict=True)
        path = (archive / relative).resolve(strict=True)
        if not archive.is_dir() or not path.is_relative_to(archive):
            raise RetrievalNativeError("A path inside the configured archive is required")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or not 1 <= before.st_size <= MAX_FILE_BYTES:
                raise RetrievalNativeError("A bounded regular parser input file is required")
            digest, count = hashlib.sha256(), 0
            while block := os.read(descriptor, 1024**2):
                count += len(block)
                if count > MAX_FILE_BYTES:
                    raise RetrievalNativeError("Input exceeds the file observation limit")
                digest.update(block)
            after, named = os.fstat(descriptor), path.stat(follow_symlinks=False)
            fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
            if (any(getattr(before, key) != getattr(after, key) or getattr(before, key) != getattr(named, key)
                    for key in fields) or count != before.st_size):
                raise RetrievalNativeError("Parser input changed during observation")
            actual = digest.hexdigest()
            if ((expected_bytes is not None and expected_bytes != count)
                    or provider_sha256 is not None and provider_sha256 != actual):
                raise RetrievalNativeError("Actual parser input does not match its delivery evidence")
            return FileObservation(str(path.relative_to(archive)), actual, count, datetime.now(UTC))
        finally:
            os.close(descriptor)
    except (OSError, RuntimeError):
        raise RetrievalNativeError("Retained parser input is unavailable") from None


def _clean(db, dry_run):
    if type(dry_run) is not bool or db.new or db.dirty or db.deleted:
        raise RetrievalNativeError("Flush pending caller changes and select an explicit preview/apply mode")


def _json(value):
    def convert(item):
        if isinstance(item, UUID):
            return str(item)
        if isinstance(item, bytes):
            return "\\x" + item.hex()
        raise TypeError("Unsupported native binding field")
    return json.loads(json.dumps(value, default=convert, sort_keys=True, separators=(",", ":"), allow_nan=False))


async def _existing(db, table, identifier):
    if table not in {"retrieval_input_receipts_v2", "retrieval_native_revisions_v2"}:
        raise RetrievalNativeError("Unknown native history table")
    body = ("to_jsonb(n)||jsonb_build_object('vector_bytes',concat(chr(92),'x',encode(n.vector_bytes,'hex')))"
            if table == "retrieval_native_revisions_v2" else "to_jsonb(n)")
    result = (await db.execute(sa.text(f"SELECT {body} AS body, "
        f"n.record_sha256=public.sclib_retrieval_record_hash_v2(to_jsonb(n)) AS intact FROM {table} n WHERE id=:id"),
        {"id": UUID(str(identifier))})).mappings().first()
    if result is not None and result["intact"] is not True:
        raise RetrievalNativeError("Native history integrity mismatch")
    return result["body"] if result is not None else None


async def append_input_receipt(db, *, archive_root, relative_path, paper_id, source_uri, source_scope,
                               media_type, parser_version, chunker_version, expected_bytes=None,
                               provider_sha256=None, dry_run=True):
    _clean(db, dry_run)
    paper_id, source_uri = _text(paper_id, 100), _text(source_uri, 2048)
    media_type = _text(media_type, 128)
    parser_version, chunker_version = _label(parser_version), _label(chunker_version)
    if type(source_scope) is not str or source_scope not in {"abstract", "full_text", "structured_record"}:
        raise RetrievalNativeError("An explicit retained representation scope is required")
    observed = observe_archive_file(Path(archive_root), relative_path,
                                    expected_bytes=expected_bytes, provider_sha256=provider_sha256)
    transaction = await db.begin_nested()
    try:
        await db.execute(sa.text("SELECT public.sclib_index_lock_v1()"))
        source = await db.scalar(sa.text("SELECT public.sclib_source_lifecycle_snapshot_hash_v1('paper',to_jsonb(p)) "
                                        "FROM papers p WHERE id=:id"), {"id": paper_id})
        if source is None:
            raise RetrievalNativeError("Current input source is unavailable")
        body = {"version": "retrieval-input/2.0.0", "paper_id": paper_id, "source_scope": source_scope,
                "source_uri": source_uri, "archive_relative_path": observed.relative_path, "media_type": media_type,
                "representation_sha256": observed.sha256, "representation_bytes": observed.bytes,
                "expected_bytes": expected_bytes, "provider_sha256": provider_sha256,
                "source_snapshot_sha256": source, "parser_version": parser_version,
                "chunker_version": chunker_version, "capture_method": "regular-file-full-read/1"}
        identifier = uuid5(NAMESPACE, json.dumps(body, sort_keys=True, separators=(",", ":")))
        existing = await _existing(db, "retrieval_input_receipts_v2", identifier)
        if existing is not None:
            if any(existing[key] != value for key, value in body.items()):
                raise RetrievalNativeError("Immutable input identity conflict")
            await transaction.rollback()
        else:
            await db.execute(Base.metadata.tables["retrieval_input_receipts_v2"].insert().values(
                id=identifier, **body, observed_at=observed.observed_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ")))
            existing = await _existing(db, "retrieval_input_receipts_v2", identifier)
            await (transaction.rollback() if dry_run else transaction.commit())
        return {"input_receipt_id": str(identifier), "record_sha256": existing["record_sha256"],
                "representation_sha256": observed.sha256, "representation_bytes": observed.bytes,
                "dry_run": dry_run, "committed": False, "active_pointer_changed": False}
    except BaseException:
        if transaction.is_active:
            await transaction.rollback()
        raise


async def append_native_revisions(db, *, input_receipt_id, items, dry_run=True):
    """Capture <=1000 actual current chunks with existing complete receipts.

    Identical existing revision replay is a no-op. An original provider receipt
    must already be bound to the exact current evidence; no fake Vertex index
    or test-backend generation is created to stage native data.
    """
    _clean(db, dry_run)
    identifier = UUID(str(input_receipt_id))
    if type(items) is not list or not 1 <= len(items) <= 1000:
        raise RetrievalNativeError("A native capture requires 1..1000 actual chunks")
    inputs = {}
    for item in items:
        if type(item) is not dict or set(item) != {"chunk_id", "receipt_id", "vector"}:
            raise RetrievalNativeError("Exact native capture fields are required")
        key = _text(item["chunk_id"], 200)
        if key in inputs:
            raise RetrievalNativeError("Duplicate native chunk identity")
        vector = validate_vector(item["vector"])
        inputs[key] = {"receipt_id": UUID(str(item["receipt_id"])), "vector": vector,
                       "vector_bytes": struct.pack(">768f", *vector)}
    receipts = Base.metadata.tables["embedding_completion_receipts"]
    needs_encoder = await db.scalar(sa.select(sa.exists().where(
        receipts.c.id.in_([value["receipt_id"] for value in inputs.values()]),
        receipts.c.metadata_json["local_count_method"].astext == LOCAL_DOCUMENT_COUNT_METHOD)))
    encoder = _document_encoder() if needs_encoder else None
    transaction = await db.begin_nested()
    try:
        await db.execute(sa.text("SELECT public.sclib_index_lock_v1()"))
        observed = await _existing(db, "retrieval_input_receipts_v2", identifier)
        if observed is None:
            raise RetrievalNativeError("An actual retained input receipt is required")
        joins = """FROM chunks c JOIN papers p ON p.id=c.paper_id
          JOIN chunk_evidence_current link ON link.chunk_id=c.id
          JOIN rag_evidence_revisions e ON e.id=link.evidence_revision_id
          JOIN embedding_completion_receipts r ON r.chunk_key=c.id AND r.evidence_revision_id=e.id
          WHERE c.id IN :chunks AND r.id IN :receipts"""
        parameters = {"chunks": list(inputs), "receipts": [value["receipt_id"] for value in inputs.values()]}
        def statement(body):
            return sa.text(body + joins).bindparams(sa.bindparam("chunks", expanding=True),
                                                   sa.bindparam("receipts", expanding=True))
        count, size = (await db.execute(statement("SELECT count(*),COALESCE(sum(octet_length(to_jsonb(c)::text)+"
            "octet_length(public.sclib_index_paper_snapshot_v1(to_jsonb(p))::text)),0) "), parameters)).one()
        if count != len(inputs) or size > MAX_SNAPSHOT_BYTES:
            raise RetrievalNativeError("Exact bounded native receipt inventory unavailable")
        captured = (await db.execute(statement("""SELECT c.id AS chunk_key,c.paper_id,to_jsonb(c) AS snapshot_json,
          public.sclib_index_paper_snapshot_v1(to_jsonb(p)) AS paper_snapshot_json,
          public.sclib_index_hash_v1(jsonb_build_object('chunk',to_jsonb(c),'paper',public.sclib_index_paper_snapshot_v1(to_jsonb(p)))) AS snapshot_sha256,
          e.id AS evidence_revision_id,e.record_sha256 AS evidence_record_sha256,e.source_snapshot_sha256,
          e.rendering_version AS chunker_version,r.id AS receipt_id,r.record_sha256 AS receipt_record_sha256,
          r.content_sha256,r.vector_sha256,r.metadata_json,
          octet_length(to_jsonb(c)::text)+octet_length(public.sclib_index_paper_snapshot_v1(to_jsonb(p))::text) AS snapshot_bytes
          """), parameters)).mappings().all()
        if len(captured) != len(inputs) or sum(row["snapshot_bytes"] for row in captured) > MAX_SNAPSHOT_BYTES:
            raise RetrievalNativeError("Native snapshot budget exceeded")
        result, inserted = [], 0
        for source in captured:
            body = dict(source)
            selected = inputs[body["chunk_key"]]
            if (body["receipt_id"] != selected["receipt_id"] or body["paper_id"] != observed["paper_id"]
                    or body["source_snapshot_sha256"] != observed["source_snapshot_sha256"]
                    or body["chunker_version"] != observed["chunker_version"]):
                raise RetrievalNativeError("Native input and current source do not agree")
            metadata = body.pop("metadata_json")
            validate_embedding_provenance(metadata, text=body["snapshot_json"]["text"],
                                         vector=selected["vector"], expected_task="RETRIEVAL_DOCUMENT")
            if (metadata["local_count_method"] == LOCAL_DOCUMENT_COUNT_METHOD
                    and _document_token_count(body["snapshot_json"]["text"], encoder) != metadata["local_count"]):
                raise RetrievalNativeError("Actual native token count does not match its receipt")
            body.pop("snapshot_bytes")
            body.update(input_receipt_id=identifier, input_receipt_record_sha256=observed["record_sha256"],
                        parser_version=observed["parser_version"])
            digest = await db.scalar(sa.text("SELECT public.sclib_retrieval_native_hash_v2(CAST(:body AS jsonb))"),
                                     {"body": json.dumps(_json(body), sort_keys=True, separators=(",", ":"))})
            revision_id = uuid5(NAMESPACE, "native-revision:" + digest)
            body.update(id=revision_id, vector_id="rv2_" + digest, chunk_revision_sha256=digest,
                        vector_bytes=selected["vector_bytes"])
            existing = await _existing(db, "retrieval_native_revisions_v2", revision_id)
            if existing is not None:
                if any(existing[key] != value for key, value in _json(body).items()):
                    raise RetrievalNativeError("Immutable native revision identity conflict")
            else:
                await db.execute(Base.metadata.tables["retrieval_native_revisions_v2"].insert().values(**body))
                existing = await _existing(db, "retrieval_native_revisions_v2", revision_id)
                inserted += 1
            result.append({"revision_id": str(revision_id), "vector_id": body["vector_id"],
                           "record_sha256": existing["record_sha256"], "content_sha256": body["content_sha256"],
                           "vector_sha256": body["vector_sha256"]})
        await (transaction.rollback() if dry_run or not inserted else transaction.commit())
        return {"input_receipt_id": str(identifier), "revisions": sorted(result, key=lambda row: row["vector_id"]),
                "dry_run": dry_run, "committed": False, "active_pointer_changed": False}
    except BaseException:
        if transaction.is_active:
            await transaction.rollback()
        raise
