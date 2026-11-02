"""Bounded SQL candidate transport for independently identified projections.

This module is deliberately not wired into Search/Ask/Similar yet. A projection
spec is an address, not a validation receipt or an activation. The v2 publisher
and read coordinator must select a validated build from the database, check its
content bindings, and hydrate candidates with current evidence/rights checks.
No embedding RPC, Vertex fallback, mutable Chunk lookup or activation occurs here.
"""
from __future__ import annotations

import asyncio
import math
import re
from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa

from services.embedding_contract import validate_vector

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,200}\Z")
_COLUMNS = "vector_id,paper_id,content_sha256,vector_sha256,chunk_revision_sha256"


class PgvectorQueryError(ValueError):
    """The bounded transport request or response is incompatible."""


class PgvectorUnavailable(RuntimeError):
    """No complete candidate batch was obtained within the SQL budget."""


@dataclass(frozen=True, slots=True)
class ProjectionSpec:
    build_id: str
    content_version_id: str
    manifest_sha256: str

    def __post_init__(self):
        try:
            if any(type(value) is not str or str(UUID(value)) != value
                   for value in (self.build_id, self.content_version_id)):
                raise ValueError
            if type(self.manifest_sha256) is not str or not _SHA.fullmatch(self.manifest_sha256):
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise PgvectorQueryError("Canonical build/content identities and manifest are required") from None

    @property
    def table(self):
        # A user/config-supplied SQL object name never crosses this boundary.
        return "retrieval_projection.b_" + UUID(self.build_id).hex


@dataclass(frozen=True, slots=True)
class QueryBudget:
    concurrency: int = 4
    total_seconds: float = 3.0
    statement_ms: int = 2000
    exact_cohort_limit: int = 1000
    ef_search: int = 1000
    candidate_pool: int = 1024
    max_scan_tuples: int = 20000

    def __post_init__(self):
        bounds = ((self.concurrency, 1, 8), (self.statement_ms, 1, 5000),
                  (self.exact_cohort_limit, 1, 5000), (self.ef_search, 40, 1000),
                  (self.max_scan_tuples, 1000, 50000), (self.candidate_pool, 101, 4096))
        if (any(type(value) is not int or not low <= value <= high for value, low, high in bounds)
                or type(self.total_seconds) not in {int, float}
                or not math.isfinite(self.total_seconds) or not 0 < self.total_seconds <= 10
                or self.statement_ms > self.total_seconds * 1000
                or self.candidate_pool <= self.ef_search):
            raise PgvectorQueryError("Invalid pgvector query budget")


@dataclass(frozen=True, slots=True)
class SqlNeighbor:
    vector_id: str
    paper_id: str
    content_sha256: str
    vector_sha256: str
    chunk_revision_sha256: str
    distance: float


@dataclass(frozen=True, slots=True)
class CandidateBatch:
    projection: ProjectionSpec
    neighbors: tuple[SqlNeighbor, ...]
    strategy: str
    exhaustive: bool


def _request(vector, top_k, year_min, year_max, excluded_revisions):
    if type(top_k) is not int or not 1 <= top_k <= 100:
        raise PgvectorQueryError("Invalid candidate limit")
    for year in (year_min, year_max):
        if year is not None and (type(year) is not int or not 1 <= year <= 9999):
            raise PgvectorQueryError("Invalid year filter")
    if year_min is not None and year_max is not None and year_min > year_max:
        raise PgvectorQueryError("Invalid year interval")
    if (type(excluded_revisions) not in {tuple, list} or len(excluded_revisions) > 20000
            or any(type(value) is not str or not _SHA.fullmatch(value) for value in excluded_revisions)
            or len(set(excluded_revisions)) != len(excluded_revisions)):
        raise PgvectorQueryError("Invalid revision exclusions")
    try:
        values = validate_vector(vector)
    except ValueError:
        raise PgvectorQueryError("A canonical finite 768-dimensional query vector is required") from None
    return {"query": "[" + ",".join(repr(value) for value in values) + "]", "limit": top_k,
            "year_min": year_min, "year_max": year_max, "excluded": list(excluded_revisions)}


def _neighbors(rows, top_k, year_min, year_max, excluded):
    seen, result = set(), []
    if len(rows) > top_k:
        raise PgvectorQueryError("Candidate result exceeded its bound")
    previous = -1.0
    for row in rows:
        identifier, distance, year = row["vector_id"], row["distance"], row["year"]
        if (type(identifier) is not str or not _IDENTIFIER.fullmatch(identifier) or identifier in seen
                or type(row["paper_id"]) is not str or not 1 <= len(row["paper_id"]) <= 200
                or any(type(row[key]) is not str or not _SHA.fullmatch(row[key])
                       for key in ("content_sha256", "vector_sha256", "chunk_revision_sha256"))
                or row["chunk_revision_sha256"] in excluded
                or type(distance) not in {int, float} or not math.isfinite(distance)
                or not -1e-6 <= distance <= 2 + 1e-6 or distance < previous
                or (year_min is not None or year_max is not None) and (
                    type(year) is not int or year_min is not None and year < year_min
                    or year_max is not None and year > year_max)):
            raise PgvectorQueryError("Candidate bindings, ordering or distance are incompatible")
        previous = distance
        seen.add(identifier)
        result.append(SqlNeighbor(**{key: row[key] for key in _COLUMNS.split(",")},
                                  distance=min(2.0, max(0.0, float(distance)))))
    return tuple(result)


