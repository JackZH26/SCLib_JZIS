"""Private, resumable preparation of retained legacy text for a new index.

This is an input pack, not an embedding receipt or an active generation. It
retains unknown historical lineage explicitly. No provider/application writes.
SQLite keeps the corpus on disk; memory is bounded by one source row/window.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
from pathlib import Path

VERSION = "sclib-legacy-input-pack/1.0.0"
MAX_SOURCE_BYTES = 16 * 1024 * 1024
PARTITION_MEMBERS = 1000
PARTITION_BYTES = 16 * 1024 * 1024
TOKEN_LIMIT = 1536
OVERLAP = 128


class PackError(ValueError):
    """Static diagnostics; never include retained text or connection details."""


def require(value, code="invalid_legacy_input_pack"):
    if not value:
        raise PackError(code)


def canonical(value):
    try:
        raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        require(len(raw) <= MAX_SOURCE_BYTES, "legacy_source_byte_limit")
        return raw
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise PackError("invalid_legacy_source_json") from None


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def identifier(value):
    require(type(value) is str and 1 <= len(value) <= 200
            and not any(ord(c) < 32 or ord(c) == 127 for c in value), "invalid_legacy_source_identity")
    return value


def specification(provenance):
    require(type(provenance) is dict and bool(provenance), "legacy_provenance_required")
    # Callers bind source implementation, tokenizer runtime and backup identity.
    return {"version": VERSION, "provenance": json.loads(canonical(provenance)),
            "token_limit": TOKEN_LIMIT, "overlap_limit": OVERLAP,
            "partition_member_limit": PARTITION_MEMBERS, "partition_input_byte_limit": PARTITION_BYTES,
            "representation": "retained_legacy_snapshot", "historical_parser_version": None,
            "historical_embedding_completion": None, "original_source_verified": False,
            "permission_status": "unresolved", "scientific_acceptance": False,
            "local_count_method": "cl100k_base", "provider_token_count": None}


def windows(chunk):
    """Keep fitting text intact; split long text at exact character coordinates.

    The new prefix is separate from retained source bytes. Each window is an
    excerpt of an unverified legacy snapshot, never an independent fact/root.
    """
    from ingestion.chunk import chunker
    body = chunk.get("text")
    require(type(body) is str and bool(body), "empty_legacy_source")
    require(len(body.encode()) <= MAX_SOURCE_BYTES, "legacy_source_byte_limit")
    count = chunker.count_tokens(body)
    if count <= TOKEN_LIMIT:
        yield 0, len(body), "", count
        return
    title, section = chunk.get("title") or "", chunk.get("section") or ""
    require(type(title) is str and type(section) is str)
    prefix = chunker.build_bounded_prefix(title, section, max_tokens=TOKEN_LIMIT)
    for span in chunker._section_windows(body, prefix=prefix, size=TOKEN_LIMIT, overlap=OVERLAP):
        text = prefix + body[span.char_start:span.char_end]
        yield span.char_start, span.char_end, prefix, chunker.require_token_budget(text, max_tokens=TOKEN_LIMIT)


def member(source_hash, start, end, prefix, body, count):
    text = prefix + body[start:end]
    value = {"source_sha256": source_hash, "char_start": start, "char_end": end, "prefix": prefix,
             "content_sha256": sha(text.encode()), "local_tokens": count,
             "input_characters": len(text), "input_utf8_bytes": len(text.encode()),
             "embedding_input_admissible": bool(text.strip()) and len(text.encode()) <= 1024 * 1024}
    value["id"] = "ls1_" + sha(canonical({"version": VERSION, **value}))
    return value


class Pack:
    def __init__(self, path, spec=None, *, resume=False, readonly=False):
        self.db = None
        try:
            self._initialize(path, spec, resume=resume, readonly=readonly)
        except BaseException:
            if self.db is not None:
                self.db.close()
            raise

    def _initialize(self, path, spec, *, resume, readonly):
        self.path = Path(path).absolute()
        parent = self.path.parent.lstat()
        require(stat.S_ISDIR(parent.st_mode) and parent.st_uid == os.getuid()
                and stat.S_IMODE(parent.st_mode) == 0o700, "private_pack_directory_required")
        created = not (resume or readonly)
        if created:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            os.close(fd)
        info = self.path.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o600, "unsafe_legacy_pack_file")
        uri = self.path.as_uri() + ("?mode=ro" if readonly else "?mode=rw")
        self.db = sqlite3.connect(uri, uri=True)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA trusted_schema=OFF")
        self.db.execute("PRAGMA cache_size=-16384")
        if not readonly:
            self.db.execute("PRAGMA journal_mode=DELETE")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("PRAGMA max_page_count=8388608")  # 32 GiB at 4096-byte pages
        if created:
            require(spec is not None)
            self.db.executescript("""
                CREATE TABLE metadata (key TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE papers (id TEXT PRIMARY KEY, sha TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE sources (seq INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL,
                    paper_id TEXT NOT NULL REFERENCES papers(id), sha TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE members (seq INTEGER PRIMARY KEY, source_seq INTEGER NOT NULL REFERENCES sources(seq),
                    partition_id INTEGER NOT NULL, id TEXT UNIQUE NOT NULL, body TEXT NOT NULL);
                CREATE INDEX members_source ON members(source_seq,seq);
            """)
            self.db.execute("INSERT INTO metadata VALUES ('spec',?)", (canonical(spec).decode(),))
            self.db.commit()
        row = self.db.execute("SELECT body FROM metadata WHERE key='spec'").fetchone()
        require(row is not None)
        self.spec = json.loads(row[0])
        require(self.spec == specification(self.spec["provenance"]), "legacy_pack_specification_mismatch")
        if spec is not None:
            require(self.spec == spec, "legacy_pack_provenance_changed")
        self.sealed = self.db.execute("SELECT body FROM metadata WHERE key='report'").fetchone()
        self.readonly = readonly
        self.source_count = self.db.execute("SELECT count(*) FROM sources").fetchone()[0]
        self.member_count = self.db.execute("SELECT count(*) FROM members").fetchone()[0]
        last = self.db.execute("SELECT partition_id FROM members ORDER BY seq DESC LIMIT 1").fetchone()
        self.partition = last[0] if last else 1
        self.partition_count = 0
        self.partition_bytes = 0
        if last:
            for (body,) in self.db.execute("SELECT body FROM members WHERE partition_id=? AND seq>?",
                                          (self.partition, max(0, self.member_count - PARTITION_MEMBERS))):
                self.partition_count += 1
                self.partition_bytes += json.loads(body)["input_utf8_bytes"]

    def append(self, seq, chunk, paper):
        return self.append_windows(seq, chunk, paper, windows(chunk))

    def append_windows(self, seq, chunk, paper, spans):
        """Retain explicitly planned spans; seal still verifies every source byte.

        A repaired pack records its parent and window policy in provenance.
        Existing source identities remain exact, while new windows get new IDs.
        """
        require(not self.readonly and not self.sealed, "sealed_legacy_pack")
        key = identifier(chunk.get("id"))
        paper_id = identifier(paper.get("id"))
        require(chunk.get("paper_id") == paper_id, "crossed_legacy_paper_identity")
        source_raw, paper_raw = canonical(chunk), canonical(paper)
        paper_hash = sha(paper_raw)
        source_hash = sha(canonical({"chunk": chunk, "paper_sha256": paper_hash}))
        if seq <= self.source_count:
            row = self.db.execute("SELECT id,sha FROM sources WHERE seq=?", (seq,)).fetchone()
            require(row == (key, source_hash), "legacy_snapshot_changed_on_resume")
            return False
        require(seq == self.source_count + 1, "legacy_source_sequence_gap")
        old_paper = self.db.execute("SELECT sha FROM papers WHERE id=?", (paper_id,)).fetchone()
        require(old_paper is None or old_paper[0] == paper_hash, "legacy_paper_changed")
        self.db.execute("INSERT OR IGNORE INTO papers VALUES (?,?,?)", (paper_id, paper_hash, paper_raw.decode()))
        self.db.execute("INSERT INTO sources VALUES (?,?,?,?,?)", (seq, key, paper_id, source_hash, source_raw.decode()))
        for start, end, prefix, count in spans:
            value = member(source_hash, start, end, prefix, chunk["text"], count)
            require(0 < value["input_utf8_bytes"] <= PARTITION_BYTES)
            if (self.partition_count >= PARTITION_MEMBERS
                    or self.partition_bytes + value["input_utf8_bytes"] > PARTITION_BYTES):
                self.partition += 1
                self.partition_count = self.partition_bytes = 0
            self.member_count += 1
            self.db.execute("INSERT INTO members VALUES (?,?,?,?,?)",
                            (self.member_count, seq, self.partition, value["id"], canonical(value).decode()))
            self.partition_count += 1
            self.partition_bytes += value["input_utf8_bytes"]
        self.source_count += 1
        return True

    def verify(self, expected_sources):
        """Stream every stored byte/window; no sampled completeness claim."""
        from ingestion.chunk import chunker
        require(type(expected_sources) is int and expected_sources > 0)
        require(self.db.execute("PRAGMA quick_check").fetchall() == [("ok",)], "legacy_pack_sqlite_integrity")
        require(not self.db.execute("PRAGMA foreign_key_check").fetchall(), "legacy_pack_foreign_key_integrity")
        source_digest, member_digest, partition_digest = (hashlib.sha256() for _ in range(3))
        totals = {name: 0 for name in ("sources", "members", "source_characters", "source_utf8_bytes",
            "input_characters", "input_utf8_bytes", "local_tokens", "split_sources", "max_input_tokens",
            "inadmissible_embedding_inputs")}
        previous_id = None
        part, part_count, part_bytes = 1, 0, 0
        part_hash = hashlib.sha256()
        def finish_partition():
            require(1 <= part_count <= PARTITION_MEMBERS and 1 <= part_bytes <= PARTITION_BYTES,
                    "legacy_partition_limit")
            partition_digest.update(canonical({"partition": part, "members": part_count,
                "input_utf8_bytes": part_bytes, "sha256": part_hash.hexdigest()}) + b"\n")
        paper_count = 0
        paper_digest = hashlib.sha256()
        for key, stored_hash, raw in self.db.execute("SELECT id,sha,body FROM papers ORDER BY id COLLATE BINARY"):
            paper = json.loads(raw)
            require(paper.get("id") == key and sha(canonical(paper)) == stored_hash, "legacy_paper_hash_mismatch")
            paper_digest.update(canonical([key, stored_hash]) + b"\n")
            paper_count += 1
        query = "SELECT s.seq,s.id,s.sha,s.body,p.sha FROM sources s JOIN papers p ON p.id=s.paper_id ORDER BY s.seq"
        for seq, key, stored_hash, raw, paper_hash in self.db.execute(query):
            totals["sources"] += 1
            require(seq == totals["sources"] and (previous_id is None or previous_id < key), "legacy_source_order")
            previous_id = key
            chunk = json.loads(raw)
            require(chunk.get("id") == key and stored_hash == sha(canonical({"chunk": chunk, "paper_sha256": paper_hash})),
                    "legacy_source_hash_mismatch")
            text = chunk["text"]
            totals["source_characters"] += len(text)
            totals["source_utf8_bytes"] += len(text.encode())
            source_digest.update(canonical([seq, key, stored_hash]) + b"\n")
            covered = prior_start = count = 0
            for n, partition, identifier_, member_raw in self.db.execute(
                    "SELECT seq,partition_id,id,body FROM members WHERE source_seq=? ORDER BY seq", (seq,)):
                value = json.loads(member_raw)
                start, end, prefix = value["char_start"], value["char_end"], value["prefix"]
                require(type(start) is int and type(end) is int and type(prefix) is str
                        and 0 <= start <= covered < end <= len(text) and (count == 0 or start > prior_start),
                        "legacy_source_span_gap")
                require(chunker.count_tokens(text[start:covered]) <= OVERLAP, "legacy_overlap_limit")
                actual_tokens = chunker.count_tokens(prefix + text[start:end])
                require(1 <= actual_tokens <= TOKEN_LIMIT, "legacy_member_token_limit")
                require(value == member(stored_hash, start, end, prefix, text, actual_tokens)
                        and value["id"] == identifier_, "legacy_member_hash_mismatch")
                totals["members"] += 1
                require(n == totals["members"], "legacy_member_sequence_gap")
                require(partition in (part, part + 1), "legacy_partition_sequence_gap")
                if partition != part:
                    finish_partition()
                    part, part_count, part_bytes, part_hash = partition, 0, 0, hashlib.sha256()
                row_hash = sha(canonical(value))
                manifest_line = canonical([n, seq, partition, identifier_, row_hash]) + b"\n"
                member_digest.update(manifest_line)
                part_hash.update(manifest_line)
                part_count += 1
                part_bytes += value["input_utf8_bytes"]
                for field in ("input_characters", "input_utf8_bytes"):
                    totals[field] += value[field]
                totals["local_tokens"] += actual_tokens
                totals["inadmissible_embedding_inputs"] += int(not value["embedding_input_admissible"])
                totals["max_input_tokens"] = max(totals["max_input_tokens"], actual_tokens)
                covered, prior_start, count = end, start, count + 1
            require(count > 0 and covered == len(text), "incomplete_legacy_source_coverage")
            totals["split_sources"] += int(count > 1)
        finish_partition()
        require(totals["sources"] == expected_sources == self.source_count
                and totals["members"] == self.member_count, "incomplete_legacy_pack_inventory")
        report = {"version": VERSION, "specification_sha256": sha(canonical(self.spec)), **totals,
            "papers_with_chunks": paper_count, "partitions": part, "source_manifest_sha256": source_digest.hexdigest(),
            "paper_manifest_sha256": paper_digest.hexdigest(), "member_manifest_sha256": member_digest.hexdigest(),
            "partition_manifest_sha256": partition_digest.hexdigest(), "retained_text_coverage_complete": True,
            "original_source_coverage_verified": False, "historical_text_vector_binding_proven": False,
            "provider_calls": 0, "application_database_writes": 0, "index_writes": 0,
            "embedding_completion_verified": False, "activation_eligible": False}
        if self.sealed:
            require(json.loads(self.sealed[0]) == report, "sealed_legacy_pack_changed")
        return report

    def seal(self, expected_sources):
        require(not self.readonly and not self.sealed, "sealed_legacy_pack")
        report = self.verify(expected_sources)
        self.db.execute("INSERT INTO metadata VALUES ('report',?)", (canonical(report).decode(),))
        self.db.commit()
        self.sealed = (canonical(report).decode(),)
        return report

    def close(self):
        self.db.close()
