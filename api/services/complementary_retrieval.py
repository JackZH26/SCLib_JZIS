"""Bounded same-snapshot sibling discovery, not scientific evidence promotion.

Section/table flags are navigation hints only. They do not establish experiment
identity, table completeness, primary authorship or independent replication.
The caller must hydrate/verify and apply every current admission gate to each
new candidate, exactly as it does to ordinary retrieval hits.
"""
from __future__ import annotations

import re
from uuid import UUID

import sqlalchemy as sa

from models.db import Base
from services.index_retrieval import GenerationChunk, IndexRetrievalError
from services.retrieval import RankedCandidate

MAX_SEED_GROUPS = 20
MAX_METADATA_ROWS = 1000  # matches the immutable-generation pilot ceiling
MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_ADDITIONS = 180  # 20 exact sources x 3 roles x 3 bounded alternatives
_METHOD = re.compile(r"\b(methods?|experimental|synthesis|preparation|computational details)\b", re.I)
_RESULT = re.compile(r"\b(results?|discussion|measurements?|characterization)\b", re.I)


def role_hint(section, has_table):
    if has_table is True:
        return "table"
    if type(section) is not str or len(section) > 2048:
        return "other"
    method, result = bool(_METHOD.search(section)), bool(_RESULT.search(section))
    return "methods" if method and not result else "results" if result and not method else "other"


async def expand_candidates(db, pin, candidates, chunk_by_id):
    """Keep seed rank; append metadata-selected siblings without fake ANN scores.

    Only exact paper AND retained source-snapshot matches are expanded. Legacy
    text has no snapshot binding and is deliberately not expanded. All returned
    IDs must still pass immutable member/evidence verification before use.
    """
    if type(candidates) is not list or len(candidates) > 100:
        raise IndexRetrievalError("Complementary seed inventory exceeds its bound")
    if pin is None or not candidates:
        return list(candidates)
    groups = []
    for candidate in candidates:
        chunk = chunk_by_id.get(candidate.chunk_id)
        if not isinstance(chunk, GenerationChunk):
            continue
        snapshot = chunk.member.get("source_snapshot_sha256")
        if type(snapshot) is not str or not re.fullmatch(r"[0-9a-f]{64}", snapshot):
            continue
        key = (chunk.paper_id, snapshot)
        if key not in groups:
            groups.append(key)
        if len(groups) >= MAX_SEED_GROUPS:
            break
    if not groups:
        return list(candidates)
    member = Base.metadata.tables["index_generation_members"]
    evidence = Base.metadata.tables["rag_evidence_revisions"]
    projection = sa.select(member.c.vector_id, member.c.paper_id, member.c.source_snapshot_sha256,
        member.c.snapshot_json["section"].astext.label("section"),
        member.c.snapshot_json["has_table"].label("has_table")).join(
            evidence, evidence.c.id == member.c.evidence_revision_id).where(
        member.c.generation_id == UUID(str(pin["generation_id"])),
        sa.tuple_(member.c.paper_id, member.c.source_snapshot_sha256).in_(groups),
        evidence.c.chunk_kind == "original_passage")
    metadata = projection.subquery()
    count, size = (await db.execute(sa.select(sa.func.count(), sa.func.coalesce(sa.func.sum(
        sa.func.octet_length(sa.cast(sa.func.to_jsonb(metadata.table_valued()), sa.Text))), 0)))).one()
    if count > MAX_METADATA_ROWS or size > MAX_METADATA_BYTES:
        raise IndexRetrievalError("Complementary metadata inventory exceeds its bound")
    rows = (await db.execute(projection.order_by(member.c.vector_id))).mappings().all()
    if len(rows) != count:
        raise IndexRetrievalError("Complementary metadata inventory changed")
    by_group = {group: {role: [] for role in ("methods", "results", "table")} for group in groups}
    for row in rows:
        role = role_hint(row["section"], row["has_table"])
        if role != "other":
            by_group[(row["paper_id"], row["source_snapshot_sha256"])][role].append(row["vector_id"])
    result, seen = list(candidates), {item.chunk_id for item in candidates}
    for alternative in range(3):
        for group in groups:
            for role in ("methods", "results", "table"):
                ids = by_group[group][role]
                if len(ids) <= alternative or ids[alternative] in seen:
                    continue
                identifier = ids[alternative]
                result.append(RankedCandidate(identifier, 0.0, None, None, ("source_complement",)))
                seen.add(identifier)
    if len(result) > len(candidates) + MAX_ADDITIONS:
        raise IndexRetrievalError("Complementary candidate inventory exceeds its bound")
    return result