class PgvectorQueries:
    """One process-wide coordinator per event loop and dedicated read engine.

    The engine is dependency-injected; no DSN/credential is accepted here. The
    caller must reserve its pool separately from ordinary API reads/writes.
    Queue wait, connection acquisition and SQL share a hard request deadline.
    """
    def __init__(self, engine, budget=None):
        self.engine = engine
        self.budget = budget or QueryBudget()
        if type(self.budget) is not QueryBudget:
            raise PgvectorQueryError("An exact query budget is required")
        self._slots = asyncio.Semaphore(self.budget.concurrency)

    async def query(self, projection, vector, *, top_k, year_min=None, year_max=None,
                    excluded_revisions=()):
        if type(projection) is not ProjectionSpec:
            raise PgvectorQueryError("An explicit projection identity is required")
        params = _request(vector, top_k, year_min, year_max, excluded_revisions)
        params["candidate_pool"] = self.budget.candidate_pool
        # SQL structure comes only from closed code and canonical UUIDs. All
        # query values, including the exclusion array, remain bind parameters.
        predicate = ("(CAST(:year_min AS integer) IS NULL OR year>=:year_min) AND "
                     "(CAST(:year_max AS integer) IS NULL OR year<=:year_max) AND "
                     "NOT (chunk_revision_sha256=ANY(CAST(:excluded AS text[])))")
        distance = "embedding <=> CAST(:query AS vector(768))"
        try:
            async with asyncio.timeout(self.budget.total_seconds), self._slots:
                async with self.engine.connect() as connection, connection.begin():
                    await connection.execute(sa.text("SET TRANSACTION READ ONLY"))
                    settings = {"statement_timeout": str(self.budget.statement_ms), "lock_timeout": "250ms",
                                "work_mem": "8MB", "hnsw.ef_search": str(self.budget.ef_search),
                                "hnsw.iterative_scan": "relaxed_order",
                                "hnsw.max_scan_tuples": str(self.budget.max_scan_tuples),
                                "hnsw.scan_mem_multiplier": "1"}
                    for key, value in settings.items():
                        await connection.execute(sa.text("SELECT set_config(:key,:value,true)"),
                                                 {"key": key, "value": value})
                    filtered = year_min is not None or year_max is not None or bool(excluded_revisions)
                    cohort = None
                    if filtered:
                        cohort = await connection.scalar(sa.text(
                            f"SELECT count(*) FROM (SELECT 1 FROM {projection.table} WHERE {predicate} "
                            "LIMIT :cohort_limit) cohort"),
                            {**params, "cohort_limit": self.budget.exact_cohort_limit + 1})
                    exhaustive = cohort is not None and cohort <= self.budget.exact_cohort_limit
                    if exhaustive:
                        # The materialization prevents an ANN index scan from
                        # being substituted for the small-cohort exact sort.
                        sql = (f"WITH cohort AS MATERIALIZED (SELECT {_COLUMNS},year,embedding "
                               f"FROM {projection.table} WHERE {predicate}) "
                               f"SELECT {_COLUMNS},year,{distance} AS distance FROM cohort "
                               f'ORDER BY {distance},vector_id COLLATE "C" LIMIT :limit')
                    else:
                        await connection.execute(sa.text("SET LOCAL enable_seqscan=off"))
                        await connection.execute(sa.text("SET LOCAL enable_bitmapscan=off"))
                        # Iteration can discover closer candidates after its
                        # initial frontier. Admit those candidates, then sort
                        # the bounded materialized pool by actual distance.
                        # Strict iteration discarded such late discoveries in
                        # the retained full-corpus English outlier evaluation.
                        sql = (f"WITH candidates AS MATERIALIZED (SELECT {_COLUMNS},year,{distance} AS distance "
                               f"FROM {projection.table} WHERE {predicate} ORDER BY {distance} LIMIT :candidate_pool) "
                               f"SELECT {_COLUMNS},year,distance FROM candidates "
                               'ORDER BY distance,vector_id COLLATE "C" LIMIT :limit')
                    rows = (await connection.execute(sa.text(sql), params)).mappings().all()
                    neighbors = _neighbors(rows, top_k, year_min, year_max, set(excluded_revisions))
                    if cohort is not None and len(neighbors) < min(top_k, cohort):
                        # A filtered graph budget exhaustion is unavailable,
                        # not a successful empty/partial search or a cloud fallback.
                        raise PgvectorUnavailable("Filtered candidate budget exhausted")
                    return CandidateBatch(projection, neighbors,
                                          "exact_filtered" if exhaustive else "hnsw", exhaustive)
        except (PgvectorQueryError, PgvectorUnavailable):
            raise
        except Exception:
            # Database/driver errors may include query values or credentials.
            raise PgvectorUnavailable("pgvector candidate query unavailable") from None
