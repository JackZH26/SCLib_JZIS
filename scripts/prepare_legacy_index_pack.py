"""Prepare/verify private legacy input packs; never embed, publish or activate.

Build accepts only the explicitly named restored database, and every SQL query
runs in a repeatable-read, read-only transaction. DATABASE_URL stays private.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import sys
import time
from functools import lru_cache
from pathlib import Path

from legacy_index_pack import Pack, PackError, require, specification

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ingestion"))


def provenance(backup_sha256, schema):
    paths = ["scripts/legacy_index_pack.py", "scripts/prepare_legacy_index_pack.py",
             "ingestion/ingestion/chunk/chunker.py", "ingestion/ingestion/models.py",
             "ingestion/ingestion/rag_evidence_contract.py"]
    return {"declared_backup_sha256": backup_sha256, "schema_revision": schema,
            "backup_identity_independently_verified_by_this_tool": False,
            "source_files": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in paths},
            "tokenizer_distribution": "tiktoken", "tokenizer_version": importlib.metadata.version("tiktoken")}


def build(args):
    import psycopg2
    require(re.fullmatch(r"[0-9a-f]{64}", args.backup_sha256 or ""), "exact_backup_hash_required")
    require(re.fullmatch(r"sclib_upgrade(?:_[a-z0-9_]+)?", args.restored_database or ""),
            "explicit_restored_database_required")
    require(re.fullmatch(r"[0-9]{4}_[a-z0-9_]+", args.schema or ""), "exact_restored_schema_required")
    url = os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
    require(bool(url), "database_url_required")
    pack = None
    started = time.monotonic()
    try:
        with psycopg2.connect(url, connect_timeout=5) as db:
            db.set_session(readonly=True, isolation_level="REPEATABLE READ")
            with db.cursor() as cur:
                cur.execute("SELECT current_database(),current_setting('transaction_read_only'),current_setting('transaction_isolation')")
                require(cur.fetchone() == (args.restored_database, "on", "repeatable read"), "restored_readonly_session_required")
                cur.execute("SELECT version_num FROM alembic_version")
                require(cur.fetchall() == [(args.schema,)], "restored_schema_mismatch")
                cur.execute("SELECT count(*) FROM chunks")
                expected = cur.fetchone()[0]
            spec = specification(provenance(args.backup_sha256, args.schema))
            pack = Pack(args.pack, spec, resume=args.resume)
            require(not pack.sealed, "sealed_pack_use_verify_command")
            previous = None
            checkpoint = time.monotonic()
            @lru_cache(maxsize=64)
            def paper_snapshot(paper_id):
                # Repeated chunks share a frozen bibliography. Computing and
                # transferring a large paper JSON once per chunk amplifies
                # the million-row scan unnecessarily. The same read-only
                # transaction supplies this bounded cache throughout.
                with db.cursor() as paper_cursor:
                    paper_cursor.execute("SELECT public.sclib_index_paper_snapshot_v1(to_jsonb(p)) "
                                         "FROM papers p WHERE id=%s", (paper_id,))
                    row = paper_cursor.fetchone()
                    require(row is not None, "legacy_source_paper_missing")
                    return row[0]
            with db.cursor(name="sclib_legacy_pack_readonly") as cur:
                cur.itersize = 32
                # Use the existing primary-key order, then explicitly reject
                # an order incompatible with the portable manifest. No large
                # full-row C-collation sort or server-side materialization.
                cur.execute("SELECT to_jsonb(c) FROM chunks c ORDER BY c.id")
                count = 0
                for count, (chunk,) in enumerate(cur, 1):
                    paper = paper_snapshot(chunk["paper_id"])
                    key = chunk["id"]
                    require(previous is None or previous < key, "legacy_input_order")
                    previous = key
                    pack.append(count, chunk, paper)
                    if count % 128 == 0:
                        pack.db.commit()
                    if time.monotonic() - checkpoint > 30:
                        pack.db.commit()
                        print(json.dumps({"stage": "prepare", "scanned_sources": count,
                                          "expected_sources": expected, "members": pack.member_count}), flush=True)
                        checkpoint = time.monotonic()
            require(count == expected == pack.source_count, "legacy_input_inventory_changed")
            pack.db.commit()
            db.rollback()
        print(json.dumps({"stage": "verify_all_retained_bytes", "expected_sources": expected}), flush=True)
        report = pack.seal(expected)
        print(json.dumps({"report": report, "elapsed_seconds": round(time.monotonic()-started, 3)}), flush=True)
    finally:
        if pack is not None:
            pack.close()


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("build")
    prepare.add_argument("--pack", required=True, type=Path)
    prepare.add_argument("--backup-sha256", required=True)
    prepare.add_argument("--restored-database", required=True)
    prepare.add_argument("--schema", required=True)
    prepare.add_argument("--resume", action="store_true")
    verify = sub.add_parser("verify")
    verify.add_argument("--pack", required=True, type=Path)
    verify.add_argument("--expected-sources", required=True, type=int)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            build(args)
        else:
            pack = Pack(args.pack, readonly=True)
            try:
                require(bool(pack.sealed), "unsealed_legacy_pack")
                print(json.dumps({"report": pack.verify(args.expected_sources)}))
            finally:
                pack.close()
        return 0
    except Exception as exc:
        # Driver/filesystem/tokenizer errors can carry DSNs or private text.
        code = str(exc) if type(exc) is PackError else "legacy_pack_operation_failed"
        print(json.dumps({"status": "failed", "code": code}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
