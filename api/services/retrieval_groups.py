"""Private current Work-mapping witnesses for retrieval diversity only.

No scientific identity, permission, claim review or independence is established.
The entire current map (including a missing map) is bound so a packing decision
can be rechecked after generation without exposing raw Work IDs publicly.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Text, cast, func, select

from models.db import PaperWorkMap

VERSION = "retrieval-group-binding/1.0.0"
MAX_PAPERS = 300
MAX_ROW_BYTES = 16384
MAX_TOTAL_BYTES = 256 * 1024
_FIELDS = {"paper_id", "work_id", "relation_type", "match_method", "match_score", "review_status", "created_at"}
_SHA = re.compile(r"^[0-9a-f]{64}$")


class RetrievalGroupingError(ValueError):
    """A complete current diversity-mapping inventory is unavailable."""


def _paper(value):
    if (type(value) is not str or not 1 <= len(value) <= 100 or not value.strip()
            or any(ord(character) < 32 or ord(character) == 127 for character in value)):
        raise RetrievalGroupingError("A bounded source identity is required")
    return value


def _uuid(value):
    if type(value) is not str:
        raise RetrievalGroupingError("A canonical Work identity is required")
    try:
        valid = str(UUID(value)) == value
    except ValueError:
        valid = False
    if not valid:
        raise RetrievalGroupingError("A canonical Work identity is required")
    return value


@dataclass(frozen=True, slots=True)
class GroupBinding:
    paper_id: str
    accepted_work_id: str | None = field(repr=False)
    mapping_sha256: str

    def __post_init__(self):
        _paper(self.paper_id)
        if self.accepted_work_id is not None:
            _uuid(self.accepted_work_id)
        if type(self.mapping_sha256) is not str or not _SHA.fullmatch(self.mapping_sha256):
            raise RetrievalGroupingError("A complete mapping digest is required")


def _binding(paper_id, mapping):
    if mapping is not None:
        if type(mapping) is not dict or set(mapping) != _FIELDS or mapping["paper_id"] != paper_id:
            raise RetrievalGroupingError("The exact current mapping fields are required")
        mapping = dict(mapping)
        _uuid(mapping["work_id"])
        if mapping["review_status"] not in {"pending", "accepted", "rejected"}:
            raise RetrievalGroupingError("Unknown mapping review state")
        if mapping["relation_type"] not in {"canonical_version", "preprint", "published_version", "supplement", "correction", "unknown"}:
            raise RetrievalGroupingError("Unknown mapping relation")
        if mapping["match_method"] not in {"exact_doi", "related_paper", "exact_arxiv", "metadata", "manual", "singleton"}:
            raise RetrievalGroupingError("Unknown mapping method")
        score = mapping["match_score"]
        if score is not None and (type(score) not in {int, float} or not math.isfinite(score) or not 0 <= score <= 1):
            raise RetrievalGroupingError("Invalid mapping score")
        stamp = mapping["created_at"]
        if type(stamp) is not str or len(stamp) > 80:
            raise RetrievalGroupingError("A finite mapping timestamp is required")
        try:
            parsed = datetime.fromisoformat(stamp)
            if parsed.tzinfo is None:
                raise ValueError
            mapping["created_at"] = parsed.astimezone(UTC).isoformat(timespec="microseconds")
        except (ValueError, OverflowError):
            raise RetrievalGroupingError("A finite mapping timestamp is required") from None
    payload = json.dumps({"version": VERSION, "paper_id": paper_id, "mapping": mapping},
                         sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(payload) > MAX_ROW_BYTES:
        raise RetrievalGroupingError("Current mapping exceeds its byte bound")
    return GroupBinding(paper_id, mapping["work_id"] if mapping and mapping["review_status"] == "accepted" else None,
                        hashlib.sha256(payload).hexdigest())


async def resolve_grouping_bindings(db, paper_ids) -> dict[str, GroupBinding]:
    """Two bounded reads, no writes/commit/locks or unrelated source hydration."""
    if type(paper_ids) not in {list, tuple, set, frozenset} or len(paper_ids) > MAX_PAPERS:
        raise RetrievalGroupingError("At most 300 current source identities are allowed")
    identifiers = sorted({_paper(value) for value in paper_ids})
    if not identifiers:
        return {}
    table = PaperWorkMap.__table__
    body = func.to_jsonb(table.table_valued())
    sizes = (await db.execute(select(table.c.paper_id, func.octet_length(cast(body, Text)))
                             .where(table.c.paper_id.in_(identifiers)))).all()
    if (len(sizes) > len(identifiers) or any(type(size) is not int or size > MAX_ROW_BYTES for _, size in sizes)
            or sum(size for _, size in sizes) > MAX_TOTAL_BYTES):
        raise RetrievalGroupingError("Current mapping inventory exceeds its byte bound")
    rows = (await db.execute(select(table.c.paper_id, body).where(table.c.paper_id.in_(identifiers)))).all()
    if len(rows) > len(identifiers) or len({identifier for identifier, _ in rows}) != len(rows):
        raise RetrievalGroupingError("Current mapping identity inventory is malformed")
    captured = {identifier: mapping for identifier, mapping in rows}
    if sum(len(json.dumps(mapping, ensure_ascii=False, allow_nan=False).encode("utf-8")) for mapping in captured.values()) > MAX_TOTAL_BYTES:
        raise RetrievalGroupingError("Current mapping inventory changed beyond its byte bound")
    return {identifier: _binding(identifier, captured.get(identifier)) for identifier in identifiers}
