"""Retire derived local search indexes after moving readers back to Google."""
import re
from pathlib import Path

from alembic import op
from alembic.script import ScriptDirectory
import sqlalchemy as sa

from migration_history import (
    content_answer_storage_v2 as answers,
    retrieval_activation_v2 as activation,
    retrieval_backend_v2 as backend,
    retrieval_bounded_validation_v3 as validation,
    retrieval_content_v2 as content,
    retrieval_native_v2 as native,
    retrieval_navigation_v2 as navigation,
    retrieval_policy_v3 as policy3,
    retrieval_policy_v4 as policy4,
    retrieval_publication_queue_v2 as queue,
)

revision = "0118_google_search"
down_revision = "0117_retrieval_policy_v4"
branch_labels = None
depends_on = None


def upgrade():
    db = op.get_bind()
    tables = (*native.TABLE_ORDER, *content.TABLE_ORDER, *backend.TABLE_ORDER,
              *activation.TABLE_ORDER, navigation.TABLE, answers.TABLE, *queue.TABLE_ORDER)
    # Lock source writers and saved answers before deciding whether this database
    # contains unique data. A busy application can retry the whole transaction.
    db.execute(sa.text("SET LOCAL lock_timeout='4s'"))
    db.execute(sa.text("LOCK TABLE " + ", ".join("public." + t for t in tables) +
                       ", public.ask_history IN ACCESS EXCLUSIVE MODE"))
    for table in (*native.TABLE_ORDER, answers.TABLE, *queue.TABLE_ORDER[:1]):
        if db.scalar(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{table})")):
            raise RuntimeError(f"Export and reconcile retained records in {table} before retirement")
    if db.scalar(sa.text("SELECT EXISTS(SELECT 1 FROM public.ask_history "
                         "WHERE content_evidence_receipt_version IS NOT NULL)")):
        raise RuntimeError("Preserve saved content-bound answers before retirement")

    # Remove only projections identified by their original build UUID. RESTRICT
    # protects unrelated views, relations, user-defined vector columns and indexes.
    owned = {"b_" + build.hex for build in db.scalars(sa.text(
        "SELECT id FROM public.retrieval_backend_builds_v2"))}
    projections = db.scalars(sa.text(
        "SELECT relname FROM pg_class WHERE relnamespace='retrieval_projection'::regnamespace "
        "AND relkind IN ('r', 'p')")).all()
    for table in projections:
        if not re.fullmatch(r"b_[0-9a-f]{32}", table) or table not in owned:
            raise RuntimeError("Unknown relation in the retired projection schema")
        op.execute(f"DROP TABLE retrieval_projection.{table} RESTRICT")
    op.execute("DROP SCHEMA retrieval_projection RESTRICT")

    op.execute("DROP TRIGGER aa_retrieval_v2_blocks_v1 ON public.index_activation_events")
    for trigger in ("cae113_complete", "cae113_parent"):
        op.execute(f"DROP TRIGGER {trigger} ON public.ask_history")
    op.execute("DROP TABLE " + ", ".join("public." + t for t in tables) + " RESTRICT")
    op.drop_column("ask_history", "content_evidence_receipt_version", schema="public")
    # These three helper indexes were created on shared evidence/generation tables.
    for index in ("idx_retrieval_legacy_keyset_v2", "idx_index_member_evidence_nav_v2",
                  "idx_derived_evidence_nav_v2"):
        op.execute(f"DROP INDEX public.{index} RESTRICT")
    functions = [
        *native.FUNCTION_SIGNATURES, *content.FUNCTION_SIGNATURES, *backend.FUNCTION_SIGNATURES,
        *activation.FUNCTION_SIGNATURES, *navigation.FUNCTION_SIGNATURES, *answers.FUNCTIONS,
        (validation.FUNCTION, ""), (policy3.FUNCTION, ""), (policy4.FUNCTION, ""),
        *((function, "jsonb" if function.endswith("hash_v2") else "") for function in queue.FUNCTIONS),
    ]
    for name, signature in reversed(functions):
        op.execute(f"DROP FUNCTION public.{name}({signature}) RESTRICT")
    op.execute("DROP EXTENSION IF EXISTS vector RESTRICT")


def downgrade():
    # The old schema can be recreated for a historical software rollback. No
    # deleted ANN index, vector projection or search acceptance is synthesized.
    scripts = ScriptDirectory(str(Path(__file__).resolve().parents[1]))
    revisions = list(scripts.iterate_revisions(down_revision, "0106_materials_source_notation"))
    for old in reversed(revisions):
        old.module.upgrade()
