"""SQLAlchemy 2.x ORM for SCLib_JZIS.

Tables mirror PROJECT_SPEC.md section 4 one-to-one. Any change here MUST
be accompanied by an Alembic revision. DO NOT edit the schema without
generating a migration — `docker compose exec api alembic revision
--autogenerate -m "..."`.

The engine is created lazily (get_engine) so test suites can monkeypatch
the DSN before import-time side effects happen.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date, datetime
from functools import lru_cache
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
    ARRAY,
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
    text,
)


#: All datetime columns use TIMESTAMPTZ. Never store naive datetimes — see
#: routers/auth.py for how we construct values in UTC.
_TZDT = DateTime(timezone=True)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from config import get_settings


class Base(DeclarativeBase):
    """Declarative base. JSONB on Postgres, JSON fallback elsewhere (tests)."""

    type_annotation_map = {
        dict[str, Any]: JSONB,
        list[Any]: JSONB,
    }


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    institution: Mapped[str | None] = mapped_column(String(500))
    country: Mapped[str | None] = mapped_column(String(100))
    age: Mapped[int | None] = mapped_column(SmallInteger)
    research_area: Mapped[str | None] = mapped_column(String(255))
    purpose: Mapped[str | None] = mapped_column(Text)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(_TZDT, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        _TZDT, server_default=func.now(), onupdate=func.now(), nullable=False
    )
    last_login: Mapped[datetime | None] = mapped_column(_TZDT)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_reviewer: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # --- Google OAuth / unified auth -------------------------------------
    google_sub: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    auth_provider: Mapped[str] = mapped_column(String(20), default="local", server_default="local")
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{basic,sclib}", nullable=False)
    profile: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False)

    # --- Dashboard Phase A (editable profile extras) ---------------------
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    orcid: Mapped[str | None] = mapped_column(String(19), nullable=True)

    verifications: Mapped[list["EmailVerification"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    api_keys: Mapped[list["ApiKey"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("age IS NULL OR (age >= 13 AND age <= 120)", name="ck_users_age_range"),
    )


class EmailVerification(Base):
    __tablename__ = "email_verifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(_TZDT, nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TZDT, server_default=func.now(), nullable=False)

    user: Mapped[User] = relationship(back_populates="verifications")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    name: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(_TZDT, server_default=func.now(), nullable=False)
    last_used: Mapped[datetime | None] = mapped_column(_TZDT)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Dashboard Phase A: counter bumped on every successful auth in
    # deps.require_identity; paired revoked_at timestamp for the UI.
    total_requests: Mapped[int] = mapped_column(
        sa.BigInteger, server_default=sa.text("0"), default=0, nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(_TZDT, nullable=True)

    user: Mapped[User] = relationship(back_populates="api_keys")


class AskHistory(Base):
    """Per-user record of /ask interactions.

    The aggregated source list (JSONB) is a snapshot of the AskSource[]
    that the API returned; the dashboard can re-render the entry
    without re-hitting the vector store. A periodic task in main.py
    prunes rows older than 90 days.
    """

    __tablename__ = "ask_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=sa.text("'[]'::jsonb"), default=list, nullable=False
    )
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        _TZDT, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_ask_history_user_created", "user_id", sa.text("created_at DESC")),
        Index("idx_ask_history_created", "created_at"),
    )


class AuditReport(Base):
    """One row per (rule, run) of the nightly data audit.

    Lets the admin UI surface "last night's run", trend lines per
    rule, and quickly jump to the sample ids that got flagged.
    """

    __tablename__ = "audit_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
        default=uuid.uuid4,
    )
    started_at: Mapped[datetime] = mapped_column(_TZDT, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(_TZDT, nullable=False)
    rule_name: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    rows_flagged: Mapped[int] = mapped_column(
        Integer, server_default=sa.text("0"), nullable=False
    )
    delta_vs_previous: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sample_ids: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False
    )

    __table_args__ = (
        Index("idx_audit_reports_started", "started_at"),
        Index("idx_audit_reports_rule_started", "rule_name", "started_at"),
    )


class Bookmark(Base):
    """User-private bookmark of a paper or material.

    target_type is constrained to {'paper', 'material'} at the DB level;
    (user_id, target_type, target_id) is unique so double-POSTs 409.
    Cascade-deletes with the owning user.
    """

    __tablename__ = "bookmarks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        _TZDT, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "target_type IN ('paper', 'material')",
            name="ck_bookmarks_target_type",
        ),
        sa.UniqueConstraint(
            "user_id", "target_type", "target_id",
            name="uq_bookmarks_user_target",
        ),
        Index(
            "idx_bookmarks_user_type_created",
            "user_id", "target_type", sa.text("created_at DESC"),
        ),
    )


# ---------------------------------------------------------------------------
# Papers / Materials / Chunks
# ---------------------------------------------------------------------------

class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)  # "arxiv:2306.07275"
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    arxiv_id: Mapped[str | None] = mapped_column(String(20))
    doi: Mapped[str | None] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    authors: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    affiliations: Mapped[list[Any] | None] = mapped_column(JSONB)
    date_submitted: Mapped[date | None] = mapped_column(Date)
    date_published: Mapped[date | None] = mapped_column(Date)
    journal: Mapped[str | None] = mapped_column(String(300))
    abstract: Mapped[str] = mapped_column(Text, nullable=False)
    categories: Mapped[list[Any] | None] = mapped_column(JSONB)
    material_family: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="published", nullable=False)
    retraction_date: Mapped[date | None] = mapped_column(Date)
    retraction_reason: Mapped[str | None] = mapped_column(Text)
    citation_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    materials_extracted: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    quality_flags: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    indexed_at: Mapped[datetime] = mapped_column(_TZDT, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        _TZDT, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    chunks: Mapped[list["Chunk"]] = relationship(back_populates="paper", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_papers_family", "material_family"),
        Index("idx_papers_date", "date_published"),
        Index("idx_papers_status", "status"),
        Index("idx_papers_arxiv", "arxiv_id"),
    )


class Material(Base):
    __tablename__ = "materials"

    # --- v1 core ----------------------------------------------------------
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    formula: Mapped[str] = mapped_column(String(200), nullable=False)
    formula_normalized: Mapped[str] = mapped_column(String(200), nullable=False)
    formula_latex: Mapped[str | None] = mapped_column(String(200))
    family: Mapped[str | None] = mapped_column(String(50))
    subfamily: Mapped[str | None] = mapped_column(String(100))
    crystal_structure: Mapped[str | None] = mapped_column(String(100))
    tc_max: Mapped[float | None] = mapped_column()
    tc_max_conditions: Mapped[str | None] = mapped_column(String(300))
    tc_ambient: Mapped[float | None] = mapped_column()
    pairing_symmetry: Mapped[str | None] = mapped_column(String(100))
    arxiv_year: Mapped[int | None] = mapped_column(SmallInteger)
    total_papers: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="active_research", nullable=False)
    records: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        _TZDT, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # --- v2 structural ----------------------------------------------------
    space_group:     Mapped[str | None]  = mapped_column(String(50))
    structure_phase: Mapped[str | None]  = mapped_column(String(50))
    lattice_params:  Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # --- v2 SC parameters -------------------------------------------------
    gap_structure:   Mapped[str | None]   = mapped_column(String(50))
    hc2_tesla:       Mapped[float | None] = mapped_column(Float)
    hc2_conditions:  Mapped[str | None]   = mapped_column(String(200))
    lambda_eph:      Mapped[float | None] = mapped_column(Float)
    omega_log_k:     Mapped[float | None] = mapped_column(Float)
    rho_s_mev:       Mapped[float | None] = mapped_column(Float)

    # --- v2 competing orders ---------------------------------------------
    t_cdw_k:         Mapped[float | None] = mapped_column(Float)
    t_sdw_k:         Mapped[float | None] = mapped_column(Float)
    t_afm_k:         Mapped[float | None] = mapped_column(Float)
    rho_exponent:    Mapped[float | None] = mapped_column(Float)
    competing_order: Mapped[str | None]   = mapped_column(String(100))

    # --- v2 samples + pressure -------------------------------------------
    ambient_sc:      Mapped[bool | None]  = mapped_column(Boolean)
    pressure_type:   Mapped[str | None]   = mapped_column(String(50))
    sample_form:     Mapped[str | None]   = mapped_column(String(50))
    substrate:       Mapped[str | None]   = mapped_column(String(100))
    doping_type:     Mapped[str | None]   = mapped_column(String(50))
    doping_level:    Mapped[float | None] = mapped_column(Float)

    # --- v2 flags ---------------------------------------------------------
    is_unconventional:   Mapped[bool | None] = mapped_column(Boolean)
    has_competing_order: Mapped[bool | None] = mapped_column(Boolean, server_default="false")
    retracted:           Mapped[bool | None] = mapped_column(Boolean, server_default="false")
    disputed:            Mapped[bool | None] = mapped_column(Boolean, server_default="false")

    # --- v3 automatic sanity gate ----------------------------------------
    # Set by the aggregator when a record crosses a physical sanity
    # threshold (e.g. Tc > 250 K at ambient pressure, almost always an
    # NER confusion of Curie / structural transition with SC Tc).
    # Materials flagged here are hidden from GET /materials unless
    # ``?include_pending=true``; the row is kept for audit and for
    # direct-link access via GET /materials/{id}.
    needs_review: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False,
    )
    review_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Admin override channel: when an admin reviews a flagged row and
    # signs off, the JSON blob records the rule, reviewer, timestamp,
    # and free-form note. The nightly audit checks this to skip rows
    # whose flag has already been adjudicated.
    admin_decision: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # --- Materials Project linkage (Phase B) -----------------------------
    # Populated out-of-band by ``scripts/sync_mp_ids.py``; stays NULL for
    # rows whose formula has no MP match (NIMS oxynitrides, non-stoich
    # cuprates with δ, etc.). See alembic 0013 + DATA_SOURCES.md "mp" row.
    mp_id:            Mapped[str | None]      = mapped_column(String(50))
    mp_alternate_ids: Mapped[list[str]]       = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False,
    )
    mp_synced_at:     Mapped[datetime | None] = mapped_column(_TZDT)

    __table_args__ = (
        Index("idx_materials_family", "family"),
        Index("idx_materials_tc", "tc_max"),  # NULLS LAST handled in query
        Index("idx_materials_pairing", "pairing_symmetry"),
        Index("idx_materials_phase", "structure_phase"),
        # Partial index — see alembic 0013 for rationale.
        Index(
            "idx_materials_mp_id", "mp_id",
            postgresql_where=text("mp_id IS NOT NULL"),
        ),
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    paper_id: Mapped[str] = mapped_column(String(100), ForeignKey("papers.id"), nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    authors_short: Mapped[str | None] = mapped_column(String(200))
    year: Mapped[int | None] = mapped_column(SmallInteger)
    section: Mapped[str | None] = mapped_column(String(200))
    chunk_index: Mapped[int | None] = mapped_column(SmallInteger)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    material_family: Mapped[str | None] = mapped_column(String(50))
    materials_mentioned: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    has_equation: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_table: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    paper: Mapped[Paper] = relationship(back_populates="chunks")

    __table_args__ = (Index("idx_chunks_paper", "paper_id"),)


class StatsCache(Base):
    __tablename__ = "stats_cache"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        _TZDT, server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Data-quality infrastructure (P0 pipeline optimization)
# ---------------------------------------------------------------------------


class RefutedClaim(Base):
    """Materials whose superconductivity claims have been scientifically refuted.

    Matched by *canonical* formula during aggregation — any material whose
    ``canonical`` matches a row here is auto-flagged ``disputed=True``.

    Seed data: LK-99, CSH (Dias retractions), AgB₂, ZrZn₂, etc.
    """

    __tablename__ = "refuted_claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    formula: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    canonical: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    claim_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="room_temp_sc | superconductor | tc_value",
    )
    claimed_tc: Mapped[float | None] = mapped_column(Float)
    refutation_doi: Mapped[str | None] = mapped_column(String(200))
    refutation_year: Mapped[int | None] = mapped_column(SmallInteger)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        _TZDT, server_default=func.now(), nullable=False,
    )


class ManualOverride(Base):
    """Curated per-compound corrections and Tc caps.

    Two modes (``is_cap`` flag):

    * **Exact override** (``is_cap=False``): replaces the aggregated value
      unconditionally. Used for P0 hotfixes (LSCO tc_max=38, FeSe tc_ambient=8.5).
    * **Cap** (``is_cap=True``): clamps the aggregated value to an upper bound.
      Used for per-compound physical ceilings (LSCO tc_max ≤ 45 K).

    The nightly re-aggregation reads this table; values here are never
    overwritten by automated pipeline runs.
    """

    __tablename__ = "manual_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    formula: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    canonical: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    field: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="target column: tc_max | tc_ambient | hc2_tesla | pairing_symmetry | ...",
    )
    override_value: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="JSON-encoded value (number as string, or quoted string for enums)",
    )
    is_cap: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
        comment="True = upper-bound clamp; False = exact replacement",
    )
    source: Mapped[str] = mapped_column(
        String(200), nullable=False,
        comment="DOI, review reference, or free-text provenance",
    )
    reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(
        String(100), default="system", server_default="system", nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        _TZDT, server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        Index("idx_overrides_canonical_field", "canonical", "field"),
    )


# ---------------------------------------------------------------------------
# Engine / session (async, module-level cached)
# ---------------------------------------------------------------------------

def _to_async_dsn(dsn: str) -> str:
    """Convert a postgresql:// DSN to postgresql+asyncpg:// for the async engine.

    Alembic uses the original (sync) DSN via psycopg2, so we keep the raw
    DATABASE_URL in settings and translate only here.
    """
    if dsn.startswith("postgresql+asyncpg://"):
        return dsn
    if dsn.startswith("postgresql://"):
        return "postgresql+asyncpg://" + dsn[len("postgresql://"):]
    if dsn.startswith("postgres://"):
        return "postgresql+asyncpg://" + dsn[len("postgres://"):]
    return dsn


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        _to_async_dsn(settings.database_url),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )


@lru_cache(maxsize=1)
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields an AsyncSession scoped to the request."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
