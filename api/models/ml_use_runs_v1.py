"""Immutable requested run contracts and independent conditional approval.

No insert executes a model, reserves resources or authenticates a SQL caller.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

VERSION = "ml-use-run-governance/1.0.0"
PLAN_INTENT = "ml-use-run-plan-intent/1.0.0"
DECISION_INTENT = "ml-use-run-decision-intent/1.0.0"
TABLES = ("ml_use_run_plans", "ml_use_run_decisions")
PARENTS = ("users", "ml_use_submissions", "ml_use_private_inputs", "ml_use_role_decisions",
           "research_role_grants", "research_publication_actions")
FUNCTIONS = ("sclib_ml_run_insert_v1",)
PLAN_FIELDS = ("actor_user_id", "requester_grant_id", "curator_grant_id", "submission_id", "submission_sha256",
               "inventory_sha256", "prepared_sha256", "task_sha256", "config_sha256", "package_sha256",
               "implementation_sha256", "runtime_sha256", "cpu_seconds", "wall_seconds", "memory_mib", "request_key")
DECISION_FIELDS = ("actor_user_id", "approver_grant_id", "curator_grant_id", "plan_id", "plan_sha256", "request_key",
                   "decision", "reason_code", "evidence_sha256", "expires_epoch", "supersedes_id", "supersedes_sha256")
PROFILE = "private-cpu-baseline/1.0.0"


def guards():
    canonical = "public.sclib_scientific_adjudication_canonical_v1"
    hashed = "public.sclib_scientific_adjudication_text_hash_v1"
    statements = [f"""
      CREATE OR REPLACE FUNCTION public.sclib_ml_run_insert_v1() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
      DECLARE submission public.ml_use_submissions%ROWTYPE; plan public.{TABLES[0]}%ROWTYPE;
        prior public.{TABLES[1]}%ROWTYPE; body jsonb; intent jsonb; ml_role text; grant_id uuid;
      BEGIN
        body:=to_jsonb(NEW)-ARRAY['record_sha256','created_at'];
        IF NEW.record_sha256 IS DISTINCT FROM {hashed}({canonical}(body)) THEN
          RAISE EXCEPTION 'ml_run_record_hash' USING ERRCODE='23514'; END IF;
        intent:=(body-ARRAY['id','version','intent_sha256','implementation_json','runtime_json','runner_profile','purpose']);
        IF TG_TABLE_NAME='{TABLES[0]}' THEN
          intent:=intent||jsonb_build_object('version','{PLAN_INTENT}');
          ml_role:='requester'; grant_id:=NEW.requester_grant_id;
        ELSE
          intent:=intent||jsonb_build_object('version','{DECISION_INTENT}');
          ml_role:='run_approver'; grant_id:=NEW.approver_grant_id;
        END IF;
        IF NEW.intent_sha256 IS DISTINCT FROM {hashed}({canonical}(intent)) THEN
          RAISE EXCEPTION 'ml_run_intent_hash' USING ERRCODE='23514'; END IF;
        IF NOT public.sclib_research_publication_actor_v1(NEW.actor_user_id,true)
          OR NOT public.sclib_research_publication_role_v1(NEW.actor_user_id,NEW.curator_grant_id,'curator')
          OR NOT EXISTS(SELECT 1 FROM public.ml_use_role_decisions g WHERE g.id=grant_id
            AND g.user_id=NEW.actor_user_id AND g.role=ml_role AND g.action='grant'
            AND g.record_sha256=public.sclib_ml_use_role_hash_v1(to_jsonb(g))
            AND NOT EXISTS(SELECT 1 FROM public.ml_use_role_decisions r WHERE r.supersedes_id=g.id)) THEN
          RAISE EXCEPTION 'ml_run_explicit_membership_required' USING ERRCODE='42501'; END IF;
        IF TG_TABLE_NAME='{TABLES[0]}' THEN
          SELECT * INTO STRICT submission FROM public.ml_use_submissions WHERE id=NEW.submission_id;
          IF NEW.actor_user_id<>submission.actor_user_id OR NEW.requester_grant_id<>submission.requester_grant_id
            OR NEW.curator_grant_id<>submission.curator_grant_id
            OR NEW.submission_sha256<>submission.record_sha256 OR NEW.inventory_sha256<>submission.inventory_sha256
            OR NEW.prepared_sha256 IS DISTINCT FROM submission.observation_json::jsonb->'reconstruction'->>'prepared_sha256'
            OR NEW.task_sha256 IS DISTINCT FROM submission.request_json::jsonb->'input_pins'->>'task_sha256'
            OR NEW.config_sha256 IS DISTINCT FROM submission.request_json::jsonb->'input_pins'->>'config_sha256'
            OR NEW.package_sha256 IS DISTINCT FROM submission.request_json::jsonb->'input_pins'->>'package_sha256'
            OR NEW.implementation_sha256<>encode(public.digest(convert_to(NEW.implementation_json,'UTF8'),'sha256'),'hex')
            OR NEW.runtime_sha256<>encode(public.digest(convert_to(NEW.runtime_json,'UTF8'),'sha256'),'hex')
            OR NOT EXISTS(SELECT 1 FROM public.ml_use_private_inputs WHERE submission_id=submission.id)
            OR submission.expires_at<=clock_timestamp() THEN
            RAISE EXCEPTION 'ml_run_exact_retained_owner_plan' USING ERRCODE='23514'; END IF;
          IF (SELECT count(*) FROM public.{TABLES[0]})>=10000
            OR (SELECT count(*) FROM public.{TABLES[0]} WHERE submission_id=submission.id)>=20 THEN
            RAISE EXCEPTION 'ml_run_plan_capacity' USING ERRCODE='54000'; END IF;
        ELSE
          SELECT * INTO STRICT plan FROM public.{TABLES[0]} WHERE id=NEW.plan_id;
          SELECT * INTO STRICT submission FROM public.ml_use_submissions WHERE id=plan.submission_id;
          IF NEW.actor_user_id=plan.actor_user_id OR NEW.plan_sha256<>plan.record_sha256 THEN
            RAISE EXCEPTION 'ml_run_independent_exact_plan' USING ERRCODE='23514'; END IF;
          IF NEW.supersedes_id IS NULL THEN
            IF NEW.decision='revoke' OR NEW.supersedes_sha256 IS NOT NULL
              OR EXISTS(SELECT 1 FROM public.{TABLES[1]} WHERE plan_id=NEW.plan_id) THEN
              RAISE EXCEPTION 'ml_run_exact_root' USING ERRCODE='23514'; END IF;
          ELSE
            SELECT * INTO prior FROM public.{TABLES[1]} WHERE id=NEW.supersedes_id;
            IF prior.id IS NULL OR prior.plan_id<>NEW.plan_id OR prior.record_sha256<>NEW.supersedes_sha256
              OR EXISTS(SELECT 1 FROM public.{TABLES[1]} WHERE supersedes_id=prior.id)
              OR (NEW.decision='revoke' AND prior.decision<>'approve') THEN
              RAISE EXCEPTION 'ml_run_exact_predecessor' USING ERRCODE='23514'; END IF;
          END IF;
          IF NEW.decision='approve' AND (NEW.expires_epoch<=extract(epoch FROM clock_timestamp())
            OR NEW.expires_epoch>extract(epoch FROM submission.expires_at)
            OR NOT EXISTS(SELECT 1 FROM public.ml_use_private_inputs WHERE submission_id=submission.id)
            OR NOT public.sclib_research_publication_actor_v1(plan.actor_user_id,true)
            OR NOT public.sclib_research_publication_role_v1(plan.actor_user_id,plan.curator_grant_id,'curator')
            OR NOT EXISTS(SELECT 1 FROM public.ml_use_role_decisions g WHERE g.id=plan.requester_grant_id
              AND g.user_id=plan.actor_user_id AND g.role='requester' AND g.action='grant'
              AND g.record_sha256=public.sclib_ml_use_role_hash_v1(to_jsonb(g))
              AND NOT EXISTS(SELECT 1 FROM public.ml_use_role_decisions r WHERE r.supersedes_id=g.id))) THEN
            RAISE EXCEPTION 'ml_run_live_owner_retention' USING ERRCODE='23514'; END IF;
          IF NEW.decision<>'revoke' AND ((SELECT count(*) FROM public.{TABLES[1]})>=100000
            OR (SELECT count(*) FROM public.{TABLES[1]} WHERE plan_id=NEW.plan_id)>=100) THEN
            RAISE EXCEPTION 'ml_run_review_capacity' USING ERRCODE='54000'; END IF;
        END IF;
        NEW.created_at:=clock_timestamp(); RETURN NEW;
      END $$
    """]
    for name in TABLES:
        statements += [f"CREATE TRIGGER mu74_writer BEFORE INSERT ON public.{name} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_research_publication_writer_v1()",
            f"CREATE TRIGGER mu74_insert BEFORE INSERT ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_ml_run_insert_v1()",
            f"CREATE TRIGGER mu74_immutable BEFORE UPDATE OR DELETE ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_research_publication_immutable_v1()",
            f"CREATE TRIGGER mu74_no_truncate BEFORE TRUNCATE ON public.{name} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_research_publication_immutable_v1()"]
    return statements


def register(metadata):
    def uid(name, target=None, nullable=False):
        args = [sa.ForeignKey(target + ".id", ondelete="RESTRICT", onupdate="RESTRICT")] if target else []
        return sa.Column(name, UUID(as_uuid=True), *args, nullable=nullable)
    def common(fields, prefix):
        return [sa.Column("version", sa.Text, nullable=False), sa.Column("intent_sha256", sa.Text, nullable=False),
            sa.Column("record_sha256", sa.Text, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("actor_user_id", "request_key", name="uq_" + prefix + "_request"),
            sa.CheckConstraint(f"version='{VERSION}'", name="ck_" + prefix + "_version"),
            sa.CheckConstraint("request_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$'", name="ck_" + prefix + "_key"),
            sa.CheckConstraint("isfinite(created_at)", name="ck_" + prefix + "_date"),
            *(sa.CheckConstraint(f"{f} IS NULL OR {f} ~ '^[a-f0-9]{{64}}$'", name="ck_" + prefix + "_" + f)
              for f in (*[k for k in fields if k.endswith("sha256")], "intent_sha256", "record_sha256"))]
    plan_uuids = {"actor_user_id", "requester_grant_id", "curator_grant_id", "submission_id"}
    numeric = {"cpu_seconds", "wall_seconds", "memory_mib"}
    plans = sa.Table(TABLES[0], metadata, uid("id"), uid("actor_user_id", "users"), uid("requester_grant_id", "ml_use_role_decisions"),
        uid("curator_grant_id", "research_role_grants"), uid("submission_id", "ml_use_submissions"),
        *(sa.Column(f, sa.Integer if f in numeric else sa.Text, nullable=False) for f in PLAN_FIELDS if f not in plan_uuids),
        *(sa.Column(f, sa.Text, nullable=False) for f in ("implementation_json", "runtime_json", "runner_profile", "purpose")),
        *common(PLAN_FIELDS, "mu74_plan"), sa.Index("idx_mu74_submission", "submission_id"),
        sa.CheckConstraint(f"runner_profile='{PROFILE}' AND purpose='private_baseline_evaluation'", name="ck_mu74_profile"),
        sa.CheckConstraint("cpu_seconds BETWEEN 1 AND 1800 AND wall_seconds BETWEEN 1 AND 1800 AND cpu_seconds<=wall_seconds "
                           "AND memory_mib BETWEEN 128 AND 4096", name="ck_mu74_budget"),
        sa.CheckConstraint("octet_length(implementation_json)<=16384 AND octet_length(runtime_json)<=16384 "
                           "AND jsonb_typeof(implementation_json::jsonb)='object' AND jsonb_typeof(runtime_json::jsonb)='object'", name="ck_mu74_host_sizes"))
    decision_uuids = {"actor_user_id", "approver_grant_id", "curator_grant_id", "plan_id", "supersedes_id"}
    decisions = sa.Table(TABLES[1], metadata, uid("id"), uid("actor_user_id", "users"), uid("approver_grant_id", "ml_use_role_decisions"),
        uid("curator_grant_id", "research_role_grants"), uid("plan_id", TABLES[0]), uid("supersedes_id", TABLES[1], nullable=True),
        *(sa.Column(f, sa.BigInteger if f == "expires_epoch" else sa.Text, nullable=f in {"expires_epoch", "evidence_sha256", "supersedes_sha256"})
          for f in DECISION_FIELDS if f not in decision_uuids), *common(DECISION_FIELDS, "mu74_review"),
        sa.UniqueConstraint("supersedes_id", name="uq_mu74_successor"),
        sa.Index("uq_mu74_root", "plan_id", unique=True, postgresql_where=sa.text("supersedes_id IS NULL")),
        sa.Index("idx_mu74_plan_review", "plan_id"),
        sa.CheckConstraint("decision IN ('approve','deny','revoke')", name="ck_mu74_decision"),
        sa.CheckConstraint("reason_code ~ '^[a-z][a-z0-9_]{0,159}$'", name="ck_mu74_reason"),
        sa.CheckConstraint("(decision='approve' AND evidence_sha256 IS NOT NULL AND expires_epoch>0) OR "
                           "(decision IN ('deny','revoke') AND expires_epoch IS NULL)", name="ck_mu74_review_terms"),
        sa.CheckConstraint("(supersedes_id IS NULL)=(supersedes_sha256 IS NULL) AND (supersedes_id IS NULL OR supersedes_id<>id)", name="ck_mu74_predecessor"))
    for parent in PARENTS:
        plans.add_is_dependent_on(metadata.tables[parent])
    for statement in guards():
        sa.event.listen(decisions, "after_create", sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"))
    return plans, decisions
