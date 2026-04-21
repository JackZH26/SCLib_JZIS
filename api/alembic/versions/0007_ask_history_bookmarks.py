"""Dashboard redesign — phase B: Ask history + Bookmarks.

Revision ID: 0007_ask_history_bookmarks
Down revision: 0006_dashboard_phase_a

Two new user-owned tables:

* ``ask_history`` — one row per authenticated /ask call. Keeps the
  question, the grounded markdown answer, the citation list (JSONB
  snapshot of AskSource[] at answer time, so the UI can re-render the
  entry without re-hitting the vector store), and timing. A periodic
  task in the API lifespan prunes rows older than 90 days (product
  decision — see project memory).

* ``bookmarks`` — user-private saves of papers and materials. Single
  table keyed by ``target_type`` + ``target_id`` with a CHECK
  constraint so a buggy client can't invent new target types.
  UNIQUE(user_id, target_type, target_id) so duplicate POSTs 409 at
  the DB level instead of racing.

Both tables cascade-delete with the owning user, matching how
api_keys / email_verifications behave.
"""
from alembic import op
import sqlalchemy as sa


revision = "0007_ask_history_bookmarks"
down_revision = "0006_dashboard_phase_a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- ask_history ------------------------------------------------------
    op.create_table(
        "ask_history",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("sources", sa.dialects.postgresql.JSONB(),
                  server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("tokens_used", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(10), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "idx_ask_history_user_created",
        "ask_history",
        ["user_id", sa.text("created_at DESC")],
    )
    # Index on created_at alone supports the 90-day prune job without
    # forcing it to walk the user-partitioned index.
    op.create_index("idx_ask_history_created", "ask_history", ["created_at"])

    # --- bookmarks --------------------------------------------------------
    op.create_table(
        "bookmarks",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("target_type", sa.String(20), nullable=False),
        sa.Column("target_id", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "target_type IN ('paper', 'material')",
            name="ck_bookmarks_target_type",
        ),
        sa.UniqueConstraint(
            "user_id", "target_type", "target_id",
            name="uq_bookmarks_user_target",
        ),
    )
    op.create_index(
        "idx_bookmarks_user_type_created",
        "bookmarks",
        ["user_id", "target_type", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_bookmarks_user_type_created", table_name="bookmarks")
    op.drop_table("bookmarks")
    op.drop_index("idx_ask_history_created", table_name="ask_history")
    op.drop_index("idx_ask_history_user_created", table_name="ask_history")
    op.drop_table("ask_history")
