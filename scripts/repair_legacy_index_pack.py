"""Exact replacements for provider-rejected inputs and a complete joined inventory.

Original receipts remain bound to their original requests. Replacement windows
cover entire affected sources, and have independent actual provider receipts.
No unverified vector is relabeled, no input truncated, and no source is omitted.
"""

from __future__ import annotations

import argparse
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "api"), str(ROOT / "ingestion")]
from legacy_index_pack import (
    Pack,
    PackError,
    canonical,
    require,
    sha,
    specification,
)
from embed_legacy_index_pack import file_sha
from services.embedding_contract import validate_embedding_provenance

VERSION = "sclib-repaired-completions/1.0.0"
POLICY = "utf8-1280-complete-source/1.0.0"


def private_db(path, *, create=False):
    path = Path(path).absolute()
    parent = path.parent.lstat()
    require(
        stat.S_ISDIR(parent.st_mode)
        and parent.st_uid == os.getuid()
        and stat.S_IMODE(parent.st_mode) == 0o700,
        "private_inventory_directory_required",
    )
    if create:
        os.close(
            os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        )
    info = path.lstat()
    require(
        stat.S_ISREG(info.st_mode)
        and info.st_nlink == 1
        and info.st_uid == os.getuid()
        and stat.S_IMODE(info.st_mode) == 0o600,
        "private_inventory_file_required",
    )
    db = sqlite3.connect(
        path.as_uri() + ("?mode=rw" if create else "?mode=ro"), uri=True
    )
    db.execute("PRAGMA trusted_schema=OFF")
    db.execute("PRAGMA cache_size=-16384")
    return db


def conservative_windows(chunk):
    from ingestion.chunk.chunker import count_tokens

    body, start = chunk["text"], 0
    # A short neutral prefix also keeps whitespace-only retained spans valid;
    # it is recorded separately and never mistaken for historical source bytes.
    prefix = "Retained text:\n"
    while start < len(body):
        low, high = start + 1, min(len(body), start + 1280)
        while low < high:
            mid = (low + high + 1) // 2
            if len(body[start:mid].encode()) <= 1280:
                low = mid
            else:
                high = mid - 1
        end = low
        text = prefix + body[start:end]
        require(len(text.encode()) <= 1295 and 1 <= count_tokens(text) <= 1536)
        yield start, end, prefix, count_tokens(text)
        start = end


class Origin:
    """Read-only finalized ledger, including explicit rejected-input holes."""

    def __init__(self, pack_path, ledger_path):
        self.pack = Pack(pack_path, readonly=True)
        self.path = Path(ledger_path)
        self.db = private_db(self.path)
        self.digest = file_sha(self.path)
        self.spec = json.loads(
            self.db.execute("SELECT body FROM metadata WHERE key='spec'").fetchone()[0]
        )
        require(
            self.pack.sealed and self.spec["input_pack_sha256"] == file_sha(pack_path),
            "origin_pack_mismatch",
        )
        self.report = self.pack.verify(self.pack.source_count)
        require(
            json.loads(self.pack.sealed[0]) == self.report, "origin_report_mismatch"
        )
        require(
            self.db.execute("PRAGMA quick_check").fetchall() == [("ok",)]
            and not self.db.execute("PRAGMA foreign_key_check").fetchall(),
            "origin_integrity",
        )
        complete = self.db.execute("SELECT count(*) FROM completions").fetchone()[0]
        rejected = self.db.execute("SELECT count(*) FROM input_rejections").fetchone()[
            0
        ]
        require(
            complete + rejected == self.report["members"], "origin_still_incomplete"
        )
        require(
            not self.db.execute(
                "SELECT 1 FROM completions c JOIN input_rejections r USING(seq) LIMIT 1"
            ).fetchone()
        )
        self.cost = [0, 0, 0]
        for (raw,) in self.db.execute("SELECT body FROM attempts"):
            a = json.loads(raw)
            self.cost = [
                self.cost[0] + a["characters"],
                self.cost[1] + a["local_tokens"],
                self.cost[2] + 1,
            ]

    @lru_cache(maxsize=128)
    def attempt(self, identifier):
        raw = self.db.execute(
            "SELECT a.body,o.body FROM attempts a JOIN outcomes o ON o.attempt_id=a.id WHERE a.id=?",
            (identifier,),
        ).fetchone()
        require(
            raw is not None and json.loads(raw[1])["status"] == "complete",
            "origin_attempt_incomplete",
        )
        a = json.loads(raw[0])
        entries = []
        for seq in a["seqs"]:
            row = self.pack.db.execute(
                "SELECT id,body FROM members WHERE seq=?", (seq,)
            ).fetchone()
            require(row is not None)
            entries.append([row[0], json.loads(row[1])["content_sha256"]])
        require(a["input_sha256"] == sha(canonical(entries)), "origin_attempt_binding")
        return frozenset(a["seqs"])

    def completion(self, value, text):
        row = self.db.execute(
            "SELECT seq,member_id,partition_id,vector,receipt,attempt_id FROM completions WHERE member_id=?",
            (value["id"],),
        ).fetchone()
        require(row is not None, "origin_completion_missing")
        seq, identifier, partition, vector, raw, attempt = row
        original = self.pack.db.execute(
            "SELECT id,partition_id,body FROM members WHERE seq=?", (seq,)
        ).fetchone()
        require(
            original
            and original[:2] == (identifier, partition)
            and json.loads(original[2]) == value
            and seq in self.attempt(attempt),
            "origin_member_binding",
        )
        receipt = json.loads(raw)
        validate_embedding_provenance(
            receipt,
            text=text,
            vector=list(struct.unpack(">768f", vector)),
            expected_task="RETRIEVAL_DOCUMENT",
        )
        require(receipt["local_count"] == value["local_tokens"])
        return vector, raw, self.digest, seq, attempt

    def unchanged(self):
        require(
            file_sha(self.path) == self.digest, "origin_ledger_changed_during_operation"
        )

    def close(self):
        self.db.close()
        self.pack.close()
        self.attempt.cache_clear()


