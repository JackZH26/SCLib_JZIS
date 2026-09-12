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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from config import get_settings

#: All datetime columns use TIMESTAMPTZ. Never store naive datetimes — see
#: routers/auth.py for how we construct values in UTC.
_TZDT = DateTime(timezone=True)


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
    # Incrementing this invalidates every previously issued JWT while API
    # keys remain governed by their separate revocation lifecycle.
    session_version: Mapped[int] = mapped_column(
        Integer, default=0, server_default=sa.text("0"), nullable=False
    )

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
    password_reset_tokens: Mapped[list["PasswordResetToken"]] = relationship(
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


class PasswordResetToken(Base):
    """Single-use password reset grant; plaintext tokens are never stored."""

    __tablename__ = "password_reset_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(_TZDT, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(_TZDT, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        _TZDT, server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="password_reset_tokens")

    __table_args__ = (
        Index("idx_password_reset_user_created", "user_id", "created_at"),
        Index("idx_password_reset_expires", "expires_at"),
    )


class AuthAuditEvent(Base):
    """Privacy-preserving record of accepted authentication operations."""

    __tablename__ = "auth_audit_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    account_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_ip_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    user_agent_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=sa.text("'{}'::jsonb"), default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        _TZDT, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_auth_audit_created", "created_at"),
        Index("idx_auth_audit_user_created", "user_id", "created_at"),
        Index("idx_auth_audit_account_created", "account_hash", "created_at"),
    )


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
    # NULL is deliberately retained for pre-0068 snapshots; never backfilled.
    evidence_receipt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
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
    suggested_fix: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_fixes: Mapped[list[Any]] = mapped_column(
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


class SourceSnapshot(Base):
    """Immutable lineage anchor for one captured SCLib source state.

    A row may be assembled while ``status='building'``.  Once frozen, its
    manifest hash and timestamp are mandatory and the application must treat
    it as immutable.  The schema deliberately stores counts and versions, not
    a copy of source payloads.
    """

    __tablename__ = "source_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
        default=uuid.uuid4,
    )
    dataset_version: Mapped[str] = mapped_column(String(50), nullable=False)
    site_git_sha: Mapped[str | None] = mapped_column(String(40))
    database_watermark: Mapped[datetime | None] = mapped_column(_TZDT)
    paper_count: Mapped[int] = mapped_column(
        sa.BigInteger, server_default="0", default=0, nullable=False,
    )
    material_count: Mapped[int] = mapped_column(
        sa.BigInteger, server_default="0", default=0, nullable=False,
    )
    chunk_count: Mapped[int] = mapped_column(
        sa.BigInteger, server_default="0", default=0, nullable=False,
    )
    schema_version: Mapped[str] = mapped_column(String(30), nullable=False)
    manifest_sha256: Mapped[str | None] = mapped_column(String(64))
    license_manifest_sha256: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(
        String(20), server_default="building", default="building", nullable=False,
    )
    # ``metadata`` is reserved by SQLAlchemy's declarative base; retain the
    # concise database column name while exposing a safe Python attribute.
    snapshot_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        server_default=sa.text("'{}'::jsonb"),
        default=dict,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        _TZDT, server_default=func.now(), nullable=False,
    )
    frozen_at: Mapped[datetime | None] = mapped_column(_TZDT)

    __table_args__ = (
        CheckConstraint(
            "status IN ('building', 'validated', 'frozen', 'failed')",
            name="ck_source_snapshots_status",
        ),
        CheckConstraint(
            "paper_count >= 0 AND material_count >= 0 AND chunk_count >= 0",
            name="ck_source_snapshots_counts_nonnegative",
        ),
        CheckConstraint(
            "manifest_sha256 IS NULL OR length(manifest_sha256) = 64",
            name="ck_source_snapshots_manifest_hash",
        ),
        CheckConstraint(
            "license_manifest_sha256 IS NULL OR length(license_manifest_sha256) = 64",
            name="ck_source_snapshots_license_hash",
        ),
        CheckConstraint(
            "status <> 'frozen' OR (manifest_sha256 IS NOT NULL AND frozen_at IS NOT NULL)",
            name="ck_source_snapshots_frozen_manifest",
        ),
        CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name="ck_source_snapshots_metadata_object",
        ),
        sa.UniqueConstraint("manifest_sha256", name="uq_source_snapshots_manifest"),
        Index("idx_source_snapshots_version", "dataset_version"),
        Index("idx_source_snapshots_status_created", "status", "created_at"),
    )


