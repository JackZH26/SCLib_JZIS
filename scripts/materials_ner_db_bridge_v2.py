"""Transactional private proposal/1+2 importer with exact relational readback.

Run locally with the matching ingestion and API sources available. The legacy
remote bridge is frozen. This module neither grants access nor promotes claims.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
for part in ("api", "ingestion"):
    sys.path.insert(0, str(REPO / part))

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from ingestion.materials_ner.proposals import verify_packet
from models import materials_ner_proposals_v1 as base, materials_ner_proposals_v2 as schema
from services.materials_proposal_storage import COLUMNS, INSERT_ORDER, canonical, projected_rows, verify_readback


async def apply_packet(connection, packet):
    verify_packet(packet)
    rows = projected_rows(packet)
    return await _apply_projected_packet(connection, packet, rows)


async def _apply_projected_packet(connection, packet, rows):
    """Internal write phase. The packaged importer validates before opening SQL.

    Callers must own a detached projection of a verified packet. This is not a
    public ingestion entry point; apply_packet retains full validation.
    """
    previous = (await connection.execute(text("SELECT packet_hash FROM materials_ner_v1.runs WHERE id=:id"),
        {"id": packet["run_id"]})).scalar_one_or_none()
    if previous is not None:
        if previous != packet["packet_hash"]:
            raise ValueError("immutable proposal collision")
        return False, await verify_readback(connection, packet)
    for name in INSERT_ORDER:
        columns = COLUMNS[name]
        placeholders = ["CAST(:payload AS jsonb)" if col == "payload" else ":" + col for col in columns]
        conflict = " ON CONFLICT(id) DO NOTHING" if name == "bundles" else ""
        statement = text(f"INSERT INTO materials_ner_v1.{name} ({','.join(columns)}) "
                         f"VALUES({','.join(placeholders)}){conflict}")
        for row in rows[name]:
            await connection.execute(statement, {k: canonical(v) if k == "payload" else v for k, v in row.items()})
    return True, await verify_readback(connection, packet)


async def process(request, database_url=None):
    if request.get("action") not in {"initialize", "ingest", "status"}:
        raise ValueError("unsupported bridge operation")
    action = request["action"]
    engine = create_async_engine(make_url(database_url or os.environ["DATABASE_URL"]).set(drivername="postgresql+asyncpg"))
    try:
        async with engine.begin() as connection:
            await connection.execute(text("SET LOCAL statement_timeout='45s'"))
            await connection.execute(text("SET LOCAL lock_timeout='10s'"))
            await connection.execute(text("SELECT pg_advisory_xact_lock(924601)"))
            exists = (await connection.execute(text("SELECT to_regclass('materials_ner_v1.schema_version')"))).scalar()
            if not exists:
                if action != "initialize":
                    raise ValueError("proposal schema not initialized")
                for statement in base.initialize_statements():
                    await connection.execute(text(statement))
            if action == "initialize":
                await connection.run_sync(schema.upgrade)
            versions = dict((await connection.execute(text("SELECT version,fingerprint FROM materials_ner_v1.schema_version"))).all())
            if versions.get("materials-ner-proposals/1") != base.FINGERPRINT or versions.get(schema.VERSION) != schema.FINGERPRINT:
                raise ValueError("proposal schema fingerprint mismatch")
            inserted = readback = None
            if action == "ingest":
                inserted, readback = await apply_packet(connection, request["packet"])
            counts = {name: (await connection.execute(text(f"SELECT count(*) FROM materials_ner_v1.{name}"))).scalar_one()
                      for name in schema.TABLES}
            states = dict((await connection.execute(text("SELECT review_status,count(*) FROM materials_ner_v1.results GROUP BY review_status"))).all())
            receipt = dict(ok=True, schema=schema.VERSION, schema_fingerprint=schema.FINGERPRINT,
                action=action, inserted=inserted, tables=counts, result_review_states=states,
                scientific_acceptance=False, ml_training_eligible=False, canonical_tables_written=False)
            if action == "ingest":
                receipt.update(run_id=request["packet"]["run_id"], packet_hash=request["packet"]["packet_hash"],
                               readback_verified=True, relational_readback=readback)
        return receipt  # Commit precedes any success receipt.
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        raw = sys.stdin.buffer.read(16 * 1024**2 + 1)
        if len(raw) > 16 * 1024**2:
            raise ValueError("bridge request too large")
        print(canonical(asyncio.run(process(json.loads(raw)))))
    except Exception as error:
        print(canonical(dict(ok=False, error_class=type(error).__name__,
            sqlstate=getattr(getattr(error, "orig", None), "sqlstate", None))))
        sys.exit(1)
