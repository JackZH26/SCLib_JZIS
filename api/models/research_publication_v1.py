"""Frozen additive 0055 governance for bounded metadata-only disclosure.

Trusted callers must supply authenticated actor identities to internal writers.
These database guards independently enforce the declared user's grants, exact
object targets, three-account separation, and append-only history. They do not
authenticate a person from SQL/JSON or establish that accounts represent different
people. A permission assertion is not legal proof.
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from models.research_release_v1 import ALLOWED_TABLES

TABLE_ORDER = (
    "research_publication_epoch", "research_role_grants", "research_role_revocations",
    "research_publication_permissions", "research_publication_proposals",
    "research_publication_reviews", "research_publication_actions",
)
PARENT_TABLES = ("users", "research_releases", "research_release_pins", "research_release_notices")
LOCK_KEY = 550017026
LOCK_FUNCTION = "sclib_research_publication_lock_v1"
FUNCTION_NAMES = (
    LOCK_FUNCTION, "sclib_research_publication_writer_v1", "sclib_research_publication_immutable_v1",
    "sclib_research_publication_actor_v1", "sclib_research_publication_role_v1",
    "sclib_research_publication_object_v1", "sclib_research_publication_payload_v1",
    "sclib_research_publication_insert_v1",
)
_SQL_SETTINGS = "LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp SET TimeZone = 'UTC'"
ROLES = ("curator", "reviewer", "publisher")
LICENSES = ("CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0", "permission-on-file")


def guard_statements() -> list[str]:
    """Versioned SQL shared by Alembic and guarded metadata fixtures."""
    table_names = ",".join("'" + name + "'" for name in sorted(ALLOWED_TABLES))
    exclusions = json.dumps({name: True for name in (
        "scientific_values", "training_examples_and_features", "source_text_and_raw_records",
        "artifact_bytes_and_coordinates", "raw_object_and_material_identifiers", "source_locators_and_uris",
        "reviewer_and_account_identifiers", "free_text_and_flexible_json", "run_settings_and_connection_configuration",
    )}, separators=(",", ":"))
    statements = [f"""
      CREATE OR REPLACE FUNCTION public.{LOCK_FUNCTION}() RETURNS void {_SQL_SETTINGS} AS $$
      BEGIN
        IF current_setting('transaction_isolation')<>'serializable' THEN
          RAISE EXCEPTION 'research_publication_requires_serializable' USING ERRCODE='25000';
        END IF;
        IF NOT pg_try_advisory_xact_lock({LOCK_KEY}) THEN
          RAISE EXCEPTION 'research_publication_busy_retry_transaction' USING ERRCODE='55P03';
        END IF;
        UPDATE public.research_publication_epoch SET epoch=epoch+1 WHERE id=1;
        IF NOT FOUND THEN
          RAISE EXCEPTION 'research_publication_epoch_missing' USING ERRCODE='55000';
        END IF;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_research_publication_writer_v1() RETURNS trigger {_SQL_SETTINGS} AS $$
      BEGIN PERFORM public.{LOCK_FUNCTION}(); RETURN NULL; END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_research_publication_immutable_v1() RETURNS trigger {_SQL_SETTINGS} AS $$
      BEGIN RAISE EXCEPTION 'research publication history is append-only: %',TG_TABLE_NAME USING ERRCODE='55000'; END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_research_publication_actor_v1(actor uuid, admin_required boolean)
        RETURNS boolean {_SQL_SETTINGS} AS $$
      DECLARE accepted boolean;
      BEGIN
        SELECT is_active AND email_verified AND (NOT admin_required OR is_admin) INTO accepted
          FROM public.users WHERE id=actor FOR SHARE;
        RETURN COALESCE(accepted,false);
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_research_publication_role_v1(actor uuid, actor_grant uuid, required_role text)
        RETURNS boolean {_SQL_SETTINGS} AS $$
      BEGIN
        RETURN public.sclib_research_publication_actor_v1(actor,false) AND EXISTS (
          SELECT 1 FROM public.research_role_grants g WHERE g.id=actor_grant AND g.user_id=actor AND g.role=required_role
            AND NOT EXISTS(SELECT 1 FROM public.research_role_revocations r WHERE r.grant_id=g.id));
      END $$
    """, """
      CREATE OR REPLACE FUNCTION public.sclib_research_publication_object_v1(
        capsule text, table_name text, row_id text, row_hash text) RETURNS text
        LANGUAGE sql IMMUTABLE SET search_path = pg_catalog, public, pg_temp AS $$
        SELECT encode(public.digest(convert_to(format(
          '{"capsule_sha256":%s,"row_id":%s,"row_sha256":%s,"table":%s,"version":%s}',
          to_jsonb(capsule),to_jsonb(row_id),to_jsonb(row_hash),to_jsonb(table_name),
          to_jsonb('research-public-metadata/1.0.0'::text)),'UTF8'),'sha256'),'hex')
      $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_research_publication_payload_v1(
        body jsonb, capsule_id uuid, capsule_hash text, policy text) RETURNS void {_SQL_SETTINGS} AS $$
      DECLARE item jsonb; permission public.research_publication_permissions%ROWTYPE;
        object_count integer; expected_count integer; expected_counts jsonb; root_hash text;
      BEGIN
        IF jsonb_typeof(body) IS DISTINCT FROM 'object'
          OR NOT(body ?& ARRAY['version','scope','capsule_sha256','dataset_object_sha256','objects','counts',
                              'exclusions','limits','scientific_acceptance','ml_training_approved'])
          OR body-ARRAY['version','scope','capsule_sha256','dataset_object_sha256','objects','counts',
                        'exclusions','limits','scientific_acceptance','ml_training_approved']<>'{{}}'::jsonb
          OR body->>'version' IS DISTINCT FROM 'research-public-metadata/1.0.0'
          OR policy IS DISTINCT FROM 'research-public-metadata/1.0.0'
          OR body->>'scope' IS DISTINCT FROM 'metadata_only'
          OR body->>'capsule_sha256' IS DISTINCT FROM capsule_hash
          OR body->'scientific_acceptance' IS DISTINCT FROM 'false'::jsonb
          OR body->'ml_training_approved' IS DISTINCT FROM 'false'::jsonb
          OR body->'limits' IS DISTINCT FROM '{{"objects":1000,"file_bytes":8388608}}'::jsonb
          OR body->'exclusions' IS DISTINCT FROM '{exclusions}'::jsonb
          OR jsonb_typeof(body->'objects') IS DISTINCT FROM 'array'
          OR jsonb_typeof(body->'counts') IS DISTINCT FROM 'array'
          OR octet_length(body::text)>1048576 THEN
          RAISE EXCEPTION 'research_publication_closed_payload_required' USING ERRCODE='23514';
        END IF;
        object_count:=jsonb_array_length(body->'objects');
        SELECT count(*) INTO expected_count FROM public.research_release_pins WHERE release_id=capsule_id;
        IF object_count=0 OR object_count>1000 OR object_count<>expected_count THEN
          RAISE EXCEPTION 'research_publication_exact_receipt_count_required' USING ERRCODE='23514';
        END IF;
        FOR item IN SELECT value FROM jsonb_array_elements(body->'objects') LOOP
          IF jsonb_typeof(item) IS DISTINCT FROM 'object'
            OR NOT(item ?& ARRAY['table','object_sha256','permission_id','permission_sha256','scope','license_code'])
            OR item-ARRAY['table','object_sha256','permission_id','permission_sha256','scope','license_code']<>'{{}}'::jsonb
            OR jsonb_typeof(item->'table') IS DISTINCT FROM 'string'
            OR jsonb_typeof(item->'object_sha256') IS DISTINCT FROM 'string'
            OR jsonb_typeof(item->'permission_id') IS DISTINCT FROM 'string'
            OR jsonb_typeof(item->'permission_sha256') IS DISTINCT FROM 'string'
            OR jsonb_typeof(item->'scope') IS DISTINCT FROM 'string'
            OR jsonb_typeof(item->'license_code') IS DISTINCT FROM 'string'
            OR item->>'table' NOT IN ({table_names})
            OR item->>'object_sha256' !~ '^[0-9a-f]{{64}}$'
            OR item->>'permission_sha256' !~ '^[0-9a-f]{{64}}$'
            OR item->>'permission_id' !~ '^[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}$' THEN
            RAISE EXCEPTION 'research_publication_closed_receipt_required' USING ERRCODE='23514';
          END IF;
          SELECT * INTO permission FROM public.research_publication_permissions WHERE id=(item->>'permission_id')::uuid;
          IF permission.id IS NULL OR permission.release_id<>capsule_id OR permission.manifest_sha256<>capsule_hash
            OR permission.table_name<>item->>'table' OR permission.record_sha256<>item->>'permission_sha256'
            OR permission.scope<>item->>'scope' OR permission.license_code<>item->>'license_code'
            OR permission.decision<>'allow'
            OR EXISTS(SELECT 1 FROM public.research_publication_permissions WHERE supersedes_id=permission.id)
            OR NOT public.sclib_research_publication_role_v1(permission.actor_user_id,permission.actor_grant_id,'reviewer')
            OR item->>'object_sha256'<>public.sclib_research_publication_object_v1(
              capsule_hash,permission.table_name,permission.row_id,permission.row_sha256)
            OR NOT EXISTS(SELECT 1 FROM public.research_release_pins p WHERE p.release_id=capsule_id
              AND p.table_name=permission.table_name AND p.row_id=permission.row_id AND p.row_sha256=permission.row_sha256) THEN
            RAISE EXCEPTION 'research_publication_current_exact_receipt_required' USING ERRCODE='23514';
          END IF;
        END LOOP;
        IF (SELECT count(DISTINCT entry.value->>'permission_id') FROM jsonb_array_elements(body->'objects') entry(value))<>object_count
          OR (SELECT count(DISTINCT entry.value->>'object_sha256') FROM jsonb_array_elements(body->'objects') entry(value))<>object_count THEN
          RAISE EXCEPTION 'research_publication_duplicate_receipt' USING ERRCODE='23514';
        END IF;
        SELECT jsonb_agg(jsonb_build_object('table',name,'object_count',
          (SELECT count(*) FROM jsonb_array_elements(body->'objects') entry(value) WHERE entry.value->>'table'=name)) ORDER BY name)
          INTO expected_counts FROM unnest(ARRAY[{table_names}]) name;
        IF body->'counts' IS DISTINCT FROM expected_counts THEN
          RAISE EXCEPTION 'research_publication_exact_counts_required' USING ERRCODE='23514';
        END IF;
        SELECT public.sclib_research_publication_object_v1(capsule_hash,p.table_name,p.row_id,p.row_sha256)
          INTO root_hash FROM public.research_release_pins p JOIN public.research_releases r ON r.id=p.release_id
          WHERE p.release_id=capsule_id AND p.table_name='ml_dataset_snapshots' AND p.row_id=r.dataset_snapshot_id::text;
        IF root_hash IS NULL OR body->>'dataset_object_sha256' IS DISTINCT FROM root_hash THEN
          RAISE EXCEPTION 'research_publication_exact_dataset_object_required' USING ERRCODE='23514';
        END IF;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_research_publication_insert_v1() RETURNS trigger {_SQL_SETTINGS} AS $$
      DECLARE proposal public.research_publication_proposals%ROWTYPE;
        review public.research_publication_reviews%ROWTYPE;
        previous public.research_publication_permissions%ROWTYPE;
        needed_role text; release_hash text; pin_hash text; prior_review uuid;
      BEGIN
        IF TG_TABLE_NAME='research_role_grants' THEN
          IF NOT public.sclib_research_publication_actor_v1(NEW.granted_by,true)
            OR NOT public.sclib_research_publication_actor_v1(NEW.user_id,false) THEN
            RAISE EXCEPTION 'research_role_grant_requires_active_admin_and_user' USING ERRCODE='42501';
          END IF;
          IF EXISTS(SELECT 1 FROM public.research_role_grants g WHERE g.user_id=NEW.user_id AND g.role=NEW.role
            AND NOT EXISTS(SELECT 1 FROM public.research_role_revocations r WHERE r.grant_id=g.id)) THEN
            RAISE EXCEPTION 'research_role_active_grant_exists' USING ERRCODE='23505';
          END IF;
          RETURN NEW;
        END IF;
        IF TG_TABLE_NAME='research_role_revocations' THEN
          IF NOT public.sclib_research_publication_actor_v1(NEW.revoked_by,true) THEN
            RAISE EXCEPTION 'research_role_revoke_requires_active_admin' USING ERRCODE='42501';
          END IF;
          RETURN NEW;
        END IF;
        needed_role:=CASE TG_TABLE_NAME WHEN 'research_publication_proposals' THEN 'curator'
          WHEN 'research_publication_actions' THEN 'publisher' ELSE 'reviewer' END;
        IF NOT public.sclib_research_publication_role_v1(NEW.actor_user_id,NEW.actor_grant_id,needed_role) THEN
          RAISE EXCEPTION 'research_publication_explicit_active_role_required: %',needed_role USING ERRCODE='42501';
        END IF;
        IF TG_TABLE_NAME IN ('research_publication_permissions','research_publication_proposals') THEN
          SELECT manifest_sha256 INTO release_hash FROM public.research_releases WHERE id=NEW.release_id;
          IF release_hash IS NULL OR release_hash IS DISTINCT FROM NEW.manifest_sha256 THEN
            RAISE EXCEPTION 'research_publication_exact_capsule_required' USING ERRCODE='23514';
          END IF;
          IF TG_TABLE_NAME='research_publication_permissions' THEN
            SELECT row_sha256 INTO pin_hash FROM public.research_release_pins
              WHERE release_id=NEW.release_id AND table_name=NEW.table_name AND row_id=NEW.row_id;
            IF pin_hash IS NULL OR pin_hash IS DISTINCT FROM NEW.row_sha256 THEN
              RAISE EXCEPTION 'research_publication_exact_pin_required' USING ERRCODE='23514';
            END IF;
            IF NEW.supersedes_id IS NOT NULL THEN
              SELECT * INTO previous FROM public.research_publication_permissions WHERE id=NEW.supersedes_id;
              IF previous.id IS NULL OR previous.release_id<>NEW.release_id OR previous.table_name<>NEW.table_name
                OR previous.row_id<>NEW.row_id OR previous.row_sha256<>NEW.row_sha256 OR previous.scope<>NEW.scope
                OR EXISTS(SELECT 1 FROM public.research_publication_permissions WHERE supersedes_id=NEW.supersedes_id) THEN
                RAISE EXCEPTION 'research_publication_permission_predecessor_mismatch' USING ERRCODE='23514';
              END IF;
            ELSIF NEW.decision='revoke' THEN
              RAISE EXCEPTION 'research_publication_permission_revoke_requires_predecessor' USING ERRCODE='23514';
            END IF;
          ELSE
            PERFORM public.sclib_research_publication_payload_v1(NEW.public_payload,NEW.release_id,NEW.manifest_sha256,NEW.policy_version);
          END IF;
          RETURN NEW;
        END IF;
        SELECT * INTO proposal FROM public.research_publication_proposals WHERE id=NEW.proposal_id;
        IF proposal.id IS NULL OR proposal.manifest_sha256<>NEW.manifest_sha256 OR proposal.payload_sha256<>NEW.payload_sha256 THEN
          RAISE EXCEPTION 'research_publication_exact_proposal_required' USING ERRCODE='23514';
        END IF;
        IF NEW.actor_user_id=proposal.actor_user_id THEN
          RAISE EXCEPTION 'research_publication_independent_actor_required' USING ERRCODE='42501';
        END IF;
        IF TG_TABLE_NAME='research_publication_reviews' THEN RETURN NEW; END IF;
        SELECT * INTO review FROM public.research_publication_reviews WHERE id=NEW.review_id;
        IF review.id IS NULL OR review.proposal_id<>proposal.id OR review.manifest_sha256<>NEW.manifest_sha256
          OR review.payload_sha256<>NEW.payload_sha256 OR NOT review.disclosure_approved THEN
          RAISE EXCEPTION 'research_publication_approved_exact_review_required' USING ERRCODE='23514';
        END IF;
        IF NEW.actor_user_id=review.actor_user_id THEN
          RAISE EXCEPTION 'research_publication_independent_publisher_required' USING ERRCODE='42501';
        END IF;
        IF NEW.kind='withdraw' THEN
          SELECT review_id INTO prior_review FROM public.research_publication_actions
            WHERE proposal_id=proposal.id AND kind='publish';
          IF prior_review IS NULL OR prior_review<>NEW.review_id THEN
            RAISE EXCEPTION 'research_publication_withdraw_requires_publication' USING ERRCODE='23514';
          END IF;
          RETURN NEW;
        END IF;
        IF EXISTS(SELECT 1 FROM public.research_publication_reviews WHERE proposal_id=proposal.id AND NOT disclosure_approved) THEN
          RAISE EXCEPTION 'research_publication_negative_review_hold' USING ERRCODE='23514';
        END IF;
        IF NOT public.sclib_research_publication_role_v1(proposal.actor_user_id,proposal.actor_grant_id,'curator')
          OR NOT public.sclib_research_publication_role_v1(review.actor_user_id,review.actor_grant_id,'reviewer') THEN
          RAISE EXCEPTION 'research_publication_prior_actor_no_longer_authorized' USING ERRCODE='42501';
        END IF;
        IF EXISTS(SELECT 1 FROM public.research_release_notices WHERE release_id=proposal.release_id) THEN
          RAISE EXCEPTION 'research_publication_capsule_notice_hold' USING ERRCODE='23514';
        END IF;
        PERFORM public.sclib_research_publication_payload_v1(
          proposal.public_payload,proposal.release_id,proposal.manifest_sha256,proposal.policy_version);
        IF EXISTS(SELECT 1 FROM public.research_release_pins pin WHERE pin.release_id=proposal.release_id AND NOT EXISTS (
          SELECT 1 FROM public.research_publication_permissions permission
          WHERE permission.release_id=pin.release_id AND permission.table_name=pin.table_name
            AND permission.row_id=pin.row_id AND permission.row_sha256=pin.row_sha256 AND permission.scope='metadata_only'
            AND permission.decision='allow' AND NOT EXISTS(
              SELECT 1 FROM public.research_publication_permissions successor WHERE successor.supersedes_id=permission.id)
            AND public.sclib_research_publication_role_v1(permission.actor_user_id,permission.actor_grant_id,'reviewer'))) THEN
          RAISE EXCEPTION 'research_publication_recursive_permission_missing' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
      END $$
    """, "INSERT INTO public.research_publication_epoch(id,epoch) VALUES (1,0)"]
    for name in TABLE_ORDER[1:]:
        statements.extend([
            f"CREATE TRIGGER rp55_writer BEFORE INSERT ON public.{name} "
            "FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_research_publication_writer_v1()",
            f"CREATE TRIGGER rp55_insert BEFORE INSERT ON public.{name} "
            "FOR EACH ROW EXECUTE FUNCTION public.sclib_research_publication_insert_v1()",
            f"CREATE TRIGGER rp55_immutable_row BEFORE UPDATE OR DELETE ON public.{name} "
            "FOR EACH ROW EXECUTE FUNCTION public.sclib_research_publication_immutable_v1()",
            f"CREATE TRIGGER rp55_immutable_truncate BEFORE TRUNCATE ON public.{name} "
            "FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_research_publication_immutable_v1()",
        ])
    return statements


def register(metadata: sa.MetaData) -> dict[str, sa.Table]:
    tables = {}

    def uid(name, target=None, *, required=True):
        args = [sa.ForeignKey(f"{target}.id", ondelete="RESTRICT", onupdate="RESTRICT")] if target else []
        return sa.Column(name, UUID(as_uuid=True), *args, nullable=not required)

    def col(name, kind, *, required=True, default=None):
        return sa.Column(name, kind, nullable=not required, server_default=default)

    def ck(expression, name):
        return sa.CheckConstraint(expression, name=f"ck_rp55_{name}")

    def actor():
        return uid("actor_user_id", "users"), uid("actor_grant_id", "research_role_grants")

    def reason():
        return col("reason_code", sa.String(160)), ck("reason_code ~ '^[a-z][a-z0-9_]{0,159}$'", "reason")

    def hashes():
        return col("manifest_sha256", sa.String(64)), col("payload_sha256", sa.String(64))

    def table(name, *items):
        checks = [ck(f"{item.name} ~ '^[0-9a-f]{{64}}$'", item.name) for item in items
                  if isinstance(item, sa.Column) and item.name.endswith("sha256")]
        tables[name] = sa.Table(name, metadata, uid("id"), *items,
            col("record_sha256", sa.String(64)), ck("record_sha256 ~ '^[0-9a-f]{64}$'", "record_sha256"),
            col("created_at", sa.DateTime(timezone=True), default=sa.func.now()),
            ck("isfinite(created_at)", "created_at"), *checks, sa.PrimaryKeyConstraint("id"))

    tables["research_publication_epoch"] = sa.Table("research_publication_epoch", metadata,
        col("id", sa.Integer), col("epoch", sa.BigInteger), sa.PrimaryKeyConstraint("id"),
        ck("id=1 AND epoch>=0", "epoch_singleton"))
    table("research_role_grants", uid("user_id", "users"), col("role", sa.String(20)),
        uid("granted_by", "users"), *reason(), ck("role IN ('curator','reviewer','publisher')", "role"),
        sa.Index("idx_rp55_role_user", "user_id", "role"))
    table("research_role_revocations", uid("grant_id", "research_role_grants"), uid("revoked_by", "users"),
        *reason(), sa.UniqueConstraint("grant_id", name="uq_rp55_role_revocation"))
    table("research_publication_permissions", uid("release_id", "research_releases"),
        col("manifest_sha256", sa.String(64)), col("table_name", sa.String(100)), col("row_id", sa.String(200)),
        col("row_sha256", sa.String(64)), col("decision", sa.String(20)), col("scope", sa.String(30)),
        col("license_code", sa.String(30)), col("basis_code", sa.String(160)), *actor(),
        uid("supersedes_id", "research_publication_permissions", required=False), *reason(),
        ck("decision IN ('allow','revoke') AND scope='metadata_only'", "permission_scope"),
        ck("license_code IN ('CC0-1.0','CC-BY-4.0','CC-BY-SA-4.0','permission-on-file')", "permission_license"),
        ck("basis_code ~ '^[a-z][a-z0-9_]{0,159}$' AND btrim(row_id)<>''", "permission_basis"),
        ck("supersedes_id IS NULL OR supersedes_id<>id", "permission_not_self"),
        sa.UniqueConstraint("supersedes_id", name="uq_rp55_permission_successor"),
        sa.Index("uq_rp55_permission_root", "release_id", "table_name", "row_id", "scope", unique=True,
                 postgresql_where=sa.text("supersedes_id IS NULL")),
        sa.Index("idx_rp55_permission_release", "release_id"))
    table("research_publication_proposals", uid("release_id", "research_releases"),
        *hashes(), *actor(), col("public_payload", JSONB), col("policy_version", sa.String(100)),
        ck("jsonb_typeof(public_payload)='object' AND octet_length(public_payload::text)<=1048576", "payload_budget"),
        ck("btrim(policy_version)<>''", "policy_version"), sa.Index("idx_rp55_proposal_release", "release_id"))
    table("research_publication_reviews", uid("proposal_id", "research_publication_proposals"), *hashes(), *actor(),
        col("disclosure_approved", sa.Boolean), col("scientific_acceptance", sa.Boolean, default=sa.false()),
        col("ml_training_approved", sa.Boolean, default=sa.false()), *reason(),
        ck("scientific_acceptance=false AND ml_training_approved=false", "metadata_review_only"),
        sa.Index("idx_rp55_review_proposal", "proposal_id"))
    table("research_publication_actions", uid("proposal_id", "research_publication_proposals"), *hashes(), *actor(),
        col("kind", sa.String(20)), uid("review_id", "research_publication_reviews"), *reason(),
        ck("kind IN ('publish','withdraw')", "action_kind"),
        sa.UniqueConstraint("proposal_id", "kind", name="uq_rp55_proposal_action"))
    last = tables[TABLE_ORDER[-1]]
    for name in PARENT_TABLES + TABLE_ORDER[:-1]:
        last.add_is_dependent_on(metadata.tables[name])
    for statement in guard_statements():
        sa.event.listen(last, "after_create", sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"))
    return tables