class Work(Base):
    """One scholarly work shared by preprint and published paper records."""

    __tablename__ = "works"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
        default=uuid.uuid4,
    )
    canonical_title: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_doi: Mapped[str | None] = mapped_column(String(200))
    canonical_arxiv_id: Mapped[str | None] = mapped_column(String(20))
    publication_status: Mapped[str] = mapped_column(
        String(20), server_default="unknown", default="unknown", nullable=False,
    )
    available_at: Mapped[date | None] = mapped_column(Date)
    identity_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        server_default=sa.text("'{}'::jsonb"),
        default=dict,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        _TZDT, server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        _TZDT, server_default=func.now(), onupdate=func.now(), nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "publication_status IN ('active', 'retracted', 'withdrawn', 'corrected', 'unknown')",
            name="ck_works_publication_status",
        ),
        CheckConstraint(
            "btrim(canonical_title) <> ''",
            name="ck_works_canonical_title_nonempty",
        ),
        CheckConstraint(
            "jsonb_typeof(identity_metadata) = 'object'",
            name="ck_works_identity_metadata_object",
        ),
        Index(
            "uq_works_canonical_doi",
            "canonical_doi",
            unique=True,
            postgresql_where=text("canonical_doi IS NOT NULL"),
        ),
        Index(
            "uq_works_canonical_arxiv",
            "canonical_arxiv_id",
            unique=True,
            postgresql_where=text("canonical_arxiv_id IS NOT NULL"),
        ),
        Index("idx_works_available_at", "available_at"),
    )


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)  # "arxiv:2306.07275"
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    arxiv_id: Mapped[str | None] = mapped_column(String(20))
    doi: Mapped[str | None] = mapped_column(String(200))
    # --- normalized cross-source identity (alembic 0038) ------------------
    # ``external_id`` is the source-native id (arXiv: arxiv_id; APS: DOI);
    # ``id_scheme`` names its namespace ('arxiv' | 'nims' | 'doi').
    # UNIQUE(source, external_id) is the dedup anchor.
    external_id: Mapped[str | None] = mapped_column(String(200))
    id_scheme: Mapped[str | None] = mapped_column(String(20))
    # Self-FK linking an arXiv preprint to its APS published version as the
    # "same work" — the aggregator collapses identical records across the
    # pair but keeps a differing Tc as a new value (see APS plan §3①).
    related_paper_id: Mapped[str | None] = mapped_column(
        String(100), ForeignKey("papers.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    authors: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    affiliations: Mapped[list[Any] | None] = mapped_column(JSONB)
    # Backend-only author/institution geography (see alembic 0035).
    # Never exposed by an API response model — kept for analysis only.
    paper_geo: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    date_submitted: Mapped[date | None] = mapped_column(Date)
    date_published: Mapped[date | None] = mapped_column(Date)
    journal: Mapped[str | None] = mapped_column(String(300))
    # APS journal identity (alembic 0038): short handle ('PRB','PRL',...)
    # + structured bibliographic ref {volume, issue, article_id, page,
    # published_date}. NULL for arXiv/NIMS rows.
    journal_abbrev: Mapped[str | None] = mapped_column(String(30))
    publication_ref: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
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
    # --- credibility scoring -----------------------------------------------
    credibility_tier: Mapped[str | None] = mapped_column(String(2))  # T1-T5
    paper_type: Mapped[str | None] = mapped_column(String(20))       # experimental|theoretical|computational|review
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
        Index("idx_papers_journal_abbrev", "journal_abbrev"),
        # Cross-source dedup anchor (alembic 0038). Partial so legacy rows
        # with a NULL external_id never collide.
        Index(
            "uq_papers_source_external", "source", "external_id",
            unique=True, postgresql_where=text("external_id IS NOT NULL"),
        ),
        # APS rows unique by DOI, scoped so an arXiv preprint and its APS
        # version may share a DOI across sources.
        Index(
            "uq_papers_aps_doi", "doi",
            unique=True,
            postgresql_where=text("source = 'aps' AND doi IS NOT NULL"),
        ),
        Index(
            "idx_papers_related", "related_paper_id",
            postgresql_where=text("related_paper_id IS NOT NULL"),
        ),
    )


class PaperWorkMap(Base):
    """Assign each source-specific paper row to exactly one scholarly work."""

    __tablename__ = "paper_work_map"

    paper_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("papers.id", ondelete="CASCADE"),
        primary_key=True,
    )
    work_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("works.id", ondelete="CASCADE"),
        nullable=False,
    )
    relation_type: Mapped[str] = mapped_column(
        String(30), server_default="unknown", default="unknown", nullable=False,
    )
    match_method: Mapped[str] = mapped_column(String(30), nullable=False)
    match_score: Mapped[float | None] = mapped_column(Float)
    review_status: Mapped[str] = mapped_column(
        String(20), server_default="pending", default="pending", nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        _TZDT, server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "relation_type IN "
            "('canonical_version', 'preprint', 'published_version', "
            "'supplement', 'correction', 'unknown')",
            name="ck_paper_work_map_relation_type",
        ),
        CheckConstraint(
            "match_method IN "
            "('exact_doi', 'related_paper', 'exact_arxiv', 'metadata', 'manual', 'singleton')",
            name="ck_paper_work_map_match_method",
        ),
        CheckConstraint(
            "match_score IS NULL OR (match_score >= 0 AND match_score <= 1)",
            name="ck_paper_work_map_match_score",
        ),
        CheckConstraint(
            "review_status IN ('pending', 'accepted', 'rejected')",
            name="ck_paper_work_map_review_status",
        ),
        Index("idx_paper_work_map_work", "work_id"),
        Index("idx_paper_work_map_review", "review_status"),
    )


