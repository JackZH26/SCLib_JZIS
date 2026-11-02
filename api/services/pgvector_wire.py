"""Bounded PostgreSQL binary COPY and lossless 768-dimensional pgvector input.

Canonical retained vectors already contain network-order float32 values. Avoid
decimal conversion during import; pgvector receives its dimension header and
those exact bytes. PostgreSQL still validates dimensions and finite values.
"""
from __future__ import annotations

import hashlib
import re
import struct

MAGIC = b"PGCOPY\n\xff\r\n\x00"
MAX_BATCH = 1000
MAX_BYTES = 4 * 1024 * 1024
SHA = re.compile(rb"[0-9a-f]{64}\Z")
ID = re.compile(rb"[A-Za-z0-9_-]{1,120}\Z")


def decode_copy(payload: bytes, *, fields: int) -> list[list[bytes]]:
    """Strict finite frame: no extensions, NULLs, extra rows or trailing bytes."""
    if not isinstance(payload, bytes) or len(payload) > MAX_BYTES or not payload.startswith(MAGIC):
        raise ValueError("Invalid bounded COPY payload")
    offset = len(MAGIC)
    if payload[offset:offset + 8] != b"\0" * 8:
        raise ValueError("Unsupported COPY flags or extensions")
    offset += 8
    rows = []
    try:
        while True:
            count, = struct.unpack_from("!h", payload, offset)
            offset += 2
            if count == -1:
                break
            if count != fields or len(rows) >= MAX_BATCH:
                raise ValueError("Unexpected COPY row inventory")
            row = []
            for _ in range(fields):
                size, = struct.unpack_from("!i", payload, offset)
                offset += 4
                if size < 0 or size > 4096 or offset + size > len(payload):
                    raise ValueError("Invalid COPY field length")
                row.append(payload[offset:offset + size])
                offset += size
            rows.append(row)
    except struct.error:
        raise ValueError("Truncated COPY frame") from None
    if offset != len(payload):
        raise ValueError("Trailing COPY data")
    return rows


def projection_copy(payload: bytes) -> tuple[bytes, list[tuple[str, str, str]]]:
    """Seven source fields -> six projection fields; source bindings must pass."""
    rows = decode_copy(payload, fields=7)
    output = bytearray(MAGIC + b"\0" * 8)
    inventory = []
    prior = None
    for identifier, paper, content_hash, vector_hash, revision_hash, raw, valid in rows:
        if (not ID.fullmatch(identifier) or not paper or len(paper) > 400
                or any(not SHA.fullmatch(value) for value in (content_hash, vector_hash, revision_hash))
                or len(raw) != 3072 or not any(raw) or valid != b"\x01"
                or hashlib.sha256(raw).hexdigest().encode() != vector_hash
                or (prior is not None and identifier <= prior)):
            raise ValueError("Source vector or immutable bindings failed")
        # Check the actual float32 bit patterns without converting/rounding.
        words = struct.unpack("!768I", raw)
        if any((word & 0x7F800000) == 0x7F800000 or word == 0x80000000 for word in words):
            raise ValueError("Noncanonical retained float32 vector")
        values = (identifier, paper, content_hash, vector_hash, revision_hash,
                  struct.pack("!hh", 768, 0) + raw)
        output.extend(struct.pack("!h", len(values)))
        for value in values:
            output.extend(struct.pack("!i", len(value)))
            output.extend(value)
        inventory.append((identifier.decode(), content_hash.decode(), vector_hash.decode()))
        prior = identifier
    output.extend(struct.pack("!h", -1))
    return bytes(output), inventory
