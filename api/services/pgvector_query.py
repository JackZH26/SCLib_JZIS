"""Bounded SQL candidate transport for independently identified projections.

This module is deliberately not wired into Search/Ask/Similar yet. A projection
spec is an address, not a validation receipt or an activation. The v2 publisher
and read coordinator must select a validated build from the database, check its
content bindings, and hydrate candidates with current evidence/rights checks.
No embedding RPC, Vertex fallback, mutable Chunk lookup or activation occurs here.
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import re
from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa

from services.embedding_contract import validate_vector

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,200}\Z")
_COLUMNS = "vector_id,paper_id,content_sha256,vector_sha256,chunk_revision_sha256"
_SQL_SLOT_KEYS = tuple(int.from_bytes(hashlib.sha256(
    f'sclib-pgvector-sql-slot/1:{number}'.encode()).digest()[:8], 'big', signed=True) for number in range(4))


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
    year_exact_cohort_limit: int = 200000
    ef_search: int = 1000
    candidate_pool: int = 1024
    source_ef_search: int = 256
    source_candidate_pool: int = 257
    max_scan_tuples: int = 20000

    def __post_init__(self):
        bounds = ((self.concurrency, 1, 8), (self.statement_ms, 1, 5000),
                  (self.exact_cohort_limit, 1, 5000), (self.year_exact_cohort_limit, 1, 200000), (self.ef_search, 40, 1000),
                  (self.max_scan_tuples, 1000, 50000), (self.candidate_pool, 101, 4096),
                  (self.source_ef_search, 40, 1000), (self.source_candidate_pool, 101, 4096))
        if (any(type(value) is not int or not low <= value <= high for value, low, high in bounds)
                or type(self.total_seconds) not in {int, float}
                or not math.isfinite(self.total_seconds) or not 0 < self.total_seconds <= 10
                or self.statement_ms > self.total_seconds * 1000
                or self.candidate_pool <= self.ef_search
                or self.source_candidate_pool <= self.source_ef_search):
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

    async def _global_slot(self, connection):
        # Transaction locks share the four SQL permits across independent API
        # processes. Rollback, cancellation or disconnect releases a permit.
        # Metadata connections and publishers do not acquire these keys.
        while await connection.scalar(sa.text(
            'SELECT slot_key FROM unnest(CAST(:keys AS bigint[])) AS slots(slot_key) '
            'WHERE pg_catalog.pg_try_advisory_xact_lock(slot_key) LIMIT 1'),
            {'keys': list(_SQL_SLOT_KEYS)}) is None:
            await asyncio.sleep(.02)

    async def query_many(self, projection, vectors, *, top_k, year_min=None, year_max=None,
                         excluded_revisions=()):
        """One bounded Similar request, all-or-nothing and in source order.

        The outer deadline includes queue/pool wait. Individual
        source vectors share one statement and this coordinator's process-wide
        SQL semaphore. The statement timeout covers the complete batch. Never
        publish a partial successful inventory after one source vector fails.
        """
        if type(projection) is not ProjectionSpec:
            raise PgvectorQueryError("An explicit projection identity is required")
        if type(vectors) not in {list, tuple} or not 1 <= len(vectors) <= 20:
            raise PgvectorQueryError("A bounded nonempty source vector inventory is required")
        # Detach and validate the entire inventory before scheduling any SQL.
        # An invalid final item must not execute a valid prefix of the batch.
        checked = []
        for vector in vectors:
            _request(vector, top_k, year_min, year_max, excluded_revisions)
            checked.append(tuple(validate_vector(vector)))
        excluded = tuple(excluded_revisions)
        params = _request(checked[0], top_k, year_min, year_max, excluded)
        params['queries'] = [_request(vector, top_k, year_min, year_max, excluded)['query'] for vector in checked]
        params['candidate_pool'] = self.budget.source_candidate_pool
        predicate = " AND ".join([
            *(["year>=:year_min"] if year_min is not None else []),
            *(["year<=:year_max"] if year_max is not None else []),
            *(["NOT (chunk_revision_sha256=ANY(CAST(:excluded AS text[])))"] if excluded else []),
        ]) or "true"
        distance = "embedding <=> inputs.query"
        try:
            async with asyncio.timeout(self.budget.total_seconds), self._slots:
                async with self.engine.connect() as connection, connection.begin():
                    await connection.execute(sa.text("SET TRANSACTION READ ONLY"))
                    await self._global_slot(connection)
                    await self._configure(connection, self.budget.source_ef_search)
                    filtered = year_min is not None or year_max is not None or bool(excluded)
                    cohort = None
                    if filtered:
                        ceiling = (self.budget.year_exact_cohort_limit if year_min is not None or year_max is not None
                                   else self.budget.exact_cohort_limit)
                        cohort = await connection.scalar(sa.text(
                            f"SELECT count(*) FROM (SELECT 1 FROM {projection.table} WHERE {predicate} "
                            "LIMIT :cohort_limit) cohort"), {**params, 'cohort_limit': ceiling + 1})
                    exhaustive = cohort is not None and cohort <= ceiling
                    if exhaustive:
                        per_source = (f"SELECT {_COLUMNS},year,{distance} AS distance FROM {projection.table} "
                            f'WHERE {predicate} ORDER BY ({distance})+0,vector_id COLLATE "C" LIMIT :limit')
                    else:
                        await connection.execute(sa.text("SELECT set_config('enable_seqscan','off',true),"
                                                         "set_config('enable_bitmapscan','off',true)"))
                        per_source = (f"WITH candidates AS MATERIALIZED (SELECT {_COLUMNS},year,{distance} AS distance "
                            f"FROM {projection.table} WHERE {predicate} ORDER BY {distance} LIMIT :candidate_pool) "
                            f"SELECT {_COLUMNS},year,distance FROM candidates "
                            'ORDER BY distance,vector_id COLLATE "C" LIMIT :limit')
                    # Each correlated source retains its own candidate frontier
                    # and exact distance ordering. One statement owns the same
                    # shared SQL permit and deadline for the complete inventory.
                    statement = ("WITH inputs AS MATERIALIZED (SELECT raw.query::vector(768) AS query,source_order "
                        "FROM unnest(CAST(:queries AS text[])) WITH ORDINALITY AS raw(query,source_order)) "
                        "SELECT inputs.source_order,neighbor.* FROM inputs "
                        f"CROSS JOIN LATERAL ({per_source}) neighbor "
                        'ORDER BY inputs.source_order,neighbor.distance,neighbor.vector_id COLLATE "C"')
                    rows = (await connection.execute(sa.text(statement), params)).mappings().all()
                    grouped = [[] for _ in checked]
                    for row in rows:
                        ordinal = row['source_order']
                        if type(ordinal) is not int or not 1 <= ordinal <= len(checked):
                            raise PgvectorQueryError('Source batch ordering is incompatible')
                        grouped[ordinal - 1].append(row)
                    batches = []
                    for source in grouped:
                        neighbors = _neighbors(source, top_k, year_min, year_max, set(excluded))
                        if cohort is not None and len(neighbors) < min(top_k, cohort):
                            raise PgvectorUnavailable('Filtered source candidate budget exhausted')
                        batches.append(CandidateBatch(projection, neighbors,
                            'exact_filtered' if exhaustive else 'hnsw', exhaustive))
                    return tuple(batches)
        except PgvectorQueryError:
            raise
        except Exception:
            raise PgvectorUnavailable("pgvector source batch unavailable") from None

    async def _configure(self, connection, ef_search):
        settings = {"statement_timeout": str(self.budget.statement_ms), "lock_timeout": "250ms",
                    "work_mem": "8MB", "hnsw.ef_search": str(ef_search),
                    "hnsw.iterative_scan": "relaxed_order",
                    "hnsw.max_scan_tuples": str(self.budget.max_scan_tuples),
                    "hnsw.scan_mem_multiplier": "1"}
        setup = ",".join(f"set_config('{key}',:setting_{index},true)"
                         for index, key in enumerate(settings))
        await connection.execute(sa.text("SELECT " + setup),
            {f"setting_{index}": value for index, value in enumerate(settings.values())})

    async def query(self, projection, vector, *, top_k, year_min=None, year_max=None,
                    excluded_revisions=()):
        return await self._query(projection, vector, top_k=top_k, year_min=year_min, year_max=year_max,
            excluded_revisions=excluded_revisions, ef_search=self.budget.ef_search,
            candidate_pool=self.budget.candidate_pool)

    async def _query(self, projection, vector, *, top_k, year_min, year_max,
                     excluded_revisions, ef_search, candidate_pool):
        if type(projection) is not ProjectionSpec:
            raise PgvectorQueryError("An explicit projection identity is required")
        params = _request(vector, top_k, year_min, year_max, excluded_revisions)
        params["candidate_pool"] = candidate_pool
        # SQL structure comes only from closed code and canonical UUIDs. All
        # query values, including the exclusion array, remain bind parameters.
        # Select only closed predicate shapes after input validation. Avoid
        # nullable OR terms obscuring the year index in a generic prepared plan.
        predicate = " AND ".join([
            *(["year>=:year_min"] if year_min is not None else []),
            *(["year<=:year_max"] if year_max is not None else []),
            *(["NOT (chunk_revision_sha256=ANY(CAST(:excluded AS text[])))"] if excluded_revisions else []),
        ]) or "true"
        distance = "embedding <=> CAST(:query AS vector(768))"
        try:
            async with asyncio.timeout(self.budget.total_seconds), self._slots:
                async with self.engine.connect() as connection, connection.begin():
                    await connection.execute(sa.text("SET TRANSACTION READ ONLY"))
                    await self._global_slot(connection)
                    await self._configure(connection, ef_search)
                    filtered = year_min is not None or year_max is not None or bool(excluded_revisions)
                    cohort = None
                    # Year filtering has a measured exact path. Source-only
                    # exclusions keep their small count ceiling; Similar must
                    # not count 200k members for every stored source vector.
                    exact_limit=(self.budget.year_exact_cohort_limit if year_min is not None or year_max is not None
                        else self.budget.exact_cohort_limit)
                    if filtered:
                        cohort = await connection.scalar(sa.text(
                            f"SELECT count(*) FROM (SELECT 1 FROM {projection.table} WHERE {predicate} "
                            "LIMIT :cohort_limit) cohort"),
                            {**params, "cohort_limit": exact_limit + 1})
                    exhaustive = cohort is not None and cohort <= exact_limit
                    if exhaustive:
                        # The non-indexable distance expression forces complete
                        # exact scoring. Keep only result fields in the sort,
                        # rather than materializing every 3-KiB vector.
                        sql = (f"SELECT {_COLUMNS},year,{distance} AS distance FROM {projection.table} "
                               f'WHERE {predicate} ORDER BY ({distance})+0,vector_id COLLATE "C" LIMIT :limit')
                    else:
                        await connection.execute(sa.text("SELECT set_config('enable_seqscan','off',true),"
                                                         "set_config('enable_bitmapscan','off',true)"))
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