class Material(Base):
    __tablename__ = "materials"

    # --- v1 core ----------------------------------------------------------
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    formula: Mapped[str] = mapped_column(String(200), nullable=False)
    formula_normalized: Mapped[str] = mapped_column(String(200), nullable=False)
    formula_latex: Mapped[str | None] = mapped_column(String(200))
    # --- ML Foundation v1 composition enrichment ------------------------
    # NULL means not processed yet. Ambiguous/non-stoichiometric formulae
    # retain their original spelling and receive an explicit non-exact state.
    composition_status: Mapped[str | None] = mapped_column(String(20))
    composition_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    composition_enriched_at: Mapped[datetime | None] = mapped_column(_TZDT)
    family: Mapped[str | None] = mapped_column(String(50))
    subfamily: Mapped[str | None] = mapped_column(String(100))
    crystal_structure: Mapped[str | None] = mapped_column(String(100))
    tc_max: Mapped[float | None] = mapped_column()
    tc_max_conditions: Mapped[str | None] = mapped_column(String(300))
    tc_ambient: Mapped[float | None] = mapped_column()
    # P1b A2: evidence-tier split
    dominant_evidence: Mapped[str | None] = mapped_column(String(20))
    tc_max_experimental: Mapped[float | None] = mapped_column(Float)
    tc_max_theoretical: Mapped[float | None] = mapped_column(Float)
    pairing_symmetry: Mapped[str | None] = mapped_column(String(100))
    arxiv_year: Mapped[int | None] = mapped_column(SmallInteger)
    total_papers: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="active_research", nullable=False)
    records: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    # Rebuildable review projection and bounded legacy review-rule inputs.
    # Neither field is permission to alter raw records or approve a claim.
    anomaly_review: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False)
    anomaly_context: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False)
    # SC10: rebuildable reported-property/heterogeneity view, not approval.
    material_semantics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False)
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
    has_competing_order: Mapped[bool | None] = mapped_column(Boolean)
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
    # Legacy governance note, not revision-bound scientific approval. Fresh
    # audits must reevaluate current evidence regardless of this field. The
    # historical note is retained, never silently erased by re-aggregation.
    admin_decision: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Best credibility tier across all records (T1 < T2 < T3).
    best_credibility_tier: Mapped[str | None] = mapped_column(String(2))

    # --- P2: Parent-variant model (A4) ------------------------------------
    # Doping variants (YBa2Cu3O6.95) point at parent (YBa2Cu3O7-δ).
    parent_material_id: Mapped[str | None] = mapped_column(
        String(100), ForeignKey("materials.id", ondelete="SET NULL"),
    )
    variant_count: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False,
    )

    # --- P2: Interface material decomposition (A5) ----------------------
    formula_substrate:  Mapped[str | None]   = mapped_column(String(200))
    formula_overlayer:  Mapped[str | None]   = mapped_column(String(200))
    layer_thickness_nm: Mapped[float | None] = mapped_column(Float)

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
        CheckConstraint(
            "composition_status IS NULL OR composition_status IN "
            "('exact', 'variable', 'interface', 'mixture', 'invalid')",
            name="ck_materials_composition_status",
        ),
        CheckConstraint(
            "composition_data IS NULL OR jsonb_typeof(composition_data) = 'object'",
            name="ck_materials_composition_data_object",
        ),
        CheckConstraint(
            "composition_enriched_at IS NULL OR composition_status IS NOT NULL",
            name="ck_materials_composition_enriched_status",
        ),
        Index("idx_materials_family", "family"),
        Index("idx_materials_tc", "tc_max"),  # NULLS LAST handled in query
        Index("idx_materials_composition_status", "composition_status"),
        Index("idx_materials_pairing", "pairing_symmetry"),
        Index("idx_materials_phase", "structure_phase"),
        Index(
            "idx_materials_parent_id", "parent_material_id",
            postgresql_where=text("parent_material_id IS NOT NULL"),
        ),
        # Partial index — see alembic 0013 for rationale.
        Index(
            "idx_materials_mp_id", "mp_id",
            postgresql_where=text("mp_id IS NOT NULL"),
        ),
    )


class TimelineProjectionPoint(Base):
    """Read-optimized projection of one source-reported Timeline occurrence.

    ``materials.records`` remains the authoritative source. Rows are updated
    transactionally by the API's projection refresher; stale derived rows are
    soft-disabled with ``active=False`` so source data is never removed.
    """

    __tablename__ = "timeline_projection_points"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    material_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("materials.id", ondelete="CASCADE"),
        nullable=False,
    )
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    tc_kelvin: Mapped[float] = mapped_column(Float, nullable=False)
    pressure_gpa: Mapped[float | None] = mapped_column(Float)
    pressure_semantics: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    # Rebuildable identity/date provenance; never an accepted result ledger.
    result_metadata: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    paper_id: Mapped[str | None] = mapped_column(String(100))
    is_theoretical: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False,
    )
    knowledge_origin: Mapped[str] = mapped_column(String(20), server_default="Unknown", nullable=False)
    classification_status: Mapped[str] = mapped_column(String(20), server_default="unknown", nullable=False)
    source_role: Mapped[str] = mapped_column(String(20), server_default="unknown", nullable=False)
    classifier_version: Mapped[str] = mapped_column(String(80), server_default="legacy/unclassified", nullable=False)
    is_aps: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False,
    )
    active: Mapped[bool] = mapped_column(
        Boolean, server_default="true", nullable=False,
    )
    source_updated_at: Mapped[datetime] = mapped_column(_TZDT, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        _TZDT, server_default=func.now(), onupdate=func.now(), nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "year >= 1900 AND year <= 2200",
            name="ck_timeline_projection_year",
        ),
        CheckConstraint(
            "tc_kelvin > 0 AND tc_kelvin < 'Infinity'::float8 AND tc_kelvin <> 'NaN'::float8",
            name="ck_timeline_projection_tc",
        ),
        Index(
            "idx_timeline_projection_active_year",
            "year",
            postgresql_where=text("active IS TRUE"),
        ),
        Index(
            "idx_timeline_projection_material_active",
            "material_id",
            postgresql_where=text("active IS TRUE"),
        ),
        Index(
            "idx_timeline_projection_aps_active",
            "is_aps",
            postgresql_where=text("active IS TRUE"),
        ),
        Index(
            "idx_timeline_projection_theory_active",
            "is_theoretical",
            postgresql_where=text("active IS TRUE"),
        ),
    )


class TimelineProjectionState(Base):
    """Singleton readiness and incremental-refresh watermark."""

    __tablename__ = "timeline_projection_state"

    id: Mapped[int] = mapped_column(
        SmallInteger, primary_key=True, autoincrement=False,
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    classifier_version: Mapped[str] = mapped_column(String(80), server_default="legacy/unclassified", nullable=False)
    pressure_policy_version: Mapped[str] = mapped_column(String(80), server_default="legacy/unclassified", nullable=False)
    anomaly_policy_version: Mapped[str] = mapped_column(String(80), server_default="legacy/unclassified", nullable=False)
    source_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    source_watermark: Mapped[datetime] = mapped_column(_TZDT, nullable=False)
    refreshed_at: Mapped[datetime] = mapped_column(_TZDT, nullable=False)
    material_count: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False,
    )
    active_point_count: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False,
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_timeline_projection_state_singleton"),
    )


