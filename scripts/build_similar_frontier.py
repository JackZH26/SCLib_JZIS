"""Build a bounded, resumable offline slice of one previously accepted pgvector graph."""

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import shutil
import struct
import sys
import time
from contextlib import AsyncExitStack, asynccontextmanager, closing
from dataclasses import asdict
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import sqlalchemy as sa

from services import similar_frontier_checkpoint as checkpoint
from services.pgvector_query import PgvectorQueries
from services.retrieval_activation import load_accepted_build_for_frontier
from services.retrieval_readiness import physical_witness
from services.similar_frontier_release import graph_scope


@asynccontextmanager
async def snapshot(sessions):
    async with sessions() as db:
        await db.execute(
            sa.text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        )
        await db.execute(sa.text("SET LOCAL statement_timeout='2000ms'"))
        await db.execute(sa.text("SET LOCAL lock_timeout='250ms'"))
        yield db


async def accepted_scope(sessions, logical_index, event, build, content):
    async with snapshot(sessions) as db:
        pin = await load_accepted_build_for_frontier(
            db, logical_index=logical_index, event_id=event
        )
        if pin is None or (pin.build_id, pin.content_id) != (str(build), str(content)):
            raise ValueError("Sealed build and accepted event mismatch")
        witness = await physical_witness(db, pin)
        return pin, graph_scope(witness)


async def next_paper(sessions, pin, after):
    async with snapshot(sessions) as db:
        return await db.scalar(
            sa.text(
                "SELECT paper_id FROM retrieval_content_members_v2 "
                "WHERE content_id=:id AND paper_id>:after ORDER BY paper_id LIMIT 1"
            ),
            {"id": UUID(pin.content_id), "after": after},
        )


