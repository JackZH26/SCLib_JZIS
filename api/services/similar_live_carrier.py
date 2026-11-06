"""Live traversal over an admitted, private copy of the sealed HNSW graph.

Only physical candidate discovery uses the carrier. The authoritative database
resolves every row, applies exclusions, computes distances and retains the four
global SQL permits. ContentSimilarity still owns all live rights/currentness and
final response checks. No per-paper cache or offline neighbor inventory is used.
"""

import asyncio
import hashlib
import json
import re
from contextlib import AsyncExitStack, asynccontextmanager
from importlib.resources import files
from pathlib import Path
from uuid import UUID

import asyncpg
import sqlalchemy as sa

from services import pgvector_query as pg
from services.retrieval_candidate import current_read_pin
from services.retrieval_readiness import physical_witness
from services.similar_frontier_release import graph_scope

MOUNT = Path("/run/sclib/similar-carrier")
ROOT = re.compile(r"\([0-9]+,[0-9]+\)\Z")
EXCLUDED = "NOT (chunk_revision_sha256=ANY(CAST(:excluded AS text[])))"
ROOTS = "ctid=ANY(CAST(CAST(:roots AS text[]) AS tid[]))"
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def binding_payload(entry):
    """Bind the operator's verified pages and engine/helper to signed admission."""
    digest = hashlib.sha256(json.dumps(entry, sort_keys=True, separators=(",", ":"),
        allow_nan=False).encode()).hexdigest()
    return {"scope": entry["scope"], "release_manifest_sha256": digest}


async def _check_connection(connection):
    safe = await connection.fetchval("""
        SELECT current_user='sclib_frontier_scan' AND inet_server_addr() IS NULL
          AND current_setting('listen_addresses')=''
          AND current_setting('server_version_num')='160013'
          AND (SELECT extversion FROM pg_extension WHERE extname='vector')='0.8.7'
          AND NOT has_table_privilege('sclib_private_carrier.carrier','SELECT')
          AND NOT has_schema_privilege('sclib_private_carrier','CREATE')
          AND NOT has_table_privilege('sclib_private_carrier.binding','UPDATE,INSERT,DELETE,TRUNCATE')
    """)
    if safe is not True:
        raise pg.PgvectorQueryError("Unexpected private graph reader or engine")


async def eligible_source_roots(scratch, authority, table, queries, excluded, pool_limit,
                                *, year_min=None, year_max=None):
    """Keep each native prefix while resolving a whole round in one heap read.

    Similar may supply two native connections. Each owns a disjoint, ordered
    source partition; the authority still resolves each complete round once.
    All cursors, rounds and final ranking share the caller's ONE 2s budget.
    Transaction rollback closes every cursor on any failure or cancellation.
    """
    predicate = EXCLUDED
    parameters = {"excluded": excluded}
    if year_min is not None:
        predicate += " AND year>=:year_min"
        parameters["year_min"] = year_min
    if year_max is not None:
        predicate += " AND year<=:year_max"
        parameters["year_max"] = year_max
    if year_min is not None or year_max is not None:
        # SQL WHERE rejects NULL years; the eligibility column must do so too.
        predicate = f"COALESCE(({predicate}),false)"
    seen = [set() for _ in queries]
    eligible = [[] for _ in queries]
    active = set(range(len(queries)))
    connections = scratch if isinstance(scratch, tuple) else (scratch,)
    if not 1 <= len(connections) <= 2:
        raise pg.PgvectorQueryError("One or two native source connections required")
    for index, query in enumerate(queries):
        await connections[index % len(connections)].execute(
            f"DECLARE source_{index} NO SCROLL CURSOR FOR "
            "SELECT sclib_private_carrier.stream($1::text::public.vector(768))::text",
            query,
        )
    while active:
        round_roots = {}
        pending = sorted(active)
        async def fetch_partition(partition):
            for index in pending:
                if index % len(connections) != partition:
                    continue
                needed = pool_limit - len(eligible[index])
                rows = await connections[partition].fetch(f"FETCH FORWARD {needed} FROM source_{index}")
                roots = [row[0] for row in rows]
                if (len(roots) > needed or any(type(root) is not str or not ROOT.fullmatch(root) for root in roots)
                        or len(set(roots)) != len(roots) or seen[index].intersection(roots)):
                    raise pg.PgvectorQueryError("Invalid native source candidate inventory")
                seen[index].update(roots)
                round_roots[index] = roots
                if len(roots) < needed:
                    active.remove(index)
        if len(connections) == 1:
            await fetch_partition(0)
        else:
            async with asyncio.TaskGroup() as tasks:
                for partition in range(len(connections)):
                    tasks.create_task(fetch_partition(partition))
        unique = sorted({root for roots in round_roots.values() for root in roots})
        if unique:
            resolved = (await authority.execute(sa.text(
                f"SELECT ctid::text,{predicate} FROM {table} WHERE {ROOTS}"
            ), {"roots": unique, **parameters})).all()
            allowed = dict(resolved)
            # Missing roots may be HOT roots. Silently dropping them changes the
            # native frontier and is never a substitute for an admitted seal.
            if (len(resolved) != len(unique) or allowed.keys() != set(unique)
                    or any(type(value) is not bool for value in allowed.values())):
                raise pg.PgvectorQueryError("Unresolved native source candidate")
            for index, roots in round_roots.items():
                eligible[index].extend(root for root in roots if allowed[root])
                if len(eligible[index]) == pool_limit:
                    active.discard(index)
    for index in range(len(queries)):
        await connections[index % len(connections)].execute(f"CLOSE source_{index}")
    return eligible


