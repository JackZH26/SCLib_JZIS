"""Bounded bulk replay with the same immutable SQL guards as single-window import.

The caller stages frozen members and removes only its replay windows before
committing. Historical chunks remain unchanged and never gain duplicate public
retrieval rows. Each batch stays below 100 windows / 32 MiB source material.
"""

import json
import struct
from uuid import UUID
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from models.db import Base
from models.retained_legacy_v1 import KIND, RENDERER, PARSER
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


def _prepared(entries, *, limit):
    require(type(entries) is list and 1 <= len(entries) <= limit)
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
    return prepared


def _evidence(chunk, paper, member, text, binding, source_hash):
    return build_revision_rows(
        paper_id=paper["id"],
        chunk_id=member["id"],
        chunk_text=text,
        chunk_binding_sha256=binding,
        source_snapshot_sha256=source_hash,
        candidate={
            "version": "rag-evidence/1.0.0",
            "chunk_kind": KIND,
            "rendering_version": RENDERER,
            "source_locator": {"char_start": member["char_start"], "char_end": member["char_end"]},
            "unresolved_reason": "legacy_unresolved",
        },
    )["evidence"]


async def plan_completions(db, *, generation_id, entries):
    """Read-only projections, checked again by actual INSERT guards at staging.

    PostgreSQL supplies the exact typed snapshots and record hashes. Planning
    creates no receipt, evidence, replay chunk or activation. A source change
    or a changed completion cannot be hidden by the eventual stage operation.
    """
    from services import index_generations as generations

    require(not db.new and not db.dirty and not db.deleted)
    identifier = UUID(str(generation_id))
    prepared = _prepared(entries, limit=1000)
    bodies = [
        {"source": c, "paper": p, "window": {**c, "id": m["id"], "text": t}}
        for e, c, p, m, t, v, r in prepared
    ]
    rows = (
        (
            await db.execute(
                sa.text("""WITH supplied AS (
        SELECT value,n FROM jsonb_array_elements(CAST(:body AS jsonb)) WITH ORDINALITY x(value,n)
      ), typed AS MATERIALIZED (
        SELECT n,to_jsonb(jsonb_populate_record(NULL::public.chunks,value->'window')) AS snapshot_json,
          public.sclib_index_paper_snapshot_v1(to_jsonb(p)) AS paper_snapshot_json,
          public.sclib_source_lifecycle_snapshot_hash_v1('paper',to_jsonb(p)) AS source_snapshot_sha256
        FROM supplied JOIN public.chunks c ON c.id=value->'source'->>'id'
          JOIN public.papers p ON p.id=c.paper_id
        WHERE to_jsonb(c)=value->'source' AND public.sclib_index_paper_snapshot_v1(to_jsonb(p))=value->'paper'
      ) SELECT *,public.sclib_rag_chunk_hash_v1(snapshot_json) AS chunk_binding_sha256,
        public.sclib_index_hash_v1(jsonb_build_object('chunk',snapshot_json,'paper',paper_snapshot_json)) AS snapshot_sha256,
        octet_length(snapshot_json::text)+octet_length(paper_snapshot_json::text) AS snapshot_bytes
        FROM typed ORDER BY n"""),
                {"body": json.dumps(bodies, ensure_ascii=False, allow_nan=False)},
            )
        )
        .mappings()
        .all()
    )
    require(
        len(rows) == len(entries)
        and sum(row["snapshot_bytes"] for row in rows) <= generations.MAX_SNAPSHOT_BYTES
    )
    evidence = [
        _evidence(c, p, m, t, row["chunk_binding_sha256"], row["source_snapshot_sha256"])
        for (e, c, p, m, t, v, r), row in zip(prepared, rows, strict=True)
    ]
    evidence_hashes = await generations._hashes(db, evidence, "sclib_rag_evidence_record_hash_v1")
    receipts = [
        build_embedding_receipt_row(
            chunk_key=m["id"],
            evidence_revision_id=ev["id"],
            evidence_record_sha256=digest,
            chunk_binding_sha256=row["chunk_binding_sha256"],
            receipt=r,
        )
        for (e, c, p, m, t, v, r), row, ev, digest in zip(
            prepared, rows, evidence, evidence_hashes, strict=True
        )
    ]
    receipt_hashes = await generations._hashes(db, receipts, "sclib_embedding_receipt_hash_v1")
    members = []
    for (e, c, p, m, t, v, r), row, ev, ev_hash, receipt, receipt_hash in zip(
        prepared, rows, evidence, evidence_hashes, receipts, receipt_hashes, strict=True
    ):
        members.append(
            dict(
                generation_id=identifier,
                chunk_key=m["id"],
                paper_id=p["id"],
                snapshot_json=row["snapshot_json"],
                paper_snapshot_json=row["paper_snapshot_json"],
                snapshot_sha256=row["snapshot_sha256"],
                snapshot_bytes=row["snapshot_bytes"],
                source_snapshot_sha256=row["source_snapshot_sha256"],
                evidence_revision_id=UUID(ev["id"]),
                evidence_record_sha256=ev_hash,
                receipt_id=UUID(receipt["id"]),
                receipt_record_sha256=receipt_hash,
                content_sha256=r["content_sha256"],
                vector_sha256=r["vector_sha256"],
                vector_bytes=struct.pack(">768f", *v),
                parser_version=PARSER,
                chunker_version=RENDERER,
            )
        )
    for member, revision_hash in zip(members, await generations._hashes(db, members), strict=True):
        member.update(
            chunk_revision_sha256=revision_hash,
            vector_id=generations.vector_id_for(identifier, revision_hash),
        )
    return sorted(members, key=lambda row: row["vector_id"])


async def import_completions(db, *, entries):
    require(not db.new and not db.dirty and not db.deleted)
    prepared = _prepared(entries, limit=100)
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
            rows.append(_evidence(c, p, m, t, bindings[m["id"]], hashes[p["id"]]))
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
