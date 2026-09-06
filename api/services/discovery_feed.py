"""Strict Discovery validation and crash-safe, local-only cache publication.

One envelope stores the feed and its matching producer metadata together. A
single os.replace publishes that pair; the previous validated envelope remains
recoverable in a last-good sidecar. Legacy raw feed files can still be read.
No DB, settings, network or cloud imports are permitted in this module.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from services.discovery_contract import DiscoveryContract, DiscoveryResponse

MAX_FEED_BYTES = 50_000_000
CACHE_SCHEMA = "discovery-cache/1"


def strict_json(text: str) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON object key")
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f"non-finite JSON constant: {value}")

    result = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    if not isinstance(result, dict):
        raise ValueError("Discovery payload must be an object")
    # Also catches an overflowing JSON exponent (1e999), at every depth.
    json.dumps(result, allow_nan=False)
    return result


def producer_digest(payload: dict) -> str:
    """Preserve the existing producer's canonical SHA-256 convention."""
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class ProducerMetadata(DiscoveryContract):
    status: Literal["active", "planned"]
    candidate_count: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    mode: str | None = None
    updated_at_utc: datetime | None = None
    source: str | None = None


@dataclass(frozen=True)
class FeedDocument:
    feed: DiscoveryResponse
    raw_feed: dict[str, Any]
    metadata: dict | None
    validated_at: datetime

    def envelope(self) -> dict:
        return {
            "cache_schema": CACHE_SCHEMA,
            "feed": self.raw_feed,
            "metadata": self.metadata,
            "content_sha256": producer_digest(self.raw_feed),
            "validated_at": self.validated_at.isoformat(),
        }


def validate_feed(raw: dict, metadata: dict | None = None) -> DiscoveryResponse:
    # JSON-mode strict validation accepts ISO datetimes, but not coercions of
    # numeric strings, booleans, list elements or extra fields.
    feed = DiscoveryResponse.model_validate_json(json.dumps(raw, allow_nan=False))
    if metadata is not None:
        meta = ProducerMetadata.model_validate_json(json.dumps(metadata, allow_nan=False))
        if meta.sha256 != producer_digest(raw):
            raise ValueError("metadata/feed digest mismatch")
        if meta.status != feed.status or meta.candidate_count != len(feed.candidates):
            raise ValueError("metadata/feed status or count mismatch")
        if meta.updated_at_utc != feed.updated_at_utc:
            raise ValueError("metadata/feed timestamp mismatch")
        if meta.source is not None and meta.source != feed.source:
            raise ValueError("metadata/feed source mismatch")
    return feed


def read_json_file(path: Path) -> dict:
    # Bound the actual read, not just stat(), which could race a replacement.
    with path.open("rb") as stream:
        raw = stream.read(MAX_FEED_BYTES + 1)
    if len(raw) > MAX_FEED_BYTES:
        raise ValueError("Discovery file exceeds the size limit")
    return strict_json(raw.decode("utf-8"))


def read_document(path: Path) -> FeedDocument:
    payload = read_json_file(path)
    metadata = None
    validated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    if "cache_schema" in payload:
        if set(payload) != {"cache_schema", "feed", "metadata", "content_sha256", "validated_at"}:
            raise ValueError("invalid Discovery cache envelope fields")
        if payload["cache_schema"] != CACHE_SCHEMA:
            raise ValueError("unsupported Discovery cache version")
        metadata = payload["metadata"]
        raw = payload["feed"]
        if not isinstance(raw, dict) or producer_digest(raw) != payload["content_sha256"]:
            raise ValueError("Discovery cache content digest mismatch")
        validated_at = datetime.fromisoformat(payload["validated_at"])
        if validated_at.tzinfo is None:
            raise ValueError("cache validation time requires a timezone")
    else:
        raw = payload
    return FeedDocument(validate_feed(raw, metadata), raw, metadata, validated_at)


def last_good_path(path: Path) -> Path:
    return path.with_name(path.name + ".last-good.json")


def update_status_path(path: Path) -> Path:
    return path.with_name(path.name + ".update-status.json")


def record_update_failure(path: Path) -> None:
    _atomic_write(path=update_status_path(path), body=json.dumps({
        "schema_version": "discovery-update-status/1",
        "status": "failed",
        "attempted_at": datetime.now(UTC).isoformat(),
    }).encode("utf-8"))


def update_failed_after(path: Path, validated_at: datetime) -> bool:
    try:
        status = read_json_file(update_status_path(path))
    except FileNotFoundError:
        return False
    if set(status) != {"schema_version", "status", "attempted_at"} or status["schema_version"] != "discovery-update-status/1" or status["status"] != "failed":
        raise ValueError("invalid Discovery update status")
    attempted_at = datetime.fromisoformat(status["attempted_at"])
    if attempted_at.tzinfo is None:
        raise ValueError("update time requires a timezone")
    return attempted_at >= validated_at


def _atomic_write(path: Path, body: bytes) -> None:
    """Write/fsync a sibling temporary file, then atomically promote it."""
    if len(body) > MAX_FEED_BYTES:
        raise ValueError("Discovery cache envelope exceeds the size limit")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fchmod(stream.fileno(), 0o644)
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_write_document(path: Path, document: FeedDocument) -> None:
    _atomic_write(path, json.dumps(document.envelope(), ensure_ascii=False, allow_nan=False).encode("utf-8"))


def publish_feed(feed_path: Path, metadata_path: Path, destination: Path) -> FeedDocument:
    """Called by the pull CLI under its local lock, never by a public endpoint."""
    raw = read_json_file(feed_path)
    metadata = read_json_file(metadata_path)
    feed = validate_feed(raw, metadata)
    document = FeedDocument(feed, raw, metadata, datetime.now(UTC))
    # Preserve the previous matched pair before the single publication point.
    try:
        previous = read_document(destination)
    except (OSError, ValueError, TypeError, KeyError):
        previous = None
    if previous is not None:
        atomic_write_document(last_good_path(destination), previous)
    atomic_write_document(destination, document)
    return document