class LiveSimilarCarrier:
    @classmethod
    def from_release(cls, transport):
        admission = json.loads(files("models").joinpath("similar_carrier_admission.json").read_bytes())
        if admission["version"] != "sclib-live-similar-carrier/1":
            raise pg.PgvectorQueryError("Unknown live carrier admission")
        return cls(transport, admission["builds"])

    def __init__(self, transport, approved, directory=MOUNT):
        if type(transport) is not pg.PgvectorQueries or transport.budget != pg.QueryBudget():
            raise pg.PgvectorQueryError("The frozen source query budget is required")
        if type(approved) is not dict or len(approved) != 2:
            raise pg.PgvectorQueryError("Primary and rollback graph admission required")
        shared = None
        for build, entry in approved.items():
            scope = entry["scope"]
            if (str(UUID(build)) != build or scope["build"] != build
                    or type(entry["graph_bytes"]) is not int or entry["graph_bytes"] <= 0):
                raise pg.PgvectorQueryError("Invalid graph admission")
            segments = entry["segments"]
            if (type(segments) is not list or not 1 <= len(segments) <= 5
                    or any(segment["part"] != index or type(segment["size"]) is not int
                        or not 0 < segment["size"] <= 2**30 or segment["size"] % 8192
                        or not SHA256.fullmatch(segment["source_stream_sha256"])
                        for index, segment in enumerate(segments))
                    or sum(segment["size"] for segment in segments) != entry["graph_bytes"]
                    or not SHA256.fullmatch(entry["reader_sha256"])
                    or not re.fullmatch(r"sha256:[0-9a-f]{64}", entry["postgres_image_digest"])):
                raise pg.PgvectorQueryError("Complete pinned graph, helper and engine digests required")
            identity = tuple(scope[key] for key in ("logical_index", "content", "manifest", "policy", "profile", "sealed_members"))
            if shared is not None and identity != shared:
                raise pg.PgvectorQueryError("Primary and rollback content/policy differ")
            shared = identity
        self._transport = transport
        self._approved = json.loads(json.dumps(approved, allow_nan=False))
        self._directory = Path(directory)
        if not self._directory.is_absolute():
            raise pg.PgvectorQueryError("Absolute private carrier directory required")
        self._pools = {}
        self._pool_lock = asyncio.Lock()
        self._batch_checkout_lock = asyncio.Lock()

    def require_graph(self, witness):
        entry = self._approved.get(witness.pin.build_id)
        if entry is None or entry["scope"] != graph_scope(witness) or entry["graph_bytes"] != witness.graph_bytes:
            raise pg.PgvectorQueryError("Admitted graph/content/policy changed")
        return entry

    async def _pool(self, witness):
        self.require_graph(witness)
        build = witness.pin.build_id
        async with self._pool_lock:
            if build not in self._pools:
                self._pools[build] = await asyncpg.create_pool(
                    host=str(self._directory / build), port=5542, user="sclib_frontier_scan", database="postgres",
                    min_size=0, max_size=4, timeout=2, command_timeout=2,
                    server_settings={"default_transaction_read_only": "on"}, init=_check_connection,
                )
            return self._pools[build]

    async def _binding(self, scratch, witness):
        value = await scratch.fetchval("""
            SELECT scope::text FROM sclib_private_carrier.binding WHERE singleton
              AND relation='sclib_private_carrier.sealed_hnsw'::regclass
              AND filenode=pg_relation_filenode(relation)
              AND bytes=pg_relation_size(relation) AND bytes=$1
        """, witness.graph_bytes)
        if value is None or json.loads(value) != binding_payload(self.require_graph(witness)):
            raise pg.PgvectorQueryError("Private graph binding changed")

    async def prepare(self, witness):
        # Provisioning and full segment digest verification are release admission
        # work. Requests never build, warm, copy or choose graph files themselves.
        async with asyncio.timeout(2):
            pool = await self._pool(witness)
            async with pool.acquire() as scratch:
                await self._binding(scratch, witness)

    async def close(self):
        pools, self._pools = tuple(self._pools.values()), {}
        try:
            async with asyncio.timeout(3):
                await asyncio.gather(*(pool.close() for pool in pools))
        finally:
            for pool in pools:
                pool.terminate()

    @asynccontextmanager
    async def _source_connections(self, witness, count):
        pool = await self._pool(witness)
        async with AsyncExitStack() as stack:
            # Reserve the bounded pair together: two batches must never each
            # hold one connection while waiting for the other's second one.
            async with self._batch_checkout_lock:
                connections = tuple([await stack.enter_async_context(pool.acquire())
                                     for _ in range(min(count, 2))])
            for connection in connections:
                await stack.enter_async_context(connection.transaction(readonly=True, isolation="repeatable_read"))
                await self._binding(connection, witness)
                await connection.execute("""
                    SET LOCAL work_mem='8MB'; SET LOCAL hnsw.ef_search=256;
                    SET LOCAL hnsw.iterative_scan='relaxed_order';
                    SET LOCAL hnsw.max_scan_tuples=20000; SET LOCAL hnsw.scan_mem_multiplier=1;
                    SET LOCAL statement_timeout='2s'; SET LOCAL lock_timeout='250ms';
                """)
            yield connections

    async def query(self, witness, vector, *, top_k, year_min=None, year_max=None,
                    excluded_revisions=()):
        """Search/Ask use their original 1000/1024 graph budget and exact path.

        Only graph traversal moves to the admitted carrier. The authoritative
        transaction still owns filtering, exact distances, ordering and the
        shared SQL permit. The existing coordinator verifies live source use.
        """
        self.require_graph(witness)
        params = pg._request(vector, top_k, year_min, year_max, excluded_revisions)
        transport = self._transport
        table = witness.pin.projection.table
        # Match the transport's closed predicate shapes. An empty exclusion
        # array must not turn a year-index-only cohort count into a heap read.
        predicate = " AND ".join([
            *(["year>=:year_min"] if year_min is not None else []),
            *(["year<=:year_max"] if year_max is not None else []),
            *([EXCLUDED] if params["excluded"] else []),
        ]) or "true"
        filtered = year_min is not None or year_max is not None or bool(params["excluded"])
        ceiling = (transport.budget.year_exact_cohort_limit
                   if year_min is not None or year_max is not None else transport.budget.exact_cohort_limit)
        try:
            async with asyncio.timeout(transport.budget.total_seconds), transport._slots:
                async with transport.engine.connect() as authority, authority.begin():
                    await authority.execute(sa.text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
                    await transport._global_slot(authority)
                    await transport._configure(authority, transport.budget.ef_search)
                    await current_read_pin(authority, witness.pin)
                    await authority.execute(sa.text(f"SELECT 1 FROM {table} WHERE false"))
                    if await physical_witness(authority, witness.pin) != witness:
                        raise pg.PgvectorQueryError("Authoritative projection changed")
                    cohort = None
                    if filtered:
                        cohort = await authority.scalar(sa.text(
                            f"SELECT count(*) FROM (SELECT 1 FROM {table} WHERE {predicate} LIMIT :cap) eligible"
                        ), {**params, "cap": ceiling + 1})
                    exhaustive = cohort is not None and cohort <= ceiling
                    async with asyncio.timeout(transport.budget.statement_ms / 1000):
                        if not exhaustive:
                            pool = await self._pool(witness)
                            async with pool.acquire() as scratch:
                                async with scratch.transaction(readonly=True, isolation="repeatable_read"):
                                    await self._binding(scratch, witness)
                                    await scratch.execute("""
                                        SET LOCAL work_mem='8MB'; SET LOCAL hnsw.ef_search=1000;
                                        SET LOCAL hnsw.iterative_scan='relaxed_order';
                                        SET LOCAL hnsw.max_scan_tuples=20000; SET LOCAL hnsw.scan_mem_multiplier=1;
                                        SET LOCAL statement_timeout='2s'; SET LOCAL lock_timeout='250ms';
                                    """)
                                    groups = await eligible_source_roots(scratch, authority, table,
                                        [params["query"]], params["excluded"], transport.budget.candidate_pool,
                                        year_min=year_min, year_max=year_max)
                            params["roots"] = groups[0]
                            predicate = ROOTS + " AND " + predicate
                        distance = "embedding <=> CAST(:query AS vector(768))"
                        if exhaustive:
                            # Score the full cohort once and carry only the
                            # physical root and tie key through the top-k sort.
                            # +0 preserves the non-HNSW exact path. Hydrate the
                            # bounded winners in this same authoritative snapshot.
                            columns = ",".join("p." + column for column in pg._COLUMNS.split(","))
                            statement = ("WITH nearest AS MATERIALIZED ("
                                f"SELECT ctid AS root,vector_id,({distance})+0 AS distance FROM {table} "
                                f'WHERE {predicate} ORDER BY distance,vector_id COLLATE "C" LIMIT :limit) '
                                f"SELECT {columns},p.year,n.distance FROM nearest n "
                                f"JOIN {table} p ON p.ctid=n.root "
                                'ORDER BY n.distance,n.vector_id COLLATE "C"')
                        else:
                            statement = (f"SELECT {pg._COLUMNS},year,{distance} AS distance FROM {table} "
                                f'WHERE {predicate} ORDER BY ({distance})+0,vector_id COLLATE "C" LIMIT :limit')
                        rows = (await authority.execute(sa.text(statement), params)).mappings().all()
                        neighbors = pg._neighbors(rows, top_k, year_min, year_max, set(params["excluded"]))
                        if cohort is not None and len(neighbors) < min(top_k, cohort):
                            raise pg.PgvectorUnavailable("Filtered candidate budget exhausted")
                        return pg.CandidateBatch(witness.pin.projection, neighbors,
                            "exact_filtered" if exhaustive else "hnsw", exhaustive)
        except (pg.PgvectorQueryError, pg.PgvectorUnavailable):
            raise
        except Exception:
            raise pg.PgvectorUnavailable("Live semantic candidate query unavailable") from None

    async def query_many(self, witness, vectors, *, top_k, excluded_revisions):
        self.require_graph(witness)
        if type(vectors) not in {tuple, list} or not 1 <= len(vectors) <= 20:
            raise pg.PgvectorQueryError("Complete bounded source vectors required")
        if type(top_k) is not int or not 1 <= top_k <= 55:
            raise pg.PgvectorQueryError("Bounded Similar candidate limit required")
        # Validate and detach EVERY vector and exclusion before pool or SQL work.
        requests = [pg._request(vector, top_k, None, None, excluded_revisions) for vector in vectors]
        queries = [request["query"] for request in requests]
        excluded = requests[0]["excluded"]
        transport = self._transport
        table = witness.pin.projection.table
        try:
            async with asyncio.timeout(transport.budget.total_seconds), transport._slots:
                async with transport.engine.connect() as authority, authority.begin():
                    await authority.execute(sa.text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
                    await transport._global_slot(authority)
                    await transport._configure(authority, transport.budget.source_ef_search)
                    await current_read_pin(authority, witness.pin)
                    await authority.execute(sa.text(f"SELECT 1 FROM {table} WHERE false"))
                    observed = await physical_witness(authority, witness.pin)
                    if observed != witness:
                        raise pg.PgvectorQueryError("Authoritative projection changed")
                    cohort = await authority.scalar(sa.text(
                        f"SELECT count(*) FROM (SELECT 1 FROM {table} WHERE {EXCLUDED} LIMIT :cap) eligible"
                    ), {"excluded": excluded, "cap": transport.budget.exact_cohort_limit + 1})
                    exhaustive = cohort <= transport.budget.exact_cohort_limit
                    params = {"queries": queries, "excluded": excluded, "limit": top_k}
                    async with asyncio.timeout(transport.budget.statement_ms / 1000):
                        if not exhaustive:
                            async with self._source_connections(witness, len(queries)) as connections:
                                groups = await eligible_source_roots(connections, authority, table, queries,
                                    excluded, transport.budget.source_candidate_pool)
                            params["root_groups"] = json.dumps(groups)
                        distance = "embedding <=> inputs.query"
                        predicate = EXCLUDED if exhaustive else (
                            "ctid=ANY(ARRAY(SELECT jsonb_array_elements_text(CAST(:root_groups AS jsonb)"
                            "->CAST(inputs.source_order-1 AS integer))::tid)) AND " + EXCLUDED)
                        per_source = (f"SELECT {pg._COLUMNS},year,{distance} AS distance FROM {table} "
                            f'WHERE {predicate} ORDER BY ({distance})+0,vector_id COLLATE "C" LIMIT :limit')
                        statement = ("WITH inputs AS MATERIALIZED (SELECT raw.query::vector(768) AS query,source_order "
                            "FROM unnest(CAST(:queries AS text[])) WITH ORDINALITY AS raw(query,source_order)) "
                            "SELECT inputs.source_order,neighbor.* FROM inputs "
                            f"CROSS JOIN LATERAL ({per_source}) neighbor "
                            'ORDER BY inputs.source_order,neighbor.distance,neighbor.vector_id COLLATE "C"')
                        rows = (await authority.execute(sa.text(statement), params)).mappings().all()
                        grouped = [[] for _ in vectors]
                        for row in rows:
                            ordinal = row["source_order"]
                            if type(ordinal) is not int or not 1 <= ordinal <= len(grouped):
                                raise pg.PgvectorQueryError("Invalid source batch order")
                            grouped[ordinal - 1].append(row)
                        batches = []
                        for source in grouped:
                            neighbors = pg._neighbors(source, top_k, None, None, set(excluded))
                            if len(neighbors) < min(top_k, cohort):
                                raise pg.PgvectorUnavailable("Incomplete live source frontier")
                            batches.append(pg.CandidateBatch(witness.pin.projection, neighbors,
                                "exact_filtered" if exhaustive else "hnsw", exhaustive))
                        return tuple(batches)
        except pg.PgvectorQueryError:
            raise
        except Exception:
            raise pg.PgvectorUnavailable("Live Similar source batch unavailable") from None