class HydrideTcParameter(Base):
    """Hydride-specific Tc/pressure/Eliashberg parameter enrichment.

    Written by the independent hydride NER runner, not by the generic
    material NER aggregator. APS rows store only derived structured facts
    and short provenance metadata, never licensed full-text snippets.
    """

    __tablename__ = "hydride_tc_parameters"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    record_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    material_id: Mapped[str | None] = mapped_column(
        String(100), ForeignKey("materials.id", ondelete="SET NULL"),
    )
    formula: Mapped[str] = mapped_column(String(200), nullable=False)
    formula_normalized: Mapped[str] = mapped_column(String(200), nullable=False)
    paper_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False,
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    doi: Mapped[str | None] = mapped_column(String(200))
    arxiv_id: Mapped[str | None] = mapped_column(String(20))
    year: Mapped[int | None] = mapped_column(SmallInteger)
    tc_kelvin: Mapped[float | None] = mapped_column(Float)
    pressure_gpa: Mapped[float | None] = mapped_column(Float)
    lambda_eph: Mapped[float | None] = mapped_column(Float)
    mu_star: Mapped[float | None] = mapped_column(Float)
    omega_log_k: Mapped[float | None] = mapped_column(Float)
    omega_log_source_value: Mapped[float | None] = mapped_column(Float)
    omega_log_source_unit: Mapped[str | None] = mapped_column(String(20))
    method: Mapped[str | None] = mapped_column(String(80))
    evidence_type: Mapped[str | None] = mapped_column(String(40))
    confidence: Mapped[float | None] = mapped_column(Float)
    source_section: Mapped[str | None] = mapped_column(String(200))
    validation_flags: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=sa.text("'[]'::jsonb"), default=list, nullable=False,
    )
    provenance: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=sa.text("'{}'::jsonb"), default=dict, nullable=False,
    )
    model: Mapped[str | None] = mapped_column(String(80))
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        _TZDT, server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        _TZDT, server_default=func.now(), onupdate=func.now(), nullable=False,
    )

    __table_args__ = (
        Index("idx_hydride_params_material", "material_id"),
        Index("idx_hydride_params_paper", "paper_id"),
        Index("idx_hydride_params_formula", "formula_normalized"),
        Index("idx_hydride_params_source_year", "source", "year"),
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


class MaterialClaim(Base):
    """Condition-aware, provenance-bearing superconductivity assertion.

    This table is additive: ``materials.records`` remains available to the
    existing application while records are migrated and revalidated.  NULL
    pressure is never interpreted as ambient pressure, and an accepted
    negative claim must state the experiment's minimum temperature.
    """

    __tablename__ = "material_claims"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
        default=uuid.uuid4,
    )
    material_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("materials.id", ondelete="CASCADE"),
        nullable=False,
    )
    paper_id: Mapped[str | None] = mapped_column(
        String(100), ForeignKey("papers.id", ondelete="SET NULL"),
    )
    work_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("works.id", ondelete="SET NULL"),
    )
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
    )

    property_type: Mapped[str] = mapped_column(
        String(30), server_default="tc", default="tc", nullable=False,
    )
    evidence_role: Mapped[str] = mapped_column(
        String(30), server_default="unknown", default="unknown", nullable=False,
    )
    result_status: Mapped[str] = mapped_column(
        String(20), server_default="unknown", default="unknown", nullable=False,
    )
    value_relation: Mapped[str] = mapped_column(
        String(20), server_default="unreported", default="unreported", nullable=False,
    )
    value_kelvin: Mapped[float | None] = mapped_column(Float)
    value_lower_kelvin: Mapped[float | None] = mapped_column(Float)
    value_upper_kelvin: Mapped[float | None] = mapped_column(Float)
    tc_definition: Mapped[str] = mapped_column(
        String(30), server_default="unknown", default="unknown", nullable=False,
    )

    pressure_state: Mapped[str] = mapped_column(
        String(20), server_default="not_reported", default="not_reported", nullable=False,
    )
    pressure_gpa: Mapped[float | None] = mapped_column(Float)
    minimum_temperature_k: Mapped[float | None] = mapped_column(Float)
    magnetic_field_t: Mapped[float | None] = mapped_column(Float)
    measurement_method: Mapped[str | None] = mapped_column(String(100))
    sample_form: Mapped[str | None] = mapped_column(String(50))
    structure_phase_raw: Mapped[str | None] = mapped_column(String(200))
    doping_raw: Mapped[str | None] = mapped_column(String(200))
    sample_label: Mapped[str | None] = mapped_column(String(100))

    source_kind: Mapped[str] = mapped_column(
        String(30), server_default="legacy", default="legacy", nullable=False,
    )
    chunk_id: Mapped[str | None] = mapped_column(
        String(200), ForeignKey("chunks.id", ondelete="SET NULL"),
    )
    source_locator: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        server_default=sa.text("'{}'::jsonb"),
        default=dict,
        nullable=False,
    )
    extraction_confidence: Mapped[float | None] = mapped_column(Float)
    relation_confidence: Mapped[float | None] = mapped_column(Float)
    validity_status: Mapped[str] = mapped_column(
        String(20), server_default="pending", default="pending", nullable=False,
    )
    raw_record: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        server_default=sa.text("'{}'::jsonb"),
        default=dict,
        nullable=False,
    )
    extraction_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        server_default=sa.text("'{}'::jsonb"),
        default=dict,
        nullable=False,
    )
    source_record_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Shadow v2 binding. Legacy IDs, source hashes and labels are not rewritten.
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    result_key: Mapped[str | None] = mapped_column(String(120))
    interpretation_revision: Mapped[int | None] = mapped_column(sa.Integer)
    semantic_fingerprint: Mapped[str | None] = mapped_column(String(64))
    duplicate_cluster_id: Mapped[str | None] = mapped_column(String(64))
    available_at: Mapped[date | None] = mapped_column(Date)
    extractor_version: Mapped[str] = mapped_column(String(80), nullable=False)
    ingestion_run_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        _TZDT, server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        _TZDT, server_default=func.now(), onupdate=func.now(), nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "property_type IN ('tc', 'non_transition')",
            name="ck_material_claims_property_type",
        ),
        CheckConstraint(
            "evidence_role IN "
            "('primary_experimental', 'primary_theoretical', 'cited', 'unknown')",
            name="ck_material_claims_evidence_role",
        ),
        CheckConstraint(
            "result_status IN ('observed', 'not_detected', 'inconclusive', 'unknown')",
            name="ck_material_claims_result_status",
        ),
        CheckConstraint(
            "value_relation IN ('exact', 'interval', 'lt', 'le', 'gt', 'ge', 'unreported')",
            name="ck_material_claims_value_relation",
        ),
        CheckConstraint(
            "tc_definition IN "
            "('onset', 'zero_resistance', 'midpoint', 'diamagnetic', 'heat_capacity', 'unknown')",
            name="ck_material_claims_tc_definition",
        ),
        CheckConstraint(
            "pressure_state IN ('explicit_ambient', 'reported', 'not_reported', 'ambiguous')",
            name="ck_material_claims_pressure_state",
        ),
        CheckConstraint(
            "source_kind IN ('prose', 'abstract', 'table', 'synthetic_fact', 'legacy')",
            name="ck_material_claims_source_kind",
        ),
        CheckConstraint(
            "validity_status IN ('accepted', 'pending', 'disputed', 'retracted', 'excluded')",
            name="ck_material_claims_validity_status",
        ),
        CheckConstraint(
            "(value_kelvin IS NULL OR (value_kelvin >= 0 "
            "AND value_kelvin < 'Infinity'::float8)) AND "
            "(value_lower_kelvin IS NULL OR (value_lower_kelvin >= 0 "
            "AND value_lower_kelvin < 'Infinity'::float8)) AND "
            "(value_upper_kelvin IS NULL OR (value_upper_kelvin >= 0 "
            "AND value_upper_kelvin < 'Infinity'::float8)) AND "
            "(value_lower_kelvin IS NULL OR value_upper_kelvin IS NULL "
            "OR value_lower_kelvin <= value_upper_kelvin)",
            name="ck_material_claims_value_bounds",
        ),
        CheckConstraint(
            "((value_relation = 'exact' AND value_kelvin IS NOT NULL "
            "AND value_lower_kelvin IS NULL AND value_upper_kelvin IS NULL) OR "
            "(value_relation = 'interval' AND value_kelvin IS NULL "
            "AND value_lower_kelvin IS NOT NULL AND value_upper_kelvin IS NOT NULL) OR "
            "(value_relation IN ('lt', 'le') AND value_kelvin IS NULL "
            "AND value_lower_kelvin IS NULL AND value_upper_kelvin IS NOT NULL) OR "
            "(value_relation IN ('gt', 'ge') AND value_kelvin IS NULL "
            "AND value_lower_kelvin IS NOT NULL AND value_upper_kelvin IS NULL) OR "
            "(value_relation = 'unreported' AND value_kelvin IS NULL "
            "AND value_lower_kelvin IS NULL AND value_upper_kelvin IS NULL))",
            name="ck_material_claims_value_shape",
        ),
        CheckConstraint(
            "((pressure_state = 'explicit_ambient' AND pressure_gpa = 0) OR "
            "(pressure_state = 'reported' AND pressure_gpa IS NOT NULL) OR "
            "(pressure_state = 'not_reported' AND pressure_gpa IS NULL) OR "
            "pressure_state = 'ambiguous')",
            name="ck_material_claims_pressure_semantics",
        ),
        CheckConstraint(
            "pressure_gpa IS NULL OR (pressure_gpa >= 0 "
            "AND pressure_gpa < 'Infinity'::float8)",
            name="ck_material_claims_pressure_nonnegative",
        ),
        CheckConstraint(
            "minimum_temperature_k IS NULL OR (minimum_temperature_k >= 0 "
            "AND minimum_temperature_k < 'Infinity'::float8)",
            name="ck_material_claims_minimum_temperature",
        ),
        CheckConstraint(
            "magnetic_field_t IS NULL OR (magnetic_field_t >= 0 "
            "AND magnetic_field_t < 'Infinity'::float8)",
            name="ck_material_claims_magnetic_field",
        ),
        CheckConstraint(
            "extraction_confidence IS NULL OR "
            "(extraction_confidence >= 0 AND extraction_confidence <= 1)",
            name="ck_material_claims_extraction_confidence",
        ),
        CheckConstraint(
            "relation_confidence IS NULL OR "
            "(relation_confidence >= 0 AND relation_confidence <= 1)",
            name="ck_material_claims_relation_confidence",
        ),
        CheckConstraint(
            "validity_status <> 'accepted' OR result_status <> 'observed' "
            "OR value_relation <> 'unreported'",
            name="ck_material_claims_accepted_observed_value",
        ),
        CheckConstraint(
            "validity_status <> 'accepted' OR result_status <> 'not_detected' "
            "OR minimum_temperature_k IS NOT NULL",
            name="ck_material_claims_accepted_negative_tmin",
        ),
        CheckConstraint(
            "length(source_record_hash) = 64",
            name="ck_material_claims_source_hash",
        ),
        CheckConstraint(
            "semantic_fingerprint IS NULL OR length(semantic_fingerprint) = 64",
            name="ck_material_claims_semantic_hash",
        ),
        CheckConstraint(
            "duplicate_cluster_id IS NULL OR length(duplicate_cluster_id) = 64",
            name="ck_material_claims_duplicate_cluster_hash",
        ),
        CheckConstraint(
            "jsonb_typeof(source_locator) = 'object' "
            "AND jsonb_typeof(raw_record) = 'object' "
            "AND jsonb_typeof(extraction_metadata) = 'object'",
            name="ck_material_claims_json_objects",
        ),
        sa.UniqueConstraint(
            "material_id", "source_record_hash",
            name="uq_material_claims_material_source_hash",
        ),
        sa.ForeignKeyConstraint(
            ["event_id", "material_id"], ["research_events.id", "research_events.material_id"],
            ondelete="RESTRICT", name="fk_rv2_claim_event_material",
        ),
        sa.UniqueConstraint("id", "event_id", name="uq_rv2_claim_event"),
        CheckConstraint(
            "(event_id IS NULL AND result_key IS NULL AND interpretation_revision IS NULL) OR "
            "(event_id IS NOT NULL AND result_key IS NOT NULL AND btrim(result_key)<>'' "
            "AND interpretation_revision IS NOT NULL AND interpretation_revision>=1)",
            name="ck_rv2_claim_binding",
        ),
        Index("uq_rv2_claim_result", "event_id", "result_key", unique=True,
              postgresql_where=sa.text("event_id IS NOT NULL")),
        Index("idx_material_claims_material_validity", "material_id", "validity_status"),
        Index("idx_material_claims_paper", "paper_id"),
        Index("idx_material_claims_work", "work_id"),
        Index("idx_material_claims_source_snapshot", "source_snapshot_id"),
        Index(
            "idx_material_claims_semantic_fingerprint",
            "semantic_fingerprint",
            postgresql_where=text("semantic_fingerprint IS NOT NULL"),
        ),
        Index(
            "idx_material_claims_duplicate_cluster",
            "duplicate_cluster_id",
            postgresql_where=text("duplicate_cluster_id IS NOT NULL"),
        ),
        Index("idx_material_claims_available_at", "available_at"),
    )


