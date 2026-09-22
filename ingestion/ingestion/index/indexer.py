"""Write-side: persist papers/chunks/materials to Postgres and upsert
chunk vectors into Vertex AI Vector Search.

Why SQL Core (not ORM): ingestion runs far from the API process, and
duplicating ORM definitions would require importing ``api.models.db``
which pulls in pydantic-settings and unrelated FastAPI deps. Using
``sqlalchemy.Table`` + reflected metadata keeps ingestion decoupled and
upsert-friendly via ``insert(...).on_conflict_do_update``.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any
from uuid import UUID as PythonUUID

from google.cloud import aiplatform
from google.cloud.aiplatform.matching_engine.matching_engine_index_endpoint import (
    MatchingEngineIndexEndpoint,
)
from google.cloud.aiplatform_v1.types import IndexDatapoint
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    SmallInteger,
    String,
    Table,
    Text,
    bindparam,
    case,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ingestion.chunk.chunker import require_token_budget
from ingestion.config import get_settings
from ingestion.embedding_contract import (
    LOCAL_DOCUMENT_COUNT_METHOD,
    validate_embedding_provenance,
    validate_profile,
    validate_vector,
)
from ingestion.embedding_receipt_contract import build_embedding_receipt_row
from ingestion.models import Chunk, ParsedPaper
from ingestion.rag_evidence_contract import build_revision_rows, canonical, validate_candidate

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Table definitions — must match api/alembic/versions/0001_initial_schema.py.
# ---------------------------------------------------------------------------

metadata = MetaData()

papers_table = Table(
    "papers", metadata,
    Column("id", String(100), primary_key=True),
    Column("source", String(20), nullable=False),
    Column("arxiv_id", String(20)),
    Column("doi", String(200)),
    # Normalized cross-source identity (alembic 0038).
    Column("external_id", String(200)),
    Column("id_scheme", String(20)),
    Column("related_paper_id", String(100)),
    Column("title", Text, nullable=False),
    Column("authors", JSONB, nullable=False),
    Column("affiliations", JSONB),
    Column("paper_geo", JSONB),
    Column("date_submitted", Date),
    Column("date_published", Date),
    Column("journal", String(300)),
    # APS journal identity (alembic 0038).
    Column("journal_abbrev", String(30)),
    Column("publication_ref", JSONB),
    Column("abstract", Text, nullable=False),
    Column("categories", JSONB),
    Column("material_family", String(50)),
    Column("status", String(20), nullable=False, server_default="published"),
    Column("retraction_date", Date),
    Column("retraction_reason", Text),
    Column("citation_count", Integer, nullable=False, server_default="0"),
    Column("chunk_count", Integer, nullable=False, server_default="0"),
    Column("materials_extracted", JSONB, nullable=False, server_default="[]"),
    Column("quality_flags", JSONB, nullable=False, server_default="[]"),
    Column("credibility_tier", String(2)),
    Column("paper_type", String(20)),
    Column("indexed_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

chunks_table = Table(
    "chunks", metadata,
    Column("id", String(200), primary_key=True),
    Column("paper_id", String(100), ForeignKey("papers.id"), nullable=False),
    Column("title", Text),
    Column("authors_short", String(200)),
    Column("year", SmallInteger),
    Column("section", String(200)),
    Column("chunk_index", SmallInteger),
    Column("text", Text, nullable=False),
    Column("material_family", String(50)),
    Column("materials_mentioned", JSONB, nullable=False, server_default="[]"),
    Column("has_equation", Boolean, nullable=False, server_default="false"),
    Column("has_table", Boolean, nullable=False, server_default="false"),
)

# 0060 is deliberately separate from the frozen ML04 chunks row contract.
# No original text/raw NER payload is copied into these immutable parents.
rag_extraction_revisions_table = Table(
    "rag_extraction_revisions", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("paper_id", String(100), nullable=False),
    Column("input_record_sha256", String(64), nullable=False),
    Column("extractor_version", String(160), nullable=False),
    Column("projection_version", String(50), nullable=False),
    Column("projection_json", JSONB, nullable=False),
    Column("source_snapshot_sha256", String(64), nullable=False),
    Column("scientific_acceptance", Boolean, nullable=False),
)

rag_evidence_revisions_table = Table(
    "rag_evidence_revisions", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("paper_id", String(100), nullable=False),
    Column("version", String(50), nullable=False),
    Column("chunk_kind", String(30), nullable=False),
    Column("chunk_key", String(200), nullable=False),
    Column("content_sha256", String(64), nullable=False),
    Column("chunk_binding_sha256", String(64), nullable=False),
    Column("parent_extraction_revision_id", UUID(as_uuid=True)),
    Column("source_capture_id", UUID(as_uuid=True)),
    Column("source_locator", JSONB, nullable=False),
    Column("extraction_version", String(160)),
    Column("rendering_version", String(160)),
    Column("source_snapshot_sha256", String(64), nullable=False),
    Column("root_status", String(30), nullable=False),
    Column("unresolved_reason", String(50), nullable=False),
    Column("permission_status", String(30), nullable=False),
)

chunk_evidence_current_table = Table(
    "chunk_evidence_current", metadata,
    Column("chunk_id", String(200), primary_key=True),
    Column("evidence_revision_id", UUID(as_uuid=True), nullable=False),
)

# Immutable completion observations, not evidence of upload or active index
# membership. Actual binding checks live in additive migration 0061.
embedding_completion_receipts_table = Table(
    "embedding_completion_receipts", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("chunk_key", String(200), nullable=False),
    Column("evidence_revision_id", UUID(as_uuid=True), nullable=False),
    Column("evidence_record_sha256", String(64), nullable=False),
    Column("chunk_binding_sha256", String(64), nullable=False),
    Column("content_sha256", String(64), nullable=False),
    Column("vector_sha256", String(64), nullable=False),
    Column("metadata_json", JSONB, nullable=False),
    Column("completion_scope", String(40), nullable=False),
)

materials_table = Table(
    "materials", metadata,
    # --- v1 core ----------------------------------------------------------
    Column("id", String(100), primary_key=True),
    Column("formula", String(200), nullable=False),
    Column("formula_normalized", String(200), nullable=False),
    Column("formula_latex", String(200)),
    Column("family", String(50)),
    Column("subfamily", String(100)),
    Column("crystal_structure", String(100)),
    Column("tc_max", Float),
    Column("tc_max_conditions", String(300)),
    Column("tc_ambient", Float),
    Column("dominant_evidence", String(20)),
    Column("tc_max_experimental", Float),
    Column("tc_max_theoretical", Float),
    Column("pairing_symmetry", String(100)),
    Column("arxiv_year", SmallInteger),
    Column("total_papers", Integer, nullable=False, server_default="0"),
    Column("status", String(50), nullable=False, server_default="active_research"),
    Column("records", JSONB, nullable=False, server_default="[]"),
    # SC03: derived, versioned review context; raw records remain separate.
    Column("anomaly_review", JSONB, nullable=False, server_default="{}"),
    Column("anomaly_context", JSONB, nullable=False, server_default="{}"),
    Column("material_semantics", JSONB, nullable=False, server_default="{}"),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    # --- v2 structural ----------------------------------------------------
    Column("space_group", String(50)),
    Column("structure_phase", String(50)),
    Column("lattice_params", JSONB),
    # --- v2 SC parameters -------------------------------------------------
    Column("gap_structure", String(50)),
    Column("hc2_tesla", Float),
    Column("hc2_conditions", String(200)),
    Column("lambda_eph", Float),
    Column("omega_log_k", Float),
    Column("rho_s_mev", Float),
    # --- v2 competing orders ---------------------------------------------
    Column("t_cdw_k", Float),
    Column("t_sdw_k", Float),
    Column("t_afm_k", Float),
    Column("rho_exponent", Float),
    Column("competing_order", String(100)),
    # --- v2 samples + pressure -------------------------------------------
    Column("ambient_sc", Boolean),
    Column("pressure_type", String(50)),
    Column("sample_form", String(50)),
    Column("substrate", String(100)),
    Column("doping_type", String(50)),
    Column("doping_level", Float),
    # --- v2 flags ---------------------------------------------------------
    Column("is_unconventional", Boolean),
    Column("has_competing_order", Boolean),
    Column("retracted", Boolean, server_default="false"),
    Column("disputed", Boolean, server_default="false"),
    # Aggregate best credibility tier across a material's papers. Added
    # to the DB by alembic 0033_mat_best_cred_tier and emitted by
    # _derive_summary, but this hand-maintained Table object had
    # drifted (column never added here) — so the upsert
    # ``{k: stmt.excluded[k] for k in summary}`` raised
    # KeyError('best_credibility_tier') and aggregate_from_papers
    # crashed on EVERY run since 0033. That is the real reason the
    # materials table stayed stale. Type matches models/db.py.
    Column("best_credibility_tier", String(2)),
    # v3 sanity gate (see api/alembic/versions/0005_needs_review.py)
    Column("needs_review", Boolean, nullable=False, server_default="false"),
    Column("review_reason", String(200)),
    Column("admin_decision", JSONB),
    # P2: Parent-variant model + interface
    Column("parent_material_id", String(100)),
    Column("variant_count", Integer, nullable=False, server_default="0"),
    Column("formula_substrate", String(200)),
    Column("formula_overlayer", String(200)),
    Column("layer_thickness_nm", Float),
    # Materials Project linkage (Phase B)
    Column("mp_id", String(50)),
    Column("mp_alternate_ids", JSONB, nullable=False, server_default="[]"),
    Column("mp_synced_at", DateTime(timezone=True)),
)

# Tiny key/value pipeline state. Holds materials_normalize_version —
# the canonicalisation scheme the materials table has been reconciled
# to. The aggregator refuses to run if this is behind
# nims.NORMALIZE_SCHEMA_VERSION (R2.2 interlock). Created + seeded by
# alembic 0035_pipeline_state.
pipeline_state_table = Table(
    "pipeline_state", metadata,
    Column("key", String(64), primary_key=True),
    Column("value", String(256), nullable=False),
)


# --- P0 data-quality infrastructure (alembic 0025) -----------------------

refuted_claims_table = Table(
    "refuted_claims", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("formula", String(200), nullable=False),
    Column("canonical", String(200), nullable=False),
    Column("claim_type", String(50), nullable=False),
    Column("claimed_tc", Float),
    Column("refutation_doi", String(200)),
    Column("refutation_year", SmallInteger),
    Column("notes", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

manual_overrides_table = Table(
    "manual_overrides", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("formula", String(200), nullable=False),
    Column("canonical", String(200), nullable=False),
    Column("field", String(50), nullable=False),
    Column("override_value", Text, nullable=False),
    Column("is_cap", Boolean, nullable=False, server_default="false"),
    Column("source", String(200), nullable=False),
    Column("reason", Text),
    Column("created_by", String(100), nullable=False, server_default="system"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)


# --- APS TDM compliance audit (alembic 0039) -----------------------------
# One row per APS paper processed: proves the raw Licensed Materials were
# deleted after extraction. Written by ingestion.aps_storage; never holds
# licensed content (file names/sizes only).
tdm_audit_log_table = Table(
    "tdm_audit_log", metadata,
    Column(
        "id", UUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    ),
    Column("source", String(20), nullable=False, server_default="aps"),
    Column("doi", String(200), nullable=False),
    Column("paper_id", String(100)),
    Column("harvested_at", DateTime(timezone=True)),
    Column("processed_at", DateTime(timezone=True)),
    Column("bagit_bytes", BigInteger),
    Column("files_processed", JSONB, nullable=False, server_default="[]"),
    Column("ner_record_count", Integer, nullable=False, server_default="0"),
    Column("deleted_at", DateTime(timezone=True)),
    Column("deletion_confirmed", Boolean, nullable=False, server_default="false"),
    Column("temp_path", Text),
    Column("status", String(20), nullable=False, server_default="pending"),
    Column("error", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

hydride_tc_parameters_table = Table(
    "hydride_tc_parameters", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("record_key", String(80), nullable=False),
    Column("material_id", String(100)),
    Column("formula", String(200), nullable=False),
    Column("formula_normalized", String(200), nullable=False),
    Column("paper_id", String(100), nullable=False),
    Column("source", String(20), nullable=False),
    Column("doi", String(200)),
    Column("arxiv_id", String(20)),
    Column("year", SmallInteger),
    Column("tc_kelvin", Float),
    Column("pressure_gpa", Float),
    Column("lambda_eph", Float),
    Column("mu_star", Float),
    Column("omega_log_k", Float),
    Column("omega_log_source_value", Float),
    Column("omega_log_source_unit", String(20)),
    Column("method", String(80)),
    Column("evidence_type", String(40)),
    Column("confidence", Float),
    Column("source_section", String(200)),
    Column("validation_flags", JSONB, nullable=False, server_default="[]"),
    Column("provenance", JSONB, nullable=False, server_default="{}"),
    Column("model", String(80)),
    Column("prompt_version", String(40), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)


# ---------------------------------------------------------------------------
# Async engine
# ---------------------------------------------------------------------------

def _to_async_dsn(dsn: str) -> str:
    if dsn.startswith("postgresql+asyncpg://"):
        return dsn
    if dsn.startswith("postgresql://"):
        return "postgresql+asyncpg://" + dsn[len("postgresql://"):]
    if dsn.startswith("postgres://"):
        return "postgresql+asyncpg://" + dsn[len("postgres://"):]
    return dsn


@lru_cache(maxsize=1)
def _engine() -> AsyncEngine:
    return create_async_engine(
        _to_async_dsn(get_settings().database_url),
        pool_pre_ping=True,
    )


@lru_cache(maxsize=1)
def _session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(_engine(), expire_on_commit=False)


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

async def _insert_evidence_revision(session: AsyncSession, table: Table, values: dict) -> None:
    """Append or verify an exact replay; never overwrite an immutable revision."""
    values = dict(values)
    for key in ("id", "parent_extraction_revision_id", "source_capture_id", "evidence_revision_id"):
        if values.get(key) is not None:
            values[key] = PythonUUID(values[key])
    await session.execute(pg_insert(table).values(**values).on_conflict_do_nothing(index_elements=[table.c.id]))
    # A pre-existing identifier is not evidence of an equivalent payload.
    # Verify every input field, including JSON projection and SQL source hash.
    exact = (await session.execute(select(table.c.id).where(
        *(table.c[key] == value for key, value in values.items())
    ))).scalar_one_or_none()
    if exact is None:
        raise ValueError("Conflicting immutable evidence revision")


async def _persist_chunk_evidence(session: AsyncSession, paper_id: str, chunks: list[Chunk]) -> None:
    """Bind real producer candidates to the actual rows in the caller's SQL tx.

    Missing legacy candidates create no invented lineage. The paper/chunk
    write and these append-only revisions/current pointers either all commit
    or all roll back. No helper owns a transaction or calls vector services.
    """
    candidates = {}
    for chunk in chunks:
        if chunk.paper_id != paper_id or chunk.id in candidates:
            raise ValueError("Evidence chunk identity does not match the paper")
        if chunk.evidence_candidate is not None:
            candidates[chunk.id] = validate_candidate(chunk.evidence_candidate)
    if not candidates:
        return
    # The paper upsert already acquired this shared research-integrity fence
    # through its 0054 trigger. Take it explicitly/reentrantly before reads.
    await session.execute(text("SELECT public.sclib_research_integrity_lock_v1()"))
    query = select(
        chunks_table.c.id, chunks_table.c.text, chunks_table.c.materials_mentioned,
        papers_table.c.materials_extracted,
        func.public.sclib_rag_chunk_hash_v1(func.to_jsonb(chunks_table.table_valued())).label("chunk_binding_sha256"),
        func.public.sclib_source_lifecycle_snapshot_hash_v1(
            "paper", func.to_jsonb(papers_table.table_valued())
        ).label("source_snapshot_sha256"),
    ).join(papers_table, papers_table.c.id == chunks_table.c.paper_id).where(
        chunks_table.c.paper_id == paper_id, chunks_table.c.id.in_(candidates),
    )
    rows = (await session.execute(query)).mappings().all()
    if {row["id"] for row in rows} != set(candidates):
        raise ValueError("Evidence requires every actual persisted chunk")
    for row in rows:
        candidate = candidates[row["id"]]
        if candidate["chunk_kind"] == "derived_fact":
            parent_key = canonical(candidate["parent_record"])
            actual_parent = next((record for record in row["materials_mentioned"]
                                  if canonical(record) == parent_key), None)
            if actual_parent is None or not any(
                canonical(record) == parent_key for record in row["materials_extracted"]
            ):
                raise ValueError("Derived evidence parent must match the actual paper and chunk extraction")
            # Recompute the parent input hash/projection from persisted JSON,
            # not an ID, digest, or cached projection supplied by a candidate.
            candidate = {**candidate, "parent_record": actual_parent}
        values = build_revision_rows(
            paper_id=paper_id, chunk_id=row["id"], chunk_text=row["text"],
            chunk_binding_sha256=row["chunk_binding_sha256"],
            source_snapshot_sha256=row["source_snapshot_sha256"], candidate=candidate,
        )
        if values["extraction"] is not None:
            await _insert_evidence_revision(session, rag_extraction_revisions_table, values["extraction"])
        await _insert_evidence_revision(session, rag_evidence_revisions_table, values["evidence"])
        pointer = pg_insert(chunk_evidence_current_table).values(
            chunk_id=row["id"], evidence_revision_id=PythonUUID(values["evidence"]["id"]),
        )
        await session.execute(pointer.on_conflict_do_update(
            index_elements=[chunk_evidence_current_table.c.chunk_id],
            set_={"evidence_revision_id": pointer.excluded.evidence_revision_id},
        ))

def _complete_embedding(chunk: Chunk) -> tuple[list[float], dict]:
    """Recheck exact current inputs, never trusting cached token counts."""
    settings = get_settings()
    validate_profile(model=settings.embedding_model, dimension=settings.embedding_output_dimensionality,
                     task_type="RETRIEVAL_DOCUMENT")
    actual_count = require_token_budget(chunk.text, max_tokens=settings.chunk_size_tokens)
    vector = validate_vector(chunk.embedding)
    report = validate_embedding_provenance(chunk.embedding_provenance, text=chunk.text, vector=vector,
                                          expected_task="RETRIEVAL_DOCUMENT")
    if report["local_count_method"] != LOCAL_DOCUMENT_COUNT_METHOD or report["local_count"] != actual_count:
        raise ValueError("Embedding local count does not match actual complete chunk text")
    if type(chunk.token_count) is not int or chunk.token_count != actual_count:
        raise ValueError("Chunk token count does not match its current complete text")
    return vector, report


async def _persist_embedding_completions(session: AsyncSession, paper_id: str, chunks: list[Chunk]) -> None:
    """Append completion metadata in the same transaction as SQL and lineage.

    Pure SQL-only legacy chunks remain possible. A supplied vector or report
    requires its complete counterpart, exact text and the current 0060 binding.
    A later vector upload is separate and not attested by these rows.
    """
    completed = {}
    seen = set()
    for chunk in chunks:
        if chunk.paper_id != paper_id or chunk.id in seen:
            raise ValueError("Embedding chunk inventory does not match the paper")
        seen.add(chunk.id)
        if chunk.embedding is not None or chunk.embedding_provenance is not None:
            completed[chunk.id] = _complete_embedding(chunk)
    if not completed:
        return
    await session.execute(text("SELECT public.sclib_research_integrity_lock_v1()"))
    rows = (await session.execute(text("""SELECT c.id,c.text,link.evidence_revision_id,
        e.record_sha256 AS evidence_record_sha256,
        public.sclib_rag_chunk_hash_v1(to_jsonb(c)) AS chunk_binding_sha256
        FROM chunks c JOIN chunk_evidence_current link ON link.chunk_id=c.id
        JOIN rag_evidence_revisions e ON e.id=link.evidence_revision_id
        WHERE c.paper_id=:paper AND c.id IN :ids""").bindparams(
            bindparam("ids", expanding=True)),
        {"paper": paper_id, "ids": list(completed)})).mappings().all()
    if {row["id"] for row in rows} != set(completed):
        raise ValueError("Embedding completion requires every current chunk evidence binding")
    for row in rows:
        vector, report = completed[row["id"]]
        validate_embedding_provenance(report, text=row["text"], vector=vector, expected_task="RETRIEVAL_DOCUMENT")
        values = build_embedding_receipt_row(chunk_key=row["id"], receipt=report,
            **{key: row[key] for key in ("evidence_revision_id", "evidence_record_sha256", "chunk_binding_sha256")})
        await _insert_evidence_revision(session, embedding_completion_receipts_table, values)


async def upsert_paper_with_chunks(
    parsed: ParsedPaper,
    chunks: list[Chunk],
    materials_extracted: list[dict[str, Any]],
    *,
    generation_stager=None,
) -> None:
    """Upsert a paper row + replace its chunks atomically.

    An explicit SQL-only generation_stager(session, chunks) may retain a sealed
    generation in this same transaction. It must perform no cloud operations
    and must not commit the caller-owned transaction. Default ingestion creates
    no generation and cannot activate an index implicitly.
    """
    meta = parsed.meta
    paper_values: dict[str, Any] = {
        "id": meta.paper_id,
        "source": "arxiv",
        "arxiv_id": meta.arxiv_id,
        "doi": meta.doi,
        # Populate the normalized identity anchor (alembic 0038) so arXiv
        # rows satisfy UNIQUE(source, external_id). Unchanged otherwise.
        "external_id": meta.arxiv_id,
        "id_scheme": "arxiv",
        "title": meta.title,
        "authors": meta.authors,
        "date_submitted": meta.date_submitted,
        "date_published": meta.date_submitted,
        "abstract": meta.abstract,
        "categories": meta.categories,
        "material_family": None,
        # Explicit INSERT-only counterparts of 0001's server defaults. Never
        # include these in update_cols: re-ingestion cannot clear source holds.
        "status": "published",
        "citation_count": 0,
        "quality_flags": [],
        "chunk_count": len(chunks),
        "materials_extracted": materials_extracted,
        "publication_ref": {"ingestion_capture": parsed.ingestion_capture},
    }

    async with _session_factory()() as session:
        async with session.begin():
            stmt = pg_insert(papers_table).values(**paper_values)
            update_cols = {
                c: stmt.excluded[c]
                for c in [
                    "title", "authors", "abstract", "categories",
                    "date_submitted", "date_published",
                    "chunk_count", "materials_extracted", "doi",
                ]
            }
            update_cols["updated_at"] = func.now()
            # Keep unrelated bibliographic/operator metadata. This envelope is
            # diagnostic only, NOT the authoritative result-availability registry.
            existing_ref = case(
                (func.jsonb_typeof(papers_table.c.publication_ref) == "object",
                 papers_table.c.publication_ref),
                (papers_table.c.publication_ref.is_(None), text("'{}'::jsonb")),
                else_=func.jsonb_build_object("legacy_publication_ref", papers_table.c.publication_ref),
            )
            update_cols["publication_ref"] = existing_ref.op("||")(stmt.excluded.publication_ref)
            stmt = stmt.on_conflict_do_update(
                index_elements=[papers_table.c.id],
                set_=update_cols,
            )
            await session.execute(stmt)

            # Replace all chunks for this paper (simplest correct strategy
            # on re-ingest). Delete then bulk insert.
            await session.execute(
                chunks_table.delete().where(chunks_table.c.paper_id == meta.paper_id)
            )
            if chunks:
                await session.execute(
                    chunks_table.insert(),
                    [
                        {
                            "id": c.id,
                            "paper_id": c.paper_id,
                            "title": meta.title,
                            "authors_short": ", ".join(meta.authors[:2])
                                + (" et al." if len(meta.authors) > 2 else ""),
                            "year": meta.date_submitted.year if meta.date_submitted else None,
                            "section": c.section,
                            "chunk_index": c.chunk_index,
                            "text": c.text,
                            "material_family": None,
                            "materials_mentioned": c.materials_mentioned,
                            "has_equation": c.has_equation,
                            "has_table": c.has_table,
                        }
                        for c in chunks
                    ],
                )
            await _persist_chunk_evidence(session, meta.paper_id, chunks)
            await _persist_embedding_completions(session, meta.paper_id, chunks)
            if generation_stager is not None:
                await generation_stager(session, chunks)


async def upsert_aps_paper_with_chunks(
    meta: Any,
    chunks: list[Chunk],
    materials_extracted: list[dict[str, Any]],
    *,
    related_paper_id: str | None = None,
    generation_stager=None,
) -> None:
    """Upsert an APS paper row + replace its chunks atomically.

    The APS counterpart of ``upsert_paper_with_chunks``. ``meta`` is an
    ``ApsArticleMeta`` (duck-typed). Differences from the arXiv path:
    source='aps', identity anchored on the DOI (external_id=doi,
    id_scheme='doi'), arxiv_id stays NULL, journal_abbrev +
    publication_ref are populated, and related_paper_id may link this row
    to an arXiv preprint of the same work.

    COMPLIANCE: ``chunks`` here must contain ONLY authorized-derived units
    (abstract + NER fact-sentences) — never APS full-text body. The
    orchestrator (aps_pipeline) enforces this; the body ParsedPaper is
    transient and deleted. This function just writes whatever chunks it is
    given, exactly like the arXiv path.
    """
    paper_values: dict[str, Any] = {
        "id": meta.paper_id,                # "aps:10.1103/..."
        "source": "aps",
        "arxiv_id": None,
        "doi": meta.doi,
        "external_id": meta.doi,
        "id_scheme": "doi",
        "related_paper_id": related_paper_id,
        "title": meta.title,
        "authors": meta.authors,
        "date_submitted": None,
        "date_published": meta.date_published,
        "journal": meta.journal,
        "journal_abbrev": meta.journal_abbrev,
        "publication_ref": meta.publication_ref(),
        "abstract": meta.abstract,
        "categories": meta.categories,
        "material_family": None,
        "status": "published",
        "citation_count": 0,
        "quality_flags": [],
        # APS rows are formal published journal articles with DOI
        # provenance, so they are first-tier evidence by default.
        "credibility_tier": "T1",
        "chunk_count": len(chunks),
        "materials_extracted": materials_extracted,
    }

    async with _session_factory()() as session:
        async with session.begin():
            stmt = pg_insert(papers_table).values(**paper_values)
            update_cols = {
                c: stmt.excluded[c]
                for c in [
                    "title", "authors", "abstract", "categories",
                    "date_published", "journal", "journal_abbrev",
                    "publication_ref", "related_paper_id",
                    "chunk_count", "materials_extracted", "doi",
                    "credibility_tier",
                ]
            }
            update_cols["updated_at"] = func.now()
            stmt = stmt.on_conflict_do_update(
                index_elements=[papers_table.c.id],
                set_=update_cols,
            )
            await session.execute(stmt)

            await session.execute(
                chunks_table.delete().where(chunks_table.c.paper_id == meta.paper_id)
            )
            if chunks:
                year = meta.date_published.year if meta.date_published else None
                await session.execute(
                    chunks_table.insert(),
                    [
                        {
                            "id": c.id,
                            "paper_id": c.paper_id,
                            "title": meta.title,
                            "authors_short": ", ".join(meta.authors[:2])
                                + (" et al." if len(meta.authors) > 2 else ""),
                            "year": year,
                            "section": c.section,
                            "chunk_index": c.chunk_index,
                            "text": c.text,
                            "material_family": None,
                            "materials_mentioned": c.materials_mentioned,
                            "has_equation": c.has_equation,
                            "has_table": c.has_table,
                        }
                        for c in chunks
                    ],
                )
            await _persist_chunk_evidence(session, meta.paper_id, chunks)
            await _persist_embedding_completions(session, meta.paper_id, chunks)
            if generation_stager is not None:
                await generation_stager(session, chunks)


async def find_related_arxiv_paper(doi: str) -> str | None:
    """Return the id of an existing arXiv paper sharing this DOI, if any.

    The cross-source dedup anchor (APS plan §3①): when an APS article's
    DOI matches an already-ingested arXiv preprint, we link the two rows
    via ``related_paper_id`` so the aggregator can count them as one
    work. Returns None if there's no arXiv row with this DOI.
    """
    if not doi:
        return None
    async with _session_factory()() as session:
        row = (await session.execute(
            papers_table.select()
            .with_only_columns(papers_table.c.id)
            .where(
                papers_table.c.doi == doi,
                papers_table.c.source == "arxiv",
            )
            .limit(1)
        )).first()
    return row[0] if row else None


async def upsert_paper_geo(
    paper_id: str,
    affiliations: list[Any] | None,
    paper_geo: dict[str, Any] | None,
) -> None:
    """Write author-geography NER output onto an existing papers row.

    Kept separate from ``upsert_paper_with_chunks`` so the geo flow
    stays fully decoupled from the material-NER write path. The UPDATE
    simply matches nothing if the row does not exist yet.
    """
    async with _session_factory()() as session:
        async with session.begin():
            await session.execute(
                papers_table.update()
                .where(papers_table.c.id == paper_id)
                .values(affiliations=affiliations, paper_geo=paper_geo)
            )


# ---------------------------------------------------------------------------
# Vertex AI Vector Search upsert
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _index() -> Any:
    """Return the MatchingEngineIndex attached to the configured endpoint.

    The env var ``VERTEX_AI_INDEX_ENDPOINT`` points at the *endpoint*, so
    we look up the *index* by cross-referencing the deployed_index_id.
    Streaming upserts happen directly on the index resource, not the
    endpoint.
    """
    settings = get_settings()
    if not settings.vertex_ai_index_endpoint:
        raise RuntimeError(
            "VERTEX_AI_INDEX_ENDPOINT is not set — run scripts/create_vertex_index.py",
        )
    aiplatform.init(project=settings.gcp_project, location=settings.gcp_region)
    endpoint = MatchingEngineIndexEndpoint(
        index_endpoint_name=settings.vertex_ai_index_endpoint
    )
    for deployed in endpoint.deployed_indexes:
        if deployed.id == settings.vertex_ai_deployed_index_id:
            return aiplatform.MatchingEngineIndex(index_name=deployed.index)
    raise RuntimeError(
        f"deployed_index_id {settings.vertex_ai_deployed_index_id} not found on "
        f"endpoint {settings.vertex_ai_index_endpoint}",
    )


def _publication_inputs(paper_id: str, chunks: list[Chunk]) -> list[tuple[str, list[float]]]:
    """Validate the entire batch before resolving a cloud client or uploading.

    This checks in-process completion, not shared SQL/vector generation
    atomicity. A valid receipt cannot establish current index membership.
    """
    prepared = []
    seen = set()
    for chunk in chunks:
        if (type(chunk.id) is not str or not 1 <= len(chunk.id) <= 200
                or chunk.paper_id != paper_id or chunk.id in seen):
            raise ValueError("Vector publication requires an exact unique chunk inventory")
        seen.add(chunk.id)
        candidate = validate_candidate(chunk.evidence_candidate)
        if candidate["permission_status"] == "restricted":
            raise ValueError("Restricted evidence cannot be published to vector search")
        vector, _ = _complete_embedding(chunk)
        prepared.append((chunk.id, vector))
    return prepared


def upsert_chunks_to_vector_search(
    parsed: ParsedPaper,
    chunks: list[Chunk],
) -> None:
    """Streaming upsert of chunk vectors + restrict metadata.

    ``restricts`` map to filter-able namespaces so the API router can do
    ``material_family == nickelate`` at query time. Year is numeric.
    """
    if not chunks:
        return
    meta = parsed.meta
    completed = _publication_inputs(meta.paper_id, chunks)
    year = meta.date_submitted.year if meta.date_submitted else None

    datapoints: list[IndexDatapoint] = []
    for chunk_id, vector in completed:
        restricts: list[IndexDatapoint.Restriction] = []
        numeric_restricts: list[IndexDatapoint.NumericRestriction] = []
        if year is not None:
            numeric_restricts.append(
                IndexDatapoint.NumericRestriction(
                    namespace="year", value_int=year
                )
            )
        datapoints.append(
            IndexDatapoint(
                datapoint_id=chunk_id,
                feature_vector=vector,
                restricts=restricts,
                numeric_restricts=numeric_restricts,
                crowding_tag=IndexDatapoint.CrowdingTag(
                    crowding_attribute=meta.paper_id
                ),
            )
        )

    index = _index()
    index.upsert_datapoints(datapoints=datapoints)
    log.info("upserted %d datapoints to Vertex VS (paper=%s)",
             len(datapoints), meta.paper_id)


def upsert_aps_chunks_to_vector_search(
    meta: Any,
    chunks: list[Chunk],
) -> None:
    """Streaming upsert of APS chunk vectors + restrict metadata.

    The APS counterpart of ``upsert_chunks_to_vector_search``. ``meta`` is
    an ``ApsArticleMeta`` (uses ``date_published`` for the year, since APS
    rows have no ``date_submitted``). Adds a ``source='aps'`` restrict
    namespace so the search API can filter by source.

    COMPLIANCE: the ``chunks`` passed here are authorized-derived only
    (abstract + NER fact-sentences) — never APS full-text body.
    """
    if not chunks:
        return
    completed = _publication_inputs(meta.paper_id, chunks)
    year = meta.date_published.year if meta.date_published else None

    datapoints: list[IndexDatapoint] = []
    for chunk_id, vector in completed:
        restricts: list[IndexDatapoint.Restriction] = [
            IndexDatapoint.Restriction(namespace="source", allow_list=["aps"]),
        ]
        numeric_restricts: list[IndexDatapoint.NumericRestriction] = []
        if year is not None:
            numeric_restricts.append(
                IndexDatapoint.NumericRestriction(namespace="year", value_int=year)
            )
        datapoints.append(
            IndexDatapoint(
                datapoint_id=chunk_id,
                feature_vector=vector,
                restricts=restricts,
                numeric_restricts=numeric_restricts,
                crowding_tag=IndexDatapoint.CrowdingTag(
                    crowding_attribute=meta.paper_id
                ),
            )
        )

    index = _index()
    index.upsert_datapoints(datapoints=datapoints)
    log.info("upserted %d APS datapoints to Vertex VS (paper=%s)",
             len(datapoints), meta.paper_id)


# ---------------------------------------------------------------------------
# Cleanup (used by tests + a potential `drop` CLI)
# ---------------------------------------------------------------------------

async def dispose() -> None:
    await _engine().dispose()
    _engine.cache_clear()
    _session_factory.cache_clear()
