"""Offline Similar builder. Only HNSW traversal runs in the isolated graph carrier."""

import asyncio
import json
import re
from contextlib import asynccontextmanager
from uuid import UUID

import asyncpg
import sqlalchemy as sa

from services import pgvector_query as pg
from services.retrieval_activation import load_accepted_build_for_frontier
from services.retrieval_readiness import physical_witness
from services.similar_frontier_checkpoint import WIDTH
from services.similar_frontier_release import graph_scope

EXCLUDED = "NOT (chunk_revision_sha256=ANY(CAST(:excluded AS text[])))"
DISTANCE = "embedding <=> CAST(:query AS vector(768))"
ROOTS = "ctid=ANY(CAST(CAST(:roots AS text[]) AS tid[]))"


@asynccontextmanager
async def connect(socket_directory):
    if not socket_directory.is_absolute() or not socket_directory.is_dir():
        raise ValueError("Expected a private Unix socket directory")
    conn = await asyncpg.connect(
        host=str(socket_directory),
        port=5542,
        user="sclib_frontier_scan",
        database="postgres",
        timeout=2,
        server_settings={"default_transaction_read_only": "on"},
    )
    try:
        safe = await conn.fetchval("""
            SELECT current_user='sclib_frontier_scan' AND inet_server_addr() IS NULL
                AND current_setting('listen_addresses')=''
                AND current_setting('server_version_num')='160013'
                AND (SELECT extversion FROM pg_extension WHERE extname='vector')='0.8.7'
                AND NOT has_table_privilege('sclib_private_carrier.carrier','SELECT')
                AND NOT has_schema_privilege('sclib_private_carrier','CREATE')
                AND NOT has_table_privilege('sclib_private_carrier.binding','UPDATE,INSERT,DELETE,TRUNCATE')
        """)
        if safe is not True:
            raise ValueError("Unexpected scratch reader or server")
        yield conn
    finally:
        await conn.close(timeout=2)


async def eligible_roots(scratch, db, table, params, pool_limit):
    await scratch.execute(
        "DECLARE frontier_roots NO SCROLL CURSOR FOR "
        "SELECT sclib_private_carrier.stream($1::text::public.vector(768))::text",
        params["query"],
    )
    seen = set()
    eligible = []
    while len(eligible) < pool_limit:
        needed = pool_limit - len(eligible)
        rows = await scratch.fetch(f"FETCH FORWARD {needed} FROM frontier_roots")
        roots = [row[0] for row in rows]
        if not roots:
            break
        if (
            any(not re.fullmatch(r"\(\d+,\d+\)", root) for root in roots)
            or len(set(roots)) != len(roots)
            or seen.intersection(roots)
        ):
            raise ValueError("Unexpected physical candidate")
        seen.update(roots)
        resolved = (
            await db.execute(
                sa.text(f"SELECT ctid::text,{EXCLUDED} FROM {table} WHERE {ROOTS}"),
                {"roots": roots, "excluded": params["excluded"]},
            )
        ).all()
        allowed = dict(resolved)
        if len(resolved) != len(roots) or allowed.keys() != set(roots):
            # A missing item may be a HOT root. Treating it as dead would change the native prefix.
            raise ValueError("Unresolved physical candidate")
        eligible.extend(root for root in roots if allowed[root])
        if len(roots) < needed:
            break
    await scratch.execute("CLOSE frontier_roots")
    return eligible


async def query(transport, scratch, pin, scope, vector, revisions):
    budget = transport.budget
    if budget != pg.QueryBudget():
        raise ValueError("Carrier requires the qualified source query policy")
    params = pg._request(vector, WIDTH, None, None, revisions)
    table = pin.projection.table
    async with asyncio.timeout(budget.total_seconds), transport._slots:
        async with transport.engine.connect() as db, db.begin():
            await db.execute(
                sa.text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            )
            await transport._global_slot(db)
            await transport._configure(db, budget.source_ef_search)
            current = await load_accepted_build_for_frontier(
                db,
                logical_index=pin.logical_index,
                event_id=UUID(pin.activation_event_id),
            )
            if current != pin:
                raise ValueError("Accepted graph changed")
            # Hold the heap's AccessShare lock to the end of this authoritative snapshot.
            await db.execute(sa.text(f"SELECT 1 FROM {table} WHERE false"))
            witness = await physical_witness(db, pin)
            if graph_scope(witness) != scope:
                raise ValueError("Authoritative graph identity changed")
            async with scratch.transaction(readonly=True, isolation="repeatable_read"):
                binding = await scratch.fetchval(
                    """
                    SELECT scope::text FROM sclib_private_carrier.binding WHERE singleton
                      AND relation='sclib_private_carrier.sealed_hnsw'::regclass
                      AND filenode=pg_relation_filenode(relation)
                      AND bytes=pg_relation_size(relation) AND bytes=$1
                """,
                    witness.graph_bytes,
                )
                if binding is None or json.loads(binding) != scope:
                    raise ValueError("Scratch graph identity mismatch")
                await scratch.execute("""
                    SET LOCAL work_mem='8MB'; SET LOCAL hnsw.ef_search=256;
                    SET LOCAL hnsw.iterative_scan='relaxed_order'; SET LOCAL hnsw.max_scan_tuples=20000;
                    SET LOCAL hnsw.scan_mem_multiplier=1; SET LOCAL statement_timeout='2s';
                    SET LOCAL lock_timeout='250ms';
                """)
                cohort = await db.scalar(
                    sa.text(
                        f"SELECT count(*) FROM (SELECT 1 FROM {table} WHERE {EXCLUDED} LIMIT :cap) eligible"
                    ),
                    {**params, "cap": budget.exact_cohort_limit + 1},
                )
                predicate = EXCLUDED
                async with asyncio.timeout(budget.statement_ms / 1000):
                    if cohort > budget.exact_cohort_limit:
                        params["roots"] = await eligible_roots(
                            scratch, db, table, params, budget.source_candidate_pool
                        )
                        predicate = f"{ROOTS} AND {EXCLUDED}"
                    ranked = (
                        (
                            await db.execute(
                                sa.text(
                                    f"SELECT {pg._COLUMNS},year,{DISTANCE} AS distance FROM {table} WHERE {predicate} "
                                    f'ORDER BY ({DISTANCE})+0,vector_id COLLATE "C" LIMIT :limit'
                                ),
                                params,
                            )
                        )
                        .mappings()
                        .all()
                    )
                    neighbors = pg._neighbors(ranked, WIDTH, None, None, set(revisions))
                    if len(neighbors) != WIDTH:
                        raise ValueError("Incomplete offline ranking")
                    return neighbors