class ClaimQC(Base):
    """Current automated and human quality decision for one claim."""

    __tablename__ = "claim_qc"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
        default=uuid.uuid4,
    )
    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("material_claims.id", ondelete="CASCADE"),
        nullable=False,
    )
    automated_checks: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        server_default=sa.text("'{}'::jsonb"),
        default=dict,
        nullable=False,
    )
    quality_flags: Mapped[list[Any]] = mapped_column(
        JSONB,
        server_default=sa.text("'[]'::jsonb"),
        default=list,
        nullable=False,
    )
    review_status: Mapped[str] = mapped_column(
        String(20), server_default="pending", default="pending", nullable=False,
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(_TZDT)
    reviewer_notes: Mapped[str | None] = mapped_column(Text)
    is_gold: Mapped[bool] = mapped_column(
        Boolean, server_default="false", default=False, nullable=False,
    )
    qc_version: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        _TZDT, server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        _TZDT, server_default=func.now(), onupdate=func.now(), nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "review_status IN ('pending', 'needs_review', 'approved', 'rejected')",
            name="ck_claim_qc_review_status",
        ),
        CheckConstraint(
            "NOT is_gold OR "
            "(review_status = 'approved' AND reviewed_at IS NOT NULL)",
            name="ck_claim_qc_gold_reviewed",
        ),
        CheckConstraint(
            "jsonb_typeof(automated_checks) = 'object' "
            "AND jsonb_typeof(quality_flags) = 'array'",
            name="ck_claim_qc_json_shapes",
        ),
        sa.UniqueConstraint("claim_id", name="uq_claim_qc_claim_id"),
        Index("idx_claim_qc_review_status", "review_status"),
        Index(
            "idx_claim_qc_gold",
            "is_gold",
            postgresql_where=text("is_gold IS TRUE"),
        ),
    )


