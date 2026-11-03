"""Atomic prepared-paper publication, with no providers or ANN activation.

This separately locked deployment deliberately depends on both source packages.
The independent ingestion package continues to import no API modules.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import sqlalchemy as sa

from ingestion.config import get_settings
from ingestion.embedding_receipt_contract import build_embedding_receipt_row
from ingestion.index import indexer
from ingestion.models import ApsArticleMeta, ParsedPaper
from ingestion.rag_evidence_contract import validate_candidate
from services import retrieval_native, retrieval_content, retrieval_publication_queue
from services.schema_lifecycle import check_application_schema

SCOPES = {"abstract": "abstract", "original_passage": "full_text", "derived_fact": "structured_record"}


class NativePublisherError(ValueError):
    """The complete prepared paper cannot be published atomically."""


@dataclass(frozen=True)
class RetainedInput:
    relative_path: str
    source_uri: str
    media_type: str
    parser_version: str
    chunker_version: str
    expected_bytes: int
    provider_sha256: str | None


class _PreviewComplete(Exception):
    pass


async def publish_prepared(paper, chunks, materials, *, archive_root, inputs,
                           logical_index, dry_run=True, related_paper_id=None):
    """Write one complete paper and its outbox job in one outer transaction.

    Inputs refer to retained representations, not source rights or scientific
    review. A preview executes the real writes and rolls the entire paper back.
    Nothing downloads, invokes a model, uploads to Google ANN or deletes files.
    """
    if get_settings().retrieval_backend != "pgvector":
        raise NativePublisherError("An explicit pgvector publisher deployment is required")
    if (type(dry_run) is not bool or type(chunks) is not list or not 1 <= len(chunks) <= 1000
            or type(materials) is not list or any(type(row) is not dict for row in materials)
            or type(inputs) is not dict or not isinstance(archive_root, (str, Path))):
        raise NativePublisherError("A complete bounded prepared publication is required")
    if type(paper) not in {ParsedPaper, ApsArticleMeta}:
        raise NativePublisherError("An explicit arXiv or APS prepared paper is required")
    meta = paper.meta if type(paper) is ParsedPaper else paper
    groups = {}
    seen = set()
    for chunk in chunks:
        if chunk.paper_id != meta.paper_id or chunk.id in seen:
            raise NativePublisherError("Prepared chunk identities must match the complete paper")
        seen.add(chunk.id)
        candidate = validate_candidate(chunk.evidence_candidate)
        kind = candidate["chunk_kind"]
        if kind not in SCOPES or type(paper) is ApsArticleMeta and kind == "original_passage":
            raise NativePublisherError("Only admitted retained evidence may be published")
        # Validate complete provider metadata and exact text before a DB write.
        indexer._complete_embedding(chunk)
        groups.setdefault(kind, []).append(chunk)
    if set(inputs) != set(groups) or any(type(item) is not RetainedInput for item in inputs.values()):
        raise NativePublisherError("Exactly one retained input per present evidence kind is required")
    if any(validate_candidate(chunk.evidence_candidate)["rendering_version"] != inputs[kind].chunker_version
            or chunk.parser_version is not None and chunk.parser_version != inputs[kind].parser_version
            for kind, members in groups.items() for chunk in members):
        raise NativePublisherError("Actual parser/chunker versions must match every prepared chunk")
    if related_paper_id is not None and type(paper) is not ApsArticleMeta:
        raise NativePublisherError("Related-paper metadata belongs to APS input only")
    await check_application_schema(indexer._engine())
    result = None

    async def stage(session, written_chunks):
        nonlocal result
        if [chunk.id for chunk in written_chunks] != [chunk.id for chunk in chunks]:
            raise NativePublisherError("The source writer changed the prepared chunk inventory")
        revisions, observed = [], []
        for kind, members in sorted(groups.items()):
            receipt = await retrieval_native.append_input_receipt(
                session, archive_root=archive_root, paper_id=meta.paper_id,
                source_scope=SCOPES[kind], **asdict(inputs[kind]), dry_run=False)
            observed.append(receipt)
            rows = (await session.execute(sa.text("""SELECT c.id,link.evidence_revision_id,
              e.record_sha256 AS evidence_record_sha256,
              public.sclib_rag_chunk_hash_v1(to_jsonb(c)) AS chunk_binding_sha256
              FROM chunks c JOIN chunk_evidence_current link ON link.chunk_id=c.id
              JOIN rag_evidence_revisions e ON e.id=link.evidence_revision_id
              WHERE c.paper_id=:paper AND c.id IN :ids""").bindparams(sa.bindparam("ids", expanding=True)),
              {"paper": meta.paper_id, "ids": [chunk.id for chunk in members]})).mappings().all()
            bindings = {row["id"]: row for row in rows}
            if set(bindings) != {chunk.id for chunk in members}:
                raise NativePublisherError("Every written chunk needs its current evidence binding")
            items = []
            for chunk in members:
                bound = bindings[chunk.id]
                embedding = build_embedding_receipt_row(chunk_key=chunk.id,
                    receipt=chunk.embedding_provenance,
                    **{key: bound[key] for key in ("evidence_revision_id", "evidence_record_sha256", "chunk_binding_sha256")})
                items.append({"chunk_id": chunk.id, "receipt_id": str(embedding["id"]), "vector": chunk.embedding})
            captured = await retrieval_native.append_native_revisions(session,
                input_receipt_id=receipt["input_receipt_id"], items=items, dry_run=False)
            revisions.extend(row["revision_id"] for row in captured["revisions"])
        publication = await retrieval_content.seal_native_publication(session,
            paper_id=meta.paper_id, native_revision_ids=revisions, dry_run=False)
        job = await retrieval_publication_queue.enqueue_publication(session,
            logical_index=logical_index, publication_id=publication["publication_id"], dry_run=False)
        result = {"version": "native-publisher-result/1.0.0", "paper_id": meta.paper_id,
            "publication": publication, "job": job, "inputs": observed, "dry_run": dry_run,
            "committed": False, "active_pointer_changed": False, "provider_calls": False,
            "google_ann_calls": False, "archive_files_deleted": False}
        if dry_run:
            raise _PreviewComplete()

    try:
        if type(paper) is ParsedPaper:
            await indexer.upsert_paper_with_chunks(paper, chunks, materials, generation_stager=stage,
                preserve_existing_chunks=True)
        else:
            await indexer.upsert_aps_paper_with_chunks(paper, chunks, materials,
                related_paper_id=related_paper_id, generation_stager=stage, preserve_existing_chunks=True)
    except _PreviewComplete:
        if not dry_run:
            raise
    if result is None:
        raise NativePublisherError("The source writer did not stage the native publication")
    result["committed"] = not dry_run
    return result