def rejected_sources(origin):
    result = set()
    for seq, attempt in origin.db.execute(
        "SELECT seq,attempt_id FROM input_rejections"
    ):
        raw = origin.db.execute(
            "SELECT a.body,o.body FROM attempts a JOIN outcomes o ON o.attempt_id=a.id WHERE a.id=?",
            (attempt,),
        ).fetchone()
        require(
            raw
            and json.loads(raw[0])["seqs"] == [seq]
            and json.loads(raw[1])["status"] == "provider_input_limit"
        )
        result.add(
            origin.pack.db.execute(
                "SELECT source_seq FROM members WHERE seq=?", (seq,)
            ).fetchone()[0]
        )
    require(bool(result), "no_rejected_sources")
    return result


def repair(origin, output):
    affected = rejected_sources(origin)
    target = Pack(
        output,
        specification(
            {
                "repair_policy": POLICY,
                "parent_pack_sha256": origin.spec["input_pack_sha256"],
                "parent_ledger_sha256": origin.digest,
                "affected_sources": len(affected),
            }
        ),
    )
    try:
        for number, seq in enumerate(sorted(affected), 1):
            raw, paper_raw = origin.pack.db.execute(
                "SELECT s.body,p.body FROM sources s JOIN papers p ON p.id=s.paper_id WHERE s.seq=?",
                (seq,),
            ).fetchone()
            chunk, paper = json.loads(raw), json.loads(paper_raw)
            target.append_windows(number, chunk, paper, conservative_windows(chunk))
            if number % 100 == 0:
                target.db.commit()
        report = target.seal(len(affected))
        origin.unchanged()
        # A replacement ledger's complete 5% request reserve must fit the
        # original global budget before any replacement provider calls begin.
        require(
            origin.cost[0] + (report["input_characters"] * 105 + 99) // 100
            <= origin.spec["max_characters"]
            and origin.cost[1] + (report["local_tokens"] * 105 + 99) // 100
            <= origin.spec["max_local_tokens"],
            "replacement_global_budget_exhausted",
        )
        return report
    finally:
        target.close()