class MlDatasetSnapshot(Base):
    """Versioned, reproducible manifest for one ML-ready data product."""

    __tablename__ = "ml_dataset_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
        default=uuid.uuid4,
    )
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), server_default="building", default="building", nullable=False,
    )
    label_policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    feature_schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    split_ruleset_version: Mapped[str] = mapped_column(String(40), nullable=False)
    manifest_sha256: Mapped[str | None] = mapped_column(String(64))
    row_count: Mapped[int] = mapped_column(
        sa.BigInteger, server_default="0", default=0, nullable=False,
    )
    filters: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        server_default=sa.text("'{}'::jsonb"),
        default=dict,
        nullable=False,
    )
    data_card_uri: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        _TZDT, server_default=func.now(), nullable=False,
    )
    frozen_at: Mapped[datetime | None] = mapped_column(_TZDT)

    __table_args__ = (
        CheckConstraint(
            "status IN ('building', 'validated', 'frozen', 'failed')",
            name="ck_ml_dataset_snapshots_status",
        ),
        CheckConstraint(
            "row_count >= 0",
            name="ck_ml_dataset_snapshots_row_count",
        ),
        CheckConstraint(
            "manifest_sha256 IS NULL OR length(manifest_sha256) = 64",
            name="ck_ml_dataset_snapshots_manifest_hash",
        ),
        CheckConstraint(
            "status <> 'frozen' OR (manifest_sha256 IS NOT NULL AND frozen_at IS NOT NULL)",
            name="ck_ml_dataset_snapshots_frozen_manifest",
        ),
        CheckConstraint(
            "jsonb_typeof(filters) = 'object'",
            name="ck_ml_dataset_snapshots_filters_object",
        ),
        sa.UniqueConstraint("name", "version", name="uq_ml_dataset_snapshots_name_version"),
        sa.UniqueConstraint("manifest_sha256", name="uq_ml_dataset_snapshots_manifest"),
        Index("idx_ml_dataset_snapshots_source", "source_snapshot_id"),
        Index("idx_ml_dataset_snapshots_status_created", "status", "created_at"),
    )


