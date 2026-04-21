"""Dashboard redesign — phase A backend foundations.

Revision ID: 0006_dashboard_phase_a
Down revision: 0005_needs_review

Adds the columns needed by the logged-in dashboard's Overview and
API Keys tabs:

* ``users.bio``        — long-form self-description, editable via PATCH /me
* ``users.orcid``      — optional ORCID identifier (format XXXX-XXXX-XXXX-XXXX)
* ``api_keys.total_requests`` — running counter of successful authenticated
  requests, bumped in ``deps.py`` on every X-API-Key hit. Enables the
  "Total requests" column on the dashboard's keys table.
* ``api_keys.revoked_at``     — timestamp paired with the existing boolean
  ``revoked`` flag so the dashboard can display "Revoked 3 days ago".

Phase B (ask_history, bookmarks) and Phase C (feedback log if we want
one) get their own migrations so rollback stays granular.
"""
from alembic import op
import sqlalchemy as sa


revision = "0006_dashboard_phase_a"
down_revision = "0005_needs_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("bio", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("orcid", sa.String(19), nullable=True))

    op.add_column(
        "api_keys",
        sa.Column(
            "total_requests",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "api_keys",
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # Backfill: any key already flagged revoked gets a best-effort
    # timestamp so the UI doesn't show a blank "revoked ? ago". We don't
    # know the real revocation time, so we fall back to created_at —
    # explicit and defensible ("sometime after creation").
    op.execute("""
        UPDATE api_keys
        SET revoked_at = created_at
        WHERE revoked = TRUE AND revoked_at IS NULL;
    """)


def downgrade() -> None:
    op.drop_column("api_keys", "revoked_at")
    op.drop_column("api_keys", "total_requests")
    op.drop_column("users", "orcid")
    op.drop_column("users", "bio")
