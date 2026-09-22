"""Bounded bulk replay with the same immutable SQL guards as single-window import.

The caller stages frozen members and removes only its replay windows before
committing. Historical chunks remain unchanged and never gain duplicate public
retrieval rows. Each batch stays below 100 windows / 32 MiB source material.
"""

from uuid import UUID
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from models.db import Base
from models.retained_legacy_v1 import KIND, RENDERER
from services.retained_legacy import validate_window, require, digest
from services.rag_evidence_contract import build_revision_rows
from services.embedding_receipt_contract import build_embedding_receipt_row
from services.embedding_contract import validate_embedding_provenance, validate_vector


async def _batch(db, name, rows, identity):
    table = Base.metadata.tables[name]
    supplied = {}
    for value in rows:
        row = {
            key: UUID(str(v)) if v is not None and isinstance(table.c[key].type, sa.Uuid) else v
            for key, v in value.items()
        }
        key = row[identity]
        require(key not in supplied or supplied[key] == row)
        supplied[key] = row
    found = (
        (await db.execute(sa.select(table).where(table.c[identity].in_(list(supplied)))))
        .mappings()
        .all()
    )
    result = {row[identity]: row for row in found}
    for key, row in result.items():
        require(all(row[field] == value for field, value in supplied[key].items()))
    missing = [row for key, row in supplied.items() if key not in result]
    if missing:
        written = (await db.execute(table.insert().returning(table), missing)).mappings().all()
        result.update({row[identity]: row for row in written})
    require(len(result) == len(supplied))
    return result


