"""Purpose-bound independent ML rights decisions; no training/run authority.

SQL verifies exact inventory membership and declared roles, not legal validity or
the identity of a SQL caller. Current source validity is a separate use-time gate.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

VERSION = "ml-use-rights/1.0.0"
INTENT_VERSION = "ml-use-rights-intent/1.0.0"
TABLE = "ml_use_rights_decisions"
PARENTS = ("users", "ml_use_submissions", "ml_use_private_inputs", "ml_use_role_decisions",
           "research_role_grants", "research_publication_actions")
FUNCTIONS = ("sclib_ml_rights_insert_v1",)
INTENT_FIELDS = ("submission_id", "submission_sha256", "inventory_sha256", "purpose", "resource_id",
                 "actor_user_id", "reviewer_grant_id", "curator_grant_id", "request_key", "decision",
                 "basis_code", "evidence_sha256", "expires_epoch", "supersedes_id", "supersedes_sha256")
UUID_FIELDS = {"id", "submission_id", "actor_user_id", "reviewer_grant_id", "curator_grant_id", "supersedes_id"}
BASES = ("documented_license", "documented_permission", "documented_institutional_policy", "rights_unresolved", "withdrawn")


def guards():
    canonical = "public.sclib_scientific_adjudication_canonical_v1"
    hashed = "public.sclib_scientific_adjudication_text_hash_v1"
    return [f"""
      CREATE OR REPLACE FUNCTION public.sclib_ml_rights_insert_v1() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
      DECLARE parent public.ml_use_submissions%ROWTYPE; previous public.{TABLE}%ROWTYPE;
        inventory jsonb; body jsonb; proposal jsonb;
      BEGIN
        SELECT * INTO STRICT parent FROM public.ml_use_submissions WHERE id=NEW.submission_id;
        body:=to_jsonb(NEW)-ARRAY['record_sha256','created_at'];
        proposal:=(body-ARRAY['id','version','intent_sha256'])||jsonb_build_object('version','{INTENT_VERSION}');
        IF NEW.record_sha256 IS DISTINCT FROM {hashed}({canonical}(body))
          OR NEW.intent_sha256 IS DISTINCT FROM {hashed}({canonical}(proposal))
          OR NEW.submission_sha256 IS DISTINCT FROM parent.record_sha256
          OR NEW.inventory_sha256 IS DISTINCT FROM parent.inventory_sha256
          OR NEW.purpose IS DISTINCT FROM parent.request_json::jsonb->>'purpose' THEN
          RAISE EXCEPTION 'ml_rights_exact_pins_required' USING ERRCODE='23514'; END IF;
        IF NEW.actor_user_id=parent.actor_user_id
          OR NOT public.sclib_research_publication_actor_v1(NEW.actor_user_id,true)
          OR NOT public.sclib_research_publication_role_v1(NEW.actor_user_id,NEW.curator_grant_id,'curator')
          OR NOT EXISTS(SELECT 1 FROM public.ml_use_role_decisions g WHERE g.id=NEW.reviewer_grant_id
            AND g.user_id=NEW.actor_user_id AND g.role='rights_reviewer' AND g.action='grant'
            AND g.record_sha256=public.sclib_ml_use_role_hash_v1(to_jsonb(g))
            AND NOT EXISTS(SELECT 1 FROM public.ml_use_role_decisions r WHERE r.supersedes_id=g.id)) THEN
          RAISE EXCEPTION 'ml_rights_independent_reviewer_required' USING ERRCODE='42501'; END IF;
        inventory:=parent.observation_json::jsonb->'dependency_inventory';
        IF {hashed}({canonical}(inventory)) IS DISTINCT FROM NEW.inventory_sha256
          OR NOT EXISTS(SELECT 1 FROM (
            SELECT jsonb_build_object('kind','row','entry',value) AS resource
              FROM jsonb_array_elements(inventory->'rows')
            UNION ALL SELECT jsonb_build_object('kind','artifact','entry',value)
              FROM jsonb_array_elements(inventory->'artifact_digests')
          ) resources WHERE {hashed}({canonical}(resource))=NEW.resource_id) THEN
          RAISE EXCEPTION 'ml_rights_inventory_member_required' USING ERRCODE='23514'; END IF;
        IF NEW.supersedes_id IS NULL THEN
          IF NEW.decision='revoke' OR NEW.supersedes_sha256 IS NOT NULL OR EXISTS(
            SELECT 1 FROM public.{TABLE} WHERE submission_id=NEW.submission_id AND resource_id=NEW.resource_id) THEN
            RAISE EXCEPTION 'ml_rights_exact_root_required' USING ERRCODE='23514'; END IF;
        ELSE
          SELECT * INTO previous FROM public.{TABLE} WHERE id=NEW.supersedes_id;
          IF previous.id IS NULL OR previous.submission_id<>NEW.submission_id OR previous.resource_id<>NEW.resource_id
            OR previous.record_sha256 IS DISTINCT FROM NEW.supersedes_sha256
            OR EXISTS(SELECT 1 FROM public.{TABLE} WHERE supersedes_id=previous.id)
            OR (NEW.decision='revoke' AND previous.decision<>'allow') THEN
            RAISE EXCEPTION 'ml_rights_exact_predecessor_required' USING ERRCODE='23514'; END IF;
        END IF;
        IF NEW.decision='allow' THEN
          IF NEW.expires_epoch<=extract(epoch FROM clock_timestamp())
            OR NEW.expires_epoch>extract(epoch FROM parent.expires_at)
            OR NOT EXISTS(SELECT 1 FROM public.ml_use_private_inputs WHERE submission_id=parent.id)
            OR NOT public.sclib_research_publication_actor_v1(parent.actor_user_id,true)
            OR NOT public.sclib_research_publication_role_v1(parent.actor_user_id,parent.curator_grant_id,'curator')
            OR NOT EXISTS(SELECT 1 FROM public.ml_use_role_decisions g WHERE g.id=parent.requester_grant_id
              AND g.user_id=parent.actor_user_id AND g.role='requester' AND g.action='grant'
              AND g.record_sha256=public.sclib_ml_use_role_hash_v1(to_jsonb(g))
              AND NOT EXISTS(SELECT 1 FROM public.ml_use_role_decisions r WHERE r.supersedes_id=g.id)) THEN
            RAISE EXCEPTION 'ml_rights_live_retained_request_required' USING ERRCODE='23514'; END IF;
        END IF;
        IF NEW.decision<>'revoke' AND ((SELECT count(*) FROM public.{TABLE} WHERE submission_id=NEW.submission_id)>=32000
          OR (SELECT count(*) FROM public.{TABLE})>=100000) THEN
          RAISE EXCEPTION 'ml_rights_history_limit' USING ERRCODE='54000'; END IF;
        NEW.created_at:=clock_timestamp(); RETURN NEW;
      END $$
    """,
        f"CREATE TRIGGER mu73_writer BEFORE INSERT ON public.{TABLE} FOR EACH STATEMENT "
        "EXECUTE FUNCTION public.sclib_research_publication_writer_v1()",
        f"CREATE TRIGGER mu73_insert BEFORE INSERT ON public.{TABLE} FOR EACH ROW "
        "EXECUTE FUNCTION public.sclib_ml_rights_insert_v1()",
        f"CREATE TRIGGER mu73_immutable BEFORE UPDATE OR DELETE ON public.{TABLE} FOR EACH ROW "
        "EXECUTE FUNCTION public.sclib_research_publication_immutable_v1()",
        f"CREATE TRIGGER mu73_no_truncate BEFORE TRUNCATE ON public.{TABLE} FOR EACH STATEMENT "
        "EXECUTE FUNCTION public.sclib_research_publication_immutable_v1()",
    ]


def register(metadata):
    def uid(name, parent=None, nullable=False):
        refs = [sa.ForeignKey(parent + ".id", ondelete="RESTRICT", onupdate="RESTRICT")] if parent else []
        return sa.Column(name, UUID(as_uuid=True), *refs, nullable=nullable)

    relation = sa.Table(TABLE, metadata, uid("id"), uid("submission_id", "ml_use_submissions"),
        uid("actor_user_id", "users"), uid("reviewer_grant_id", "ml_use_role_decisions"),
        uid("curator_grant_id", "research_role_grants"), uid("supersedes_id", TABLE, nullable=True),
        *(sa.Column(name, sa.Text, nullable=name in {"evidence_sha256", "supersedes_sha256"})
          for name in (*INTENT_FIELDS, "version", "intent_sha256", "record_sha256")
          if name not in UUID_FIELDS | {"expires_epoch"}),
        sa.Column("expires_epoch", sa.BigInteger, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("actor_user_id", "request_key", name="uq_mu73_request"),
        sa.UniqueConstraint("supersedes_id", name="uq_mu73_successor"),
        sa.Index("uq_mu73_root", "submission_id", "resource_id", unique=True,
                 postgresql_where=sa.text("supersedes_id IS NULL")),
        sa.Index("idx_mu73_inventory", "submission_id", "resource_id"),
        sa.CheckConstraint(f"version='{VERSION}' AND purpose='private_baseline_evaluation'", name="ck_mu73_scope"),
        sa.CheckConstraint("decision IN ('allow','deny','revoke')", name="ck_mu73_decision"),
        sa.CheckConstraint("basis_code IN (" + ",".join("'" + b + "'" for b in BASES) + ")", name="ck_mu73_basis"),
        sa.CheckConstraint("(decision='allow' AND evidence_sha256 IS NOT NULL AND expires_epoch IS NOT NULL "
                           "AND expires_epoch>0 AND basis_code IN ('documented_license','documented_permission',"
                           "'documented_institutional_policy')) OR (decision IN ('deny','revoke') "
                           "AND expires_epoch IS NULL AND basis_code IN ('rights_unresolved','withdrawn'))", name="ck_mu73_terms"),
        sa.CheckConstraint("(supersedes_id IS NULL)=(supersedes_sha256 IS NULL) AND "
                           "(supersedes_id IS NULL OR supersedes_id<>id)", name="ck_mu73_predecessor"),
        sa.CheckConstraint("request_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$'", name="ck_mu73_key"),
        sa.CheckConstraint("isfinite(created_at)", name="ck_mu73_date"),
        *(sa.CheckConstraint(f"{name} IS NULL OR {name} ~ '^[a-f0-9]{{64}}$'", name="ck_mu73_" + name)
          for name in (*[f for f in INTENT_FIELDS if f.endswith("sha256")], "resource_id", "intent_sha256", "record_sha256")),
    )
    for parent in PARENTS:
        relation.add_is_dependent_on(metadata.tables[parent])
    for statement in guards():
        sa.event.listen(relation, "after_create", sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"))
    return relation
