"""Private, immutable ML intake receipts with separately purgeable input bytes.

SQL guards verify declared actors/integrity, not authenticated caller identity,
scientific reconstruction, storage rights, or permission to fit a model.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

VERSION = "ml-use-submission/1.0.0"
RETENTION_POLICY = "private-ml-input-seven-days/1.0.0"
TABLES = ("ml_use_submissions", "ml_use_private_inputs", "ml_use_input_purges")
PARENTS = ("users", "ml_use_role_decisions", "research_role_grants", "research_publication_actions")
FUNCTIONS = ("sclib_ml_submission_insert_v1", "sclib_ml_submission_complete_v1", "sclib_ml_input_delete_v1")
RECORD_FIELDS = ("id", "version", "actor_user_id", "requester_grant_id", "curator_grant_id", "request_key",
                 "intent_sha256", "request_sha256", "envelope_sha256", "inventory_sha256",
                 "observation_sha256", "retention_policy")
MAX_REQUESTS = 1000
MAX_OWNER_REQUESTS = 100
MAX_STORAGE_BYTES = 256 * 1024 * 1024
MAX_OWNER_BYTES = 64 * 1024 * 1024


def guards():
    statements = [f"""
      CREATE OR REPLACE FUNCTION public.sclib_ml_submission_insert_v1() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
      DECLARE parent public.ml_use_submissions%ROWTYPE; observed jsonb; flag text;
      BEGIN
        IF TG_TABLE_NAME='ml_use_submissions' THEN
          IF NOT public.sclib_research_publication_actor_v1(NEW.actor_user_id,true)
            OR NOT public.sclib_research_publication_role_v1(NEW.actor_user_id,NEW.curator_grant_id,'curator')
            OR NOT EXISTS(SELECT 1 FROM public.ml_use_role_decisions g WHERE g.id=NEW.requester_grant_id
              AND g.user_id=NEW.actor_user_id AND g.role='requester' AND g.action='grant'
              AND g.record_sha256=public.sclib_ml_use_role_hash_v1(to_jsonb(g))
              AND NOT EXISTS(SELECT 1 FROM public.ml_use_role_decisions r WHERE r.supersedes_id=g.id)) THEN
            RAISE EXCEPTION 'ml_submission_admission_required' USING ERRCODE='42501'; END IF;
          IF (SELECT count(*) FROM public.ml_use_submissions)>={MAX_REQUESTS}
            OR (SELECT count(*) FROM public.ml_use_submissions WHERE actor_user_id=NEW.actor_user_id)>={MAX_OWNER_REQUESTS} THEN
            RAISE EXCEPTION 'ml_submission_capacity' USING ERRCODE='54000'; END IF;
          IF NEW.record_json::jsonb IS DISTINCT FROM (to_jsonb(NEW)-ARRAY[
            'record_json','record_sha256','intent_json','request_json','observation_json','created_at','expires_at'])
            OR NEW.record_sha256<>encode(public.digest(convert_to(NEW.record_json,'UTF8'),'sha256'),'hex')
            OR NEW.intent_sha256<>encode(public.digest(convert_to(NEW.intent_json,'UTF8'),'sha256'),'hex')
            OR NEW.request_sha256<>encode(public.digest(convert_to(NEW.request_json,'UTF8'),'sha256'),'hex')
            OR NEW.observation_sha256<>encode(public.digest(convert_to(NEW.observation_json,'UTF8'),'sha256'),'hex') THEN
            RAISE EXCEPTION 'ml_submission_pin_mismatch' USING ERRCODE='23514'; END IF;
          observed:=NEW.observation_json::jsonb;
          IF NEW.intent_json::jsonb IS DISTINCT FROM jsonb_build_object(
              'version','ml-use-submission-intent/1.0.0','request_key',NEW.request_key,
              'envelope_sha256',NEW.envelope_sha256,'inventory_sha256',NEW.inventory_sha256,
              'retention_policy',NEW.retention_policy)
            OR NEW.request_json::jsonb->>'purpose' IS DISTINCT FROM 'private_baseline_evaluation'
            OR NEW.request_json::jsonb->>'version' IS DISTINCT FROM 'ml-use-request/1.0.0'
            OR NEW.request_json::jsonb->'input_pins' IS DISTINCT FROM observed->'dependency_inventory'->'input_pins' THEN
            RAISE EXCEPTION 'ml_submission_intent_binding' USING ERRCODE='23514'; END IF;
          IF observed->>'version' IS DISTINCT FROM 'ml-use-current-reconstruction/1.0.0'
            OR observed->>'dependency_inventory_sha256' IS DISTINCT FROM NEW.inventory_sha256
            OR observed->'reconstruction'->>'envelope_sha256' IS DISTINCT FROM NEW.envelope_sha256
            OR observed->'admission'->>'actor_user_id' IS DISTINCT FROM NEW.actor_user_id::text
            OR observed->'admission'->>'requester_grant_id' IS DISTINCT FROM NEW.requester_grant_id::text
            OR observed->'admission'->>'curator_grant_id' IS DISTINCT FROM NEW.curator_grant_id::text
            OR observed->'reconstruction'->>'request_sha256' IS DISTINCT FROM NEW.request_sha256
            OR observed->>'decision' IS DISTINCT FROM 'not_authorized'
            OR observed->'source_permission_granted' IS DISTINCT FROM 'false'::jsonb
            OR observed->'ml_training_approved' IS DISTINCT FROM 'false'::jsonb
            OR observed->'request_persisted' IS DISTINCT FROM 'false'::jsonb THEN
            RAISE EXCEPTION 'ml_submission_observation_scope' USING ERRCODE='23514'; END IF;
          FOREACH flag IN ARRAY ARRAY['scientific_acceptance','public_release','ml_training_approved',
            'reviewer_authority_authenticated','live_source_rights_checked','external_dependency_completeness_proven',
            'database_mutated','data_access_granted','source_permission_granted','run_authorization_granted'] LOOP
            IF observed->flag IS DISTINCT FROM 'false'::jsonb THEN
              RAISE EXCEPTION 'ml_submission_no_authority' USING ERRCODE='23514'; END IF;
          END LOOP;
          NEW.created_at:=clock_timestamp(); NEW.expires_at:=NEW.created_at+interval '7 days';
        ELSIF TG_TABLE_NAME='ml_use_private_inputs' THEN
          SELECT * INTO STRICT parent FROM public.ml_use_submissions WHERE id=NEW.submission_id;
          IF EXISTS(SELECT 1 FROM public.ml_use_input_purges WHERE submission_id=NEW.submission_id)
            OR parent.expires_at<=clock_timestamp()
            OR encode(public.digest(NEW.payload,'sha256'),'hex')<>parent.envelope_sha256 THEN
            RAISE EXCEPTION 'ml_input_unavailable_or_changed' USING ERRCODE='23514'; END IF;
          IF (SELECT COALESCE(sum(octet_length(payload)),0) FROM public.ml_use_private_inputs)+octet_length(NEW.payload)>{MAX_STORAGE_BYTES}
            OR (SELECT COALESCE(sum(octet_length(i.payload)),0) FROM public.ml_use_private_inputs i
                JOIN public.ml_use_submissions s ON s.id=i.submission_id WHERE s.actor_user_id=parent.actor_user_id)
                  +octet_length(NEW.payload)>{MAX_OWNER_BYTES} THEN
            RAISE EXCEPTION 'ml_input_capacity' USING ERRCODE='54000'; END IF;
        ELSE
          SELECT * INTO STRICT parent FROM public.ml_use_submissions WHERE id=NEW.submission_id;
          IF NOT public.sclib_research_publication_actor_v1(NEW.actor_user_id,true)
            OR (NEW.reason='owner_request' AND NEW.actor_user_id<>parent.actor_user_id)
            OR (NEW.reason='retention_expired' AND parent.expires_at>clock_timestamp()) THEN
            RAISE EXCEPTION 'ml_input_purge_admission' USING ERRCODE='42501'; END IF;
          NEW.created_at:=clock_timestamp();
        END IF;
        RETURN NEW;
      END $$
    """, """
      CREATE OR REPLACE FUNCTION public.sclib_ml_submission_complete_v1() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
        IF NOT EXISTS(SELECT 1 FROM public.ml_use_private_inputs WHERE submission_id=NEW.id)
          AND NOT EXISTS(SELECT 1 FROM public.ml_use_input_purges WHERE submission_id=NEW.id) THEN
          RAISE EXCEPTION 'ml_submission_complete_inputs_required' USING ERRCODE='23514'; END IF;
        RETURN NULL;
      END $$
    """, """
      CREATE OR REPLACE FUNCTION public.sclib_ml_input_delete_v1() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
        IF TG_TABLE_NAME='ml_use_input_purges' THEN
          DELETE FROM public.ml_use_private_inputs WHERE submission_id=NEW.submission_id;
          RETURN NULL;
        END IF;
        IF NOT EXISTS(SELECT 1 FROM public.ml_use_input_purges WHERE submission_id=OLD.submission_id) THEN
          RAISE EXCEPTION 'ml_input_purge_receipt_required' USING ERRCODE='23514'; END IF;
        RETURN OLD;
      END $$
    """]
    for name in TABLES:
        statements.extend([
            f"CREATE TRIGGER mu72_writer BEFORE INSERT ON public.{name} FOR EACH STATEMENT "
            "EXECUTE FUNCTION public.sclib_research_publication_writer_v1()",
            f"CREATE TRIGGER mu72_insert BEFORE INSERT ON public.{name} FOR EACH ROW "
            "EXECUTE FUNCTION public.sclib_ml_submission_insert_v1()",
            f"CREATE TRIGGER mu72_immutable BEFORE UPDATE{' OR DELETE' if name != TABLES[1] else ''} ON public.{name} "
            "FOR EACH ROW EXECUTE FUNCTION public.sclib_research_publication_immutable_v1()",
            f"CREATE TRIGGER mu72_no_truncate BEFORE TRUNCATE ON public.{name} FOR EACH STATEMENT "
            "EXECUTE FUNCTION public.sclib_research_publication_immutable_v1()",
        ])
    statements.extend([
        "CREATE CONSTRAINT TRIGGER mu72_complete AFTER INSERT ON public.ml_use_submissions "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.sclib_ml_submission_complete_v1()",
        "CREATE TRIGGER mu72_delete BEFORE DELETE ON public.ml_use_private_inputs "
        "FOR EACH ROW EXECUTE FUNCTION public.sclib_ml_input_delete_v1()",
        "CREATE TRIGGER mu72_purge AFTER INSERT ON public.ml_use_input_purges "
        "FOR EACH ROW EXECUTE FUNCTION public.sclib_ml_input_delete_v1()",
    ])
    return statements


def register(metadata):
    def uid(name, parent=None):
        args = [sa.ForeignKey(parent + ".id", ondelete="RESTRICT", onupdate="RESTRICT")] if parent else []
        return sa.Column(name, UUID(as_uuid=True), *args, nullable=False)

    requests = sa.Table(TABLES[0], metadata,
        uid("id"), uid("actor_user_id", "users"), uid("requester_grant_id", "ml_use_role_decisions"),
        uid("curator_grant_id", "research_role_grants"),
        *(sa.Column(name, sa.Text, nullable=False) for name in RECORD_FIELDS if name not in
          {"id", "actor_user_id", "requester_grant_id", "curator_grant_id"}),
        *(sa.Column(name, sa.Text, nullable=False) for name in
          ("record_json", "record_sha256", "intent_json", "request_json", "observation_json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("actor_user_id", "request_key", name="uq_mu72_intent"),
        sa.CheckConstraint(f"version='{VERSION}' AND retention_policy='{RETENTION_POLICY}'", name="ck_mu72_version"),
        sa.CheckConstraint("request_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$'", name="ck_mu72_key"),
        sa.CheckConstraint("octet_length(request_json)<=98304 AND octet_length(observation_json)<=1048576 "
                           "AND octet_length(record_json)<=4096 AND octet_length(intent_json)<=4096", name="ck_mu72_sizes"),
        *(sa.CheckConstraint(f"{name} ~ '^[a-f0-9]{{64}}$'", name="ck_mu72_" + name)
          for name in (*[name for name in RECORD_FIELDS if name.endswith("sha256")], "record_sha256")),
        sa.CheckConstraint("isfinite(created_at) AND expires_at=created_at+interval '7 days'", name="ck_mu72_dates"),
        sa.Index("idx_mu72_expiry", "expires_at"),
    )
    inputs = sa.Table(TABLES[1], metadata,
        sa.Column("submission_id", UUID(as_uuid=True), sa.ForeignKey(TABLES[0] + ".id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("payload", sa.LargeBinary, nullable=False),
        sa.CheckConstraint("octet_length(payload)>0 AND octet_length(payload)<=33554432", name="ck_mu72_payload_size"))
    purges = sa.Table(TABLES[2], metadata,
        sa.Column("submission_id", UUID(as_uuid=True), sa.ForeignKey(TABLES[0] + ".id", ondelete="RESTRICT"), primary_key=True),
        uid("actor_user_id", "users"), sa.Column("reason", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("reason IN ('owner_request','retention_expired')", name="ck_mu72_purge_reason"),
        sa.CheckConstraint("isfinite(created_at)", name="ck_mu72_purge_date"))
    for parent in PARENTS:
        requests.add_is_dependent_on(metadata.tables[parent])
    purges.add_is_dependent_on(inputs)
    for statement in guards():
        sa.event.listen(purges, "after_create", sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"))
    return requests, inputs, purges
