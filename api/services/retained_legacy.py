"""Admit exact replayed windows without modifying historical source chunks."""

from __future__ import annotations

import hashlib
import json
import re

import sqlalchemy as sa

from models.db import Base
from models.retained_legacy_v1 import KIND, RENDERER
from services.embedding_receipts import _document_encoder, _document_token_count
from services.rag_evidence import register_chunk_evidence


def canonical(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


def digest(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def require(value):
    if not value:
        raise ValueError("Exact bounded retained legacy window required")


async def _insert(db, name, values, identity):
    table = Base.metadata.tables[name]
    row = (
        (await db.execute(sa.select(table).where(table.c[identity] == values[identity])))
        .mappings()
        .one_or_none()
    )
    if row is not None:
        require(all(row[key] == value for key, value in values.items()))
        return
    await db.execute(table.insert().values(**values))


def validate_window(
    *, pack_sha256, source_seq, source_raw, paper_raw, member_seq, input_partition, member_raw
):
    require(
        type(pack_sha256) is str
        and re.fullmatch(r"[0-9a-f]{64}", pack_sha256)
        and all(type(n) is int and n > 0 for n in (source_seq, member_seq, input_partition))
    )
    require(
        all(
            type(raw) is str and 0 < len(raw.encode()) <= 16 * 1024 * 1024
            for raw in (source_raw, paper_raw, member_raw)
        )
    )
    source, paper, member = (json.loads(raw) for raw in (source_raw, paper_raw, member_raw))
    require(
        canonical(source) == source_raw
        and canonical(paper) == paper_raw
        and canonical(member) == member_raw
    )
    require(
        set(source) == {"chunk", "paper_sha256"} and source["paper_sha256"] == digest(paper_raw)
    )
    chunk = source["chunk"]
    require(chunk["paper_id"] == paper["id"] and member["source_sha256"] == digest(source_raw))
    first, last, prefix = member["char_start"], member["char_end"], member["prefix"]
    require(
        type(first) is int
        and type(last) is int
        and type(prefix) is str
        and 0 <= first < last <= len(chunk["text"])
    )
    text = prefix + chunk["text"][first:last]
    require(
        member["id"]
        == "ls1_"
        + digest(canonical({"version": RENDERER, **{k: v for k, v in member.items() if k != "id"}}))
        and member["content_sha256"] == digest(text)
        and member["embedding_input_admissible"] is True
        and member["input_characters"] == len(text)
        and member["input_utf8_bytes"] == len(text.encode())
        and len(text.encode()) <= 1024 * 1024
    )
    tokens = _document_token_count(text, _document_encoder())
    require(1 <= tokens <= 1536 and member["local_tokens"] == tokens)
    return chunk, paper, member, text


async def retain_window(
    db, *, pack_sha256, source_seq, source_raw, paper_raw, member_seq, input_partition, member_raw
):
    """Caller owns commit; a savepoint prevents partial admission on failure.

    Original full source and bibliography use content identities. Windows keep
    exact coordinates plus the independently bounded, separate prefix.
    """
    require(not db.new and not db.dirty and not db.deleted)
    chunk, paper, member, text = validate_window(
        pack_sha256=pack_sha256,
        source_seq=source_seq,
        source_raw=source_raw,
        paper_raw=paper_raw,
        member_seq=member_seq,
        input_partition=input_partition,
        member_raw=member_raw,
    )
    first, last = member["char_start"], member["char_end"]
    async with db.begin_nested():
        await db.execute(sa.text("SELECT public.sclib_research_integrity_lock_v1()"))
        source_hash = await db.scalar(
            sa.text(
                "SELECT public.sclib_source_lifecycle_snapshot_hash_v1('paper',to_jsonb(p)) "
                "FROM papers p WHERE id=:id"
            ),
            {"id": paper["id"]},
        )
        require(source_hash is not None)
        await _insert(
            db,
            "legacy_index_papers",
            {
                "paper_sha256": digest(paper_raw),
                "paper_id": paper["id"],
                "source_snapshot_sha256": source_hash,
                "body_raw": paper_raw,
            },
            "paper_sha256",
        )
        await _insert(
            db,
            "legacy_index_sources",
            {
                "source_sha256": digest(source_raw),
                "pack_sha256": pack_sha256,
                "source_seq": source_seq,
                "source_key": chunk["id"],
                "paper_sha256": digest(paper_raw),
                "body_raw": source_raw,
            },
            "source_sha256",
        )
        await _insert(db, "chunks", {**chunk, "id": member["id"], "text": text}, "id")
        await _insert(
            db,
            "legacy_index_windows",
            {
                "chunk_key": member["id"],
                "source_sha256": digest(source_raw),
                "member_seq": member_seq,
                "input_partition": input_partition,
                "body_raw": member_raw,
            },
            "chunk_key",
        )
        return await register_chunk_evidence(
            db,
            chunk_id=member["id"],
            dry_run=False,
            candidate={
                "version": "rag-evidence/1.0.0",
                "chunk_kind": KIND,
                "rendering_version": RENDERER,
                "source_locator": {"char_start": first, "char_end": last},
                "unresolved_reason": "legacy_unresolved",
            },
        )
