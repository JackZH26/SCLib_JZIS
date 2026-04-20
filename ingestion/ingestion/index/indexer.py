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

from google.cloud import aiplatform
from google.cloud.aiplatform.matching_engine.matching_engine_index_endpoint import (
    MatchingEngineIndexEndpoint,
)
from google.cloud.aiplatform_v1.types import IndexDatapoint
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    REAL,
    SmallInteger,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from ingestion.config import get_settings
from ingestion.models import Chunk, ParsedPaper

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
    Column("title", Text, nullable=False),
    Column("authors", JSONB, nullable=False),
    Column("affiliations", JSONB),
    Column("date_submitted", Date),
    Column("date_published", Date),
    Column("journal", String(300)),
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
    Column("tc_max", REAL),
    Column("tc_max_conditions", String(300)),
    Column("tc_ambient", REAL),
    Column("pairing_symmetry", String(100)),
    Column("discovery_year", SmallInteger),
    Column("total_papers", Integer, nullable=False, server_default="0"),
    Column("status", String(50), nullable=False, server_default="active_research"),
    Column("records", JSONB, nullable=False, server_default="[]"),
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
    Column("is_topological", Boolean, server_default="false"),
    Column("is_unconventional", Boolean),
    Column("has_competing_order", Boolean, server_default="false"),
    Column("is_2d_or_interface", Boolean, server_default="false"),
    Column("retracted", Boolean, server_default="false"),
    Column("disputed", Boolean, server_default="false"),
    # v3 sanity gate (see api/alembic/versions/0005_needs_review.py)
    Column("needs_review", Boolean, nullable=False, server_default="false"),
    Column("review_reason", String(200)),
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

async def upsert_paper_with_chunks(
    parsed: ParsedPaper,
    chunks: list[Chunk],
    materials_extracted: list[dict[str, Any]],
) -> None:
    """Upsert a paper row + replace its chunks atomically."""
    meta = parsed.meta
    paper_values: dict[str, Any] = {
        "id": meta.paper_id,
        "source": "arxiv",
        "arxiv_id": meta.arxiv_id,
        "doi": meta.doi,
        "title": meta.title,
        "authors": meta.authors,
        "date_submitted": meta.date_submitted,
        "date_published": meta.date_submitted,
        "abstract": meta.abstract,
        "categories": meta.categories,
        "material_family": None,
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
                    "date_submitted", "date_published",
                    "chunk_count", "materials_extracted", "doi",
                ]
            }
            update_cols["updated_at"] = func.now()
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
    index = _index()

    meta = parsed.meta
    year = meta.date_submitted.year if meta.date_submitted else None

    datapoints: list[IndexDatapoint] = []
    for c in chunks:
        if c.embedding is None:
            continue
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
                datapoint_id=c.id,
                feature_vector=c.embedding,
                restricts=restricts,
                numeric_restricts=numeric_restricts,
                crowding_tag=IndexDatapoint.CrowdingTag(
                    crowding_attribute=meta.paper_id
                ),
            )
        )

    if not datapoints:
        log.warning("no embedded datapoints to upsert for %s", meta.paper_id)
        return

    index.upsert_datapoints(datapoints=datapoints)
    log.info("upserted %d datapoints to Vertex VS (paper=%s)",
             len(datapoints), meta.paper_id)


# ---------------------------------------------------------------------------
# Cleanup (used by tests + a potential `drop` CLI)
# ---------------------------------------------------------------------------

async def dispose() -> None:
    await _engine().dispose()
    _engine.cache_clear()
    _session_factory.cache_clear()
