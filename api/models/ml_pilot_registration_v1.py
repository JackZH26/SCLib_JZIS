"""Immutable ML08 commitments and own-account confirmations, never pilot approval.

SQL validates declared account bindings and integrity, not authentication of its
caller, scientific document content, source rights or external review chronology.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

VERSION = "ml08-registration/1.0.0"
INTENT_VERSION = "ml08-registration-intent/1.0.0"
DECISION_VERSION = "ml08-participation-intent/1.0.0"
TABLES = ("ml_pilot_registrations", "ml_pilot_participants", "ml_pilot_participation_decisions")
PARENTS = (
    "users",
    "research_role_grants",
    "research_role_revocations",
    "research_publication_actions",
)
FUNCTIONS = ("sclib_ml_pilot_insert_v1", "sclib_ml_pilot_complete_v1")
JSON_FIELDS = ("record_json", "intent_json", "roster_json", "implementation_json", "roles_json")
MAX_REGISTRATIONS = 10000
MAX_OWNER_REGISTRATIONS = 100
MAX_PARTICIPANT_DECISIONS = 100


def guards():
    statements = [
        f"""
      CREATE OR REPLACE FUNCTION public.sclib_ml_pilot_insert_v1() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
      DECLARE reg public.ml_pilot_registrations%ROWTYPE; member public.ml_pilot_participants%ROWTYPE;
        prior public.ml_pilot_participation_decisions%ROWTYPE;
      BEGIN
        IF NEW.record_json::jsonb IS DISTINCT FROM (to_jsonb(NEW)-ARRAY[
            'record_json','record_sha256','created_at','intent_json','roster_json','implementation_json','roles_json'])
          OR NEW.record_sha256<>encode(public.digest(convert_to(NEW.record_json,'UTF8'),'sha256'),'hex') THEN
          RAISE EXCEPTION 'ml_pilot_record_hash_mismatch' USING ERRCODE='23514'; END IF;
        IF TG_TABLE_NAME='{TABLES[0]}' THEN
          IF NOT public.sclib_research_publication_actor_v1(NEW.actor_user_id,true)
            OR NOT public.sclib_research_publication_role_v1(NEW.actor_user_id,NEW.curator_grant_id,'curator') THEN
            RAISE EXCEPTION 'ml_pilot_registrar_required' USING ERRCODE='42501'; END IF;
          IF NEW.intent_json::jsonb IS DISTINCT FROM jsonb_build_object(
              'version','{INTENT_VERSION}','actor_user_id',NEW.actor_user_id,'curator_grant_id',NEW.curator_grant_id,
              'request_key',NEW.request_key,'selection_file_sha256',NEW.selection_file_sha256,
              'selection_sha256',NEW.selection_sha256,'protocol_file_sha256',NEW.protocol_file_sha256,
              'roster_sha256',NEW.roster_sha256,'implementation_sha256',NEW.implementation_sha256)
            OR NEW.intent_sha256<>encode(public.digest(convert_to(NEW.intent_json,'UTF8'),'sha256'),'hex')
            OR NEW.roster_sha256<>encode(public.digest(convert_to(NEW.roster_json,'UTF8'),'sha256'),'hex')
            OR NEW.implementation_sha256<>encode(public.digest(convert_to(NEW.implementation_json,'UTF8'),'sha256'),'hex') THEN
            RAISE EXCEPTION 'ml_pilot_document_binding' USING ERRCODE='23514'; END IF;
          IF (SELECT count(*) FROM public.{TABLES[0]})>={MAX_REGISTRATIONS}
            OR (SELECT count(*) FROM public.{TABLES[0]} WHERE actor_user_id=NEW.actor_user_id)>={MAX_OWNER_REGISTRATIONS} THEN
            RAISE EXCEPTION 'ml_pilot_registration_capacity' USING ERRCODE='54000'; END IF;
        ELSIF TG_TABLE_NAME='{TABLES[1]}' THEN
          SELECT * INTO STRICT reg FROM public.{TABLES[0]} WHERE id=NEW.registration_id;
          IF NEW.registration_sha256<>reg.record_sha256
            OR NEW.roles_sha256<>encode(public.digest(convert_to(NEW.roles_json,'UTF8'),'sha256'),'hex')
            OR NOT public.sclib_research_publication_role_v1(NEW.user_id,NEW.reviewer_grant_id,'reviewer')
            OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(reg.roster_json::jsonb) entry
              WHERE entry=jsonb_build_object('alias_sha256',NEW.alias_sha256,'user_id',NEW.user_id,
                'reviewer_grant_id',NEW.reviewer_grant_id,'roles',NEW.roles_json::jsonb)) THEN
            RAISE EXCEPTION 'ml_pilot_exact_participant_binding' USING ERRCODE='23514'; END IF;
          IF (SELECT count(*) FROM public.{TABLES[1]} WHERE registration_id=reg.id)>=30 THEN
            RAISE EXCEPTION 'ml_pilot_roster_capacity' USING ERRCODE='54000'; END IF;
        ELSE
          SELECT * INTO STRICT member FROM public.{TABLES[1]} WHERE id=NEW.participant_id;
          SELECT * INTO STRICT reg FROM public.{TABLES[0]} WHERE id=member.registration_id;
          IF NEW.actor_user_id<>member.user_id OR NEW.participant_sha256<>member.record_sha256
            OR NEW.registration_sha256<>reg.record_sha256
            OR NOT public.sclib_research_publication_actor_v1(NEW.actor_user_id,false) THEN
            RAISE EXCEPTION 'ml_pilot_own_participation_required' USING ERRCODE='42501'; END IF;
          IF NEW.intent_json::jsonb IS DISTINCT FROM jsonb_build_object(
              'version','{DECISION_VERSION}','actor_user_id',NEW.actor_user_id,
              'participant_id',NEW.participant_id,'participant_sha256',NEW.participant_sha256,
              'registration_sha256',NEW.registration_sha256,'request_key',NEW.request_key,
              'decision',NEW.decision,'reason_code',NEW.reason_code,
              'supersedes_id',NEW.supersedes_id,'supersedes_sha256',NEW.supersedes_sha256)
            OR NEW.intent_sha256<>encode(public.digest(convert_to(NEW.intent_json,'UTF8'),'sha256'),'hex') THEN
            RAISE EXCEPTION 'ml_pilot_participation_intent' USING ERRCODE='23514'; END IF;
          IF NEW.decision='accept' AND (
            NOT public.sclib_research_publication_role_v1(member.user_id,member.reviewer_grant_id,'reviewer')
            OR NOT public.sclib_research_publication_actor_v1(reg.actor_user_id,true)
            OR NOT public.sclib_research_publication_role_v1(reg.actor_user_id,reg.curator_grant_id,'curator')) THEN
            RAISE EXCEPTION 'ml_pilot_live_acceptance_roles' USING ERRCODE='42501'; END IF;
          IF NEW.supersedes_id IS NULL THEN
            IF NEW.decision='withdraw' OR EXISTS(SELECT 1 FROM public.{TABLES[2]} WHERE participant_id=member.id) THEN
              RAISE EXCEPTION 'ml_pilot_exact_participation_root' USING ERRCODE='23514'; END IF;
          ELSE
            SELECT * INTO prior FROM public.{TABLES[2]} WHERE id=NEW.supersedes_id;
            IF prior.id IS NULL OR prior.participant_id<>member.id OR prior.record_sha256<>NEW.supersedes_sha256
              OR prior.decision=NEW.decision
              OR EXISTS(SELECT 1 FROM public.{TABLES[2]} WHERE supersedes_id=prior.id)
              OR (NEW.decision='withdraw' AND prior.decision<>'accept') THEN
              RAISE EXCEPTION 'ml_pilot_exact_participation_predecessor' USING ERRCODE='23514'; END IF;
          END IF;
          IF NEW.decision='accept' AND (SELECT count(*) FROM public.{TABLES[2]} WHERE participant_id=member.id)>={MAX_PARTICIPANT_DECISIONS} THEN
            RAISE EXCEPTION 'ml_pilot_participation_capacity' USING ERRCODE='54000'; END IF;
        END IF;
        NEW.created_at:=clock_timestamp(); RETURN NEW;
      END $$
    """,
        f"""
      CREATE OR REPLACE FUNCTION public.sclib_ml_pilot_complete_v1() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
      DECLARE found jsonb;
      BEGIN
        SELECT jsonb_agg(jsonb_build_object('alias_sha256',p.alias_sha256,'user_id',p.user_id,
          'reviewer_grant_id',p.reviewer_grant_id,'roles',p.roles_json::jsonb) ORDER BY p.alias_sha256)
          INTO found FROM public.{TABLES[1]} p WHERE p.registration_id=NEW.id;
        IF found IS DISTINCT FROM NEW.roster_json::jsonb OR NOT EXISTS(
          SELECT 1 FROM public.{TABLES[1]} a JOIN public.{TABLES[1]} b ON a.registration_id=b.registration_id
          WHERE a.registration_id=NEW.id AND a.user_id<>b.user_id AND a.roles_json::jsonb ? 'primary'
            AND b.roles_json::jsonb ? 'secondary') THEN
          RAISE EXCEPTION 'ml_pilot_complete_distinct_roster_required' USING ERRCODE='23514'; END IF;
        RETURN NULL;
      END $$
    """,
    ]
    for name in TABLES:
        statements += [
            f"CREATE TRIGGER mp76_writer BEFORE INSERT ON public.{name} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_research_publication_writer_v1()",
            f"CREATE TRIGGER mp76_insert BEFORE INSERT ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_ml_pilot_insert_v1()",
            f"CREATE TRIGGER mp76_immutable BEFORE UPDATE OR DELETE ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_research_publication_immutable_v1()",
            f"CREATE TRIGGER mp76_no_truncate BEFORE TRUNCATE ON public.{name} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_research_publication_immutable_v1()",
        ]
    statements.append(
        f"CREATE CONSTRAINT TRIGGER mp76_complete AFTER INSERT ON public.{TABLES[0]} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.sclib_ml_pilot_complete_v1()"
    )
    return statements


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

    def common(prefix, hashes, *, intent=False):
        return [
            text("version"),
            text("record_json"),
            text("record_sha256"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.CheckConstraint(f"version='{VERSION}'", name=f"ck_{prefix}_version"),
            sa.CheckConstraint(
                "isfinite(created_at) AND octet_length(record_json)<=4096 AND jsonb_typeof(record_json::jsonb)='object'",
                name=f"ck_{prefix}_record",
            ),
            *(
                sa.CheckConstraint(
                    f"{name} IS NULL OR {name} ~ '^[a-f0-9]{{64}}$'", name=f"ck_{prefix}_{name}"
                )
                for name in (*hashes, "record_sha256")
            ),
            *(
                [
                    text("intent_json"),
                    text("intent_sha256"),
                    text("request_key"),
                    sa.CheckConstraint(
                        "octet_length(intent_json)<=4096 AND jsonb_typeof(intent_json::jsonb)='object'",
                        name=f"ck_{prefix}_intent",
                    ),
                    sa.CheckConstraint(
                        "intent_sha256 ~ '^[a-f0-9]{64}$'", name=f"ck_{prefix}_intent_sha256"
                    ),
                    sa.CheckConstraint(
                        "request_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$'",
                        name=f"ck_{prefix}_key",
                    ),
                    sa.UniqueConstraint(
                        "actor_user_id", "request_key", name=f"uq_{prefix}_request"
                    ),
                ]
                if intent
                else []
            ),
        ]

    reg_hashes = (
        "selection_file_sha256",
        "protocol_file_sha256",
        "selection_sha256",
        "roster_sha256",
        "implementation_sha256",
    )
    registrations = sa.Table(
        TABLES[0],
        metadata,
        uid("id"),
        uid("actor_user_id", "users"),
        uid("curator_grant_id", "research_role_grants"),
        *(text(name) for name in reg_hashes),
        text("roster_json"),
        text("implementation_json"),
        *common("mp76_reg", reg_hashes, intent=True),
        sa.UniqueConstraint("actor_user_id", "selection_sha256", name="uq_mp76_owner_selection"),
        sa.CheckConstraint(
            "octet_length(roster_json)<=16384 AND jsonb_typeof(roster_json::jsonb)='array' AND jsonb_array_length(roster_json::jsonb) BETWEEN 2 AND 30",
            name="ck_mp76_roster",
        ),
        sa.CheckConstraint(
            "octet_length(implementation_json)<=16384 AND jsonb_typeof(implementation_json::jsonb)='object'",
            name="ck_mp76_implementation",
        ),
    )
    members = sa.Table(
        TABLES[1],
        metadata,
        uid("id"),
        uid("registration_id", TABLES[0]),
        text("registration_sha256"),
        uid("user_id", "users"),
        uid("reviewer_grant_id", "research_role_grants"),
        text("alias_sha256"),
        text("roles_json"),
        text("roles_sha256"),
        *common("mp76_member", ("registration_sha256", "alias_sha256", "roles_sha256")),
        sa.UniqueConstraint("registration_id", "user_id", name="uq_mp76_roster_user"),
        sa.UniqueConstraint("registration_id", "alias_sha256", name="uq_mp76_roster_alias"),
        sa.CheckConstraint(
            'octet_length(roles_json)<=80 AND roles_json::jsonb IN (\'["primary"]\'::jsonb,\'["secondary"]\'::jsonb,\'["arbitration"]\'::jsonb,\'["primary","secondary"]\'::jsonb,\'["primary","arbitration"]\'::jsonb,\'["secondary","arbitration"]\'::jsonb,\'["primary","secondary","arbitration"]\'::jsonb)',
            name="ck_mp76_roles",
        ),
    )
    decisions = sa.Table(
        TABLES[2],
        metadata,
        uid("id"),
        uid("actor_user_id", "users"),
        uid("participant_id", TABLES[1]),
        text("participant_sha256"),
        text("registration_sha256"),
        uid("supersedes_id", TABLES[2], nullable=True),
        text("supersedes_sha256", nullable=True),
        text("decision"),
        text("reason_code"),
        *common(
            "mp76_decision",
            ("participant_sha256", "registration_sha256", "supersedes_sha256"),
            intent=True,
        ),
        sa.CheckConstraint("decision IN ('accept','decline','withdraw')", name="ck_mp76_decision"),
        sa.CheckConstraint("reason_code ~ '^[a-z][a-z0-9_]{0,159}$'", name="ck_mp76_reason"),
        sa.CheckConstraint(
            "(supersedes_id IS NULL)=(supersedes_sha256 IS NULL) AND (supersedes_id IS NULL OR supersedes_id<>id)",
            name="ck_mp76_predecessor",
        ),
        sa.UniqueConstraint("supersedes_id", name="uq_mp76_successor"),
        sa.Index(
            "uq_mp76_participation_root",
            "participant_id",
            unique=True,
            postgresql_where=sa.text("supersedes_id IS NULL"),
        ),
        sa.Index("idx_mp76_participation", "participant_id"),
    )
    for parent in PARENTS:
        registrations.add_is_dependent_on(metadata.tables[parent])
    for statement in guards():
        sa.event.listen(
            decisions,
            "after_create",
            sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"),
        )
    return registrations, members, decisions