async def inputs(sessions, pin, paper):
    async with snapshot(sessions) as db:
        if await db.scalar(
            sa.text(
                "SELECT EXISTS(SELECT FROM pg_stat_activity WHERE "
                "datname=current_database() AND application_name='pg_dump')"
            )
        ):
            raise ValueError("Backup window active")
        params = {"id": UUID(pin.content_id), "paper": paper}
        members = (
            (
                await db.execute(
                    sa.text(
                        "SELECT vector_id,chunk_revision_sha256,vector_sha256,content_sha256 FROM retrieval_content_members_v2 "
                        'WHERE content_id=:id AND paper_id=:paper ORDER BY vector_id COLLATE "C" LIMIT 20001'
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )
        revisions = tuple(m["chunk_revision_sha256"] for m in members)
        exclusion_sha = checkpoint.exclusions_digest(revisions)
        ids = [m["vector_id"] for m in members[:20]]
        rows = (
            (
                await db.execute(
                    sa.text(
                        f"SELECT vector_id,vector_sha256,content_sha256,chunk_revision_sha256,substring(vector_send(embedding) FROM 5) AS raw "
                        f"FROM {pin.projection.table} WHERE paper_id=:paper AND vector_id=ANY(CAST(:ids AS text[]))"
                    ),
                    {"ids": ids, "paper": paper},
                )
            )
            .mappings()
            .all()
        )
        by_id = {r["vector_id"]: r for r in rows}
        sources = {}
        for member in members[:20]:
            row = by_id[member["vector_id"]]
            raw = bytes(row["raw"])
            if (
                any(row[k] != member[k] for k in checkpoint.BINDINGS)
                or len(raw) != 3072
                or hashlib.sha256(raw).hexdigest() != member["vector_sha256"]
            ):
                raise ValueError("Sealed source vector mismatch")
            sources[member["vector_sha256"]] = raw
        return revisions, exclusion_sha, sources


async def build_slice(
    sessions,
    transport,
    path,
    *,
    logical_index,
    event,
    build,
    content,
    max_sources,
    max_papers,
    interval,
    minimum_free_bytes,
    carrier=None,
):
    if not (
        1 <= max_sources <= 256
        and 1 <= max_papers <= 128
        and 0.1 <= interval <= 60
        and minimum_free_bytes > 0
    ):
        raise ValueError("Explicit bounded build slice required")
    pin, scope = await accepted_scope(sessions, logical_index, event, build, content)
    written = papers = 0
    exhausted = False
    with path.with_suffix(path.suffix + ".lock").open("ab") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if shutil.disk_usage(path.parent).free < minimum_free_bytes:
            raise ValueError("Insufficient free space")
        if not path.exists():
            checkpoint.create(path, scope)
        with closing(checkpoint.open_existing(path, scope, writable=True)) as db:
            with db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS build_cursor (singleton INTEGER PRIMARY KEY CHECK(singleton=1), paper TEXT NOT NULL)"
                )
                db.execute("INSERT OR IGNORE INTO build_cursor VALUES (1,'')")
            (after,) = db.execute(
                "SELECT paper FROM build_cursor WHERE singleton=1"
            ).fetchone()
            while papers < max_papers and written < max_sources:
                paper = await next_paper(sessions, pin, after)
                if paper is None:
                    exhausted = True
                    break
                revisions, exclusion_sha, sources = await inputs(sessions, pin, paper)
                for source, raw in sources.items():
                    if (
                        checkpoint.read(
                            db, paper, source, exclusion_sha, checkpoint.WIDTH
                        )
                        is not None
                    ):
                        continue
                    if written == max_sources:
                        break
                    if shutil.disk_usage(path.parent).free < minimum_free_bytes:
                        raise ValueError("Insufficient free space")
                    started = time.monotonic()
                    vector = struct.unpack("!768f", raw)
                    if carrier is None:
                        batch = await transport._query(
                            pin.projection,
                            vector,
                            top_k=checkpoint.WIDTH,
                            year_min=None,
                            year_max=None,
                            excluded_revisions=revisions,
                            ef_search=transport.budget.source_ef_search,
                            candidate_pool=transport.budget.source_candidate_pool,
                        )
                        neighbors = batch.neighbors
                    else:
                        from similar_frontier_carrier import query

                        neighbors = await query(
                            transport, carrier, pin, scope, vector, revisions
                        )
                    checkpoint.save(
                        db,
                        paper,
                        source,
                        exclusion_sha,
                        [asdict(hit) for hit in neighbors],
                    )
                    written += 1
                    await asyncio.sleep(max(0, interval - (time.monotonic() - started)))
                else:
                    with db:
                        db.execute(
                            "UPDATE build_cursor SET paper=? WHERE singleton=1",
                            (paper,),
                        )
                    after = paper
                    papers += 1
            _, final_scope = await accepted_scope(
                sessions, logical_index, event, build, content
            )
            if final_scope != scope:
                raise ValueError("Sealed graph changed during build")
    return {
        "new_sources": written,
        "completed_papers": papers,
        "inventory_exhausted": exhausted,
    }


async def main():
    from models.db import get_engine, get_session_factory

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--logical-index", required=True)
    for name in ("event", "build", "content"):
        parser.add_argument("--" + name, type=UUID, required=True)
    parser.add_argument("--max-sources", type=int, required=True)
    parser.add_argument("--max-papers", type=int, required=True)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument(
        "--carrier-socket",
        type=Path,
        help="Verified offline graph carrier Unix socket directory",
    )
    args = vars(parser.parse_args())
    socket = args.pop("carrier_socket")
    path = args.pop("checkpoint")
    os.umask(0o077)
    engine = get_engine()
    try:
        async with AsyncExitStack() as stack:
            carrier = None
            if socket is not None:
                from similar_frontier_carrier import connect

                carrier = await stack.enter_async_context(connect(socket))
            result = await build_slice(
                get_session_factory(),
                PgvectorQueries(engine),
                path,
                minimum_free_bytes=210 * 2**30,
                carrier=carrier,
                **args,
            )
        print(json.dumps(result))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        sys.exit("Similar build stopped: " + type(exc).__name__)
