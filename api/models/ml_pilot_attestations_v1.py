"""Append-only own-account scientific declarations, not automatic pilot approval.

SQL enforces identity references and immutable intent/basis integrity. The
authenticated service must independently verify the complete original files;
privileged SQL cannot establish who actually read them or authenticate a person.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from services.ml_pilot_attestation_contract import SHA256 as DECLARATION_SHA256
from services.ml_pilot_attestation_contract import VERSION as DECLARATION_VERSION

TABLE = "ml_pilot_review_attestations"
VERSION = "ml08-review-attestation/1.0.0"
INTENT_VERSION = "ml08-review-attestation-intent/1.0.0"
FUNCTION = "sclib_ml_pilot_attestation_insert_v1"
PARENTS = ("users", "ml_pilot_participants", "ml_pilot_participation_decisions")
MAX_ATTESTATIONS = 100
JSON_FIELDS = ("record_json", "intent_json", "basis_json")
BASIS_FIELDS = (
    "input_pins",
    "selection_sha256",
    "review_log_sha256",
    "document_projection_sha256",
    "implementation_sha256",
    "selected_candidates",
    "review_record_count",
    "own_review_record_count",
    "own_review_records_sha256",
    "conclusion_author_is_current_account",
    "recorded_recommendation",
    "declared_canary_sha256",
)


def guards():
    basis_keys = ",".join("'" + key + "'" for key in BASIS_FIELDS)
    return [
        f"""
    CREATE OR REPLACE FUNCTION public.{FUNCTION}() RETURNS trigger
    LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
    DECLARE member public.ml_pilot_participants%ROWTYPE;
      reg public.ml_pilot_registrations%ROWTYPE;
      participation public.ml_pilot_participation_decisions%ROWTYPE;
      prior public.{TABLE}%ROWTYPE;
    BEGIN
      IF NEW.record_json::jsonb IS DISTINCT FROM (to_jsonb(NEW)-ARRAY[
          'record_json','record_sha256','created_at','intent_json','basis_json'])
        OR NEW.record_sha256<>encode(public.digest(convert_to(NEW.record_json,'UTF8'),'sha256'),'hex')
        OR NEW.basis_sha256<>encode(public.digest(convert_to(NEW.basis_json,'UTF8'),'sha256'),'hex')
        OR NEW.intent_sha256<>encode(public.digest(convert_to(NEW.intent_json,'UTF8'),'sha256'),'hex')
        OR NEW.intent_json::jsonb IS DISTINCT FROM (
          jsonb_build_object('version','{INTENT_VERSION}') || (to_jsonb(NEW)-ARRAY[
            'id','version','record_json','record_sha256','created_at','intent_json','intent_sha256','basis_json'])) THEN
        RAISE EXCEPTION 'pilot_attestation_integrity' USING ERRCODE='23514'; END IF;
      SELECT * INTO STRICT member FROM public.ml_pilot_participants WHERE id=NEW.participant_id;
      SELECT * INTO STRICT reg FROM public.ml_pilot_registrations WHERE id=member.registration_id;
      SELECT * INTO STRICT participation FROM public.ml_pilot_participation_decisions WHERE id=NEW.participation_id;
      IF (SELECT count(*) FROM jsonb_object_keys(NEW.basis_json::jsonb))<>{len(BASIS_FIELDS)}
        OR NEW.basis_json::jsonb - ARRAY[{basis_keys}] <> '{{}}'::jsonb
        OR jsonb_typeof(NEW.basis_json::jsonb->'input_pins') IS DISTINCT FROM 'object'
        OR (SELECT count(*) FROM jsonb_object_keys(NEW.basis_json::jsonb->'input_pins'))<>4
        OR (NEW.basis_json::jsonb->'input_pins') - ARRAY['selection_file_sha256','protocol_file_sha256','reviews_file_sha256','conclusion_file_sha256'] <> '{{}}'::jsonb
        OR EXISTS(SELECT 1 FROM jsonb_each(NEW.basis_json::jsonb->'input_pins') entry
            WHERE jsonb_typeof(entry.value)<>'string' OR (entry.value#>>'{{}}') !~ '^[a-f0-9]{{64}}$')
        OR EXISTS(SELECT 1 FROM jsonb_each(NEW.basis_json::jsonb) entry
            WHERE entry.key LIKE '%sha256' AND (jsonb_typeof(entry.value)<>'string' OR (entry.value#>>'{{}}') !~ '^[a-f0-9]{{64}}$'))
        OR jsonb_typeof(NEW.basis_json::jsonb->'conclusion_author_is_current_account') IS DISTINCT FROM 'boolean'
        OR jsonb_typeof(NEW.basis_json::jsonb->'recorded_recommendation') IS DISTINCT FROM 'string'
        OR NEW.basis_json::jsonb->>'recorded_recommendation' NOT IN ('go','narrow','stop')
        OR EXISTS(SELECT 1 FROM jsonb_each(NEW.basis_json::jsonb) entry
            WHERE entry.key IN ('selected_candidates','review_record_count','own_review_record_count')
              AND (jsonb_typeof(entry.value)<>'number' OR entry.value::text !~ '^(0|[1-9][0-9]*)$'))
        OR (NEW.basis_json::jsonb->>'selected_candidates')::int<>60
        OR (NEW.basis_json::jsonb->>'review_record_count')::int NOT BETWEEN 61 AND 2000
        OR (NEW.basis_json::jsonb->>'own_review_record_count')::int NOT BETWEEN 0 AND (NEW.basis_json::jsonb->>'review_record_count')::int THEN
        RAISE EXCEPTION 'pilot_attestation_basis_shape' USING ERRCODE='23514'; END IF;
      IF NEW.actor_user_id<>member.user_id OR NEW.participant_sha256<>member.record_sha256
        OR NEW.registration_sha256<>reg.record_sha256
        OR NOT public.sclib_research_publication_actor_v1(NEW.actor_user_id,false)
        OR participation.participant_id<>member.id OR participation.decision<>'accept'
        OR participation.record_sha256<>NEW.participation_sha256 THEN
        RAISE EXCEPTION 'pilot_attestation_own_account' USING ERRCODE='42501'; END IF;
      IF NEW.supersedes_id IS NULL THEN
        IF NEW.action<>'attest' OR EXISTS(SELECT 1 FROM public.{TABLE} WHERE participant_id=member.id) THEN
          RAISE EXCEPTION 'pilot_attestation_root' USING ERRCODE='23514'; END IF;
      ELSE
        SELECT * INTO prior FROM public.{TABLE} WHERE id=NEW.supersedes_id;
        IF prior.id IS NULL OR prior.participant_id<>member.id OR prior.record_sha256<>NEW.supersedes_sha256
          OR EXISTS(SELECT 1 FROM public.{TABLE} WHERE supersedes_id=prior.id)
          OR (NEW.action='withdraw' AND (prior.action<>'attest'
            OR NEW.basis_json<>prior.basis_json OR NEW.basis_sha256<>prior.basis_sha256
            OR NEW.participation_id<>prior.participation_id OR NEW.participation_sha256<>prior.participation_sha256))
          OR (NEW.action='attest' AND prior.action='attest' AND NEW.basis_sha256=prior.basis_sha256
            AND NEW.participation_id=prior.participation_id) THEN
          RAISE EXCEPTION 'pilot_attestation_predecessor' USING ERRCODE='23514'; END IF;
      END IF;
      IF NEW.action='attest' THEN
        IF NOT public.sclib_research_publication_role_v1(member.user_id,member.reviewer_grant_id,'reviewer')
          OR NOT public.sclib_research_publication_actor_v1(reg.actor_user_id,true)
          OR NOT public.sclib_research_publication_role_v1(reg.actor_user_id,reg.curator_grant_id,'curator')
          OR EXISTS(SELECT 1 FROM public.ml_pilot_participation_decisions WHERE supersedes_id=participation.id)
          OR (NEW.basis_json::jsonb->'input_pins'->>'selection_file_sha256') IS DISTINCT FROM reg.selection_file_sha256
          OR (NEW.basis_json::jsonb->'input_pins'->>'protocol_file_sha256') IS DISTINCT FROM reg.protocol_file_sha256
          OR (NEW.basis_json::jsonb->>'selection_sha256') IS DISTINCT FROM reg.selection_sha256
          OR (NEW.basis_json::jsonb->>'selected_candidates') IS DISTINCT FROM '60'
          OR ((NEW.basis_json::jsonb->>'own_review_record_count')::int=0
            AND (NEW.basis_json::jsonb->>'conclusion_author_is_current_account') IS DISTINCT FROM 'true') THEN
          RAISE EXCEPTION 'pilot_attestation_current_basis' USING ERRCODE='23514'; END IF;
        IF (SELECT count(*) FROM public.{TABLE} WHERE participant_id=member.id AND action='attest')>={MAX_ATTESTATIONS} THEN
          RAISE EXCEPTION 'pilot_attestation_capacity' USING ERRCODE='54000'; END IF;
      END IF;
      NEW.created_at:=clock_timestamp(); RETURN NEW;
    END $$
    """,
        f"CREATE TRIGGER mp77_writer BEFORE INSERT ON public.{TABLE} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_research_publication_writer_v1()",
        f"CREATE TRIGGER mp77_insert BEFORE INSERT ON public.{TABLE} FOR EACH ROW EXECUTE FUNCTION public.{FUNCTION}()",
        f"CREATE TRIGGER mp77_immutable BEFORE UPDATE OR DELETE ON public.{TABLE} FOR EACH ROW EXECUTE FUNCTION public.sclib_research_publication_immutable_v1()",
        f"CREATE TRIGGER mp77_no_truncate BEFORE TRUNCATE ON public.{TABLE} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_research_publication_immutable_v1()",
    ]


def register(metadata):
    def uid(name, parent=None, nullable=False):
        args = (
            [sa.ForeignKey(parent + ".id", ondelete="RESTRICT", onupdate="RESTRICT")]
            if parent
            else []
        )
        return sa.Column(name, UUID(as_uuid=True), *args, nullable=nullable)

    def text(name, nullable=False):
        return sa.Column(name, sa.Text, nullable=nullable)

    hashes = (
        "declaration_sha256",
        "participant_sha256",
        "registration_sha256",
        "participation_sha256",
        "basis_sha256",
        "intent_sha256",
        "record_sha256",
        "supersedes_sha256",
    )
    relation = sa.Table(
        TABLE,
        metadata,
        uid("id"),
        uid("actor_user_id", "users"),
        uid("participant_id", "ml_pilot_participants"),
        uid("participation_id", "ml_pilot_participation_decisions"),
        uid("supersedes_id", TABLE, nullable=True),
        *(text(name, nullable=name == "supersedes_sha256") for name in hashes),
        *(
            text(name)
            for name in (
                "version",
                "declaration_version",
                "request_key",
                "action",
                "reason_code",
                *JSON_FIELDS,
            )
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            f"version='{VERSION}' AND declaration_version='{DECLARATION_VERSION}' AND declaration_sha256='{DECLARATION_SHA256}'",
            name="ck_mp77_version",
        ),
        sa.CheckConstraint("action IN ('attest','withdraw')", name="ck_mp77_action"),
        sa.CheckConstraint("reason_code ~ '^[a-z][a-z0-9_]{0,159}$'", name="ck_mp77_reason"),
        sa.CheckConstraint(
            "request_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$'", name="ck_mp77_key"
        ),
        sa.CheckConstraint(
            "(supersedes_id IS NULL)=(supersedes_sha256 IS NULL) AND (supersedes_id IS NULL OR supersedes_id<>id)",
            name="ck_mp77_predecessor",
        ),
        sa.CheckConstraint("isfinite(created_at)", name="ck_mp77_created_at"),
        *(
            sa.CheckConstraint(
                f"{name} IS NULL OR {name} ~ '^[a-f0-9]{{64}}$'", name=f"ck_mp77_{name}"
            )
            for name in hashes
        ),
        *(
            sa.CheckConstraint(
                f"octet_length({name})<=8192 AND jsonb_typeof({name}::jsonb)='object'",
                name=f"ck_mp77_{name}",
            )
            for name in JSON_FIELDS
        ),
        sa.UniqueConstraint("actor_user_id", "request_key", name="uq_mp77_request"),
        sa.UniqueConstraint("supersedes_id", name="uq_mp77_successor"),
        sa.Index(
            "uq_mp77_root",
            "participant_id",
            unique=True,
            postgresql_where=sa.text("supersedes_id IS NULL"),
        ),
        sa.Index("idx_mp77_participant", "participant_id"),
    )
    for statement in guards():
        sa.event.listen(
            relation,
            "after_create",
            sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"),
        )
    return relation
