"""Private plain-text run-review records bound to immutable approval hashes.

No source licence, independent scientific pilot or execution authority is created.
Only new approval rows require bytes; existing historical approvals are untouched.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

VERSION = "ml-run-review-evidence/1.0.0"
MAX_BYTES = 8192
MAX_STORAGE_BYTES = 32 * 1024 * 1024
TABLES = ("ml_run_review_evidence", "ml_run_review_evidence_purges")
PARENTS = ("users", "ml_use_run_decisions", "ml_use_run_plans", "ml_use_submissions",
           "ml_use_role_decisions", "research_role_grants", "research_publication_actions")
FUNCTIONS = ("sclib_ml_run_evidence_insert_v1", "sclib_ml_run_evidence_complete_v1", "sclib_ml_run_evidence_delete_v1")
# Explicit Python str.strip whitespace set; no dependence on the DB locale.
WHITESPACE_SQL = "||".join(f"chr({code})" for code in (
    9, 10, 11, 12, 13, 28, 29, 30, 31, 32, 133, 160, 5760, *range(8192, 8203), 8232, 8233, 8239, 8287, 12288))


def guards():
    statements = [f"""
      CREATE OR REPLACE FUNCTION public.sclib_ml_run_evidence_insert_v1() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
      DECLARE decision public.ml_use_run_decisions%ROWTYPE; expiry timestamptz;
      BEGIN
        SELECT * INTO STRICT decision FROM public.ml_use_run_decisions WHERE id=NEW.decision_id;
        SELECT s.expires_at INTO STRICT expiry FROM public.ml_use_run_plans p
          JOIN public.ml_use_submissions s ON s.id=p.submission_id WHERE p.id=decision.plan_id;
        IF decision.decision<>'approve' THEN
          RAISE EXCEPTION 'ml_run_evidence_approval_required' USING ERRCODE='23514'; END IF;
        IF TG_TABLE_NAME='{TABLES[0]}' THEN
          IF encode(public.digest(NEW.payload,'sha256'),'hex')<>decision.evidence_sha256
            OR expiry<=clock_timestamp() OR EXISTS(SELECT 1 FROM public.{TABLES[1]} WHERE decision_id=NEW.decision_id)
            OR NOT public.sclib_research_publication_actor_v1(decision.actor_user_id,true)
            OR NOT public.sclib_research_publication_role_v1(decision.actor_user_id,decision.curator_grant_id,'curator')
            OR NOT EXISTS(SELECT 1 FROM public.ml_use_role_decisions g WHERE g.id=decision.approver_grant_id
              AND g.user_id=decision.actor_user_id AND g.role='run_approver' AND g.action='grant'
              AND g.record_sha256=public.sclib_ml_use_role_hash_v1(to_jsonb(g))
              AND NOT EXISTS(SELECT 1 FROM public.ml_use_role_decisions r WHERE r.supersedes_id=g.id)) THEN
            RAISE EXCEPTION 'ml_run_evidence_exact_current_review_required' USING ERRCODE='23514'; END IF;
          IF btrim(convert_from(NEW.payload,'UTF8'),{WHITESPACE_SQL})='' THEN
            RAISE EXCEPTION 'ml_run_evidence_nonempty_text_required' USING ERRCODE='23514'; END IF;
          IF (SELECT COALESCE(sum(octet_length(payload)),0) FROM public.{TABLES[0]})+octet_length(NEW.payload)>{MAX_STORAGE_BYTES} THEN
            RAISE EXCEPTION 'ml_run_evidence_storage_limit' USING ERRCODE='54000'; END IF;
        ELSE
          IF NOT public.sclib_research_publication_actor_v1(NEW.actor_user_id,true)
            OR (NEW.reason='reviewer_request' AND NEW.actor_user_id<>decision.actor_user_id)
            OR (NEW.reason='retention_expired' AND expiry>clock_timestamp())
            OR NOT EXISTS(SELECT 1 FROM public.{TABLES[0]} WHERE decision_id=NEW.decision_id) THEN
            RAISE EXCEPTION 'ml_run_evidence_purge_admission' USING ERRCODE='42501'; END IF;
          NEW.created_at:=clock_timestamp();
        END IF;
        RETURN NEW;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_ml_run_evidence_complete_v1() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
        IF NEW.decision='approve' AND NOT EXISTS(SELECT 1 FROM public.{TABLES[0]} WHERE decision_id=NEW.id)
          AND NOT EXISTS(SELECT 1 FROM public.{TABLES[1]} WHERE decision_id=NEW.id) THEN
          RAISE EXCEPTION 'ml_run_approval_document_required' USING ERRCODE='23514'; END IF;
        RETURN NULL;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_ml_run_evidence_delete_v1() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
        IF TG_TABLE_NAME='{TABLES[1]}' THEN
          DELETE FROM public.{TABLES[0]} WHERE decision_id=NEW.decision_id;
          RETURN NULL;
        END IF;
        IF NOT EXISTS(SELECT 1 FROM public.{TABLES[1]} WHERE decision_id=OLD.decision_id) THEN
          RAISE EXCEPTION 'ml_run_evidence_purge_receipt_required' USING ERRCODE='23514'; END IF;
        RETURN OLD;
      END $$
    """]
    for name in TABLES:
        statements += [
            f"CREATE TRIGGER mu75_writer BEFORE INSERT ON public.{name} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_research_publication_writer_v1()",
            f"CREATE TRIGGER mu75_insert BEFORE INSERT ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_ml_run_evidence_insert_v1()",
            f"CREATE TRIGGER mu75_immutable BEFORE UPDATE{' OR DELETE' if name == TABLES[1] else ''} ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_research_publication_immutable_v1()",
            f"CREATE TRIGGER mu75_no_truncate BEFORE TRUNCATE ON public.{name} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_research_publication_immutable_v1()",
        ]
    return [*statements,
        "CREATE CONSTRAINT TRIGGER mu75_complete AFTER INSERT ON public.ml_use_run_decisions DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW EXECUTE FUNCTION public.sclib_ml_run_evidence_complete_v1()",
        f"CREATE TRIGGER mu75_delete BEFORE DELETE ON public.{TABLES[0]} FOR EACH ROW EXECUTE FUNCTION public.sclib_ml_run_evidence_delete_v1()",
        f"CREATE TRIGGER mu75_purge AFTER INSERT ON public.{TABLES[1]} FOR EACH ROW EXECUTE FUNCTION public.sclib_ml_run_evidence_delete_v1()"]


def register(metadata):
    def decision_id():
        return sa.Column("decision_id", UUID(as_uuid=True), sa.ForeignKey("ml_use_run_decisions.id", ondelete="RESTRICT"), primary_key=True)
    evidence = sa.Table(TABLES[0], metadata, decision_id(), sa.Column("payload", sa.LargeBinary, nullable=False),
        sa.CheckConstraint(f"octet_length(payload) BETWEEN 1 AND {MAX_BYTES}", name="ck_mu75_payload"))
    purges = sa.Table(TABLES[1], metadata, decision_id(),
        sa.Column("actor_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("reason IN ('reviewer_request','retention_expired')", name="ck_mu75_purge_reason"),
        sa.CheckConstraint("isfinite(created_at)", name="ck_mu75_purge_date"))
    for name in PARENTS:
        evidence.add_is_dependent_on(metadata.tables[name])
    purges.add_is_dependent_on(evidence)
    for statement in guards():
        sa.event.listen(purges, "after_create", sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"))
    return evidence, purges