def compose(original, replacement, pack_output, completion_output):
    affected = rejected_sources(original)
    parent = replacement.pack.spec["provenance"]
    require(
        parent.get("repair_policy") == POLICY
        and parent.get("parent_pack_sha256") == original.spec["input_pack_sha256"]
        and parent.get("parent_ledger_sha256") == original.digest
        and replacement.pack.source_count == len(affected)
    )
    require(
        replacement.db.execute("SELECT count(*) FROM input_rejections").fetchone()[0]
        == 0,
        "replacement_still_rejected",
    )
    require(
        all(
            a + b <= original.spec[key]
            for a, b, key in zip(
                original.cost,
                replacement.cost,
                ("max_characters", "max_local_tokens", "max_requests"),
            )
        ),
        "combined_global_budget_exhausted",
    )
    target = Pack(
        pack_output,
        specification(
            {
                "repair_policy": POLICY,
                "original_pack_sha256": original.spec["input_pack_sha256"],
                "original_ledger_sha256": original.digest,
                "replacement_pack_sha256": replacement.spec["input_pack_sha256"],
                "replacement_ledger_sha256": replacement.digest,
                "affected_sources": len(affected),
            }
        ),
    )
    output = private_db(completion_output, create=True)
    output.executescript("""PRAGMA synchronous=FULL;
        CREATE TABLE metadata(key TEXT PRIMARY KEY,body TEXT NOT NULL);
        CREATE TABLE completions(seq INTEGER PRIMARY KEY,member_id TEXT UNIQUE NOT NULL,partition_id INTEGER NOT NULL,
          vector BLOB NOT NULL,receipt TEXT NOT NULL,origin_ledger_sha256 TEXT NOT NULL,origin_seq INTEGER NOT NULL,origin_attempt INTEGER NOT NULL);
        CREATE TRIGGER immutable_completions_update BEFORE UPDATE ON completions BEGIN SELECT RAISE(ABORT,'immutable_completion'); END;
        CREATE TRIGGER immutable_completions_delete BEFORE DELETE ON completions BEGIN SELECT RAISE(ABORT,'immutable_completion'); END;
        CREATE TRIGGER immutable_metadata_update BEFORE UPDATE ON metadata BEGIN SELECT RAISE(ABORT,'immutable_metadata'); END;
        CREATE TRIGGER immutable_metadata_delete BEFORE DELETE ON metadata BEGIN SELECT RAISE(ABORT,'immutable_metadata'); END;""")
    digest, provider_tokens = hashlib.sha256(), 0
    try:
        for seq, key, raw, paper_raw in original.pack.db.execute(
            "SELECT s.seq,s.id,s.body,p.body FROM sources s JOIN papers p ON p.id=s.paper_id ORDER BY s.seq"
        ):
            owner = replacement if seq in affected else original
            source = owner.pack.db.execute(
                "SELECT seq,body FROM sources WHERE id=?", (key,)
            ).fetchone()
            require(source and source[1] == raw, "replacement_source_bytes_changed")
            chunk, paper = json.loads(raw), json.loads(paper_raw)
            values = [
                json.loads(r[0])
                for r in owner.pack.db.execute(
                    "SELECT body FROM members WHERE source_seq=? ORDER BY seq",
                    (source[0],),
                )
            ]
            before = target.member_count
            target.append_windows(
                seq,
                chunk,
                paper,
                [
                    (v["char_start"], v["char_end"], v["prefix"], v["local_tokens"])
                    for v in values
                ],
            )
            for n, part, identifier, body in target.db.execute(
                "SELECT seq,partition_id,id,body FROM members WHERE seq>? ORDER BY seq",
                (before,),
            ):
                value = json.loads(body)
                text = (
                    value["prefix"]
                    + chunk["text"][value["char_start"] : value["char_end"]]
                )
                vector, receipt, origin_sha, origin_seq, attempt = owner.completion(
                    value, text
                )
                output.execute(
                    "INSERT INTO completions VALUES (?,?,?,?,?,?,?,?)",
                    (
                        n,
                        identifier,
                        part,
                        vector,
                        receipt,
                        origin_sha,
                        origin_seq,
                        attempt,
                    ),
                )
                provider_tokens += json.loads(receipt)["provider_token_count"]
                digest.update(
                    canonical(
                        [
                            n,
                            identifier,
                            part,
                            sha(vector),
                            sha(receipt.encode()),
                            origin_sha,
                            origin_seq,
                            attempt,
                        ]
                    )
                    + b"\n"
                )
            if seq % 1000 == 0:
                target.db.commit()
                output.commit()
            if seq % 20000 == 0:
                print(
                    json.dumps(
                        {
                            "stage": "compose",
                            "sources": seq,
                            "members": target.member_count,
                        }
                    ),
                    flush=True,
                )
        report = target.seal(original.pack.source_count)
        for key in (
            "source_manifest_sha256",
            "paper_manifest_sha256",
            "source_characters",
            "source_utf8_bytes",
            "sources",
            "papers_with_chunks",
        ):
            require(
                report[key] == original.report[key], "effective_source_coverage_changed"
            )
        original.unchanged()
        replacement.unchanged()
        result = {
            "version": VERSION,
            "input_pack_sha256": file_sha(pack_output),
            "members": target.member_count,
            "completion_manifest_sha256": digest.hexdigest(),
            "provider_tokens": provider_tokens,
            "original_ledger_sha256": original.digest,
            "replacement_ledger_sha256": replacement.digest,
            "reserved_characters": original.cost[0] + replacement.cost[0],
            "reserved_local_tokens": original.cost[1] + replacement.cost[1],
            "reserved_requests": original.cost[2] + replacement.cost[2],
            "embedding_completion_verified": True,
            "retained_text_coverage_complete": True,
            "scientific_acceptance": False,
            "index_publication_verified": False,
        }
        output.execute(
            "INSERT INTO metadata VALUES('report',?)", (canonical(result).decode(),)
        )
        output.commit()
        return result
    finally:
        target.close()
        output.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["repair", "compose"])
    parser.add_argument("--original-pack", required=True)
    parser.add_argument("--original-ledger", required=True)
    parser.add_argument("--output-pack", required=True)
    parser.add_argument("--replacement-pack")
    parser.add_argument("--replacement-ledger")
    parser.add_argument("--output-completions")
    args = parser.parse_args()
    original = Origin(args.original_pack, args.original_ledger)
    replacement = None
    try:
        if args.command == "repair":
            result = repair(original, args.output_pack)
        else:
            require(
                all(
                    (
                        args.replacement_pack,
                        args.replacement_ledger,
                        args.output_completions,
                    )
                )
            )
            replacement = Origin(args.replacement_pack, args.replacement_ledger)
            result = compose(
                original, replacement, args.output_pack, args.output_completions
            )
        print(json.dumps(result), flush=True)
    finally:
        original.close()
        if replacement:
            replacement.close()


if __name__ == "__main__":
    try:
        main()
    except PackError as exc:
        print(json.dumps({"stage": "failed", "reason": str(exc)}), flush=True)
        raise SystemExit(2)
    except Exception as exc:
        print(json.dumps({"stage": "failed", "reason": type(exc).__name__}), flush=True)
        raise SystemExit(2)
