"""Publish a standalone, digest-addressed file after checking every sealed member."""

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
from tempfile import TemporaryDirectory

import similar_frontier_checkpoint as checkpoint


def publish(
    source, directory, scope, members, *, sealed_member_count, minimum_free_bytes=0
):
    """The caller supplies an independent ordered member stream from the sealed graph."""
    if scope.get("sealed_members") != sealed_member_count:
        raise ValueError("Publication scope differs from sealed member count")
    directory = Path(directory)
    # Snapshot the resumable builder first. Coverage, the digest and the file
    # admitted by the release all refer to these same bytes, including any
    # committed WAL rows. An interrupted publication cannot replace a release.
    with TemporaryDirectory(dir=directory) as work:
        snapshot = Path(work) / "frontier.sqlite"
        with (
            closing(checkpoint.open_existing(source, scope)) as src,
            closing(sqlite3.connect(snapshot)) as dst,
        ):
            size = (
                src.execute("PRAGMA page_count").fetchone()[0]
                * src.execute("PRAGMA page_size").fetchone()[0]
            )
            if shutil.disk_usage(directory).free < minimum_free_bytes + size:
                raise ValueError("Insufficient space for standalone publication")

            def keep_reserve(status, remaining, total):
                if shutil.disk_usage(directory).free < minimum_free_bytes:
                    raise ValueError("Publication disk reserve reached")

            src.backup(dst, pages=4096, progress=keep_reserve)
            dst.execute("PRAGMA journal_mode=DELETE")
        coverage = checkpoint.verify_coverage(
            snapshot, scope, members, sealed_member_count=sealed_member_count
        )
        with (
            closing(checkpoint.open_existing(snapshot, scope, writable=True)) as db,
            db,
        ):
            if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("Invalid Similar database")
            db.execute(
                "CREATE TABLE publication (singleton INTEGER PRIMARY KEY CHECK(singleton=1), coverage TEXT NOT NULL)"
            )
            db.execute(
                "INSERT INTO publication VALUES (1,?)",
                (json.dumps(coverage, sort_keys=True),),
            )
        snapshot.chmod(0o444)
        with snapshot.open("rb") as file:
            os.fsync(file.fileno())
            digest = hashlib.file_digest(file, "sha256").hexdigest()
        destination = directory / (digest + ".sqlite")
        try:
            os.link(snapshot, destination)
        except FileExistsError:
            with destination.open("rb") as existing:
                if (
                    destination.is_symlink()
                    or hashlib.file_digest(existing, "sha256").hexdigest() != digest
                ):
                    raise ValueError("Conflicting Similar publication") from None
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        return {
            "scope": scope,
            "coverage": coverage,
            "sha256": digest,
            "bytes": snapshot.stat().st_size,
        }


def sealed_members(db, content, maximum):
    """Use the content/paper index for discovery, then sort only bounded paper groups."""
    import sqlalchemy as sa

    papers = []
    after = ""
    while True:
        page = (
            db.execute(
                sa.text(
                    "SELECT DISTINCT paper_id FROM retrieval_content_members_v2 WHERE content_id=:content "
                    "AND paper_id>:after ORDER BY paper_id LIMIT 128"
                ),
                {"content": content, "after": after},
            )
            .scalars()
            .all()
        )
        if not page:
            break
        papers.extend(page)
        if len(papers) > maximum:
            raise ValueError("Paper inventory exceeds the sealed member count")
        after = page[-1]
    # Database-native collation permits an index-only scan. Restore the C
    # ordering required by the independent coverage verifier before emission.
    papers.sort()
    for offset in range(0, len(papers), 16):
        rows = db.execute(
            sa.text(
                "SELECT paper_id,vector_id,content_sha256,vector_sha256,chunk_revision_sha256 "
                "FROM retrieval_content_members_v2 WHERE content_id=:content AND paper_id=ANY(CAST(:papers AS text[])) "
                'ORDER BY paper_id COLLATE "C",vector_id COLLATE "C"'
            ).execution_options(yield_per=512),
            {"content": content, "papers": papers[offset : offset + 16]},
        )
        with rows:
            yield from rows.mappings()


def publish_accepted(source, directory, *, logical_index, event, build, content):
    """Read only the independently sealed member inventory; no text or embeddings."""
    import asyncio
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
    import sqlalchemy as sa
    from models.db import get_engine, get_session_factory
    from build_similar_frontier import accepted_scope

    async def resolve():
        engine = get_engine()
        try:
            _, scope = await accepted_scope(
                get_session_factory(), logical_index, event, build, content
            )
            return scope, engine.url.set(drivername="postgresql+psycopg2")
        finally:
            await engine.dispose()

    scope, url = asyncio.run(resolve())
    engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
    try:
        with engine.connect() as db, db.begin():
            db.exec_driver_sql(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
            )
            db.exec_driver_sql("SET LOCAL statement_timeout='2000ms'")
            db.exec_driver_sql("SET LOCAL lock_timeout='250ms'")

            result = publish(
                source,
                directory,
                scope,
                sealed_members(db, content, scope["sealed_members"]),
                sealed_member_count=scope["sealed_members"],
                minimum_free_bytes=210 * 2**30,
            )
    finally:
        engine.dispose()
    current, _ = asyncio.run(resolve())
    if current != scope:
        raise ValueError("Publication scope changed; file cannot be admitted")
    return result


if __name__ == "__main__":
    import argparse
    import sys
    from uuid import UUID

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--logical-index", required=True)
    for name in ("event", "build", "content"):
        parser.add_argument("--" + name, type=UUID, required=True)
    args = vars(parser.parse_args())
    os.umask(0o077)
    try:
        print(
            json.dumps(
                publish_accepted(args.pop("checkpoint"), args.pop("directory"), **args)
            )
        )
    except Exception as exc:
        sys.exit("Similar publication stopped: " + type(exc).__name__)
