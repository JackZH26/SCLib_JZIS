"""Bounded additive Postgres importer. Run with frozen schema code prepended.

No credential export, no changes to public canonical tables, no scientific
approval. A whole packet is inserted transactionally and duplicates are read
back. Output contains only counts and hashes, never original source text.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys


def canon(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def hashed(value):
    return hashlib.sha256(canon(value).encode()).hexdigest()


async def apply_packet(connection, packet):
    from sqlalchemy import text
    if packet.get("schema") != "materials-ner-proposals/1":
        raise ValueError("unknown packet contract")
    body = {key: value for key, value in packet.items() if key != "packet_hash"}
    if hashed(body) != packet["packet_hash"]:
        raise ValueError("packet hash mismatch")
    if (hashed(packet["bundle"]) != packet["bundle_hash"]
            or hashed(packet["receipt"]) != packet["run_id"]
            or packet["scientific_acceptance"] or packet["ml_training_eligible"]
            or not packet["work_id"].startswith("arxiv:")
            or packet["bundle"]["work_id"] != packet["work_id"]
            or packet["receipt"]["work_id"] != packet["work_id"]
            or packet["receipt"]["bundle_sha256"] != packet["bundle_hash"]):
        raise ValueError("invalid proposal binding")
    if packet["raw_output"] is not None and hashlib.sha256(packet["raw_output"].encode()).hexdigest() != packet["receipt"].get("raw_output_sha256"):
        raise ValueError("raw output hash mismatch")
    previous = (await connection.execute(text(
        "SELECT packet_hash FROM materials_ner_v1.runs WHERE id=:id"), {"id": packet["run_id"]})).scalar()
    if previous:
        if previous != packet["packet_hash"]:
            raise ValueError("immutable run collision")
        return False
    await connection.execute(text("""INSERT INTO materials_ner_v1.bundles(id,work_id,payload)
        VALUES(:id,:work,CAST(:payload AS jsonb)) ON CONFLICT(id) DO NOTHING"""),
        {"id": packet["bundle_hash"], "work": packet["work_id"], "payload": canon(packet["bundle"])})
    await connection.execute(text("""INSERT INTO materials_ner_v1.runs
        (id,job_id,work_id,bundle_id,packet_hash,model,worker_state,payload)
        VALUES(:id,:job,:work,:bundle,:hash,:model,:state,CAST(:payload AS jsonb))"""),
        {"id": packet["run_id"], "job": packet["job_id"], "work": packet["work_id"],
         "bundle": packet["bundle_hash"], "hash": packet["packet_hash"],
         "model": packet["receipt"]["config"]["model"], "state": packet["receipt"]["state"],
         "payload": canon(packet)})
    for name in ("samples", "states", "protocols", "results"):
        for row in packet["rows"][name]:
            columns = ["run_id", "local_id", "review_status", "payload"]
            values = {"run_id": packet["run_id"], "local_id": row["local_id"],
                      "review_status": row["review_status"], "payload": canon(row)}
            for column in (["sample_id"] if name == "states" else
                           ["sample_id", "state_id", "protocol_id", "quantity_kind"] if name == "results" else []):
                columns.append(column)
                values[column] = row["payload"][column]
            placeholders = ["CAST(:payload AS jsonb)" if c == "payload" else ":" + c for c in columns]
            await connection.execute(text(f"INSERT INTO materials_ner_v1.{name} ({','.join(columns)}) "
                                          f"VALUES({','.join(placeholders)})"), values)
    for ordinal, evidence in enumerate(packet["evidence"]):
        await connection.execute(text("""INSERT INTO materials_ner_v1.evidence
            VALUES(:run,:ordinal,:path,:block,CAST(:payload AS jsonb))"""),
            {"run": packet["run_id"], "ordinal": ordinal, "path": evidence["path"],
             "block": evidence["block_id"], "payload": canon(evidence)})
    for result in packet["rows"]["results"]:
        for edge in result["payload"]["dependencies"]:
            await connection.execute(text("""INSERT INTO materials_ner_v1.dependencies
                VALUES(:run,:result,:target,:relation) ON CONFLICT DO NOTHING"""),
                {"run": packet["run_id"], "result": result["local_id"],
                 "target": edge["result_id"], "relation": edge["relation"]})
    return True


async def process(request, database_url=None):
    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import create_async_engine

    if request.get("action") not in {"initialize", "ingest", "status"}:
        raise ValueError("unsupported bridge operation")
    engine = create_async_engine(make_url(database_url or os.environ["DATABASE_URL"]).set(drivername="postgresql+asyncpg"))
    try:
        async with engine.begin() as connection:
            await connection.execute(text("SET LOCAL statement_timeout='45s'"))
            await connection.execute(text("SET LOCAL lock_timeout='10s'"))
            await connection.execute(text("SELECT pg_advisory_xact_lock(924601)"))
            exists = (await connection.execute(text("SELECT to_regclass('materials_ner_v1.schema_version')"))).scalar()
            if not exists:
                if request["action"] != "initialize":
                    raise ValueError("proposal schema not initialized")
                for statement in globals()["initialize_statements"]():
                    await connection.execute(text(statement))
            fingerprint = (await connection.execute(text(
                "SELECT fingerprint FROM materials_ner_v1.schema_version WHERE version='materials-ner-proposals/1'"
            ))).scalar()
            if fingerprint != globals()["FINGERPRINT"]:
                raise ValueError("schema fingerprint mismatch")
            inserted = None
            if request["action"] == "ingest":
                inserted = await apply_packet(connection, request["packet"])
            counts = {name: (await connection.execute(text(
                f"SELECT count(*) FROM materials_ner_v1.{name}"))).scalar() for name in globals()["TABLES"]}
            states = dict((await connection.execute(text(
                "SELECT review_status,count(*) FROM materials_ner_v1.results GROUP BY review_status"))).all())
            works = (await connection.execute(text("SELECT count(DISTINCT work_id) FROM materials_ner_v1.runs"))).scalar()
            receipt = {"ok": True, "schema": "materials-ner-proposals/1", "schema_fingerprint": fingerprint,
                       "action": request["action"], "inserted": inserted, "tables": counts, "works": works,
                       "result_review_states": states, "scientific_acceptance": False,
                       "ml_training_eligible": False, "canonical_tables_written": False}
            if request["action"] == "ingest":
                receipt["run_id"] = request["packet"]["run_id"]
                observed = (await connection.execute(text(
                    "SELECT payload FROM materials_ner_v1.runs WHERE id=:id"),
                    {"id": receipt["run_id"]})).scalar_one()
                if observed != request["packet"]:
                    raise ValueError("database packet readback mismatch")
                receipt["packet_hash"] = request["packet"]["packet_hash"]
                receipt["readback_verified"] = True
        # Receipt is returned only after the transaction has committed.
        return receipt
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        raw = sys.stdin.buffer.read(16 * 1024**2 + 1)
        if len(raw) > 16 * 1024**2:
            raise ValueError("bridge request too large")
        print(canon(asyncio.run(process(json.loads(raw)))))
    except Exception as error:
        original = getattr(error, "orig", None)
        print(canon({"ok": False, "error_class": type(error).__name__,
                     "sqlstate": getattr(original, "sqlstate", None)}))
        sys.exit(1)
