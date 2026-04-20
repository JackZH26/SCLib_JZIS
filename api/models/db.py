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

    # --- Google OAuth / unified auth -------------------------------------
    google_sub: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    auth_provider: Mapped[str] = mapped_column(String(20), default="local", server_default="local")
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{basic,sclib}", nullable=False)
    profile: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False)

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

    user: Mapped[User] = relationship(back_populates="api_keys")


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
    discovery_year: Mapped[int | None] = mapped_column(SmallInteger)
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
    is_topological:      Mapped[bool | None] = mapped_column(Boolean, server_default="false")
    is_unconventional:   Mapped[bool | None] = mapped_column(Boolean)
    has_competing_order: Mapped[bool | None] = mapped_column(Boolean, server_default="false")
    is_2d_or_interface:  Mapped[bool | None] = mapped_column(Boolean, server_default="false")
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

    __table_args__ = (
        Index("idx_materials_family", "family"),
        Index("idx_materials_tc", "tc_max"),  # NULLS LAST handled in query
        Index("idx_materials_pairing", "pairing_symmetry"),
        Index("idx_materials_phase", "structure_phase"),
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