class MlExample(Base):
    """Frozen example assignment with all keys required for leakage audits."""

    __tablename__ = "ml_examples"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
        default=uuid.uuid4,
    )
    dataset_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ml_dataset_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    example_key: Mapped[str] = mapped_column(String(100), nullable=False)
    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("material_claims.id", ondelete="RESTRICT"),
        nullable=False,
    )
    material_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("materials.id", ondelete="RESTRICT"),
        nullable=False,
    )
    work_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("works.id", ondelete="SET NULL"),
    )
    split: Mapped[str] = mapped_column(String(20), nullable=False)
    task_type: Mapped[str] = mapped_column(String(40), nullable=False)
    label_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        server_default=sa.text("'{}'::jsonb"),
        default=dict,
        nullable=False,
    )
    work_group: Mapped[str] = mapped_column(String(100), nullable=False)
    material_group: Mapped[str] = mapped_column(String(100), nullable=False)
    parent_series_group: Mapped[str | None] = mapped_column(String(100))
    chemical_system_group: Mapped[str | None] = mapped_column(String(200))
    duplicate_group: Mapped[str] = mapped_column(String(100), nullable=False)
    available_at: Mapped[date | None] = mapped_column(Date)
    assignment_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        _TZDT, server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "split IN ('train', 'validation', 'test')",
            name="ck_ml_examples_split",
        ),
        CheckConstraint(
            "task_type IN ('tc_regression', 'superconductivity_classification')",
            name="ck_ml_examples_task_type",
        ),
        CheckConstraint(
            "length(assignment_hash) = 64",
            name="ck_ml_examples_assignment_hash",
        ),
        CheckConstraint(
            "jsonb_typeof(label_data) = 'object'",
            name="ck_ml_examples_label_data_object",
        ),
        sa.UniqueConstraint(
            "dataset_snapshot_id", "example_key",
            name="uq_ml_examples_dataset_example",
        ),
        sa.UniqueConstraint(
            "dataset_snapshot_id", "claim_id", "task_type",
            name="uq_ml_examples_dataset_claim_task",
        ),
        Index("idx_ml_examples_dataset_split", "dataset_snapshot_id", "split"),
        Index("idx_ml_examples_dataset_work_group", "dataset_snapshot_id", "work_group"),
        Index(
            "idx_ml_examples_dataset_material_group",
            "dataset_snapshot_id",
            "material_group",
        ),
        Index(
            "idx_ml_examples_dataset_parent_group",
            "dataset_snapshot_id",
            "parent_series_group",
        ),
        Index(
            "idx_ml_examples_dataset_duplicate_group",
            "dataset_snapshot_id",
            "duplicate_group",
        ),
    )


class StatsCache(Base):
    __tablename__ = "stats_cache"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        _TZDT, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TdmAuditLog(Base):
    """APS TDM compliance / deletion audit trail (alembic 0039).

    One row per APS paper processed. The APS agreement requires a
    processing log recording the DOI, timestamps, and confirmation that
    the raw Licensed Materials (BagIt ZIP, full-text XML, PDF, OCR) were
    deleted after extraction. This table is that record — and the ONLY
    permanent trace APS full-text processing leaves. The licensed content
    is never persisted (no GCS upload, never written to ``chunks.text``);
    only authorized metadata/abstract + extracted structured data are
    kept, plus this proof the raw content was purged.

    ``deletion_confirmed`` is set True only after the pipeline re-checks
    the temp path is gone. ``status`` lifecycle: 'pending' -> 'processed'
    -> 'deleted' (or 'error').
    """

    __tablename__ = "tdm_audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
        default=uuid.uuid4,
    )
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="aps"
    )
    doi: Mapped[str] = mapped_column(String(200), nullable=False)
    # Nullable + SET NULL: the audit row must outlive the paper row.
    paper_id: Mapped[str | None] = mapped_column(
        String(100), ForeignKey("papers.id", ondelete="SET NULL"), nullable=True
    )
    harvested_at: Mapped[datetime | None] = mapped_column(_TZDT)
    processed_at: Mapped[datetime | None] = mapped_column(_TZDT)
    bagit_bytes: Mapped[int | None] = mapped_column(sa.BigInteger)
    # Licensed files that passed through the temp dir (names/sizes only,
    # never content): [{"name": "...", "bytes": N, "kind": "xml|pdf|ocr"}].
    files_processed: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=sa.text("'[]'::jsonb"), default=list, nullable=False
    )
    ner_record_count: Mapped[int] = mapped_column(
        Integer, server_default=sa.text("0"), default=0, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(_TZDT)
    deletion_confirmed: Mapped[bool] = mapped_column(
        Boolean, server_default="false", default=False, nullable=False
    )
    temp_path: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(20), server_default="pending", default="pending", nullable=False
    )
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        _TZDT, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_tdm_audit_doi", "doi"),
        Index("idx_tdm_audit_status", "status"),
        Index("idx_tdm_audit_created", "created_at"),
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


class ScientificCorrectionProposal(Base):
    """Source-backed, append-only proposed revisions; never auto-applied.

    Opaque actor/source identifiers retain provenance without copying account
    names, emails or licensed source text. This is not a scientific acceptance
    table. Controlled retention/deletion needs an explicit migration plan.
    """

    __tablename__ = "scientific_correction_proposals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    material_id: Mapped[str] = mapped_column(String(100), ForeignKey("materials.id", ondelete="RESTRICT"), nullable=False)
    source_result_id: Mapped[str] = mapped_column(String(100), nullable=False)
    field: Mapped[str] = mapped_column(String(50), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("scientific_correction_proposals.id", ondelete="RESTRICT"))
    source_quantity: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    proposed_quantity: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evidence_paper_id: Mapped[str] = mapped_column(String(100), nullable=False)
    evidence_locator: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    reviewer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    disposition: Mapped[str] = mapped_column(String(30), server_default="proposed", nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TZDT, server_default=func.now(), nullable=False)

    __table_args__ = (
        sa.UniqueConstraint("material_id", "source_result_id", "field", "revision", name="uq_correction_revision"),
        CheckConstraint("revision > 0", name="ck_correction_positive_revision"),
        CheckConstraint("disposition = 'proposed'", name="ck_correction_proposed_only"),
        CheckConstraint("jsonb_typeof(source_quantity) = 'object' AND jsonb_typeof(proposed_quantity) = 'object'", name="ck_correction_quantity_objects"),
        CheckConstraint("jsonb_typeof(evidence_locator) = 'object' AND evidence_locator <> '{}'::jsonb", name="ck_correction_locator"),
    )


