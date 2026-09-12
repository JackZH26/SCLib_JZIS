"""Independent ML workflow roles; membership is never data-use authorization.

0071 adds no memberships and changes no existing research-role vocabulary.
SQL guards check declared actors, not authentication of the SQL caller.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

VERSION = "ml-use-role-ledger/1.0.0"
TABLE = "ml_use_role_decisions"
ROLES = ("requester", "rights_reviewer", "run_approver")
PARENT_TABLES = ("users", "research_publication_epoch", "research_publication_actions")
FUNCTION_SIGNATURES = (
    ("sclib_ml_use_role_hash_v1", "jsonb"),
    ("sclib_ml_use_role_insert_v1", ""),
)


def guard_statements():
    return ["""
      CREATE OR REPLACE FUNCTION public.sclib_ml_use_role_hash_v1(body jsonb) RETURNS text
      LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
        SELECT encode(public.digest(convert_to(format(
          '{"action":%s,"actor_user_id":%s,"id":%s,"reason_code":%s,"request_key":%s,"role":%s,"supersedes_id":%s,"user_id":%s,"version":%s}',
          body->'action',body->'actor_user_id',body->'id',body->'reason_code',body->'request_key',
          body->'role',body->'supersedes_id',body->'user_id',body->'version'),'UTF8'),'sha256'),'hex')
      $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_ml_use_role_insert_v1() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
      DECLARE previous public.{TABLE}%ROWTYPE;
      BEGIN
        IF NEW.record_sha256 IS DISTINCT FROM public.sclib_ml_use_role_hash_v1(to_jsonb(NEW)) THEN
          RAISE EXCEPTION 'ml_use_role_record_hash_mismatch' USING ERRCODE='23514';
        END IF;
        IF NOT public.sclib_research_publication_actor_v1(NEW.actor_user_id,true) THEN
          RAISE EXCEPTION 'ml_use_role_admin_required' USING ERRCODE='42501';
        END IF;
        IF NEW.action='grant' AND NOT public.sclib_research_publication_actor_v1(NEW.user_id,false) THEN
          RAISE EXCEPTION 'ml_use_role_active_target_required' USING ERRCODE='42501';
        END IF;
        IF NEW.supersedes_id IS NULL THEN
          IF NEW.action<>'grant' OR EXISTS(SELECT 1 FROM public.{TABLE}
              WHERE user_id=NEW.user_id AND role=NEW.role) THEN
            RAISE EXCEPTION 'ml_use_role_exact_root_required' USING ERRCODE='23514';
          END IF;
        ELSE
          SELECT * INTO previous FROM public.{TABLE} WHERE id=NEW.supersedes_id;
          IF previous.id IS NULL OR previous.user_id<>NEW.user_id OR previous.role<>NEW.role
            OR previous.action=NEW.action
            OR previous.record_sha256 IS DISTINCT FROM public.sclib_ml_use_role_hash_v1(to_jsonb(previous))
            OR EXISTS(SELECT 1 FROM public.{TABLE} WHERE supersedes_id=previous.id) THEN
            RAISE EXCEPTION 'ml_use_role_exact_current_predecessor_required' USING ERRCODE='23514';
          END IF;
        END IF;
        RETURN NEW;
      END $$
    """,
        f"CREATE TRIGGER mu71_writer BEFORE INSERT ON public.{TABLE} FOR EACH STATEMENT "
        "EXECUTE FUNCTION public.sclib_research_publication_writer_v1()",
        f"CREATE TRIGGER mu71_insert BEFORE INSERT ON public.{TABLE} FOR EACH ROW "
        "EXECUTE FUNCTION public.sclib_ml_use_role_insert_v1()",
        f"CREATE TRIGGER mu71_immutable_row BEFORE UPDATE OR DELETE ON public.{TABLE} FOR EACH ROW "
        "EXECUTE FUNCTION public.sclib_research_publication_immutable_v1()",
        f"CREATE TRIGGER mu71_immutable_truncate BEFORE TRUNCATE ON public.{TABLE} FOR EACH STATEMENT "
        "EXECUTE FUNCTION public.sclib_research_publication_immutable_v1()",
    ]


def register(metadata):
    def uid(name, target=None, nullable=False):
        refs = [sa.ForeignKey(target + ".id", ondelete="RESTRICT", onupdate="RESTRICT")] if target else []
        return sa.Column(name, UUID(as_uuid=True), *refs, nullable=nullable)

    table = sa.Table(TABLE, metadata,
        uid("id"), uid("user_id", "users"), uid("actor_user_id", "users"),
        uid("supersedes_id", TABLE, nullable=True),
        sa.Column("version", sa.String(60), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("request_key", sa.String(120), nullable=False),
        sa.Column("reason_code", sa.String(160), nullable=False),
        sa.Column("record_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(f"version='{VERSION}'", name="ck_mu71_version"),
        sa.CheckConstraint("role IN ('requester','rights_reviewer','run_approver')", name="ck_mu71_role"),
        sa.CheckConstraint("action IN ('grant','revoke')", name="ck_mu71_action"),
        sa.CheckConstraint("request_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$'", name="ck_mu71_key"),
        sa.CheckConstraint("reason_code ~ '^[a-z][a-z0-9_]{0,159}$'", name="ck_mu71_reason"),
        sa.CheckConstraint("record_sha256 ~ '^[0-9a-f]{64}$'", name="ck_mu71_hash"),
        sa.CheckConstraint("isfinite(created_at)", name="ck_mu71_date"),
        sa.CheckConstraint("supersedes_id IS NULL OR supersedes_id<>id", name="ck_mu71_not_self"),
        sa.UniqueConstraint("actor_user_id", "request_key", name="uq_mu71_request"),
        sa.UniqueConstraint("supersedes_id", name="uq_mu71_successor"),
        sa.Index("uq_mu71_root", "user_id", "role", unique=True,
                 postgresql_where=sa.text("supersedes_id IS NULL")),
        sa.Index("idx_mu71_user_role", "user_id", "role"),
    )
    for parent in PARENT_TABLES:
        table.add_is_dependent_on(metadata.tables[parent])
    for statement in guard_statements():
        sa.event.listen(table, "after_create", sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"))
    return table
