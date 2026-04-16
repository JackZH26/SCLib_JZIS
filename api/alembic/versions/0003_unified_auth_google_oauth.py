"""Add Google OAuth and unified auth fields to users

Revision ID: 0003_unified_auth
Down revision: 0002_materials_v2
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision = "0003_unified_auth"
down_revision = "0002_materials_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Google OAuth
    op.add_column("users", sa.Column("google_sub", sa.String(128), unique=True, nullable=True))
    op.add_column("users", sa.Column("auth_provider", sa.String(20), server_default="local", nullable=False))
    op.add_column("users", sa.Column("avatar_url", sa.String(500), nullable=True))

    # Unified auth scopes + extensible profile
    op.add_column("users", sa.Column("scopes", ARRAY(sa.Text()), server_default="{basic,sclib}", nullable=False))
    op.add_column("users", sa.Column("profile", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False))

    # Google users have no password — allow NULL
    op.alter_column("users", "password_hash", existing_type=sa.String(255), nullable=True)

    # Partial index for fast Google sub lookup
    op.create_index(
        "idx_users_google_sub", "users", ["google_sub"],
        unique=True,
        postgresql_where=sa.text("google_sub IS NOT NULL"),
    )

    # Backfill auth_provider for existing users
    op.execute("UPDATE users SET auth_provider = 'local' WHERE auth_provider IS NULL")
    # Backfill scopes for existing users
    op.execute("UPDATE users SET scopes = ARRAY['basic','sclib'] WHERE scopes IS NULL")


def downgrade() -> None:
    op.drop_index("idx_users_google_sub", table_name="users")
    op.alter_column("users", "password_hash", existing_type=sa.String(255), nullable=False)
    op.drop_column("users", "profile")
    op.drop_column("users", "scopes")
    op.drop_column("users", "avatar_url")
    op.drop_column("users", "auth_provider")
    op.drop_column("users", "google_sub")