async def import_completions(db, *, entries):
    require(
        not db.new
        and not db.dirty
        and not db.deleted
        and type(entries) is list
        and 1 <= len(entries) <= 100
    )
    require(
        sum(
            len(item[key].encode())
            for item in entries
            for key in ("source_raw", "paper_raw", "member_raw")
        )
        <= 32 * 1024 * 1024
    )
    prepared = []
    for entry in entries:
        require(
            set(entry)
            == {
                "pack_sha256",
                "source_seq",
                "source_raw",
                "paper_raw",
                "member_seq",
                "input_partition",
                "member_raw",
                "vector",
                "receipt",
            }
        )
        args = {k: v for k, v in entry.items() if k not in {"vector", "receipt"}}
        chunk, paper, member, text = validate_window(**args)
        vector = validate_vector(entry["vector"])
        receipt = validate_embedding_provenance(
            entry["receipt"], text=text, vector=vector, expected_task="RETRIEVAL_DOCUMENT"
        )
        require(receipt["local_count"] == member["local_tokens"])
        prepared.append((entry, chunk, paper, member, text, vector, receipt))
    require(len({x[3]["id"] for x in prepared}) == len(entries))
    async with db.begin_nested():
        await db.execute(sa.text("SELECT public.sclib_research_integrity_lock_v1()"))
        paper_ids = list({x[2]["id"] for x in prepared})
        hashes = dict(
            (
                await db.execute(
                    sa.text(
                        "SELECT p.id,public.sclib_source_lifecycle_snapshot_hash_v1('paper',to_jsonb(p)) "
                        "FROM papers p WHERE p.id IN :ids"
                    ).bindparams(sa.bindparam("ids", expanding=True)),
                    {"ids": paper_ids},
                )
            ).all()
        )
        require(len(hashes) == len(paper_ids))
        await _batch(
            db,
            "legacy_index_papers",
            [
                {
                    "paper_sha256": digest(e["paper_raw"]),
                    "paper_id": p["id"],
                    "source_snapshot_sha256": hashes[p["id"]],
                    "body_raw": e["paper_raw"],
                }
                for e, c, p, m, t, v, r in prepared
            ],
            "paper_sha256",
        )
        await _batch(
            db,
            "legacy_index_sources",
            [
                {
                    "source_sha256": digest(e["source_raw"]),
                    "pack_sha256": e["pack_sha256"],
                    "source_seq": e["source_seq"],
                    "source_key": c["id"],
                    "paper_sha256": digest(e["paper_raw"]),
                    "body_raw": e["source_raw"],
                }
                for e, c, p, m, t, v, r in prepared
            ],
            "source_sha256",
        )
        await _batch(
            db,
            "chunks",
            [{**c, "id": m["id"], "text": t} for e, c, p, m, t, v, r in prepared],
            "id",
        )
        await _batch(
            db,
            "legacy_index_windows",
            [
                {
                    "chunk_key": m["id"],
                    "source_sha256": digest(e["source_raw"]),
                    "member_seq": e["member_seq"],
                    "input_partition": e["input_partition"],
                    "body_raw": e["member_raw"],
                }
                for e, c, p, m, t, v, r in prepared
            ],
            "chunk_key",
        )
        ids = [x[3]["id"] for x in prepared]
        bindings = dict(
            (
                await db.execute(
                    sa.text(
                        "SELECT c.id,public.sclib_rag_chunk_hash_v1(to_jsonb(c)) FROM chunks c WHERE c.id IN :ids"
                    ).bindparams(sa.bindparam("ids", expanding=True)),
                    {"ids": ids},
                )
            ).all()
        )
        rows = []
        for e, c, p, m, t, v, r in prepared:
            rows.append(
                build_revision_rows(
                    paper_id=p["id"],
                    chunk_id=m["id"],
                    chunk_text=t,
                    chunk_binding_sha256=bindings[m["id"]],
                    source_snapshot_sha256=hashes[p["id"]],
                    candidate={
                        "version": "rag-evidence/1.0.0",
                        "chunk_kind": KIND,
                        "rendering_version": RENDERER,
                        "source_locator": {
                            "char_start": m["char_start"],
                            "char_end": m["char_end"],
                        },
                        "unresolved_reason": "legacy_unresolved",
                    },
                )["evidence"]
            )
        evidence = await _batch(db, "rag_evidence_revisions", rows, "id")
        by_chunk = {row["chunk_key"]: row for row in evidence.values()}
        links = Base.metadata.tables["chunk_evidence_current"]
        statement = insert(links)
        await db.execute(
            statement.on_conflict_do_update(
                index_elements=[links.c.chunk_id],
                set_={"evidence_revision_id": statement.excluded.evidence_revision_id},
            ),
            [{"chunk_id": key, "evidence_revision_id": by_chunk[key]["id"]} for key in ids],
        )
        receipt_rows = []
        for e, c, p, m, t, v, r in prepared:
            ev = by_chunk[m["id"]]
            receipt_rows.append(
                build_embedding_receipt_row(
                    chunk_key=m["id"],
                    receipt=r,
                    evidence_revision_id=ev["id"],
                    evidence_record_sha256=ev["record_sha256"],
                    chunk_binding_sha256=bindings[m["id"]],
                )
            )
        receipts = await _batch(db, "embedding_completion_receipts", receipt_rows, "id")
        by_chunk_receipt = {row["chunk_key"]: row for row in receipts.values()}
        return [
            {"chunk_id": m["id"], "receipt_id": str(by_chunk_receipt[m["id"]]["id"]), "vector": v}
            for e, c, p, m, t, v, r in prepared
        ]


async def remove_replayed_chunks(db, *, chunk_ids):
    """Remove only verified new replay identities, after frozen staging/planning."""
    require(
        type(chunk_ids) is list
        and 1 <= len(chunk_ids) <= 1000
        and len(set(chunk_ids)) == len(chunk_ids)
        and all(type(key) is str and key.startswith("ls1_") for key in chunk_ids)
    )
    result = await db.execute(
        sa.text("""DELETE FROM chunks c USING legacy_index_windows w
        WHERE c.id=w.chunk_key AND c.id IN :ids AND c.id<>w.source_key
          AND public.sclib_answer_evidence_text_hash_v1(c.text)=(w.body_raw::jsonb)->>'content_sha256'
        RETURNING c.id""").bindparams(sa.bindparam("ids", expanding=True)),
        {"ids": chunk_ids},
    )
    require(set(result.scalars().all()) == set(chunk_ids))