from models.correction_ledger import CREATE_GUARD, CREATE_TRIGGER  # noqa: E402

sa.event.listen(ScientificCorrectionProposal.__table__, "after_create", sa.DDL(CREATE_GUARD).execute_if(dialect="postgresql"))
sa.event.listen(ScientificCorrectionProposal.__table__, "after_create", sa.DDL(CREATE_TRIGGER).execute_if(dialect="postgresql"))


class ManualOverride(Base):
    """Legacy requests, retained for traceability rather than scientific approval.

    SC03 numeric entries become versioned review context: is_cap=True is an
    upper review reference, False is an unapplied proposed replacement requiring
    source-linked revision. Neither mode may clip or overwrite a measurement.
    Separate legacy categorical overrides remain scoped to their prior behavior.
    Aggregation does not overwrite these input rows or trust free-text citations
    as proof that a correction was reviewed.
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
        comment="Legacy numeric request: True = upper review reference; False = unapplied exact proposal (SC03)",
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

from models.research_schema_v2 import register as _register_research_v2  # noqa: E402

RESEARCH_V2_TABLES = _register_research_v2(Base.metadata)

# Forward-only current metadata additions; the 0045 registrar stays immutable.
from models.claim_integrity import register as _register_claim_integrity  # noqa: E402

_register_claim_integrity(Base.metadata)

from models.source_provenance_v1 import register as _register_source_provenance  # noqa: E402

SOURCE_PROVENANCE_TABLES = _register_source_provenance(Base.metadata)

from models.research_import_v1 import register as _register_research_import  # noqa: E402

RESEARCH_IMPORT_TABLES = _register_research_import(Base.metadata)

from models.research_release_v1 import register as _register_research_release  # noqa: E402

RESEARCH_RELEASE_TABLES = _register_research_release(Base.metadata)

from models.research_publication_v1 import register as _register_research_publication  # noqa: E402

RESEARCH_PUBLICATION_TABLES = _register_research_publication(Base.metadata)

from models.source_lifecycle_v1 import register as _register_source_lifecycle  # noqa: E402

SOURCE_LIFECYCLE_TABLES = _register_source_lifecycle(Base.metadata)

from models.source_impact_indexes_v1 import (
    register as _register_source_impact_indexes,  # noqa: E402
)

SOURCE_IMPACT_INDEXES = _register_source_impact_indexes(Base.metadata)

from models.source_tasks_v1 import register as _register_source_tasks  # noqa: E402

SOURCE_TASK_TABLES = _register_source_tasks(Base.metadata)

from models.background_jobs_v1 import register as _register_background_jobs  # noqa: E402

BACKGROUND_JOB_CYCLES = _register_background_jobs(Base.metadata)

from models.rag_evidence_v1 import register as _register_rag_evidence  # noqa: E402

RAG_EVIDENCE_TABLES = _register_rag_evidence(Base.metadata)

from models.embedding_receipts_v1 import register as _register_embedding_receipts  # noqa: E402

EMBEDDING_COMPLETION_RECEIPTS = _register_embedding_receipts(Base.metadata)

from models.index_generations_v1 import register as _register_index_generations  # noqa: E402

INDEX_GENERATIONS = _register_index_generations(Base.metadata)

from models.research_distribution_v1 import (
    register as _register_research_distribution,  # noqa: E402
)

RESEARCH_DISTRIBUTION_TABLES = _register_research_distribution(Base.metadata)

from models.ml_feature_companion_v1 import register as _register_ml_feature_companion  # noqa: E402

ML_FEATURE_SOURCE_BINDINGS = _register_ml_feature_companion(Base.metadata)

from models.scientific_import_v1 import register as _register_scientific_import  # noqa: E402

SCIENTIFIC_IMPORT_TABLES = _register_scientific_import(Base.metadata)

from models.scientific_result_impact_indexes_v1 import (
    register as _register_scientific_result_impact_indexes,  # noqa: E402
)

SCIENTIFIC_RESULT_IMPACT_INDEXES = _register_scientific_result_impact_indexes(Base.metadata)

from models.scientific_adjudication_v1 import (
    register as _register_scientific_adjudication,  # noqa: E402
)

SCIENTIFIC_ADJUDICATION_TABLES = _register_scientific_adjudication(Base.metadata)

from models.answer_evidence_v1 import register as _register_answer_evidence  # noqa: E402

ANSWER_EVIDENCE_TABLES = _register_answer_evidence(Base.metadata)

from models.discovery_projection_v1 import register as _register_discovery_projection  # noqa: E402

DISCOVERY_PROJECTION_TABLES = _register_discovery_projection(Base.metadata)

from models.discovery_projection_v2 import (  # noqa: E402
    register as _register_discovery_projection_v2,
)

_register_discovery_projection_v2(Base.metadata)

from models.ml_use_roles_v1 import register as _register_ml_use_roles  # noqa: E402

ML_USE_ROLE_DECISIONS = _register_ml_use_roles(Base.metadata)

from models.ml_use_submissions_v1 import register as _register_ml_use_submissions  # noqa: E402

ML_USE_SUBMISSION_TABLES = _register_ml_use_submissions(Base.metadata)

from models.ml_use_rights_v1 import register as _register_ml_use_rights  # noqa: E402

ML_USE_RIGHTS_TABLE = _register_ml_use_rights(Base.metadata)

from models.ml_use_runs_v1 import register as _register_ml_use_runs  # noqa: E402

ML_USE_RUN_TABLES = _register_ml_use_runs(Base.metadata)

from models.ml_run_evidence_v1 import register as _register_ml_run_evidence  # noqa: E402

ML_RUN_EVIDENCE_TABLES = _register_ml_run_evidence(Base.metadata)

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
    engine = create_async_engine(
        _to_async_dsn(settings.database_url),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )
    from services.metrics import instrument_sqlalchemy

    instrument_sqlalchemy(engine)
    return engine


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
