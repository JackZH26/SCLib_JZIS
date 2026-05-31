"""APS source identity: normalized identifiers + journal + cross-source link

Revision ID: 0038_aps_source_identity
Revises: 0037_paper_geo
Create date: 2026-05-31

Phase 1 of the APS ingestion build (see docs/APS_INGESTION_PLAN.md).
APS is a NEW ingestion source alongside arXiv — additive, never a
replacement. This migration generalises the ``papers`` identity model
so a third source (and beyond) can coexist with arXiv/NIMS, and adds
the journal + cross-source-link columns APS needs.

New ``papers`` columns:

* ``external_id``     — the source-native id (arXiv: arxiv_id; APS: DOI).
* ``id_scheme``       — which namespace ``external_id`` lives in
                        ('arxiv' | 'nims' | 'doi').
* ``journal_abbrev``  — short journal handle for APS rows ('PRB','PRL',
                        'PRX', 'RMP', ...). Indexed for filtering.
* ``publication_ref`` — JSONB {volume, issue, article_id, page,
                        published_date} from APS Harvest metadata.
* ``related_paper_id``— self-FK linking an arXiv preprint row and its
                        APS published-version row as the "same work"
                        (used by the aggregator to avoid double-counting
                        a paper while still treating a differing Tc as a
                        new value).

Constraints:

* partial UNIQUE(source, external_id) WHERE external_id IS NOT NULL —
  the cross-source dedup anchor. Partial so legacy rows with a NULL
  external_id never collide.
* partial UNIQUE(doi) WHERE source = 'aps' — APS rows are unique by DOI.
  Scoped to APS so an arXiv preprint and its APS version may share a DOI
  across sources without conflict.

Backfill: existing arXiv/NIMS rows get external_id + id_scheme so the
new UNIQUE anchor is populated. The arXiv ingest path keeps working
unchanged (indexer.upsert_paper_with_chunks also starts writing these
two columns — see that file).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0038_aps_source_identity"
down_revision = "0037_paper_geo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- new columns -------------------------------------------------------
    op.add_column("papers", sa.Column("external_id", sa.String(200), nullable=True))
    op.add_column("papers", sa.Column("id_scheme", sa.String(20), nullable=True))
    op.add_column("papers", sa.Column("journal_abbrev", sa.String(30), nullable=True))
    op.add_column("papers", sa.Column("publication_ref", JSONB(), nullable=True))
    op.add_column(
        "papers", sa.Column("related_paper_id", sa.String(100), nullable=True)
    )

    # --- backfill existing rows -------------------------------------------
    # arXiv rows: external_id = arxiv_id, scheme = 'arxiv'.
    op.execute(
        "UPDATE papers SET external_id = arxiv_id, id_scheme = 'arxiv' "
        "WHERE source = 'arxiv' AND arxiv_id IS NOT NULL AND external_id IS NULL"
    )
    # Catch-all for any other source (e.g. nims) or arXiv rows without an
    # arxiv_id: fall back to the primary key + the row's own source label.
    op.execute(
        "UPDATE papers SET external_id = id, id_scheme = source "
        "WHERE external_id IS NULL"
    )

    # --- constraints / indexes --------------------------------------------
    # Cross-source dedup anchor. Partial → multiple NULL external_ids never
    # collide (Postgres treats NULLs as distinct anyway, but being explicit
    # also keeps the index smaller and the intent clear).
    op.create_index(
        "uq_papers_source_external",
        "papers",
        ["source", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )
    # APS rows are unique by DOI (scoped to source='aps').
    op.create_index(
        "uq_papers_aps_doi",
        "papers",
        ["doi"],
        unique=True,
        postgresql_where=sa.text("source = 'aps' AND doi IS NOT NULL"),
    )
    op.create_index("idx_papers_journal_abbrev", "papers", ["journal_abbrev"])
    op.create_index(
        "idx_papers_related",
        "papers",
        ["related_paper_id"],
        postgresql_where=sa.text("related_paper_id IS NOT NULL"),
    )

    # Self-referential link (arXiv preprint <-> APS published version).
    op.create_foreign_key(
        "fk_papers_related_paper",
        "papers",
        "papers",
        ["related_paper_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_papers_related_paper", "papers", type_="foreignkey")
    op.drop_index("idx_papers_related", table_name="papers")
    op.drop_index("idx_papers_journal_abbrev", table_name="papers")
    op.drop_index("uq_papers_aps_doi", table_name="papers")
    op.drop_index("uq_papers_source_external", table_name="papers")
    op.drop_column("papers", "related_paper_id")
    op.drop_column("papers", "publication_ref")
    op.drop_column("papers", "journal_abbrev")
    op.drop_column("papers", "id_scheme")
    op.drop_column("papers", "external_id")
