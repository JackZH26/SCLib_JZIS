"""Read complete Similar candidate lists from release-pinned, read-only SQLite files."""

import asyncio
import hashlib
import json
import os
import sqlite3
import stat
from contextlib import AsyncExitStack, closing
from importlib.resources import files
from pathlib import Path
from uuid import UUID

import sqlalchemy as sa

from services import similar_frontier_checkpoint as checkpoint
from services.pgvector_query import CandidateBatch, PgvectorQueries, QueryBudget, SqlNeighbor

MOUNT = Path("/run/sclib/similar-frontiers")
CONTRACT = "similar-source-55/scalar-v1"


def graph_scope(witness):
    pin = witness.pin
    return {
        "logical_index": pin.logical_index,
        "build": pin.build_id,
        "content": pin.content_id,
        "manifest": pin.manifest_sha256,
        "policy": pin.policy_artifact_sha256,
        "profile": hashlib.sha256(pin.profile_json.encode()).hexdigest(),
        "frontier_sql_contract": CONTRACT,
        "table_oid": witness.table_oid,
        "table_filenode": witness.table_filenode,
        "graph_oid": witness.graph_oid,
        "graph_filenode": witness.graph_filenode,
        "sealed_members": witness.member_count,
    }


def _file_identity(st):
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns


class SimilarFrontiers:
    """The release admission supplies both digests outside the artifact directory."""

    @classmethod
    def from_release(cls, transport):
        # Admission changes ship in the same signed API wheel/image as the reader.
        # Mounted candidate files and environment variables cannot choose their own digests.
        admission = json.loads(
            files("models").joinpath("similar_frontier_admission.json").read_bytes()
        )
        if admission["version"] != "sclib-similar-frontier-admission/1":
            raise ValueError("Unknown Similar frontier admission version")
        return cls(admission["builds"], transport=transport)

    def __init__(self, approved, directory=MOUNT, *, transport):
        if type(transport) is not PgvectorQueries or transport.budget != QueryBudget():
            raise ValueError("The frozen query budget and its global slots are required")
        if len(approved) != 2 or len(set(approved.values())) != 2:
            raise ValueError("Distinct primary and rollback artifacts required")
        self._files = {}
        self._transport = transport
        self._pending = set()
        content = None
        for build, digest in approved.items():
            if str(UUID(build)) != build or not checkpoint.HASH.fullmatch(digest):
                raise ValueError("Invalid Similar release identity")
            path = directory / (digest + ".sqlite")
            identity = _file_identity(path.lstat())
            with path.open("rb") as source:
                st = os.fstat(source.fileno())
                if not stat.S_ISREG(st.st_mode) or _file_identity(st) != identity:
                    raise ValueError("Expected a regular Similar artifact")
                if hashlib.file_digest(source, "sha256").hexdigest() != digest:
                    raise ValueError("Similar artifact digest mismatch")
            uri = path.as_uri() + "?mode=ro&immutable=1"
            with closing(sqlite3.connect(uri, uri=True, timeout=0)) as db:
                db.execute("PRAGMA trusted_schema=OFF")
                row = db.execute("SELECT scope FROM meta WHERE singleton=1").fetchone()
                seal = db.execute("SELECT coverage FROM publication WHERE singleton=1").fetchone()
                if not row or not seal:
                    raise ValueError("Missing Similar publication")
                scope = json.loads(row[0])["scope"]
                coverage = json.loads(seal[0])
                if (
                    row[0] != checkpoint.identity(scope)
                    or scope["build"] != build
                    or scope["frontier_sql_contract"] != CONTRACT
                    or coverage["members"] <= 0
                    or coverage["members"] != scope["sealed_members"]
                ):
                    raise ValueError("Incompatible Similar publication")
                shared = tuple(
                    scope[k]
                    for k in (
                        "logical_index",
                        "content",
                        "manifest",
                        "policy",
                        "profile",
                        "sealed_members",
                    )
                )
                if content is not None and shared != content:
                    raise ValueError(
                        "Primary and rollback must address the same sealed content and policy"
                    )
                content = shared
            if _file_identity(path.lstat()) != identity:
                raise ValueError("Similar artifact changed during verification")
            self._files[build] = (path, identity, scope)

    def require_graph(self, witness):
        entry = self._files.get(witness.pin.build_id)
        if entry is None or entry[2] != graph_scope(witness):
            raise ValueError("Similar graph, content or policy mismatch")
        if _file_identity(entry[0].lstat()) != entry[1]:
            raise ValueError("Verified Similar artifact changed")
        return entry

    def _read(self, witness, paper, sources, excluded, limit):
        path, identity, _ = self.require_graph(witness)
        # immutable=1 ignores journals/WAL and takes no locks. The admitted
        # digest covers the entire standalone file on the read-only mount.
        uri = path.as_uri() + "?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True, timeout=0)) as db:
            db.execute("PRAGMA trusted_schema=OFF")
            exclusion_hash = checkpoint.exclusions_digest(excluded)
            excluded_set = set(excluded)
            batches = []
            for source in sources:
                hits = checkpoint.read(db, paper, source, exclusion_hash, limit)
                if hits is None or any(
                    hit["chunk_revision_sha256"] in excluded_set for hit in hits
                ):
                    raise ValueError("Complete live source frontier unavailable")
                neighbors = tuple(SqlNeighbor(**hit) for hit in hits)
                batches.append(
                    CandidateBatch(witness.pin.projection, neighbors, "sealed_frontier", False)
                )
        if _file_identity(path.lstat()) != identity:
            raise ValueError("Similar artifact changed during lookup")
        return tuple(batches)

    def _finished(self, task):
        self._pending.discard(task)
        if not task.cancelled():
            task.exception()

    async def close(self):
        if self._pending:
            await asyncio.gather(*(asyncio.shield(task) for task in self._pending), return_exceptions=True)

    async def _lookup(self, reservations, witness, paper, sources, excluded, limit):
        # The file read owns both reservations until the OS thread actually finishes.
        async with reservations:
            return await asyncio.to_thread(self._read, witness, paper, sources, excluded, limit)

    async def candidates(self, witness, paper, sources, excluded, limit, *, timeout):
        transport = self._transport
        async with asyncio.timeout(min(timeout, transport.budget.total_seconds)):
            async with AsyncExitStack() as reservations:
                await reservations.enter_async_context(transport._slots)
                connection = await reservations.enter_async_context(transport.engine.connect())
                await reservations.enter_async_context(connection.begin())
                await connection.execute(sa.text("SET TRANSACTION READ ONLY"))
                await transport._global_slot(connection)
                owned = reservations.pop_all()
                try:
                    task = asyncio.create_task(self._lookup(owned, witness, paper, sources, excluded, limit))
                except BaseException:
                    await owned.aclose()
                    raise
                self._pending.add(task)
                task.add_done_callback(self._finished)
                async with asyncio.timeout(transport.budget.statement_ms / 1000):
                    return await asyncio.shield(task)
