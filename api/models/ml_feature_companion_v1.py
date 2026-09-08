"""Additive feature-source bindings; never scientific, rights or ML approval."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

TABLE_NAME = "ml_feature_source_bindings"
LOCK_FUNCTION = "sclib_ml_feature_binding_lock_v1"
FUNCTION_SIGNATURES = (("sclib_ml_feature_binding_hash_v1", "jsonb"), (LOCK_FUNCTION, ""),
                       ("sclib_ml_feature_binding_insert_v1", ""),
                       ("sclib_ml_feature_binding_immutable_v1", ""))


def statements():
    return ["""
        CREATE OR REPLACE FUNCTION public.sclib_ml_feature_binding_hash_v1(body jsonb) RETURNS text
        LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
          SELECT encode(public.digest(convert_to('{'||COALESCE(string_agg(to_jsonb(key)::text||':'||value::text,
            ',' ORDER BY key COLLATE "C"),'')||'}','UTF8'),'sha256'),'hex')
          FROM jsonb_each(body-ARRAY['created_at','record_sha256','locator'])
        $$
    """, f"""
        CREATE OR REPLACE FUNCTION public.{LOCK_FUNCTION}() RETURNS void
        LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
          IF current_setting('transaction_isolation')<>'serializable' THEN
            RAISE EXCEPTION 'ml_feature_serializable_required' USING ERRCODE='25001'; END IF;
          PERFORM public.sclib_research_integrity_lock_v1();
          IF NOT pg_try_advisory_xact_lock(640017026) THEN
            RAISE EXCEPTION 'ml_feature_busy_retry' USING ERRCODE='55P03'; END IF;
        END $$
    """, f"""
        CREATE OR REPLACE FUNCTION public.sclib_ml_feature_binding_insert_v1() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp SET TimeZone='UTC' AS $$
        DECLARE input jsonb; release_hash text; review jsonb; revision jsonb; capture jsonb;
        BEGIN
          PERFORM public.{LOCK_FUNCTION}();
          SELECT manifest_sha256 INTO release_hash FROM public.research_releases WHERE id=NEW.base_release_id;
          SELECT row_data INTO input FROM public.research_release_pins WHERE release_id=NEW.base_release_id
            AND table_name='ml_example_inputs' AND row_id=NEW.example_input_id::text;
          IF release_hash IS DISTINCT FROM NEW.base_manifest_sha256 OR input IS NULL
            OR input->>'input_kind' NOT IN ('property','structure')
            OR NEW.locator_sha256 IS DISTINCT FROM public.sclib_ml_feature_binding_hash_v1(NEW.locator) THEN
            RAISE EXCEPTION 'ml_feature_exact_frozen_input_required' USING ERRCODE='23514'; END IF;
          SELECT to_jsonb(r) INTO revision FROM public.source_revisions r WHERE id=NEW.source_revision_id;
          SELECT to_jsonb(c) INTO capture FROM public.source_captures c WHERE id=NEW.capture_id;
          SELECT to_jsonb(a) INTO review FROM public.evidence_artifacts a WHERE id=NEW.review_artifact_id;
          IF revision IS NULL OR capture IS NULL OR review IS NULL
            OR capture->>'source_revision_id' IS DISTINCT FROM NEW.source_revision_id::text
            OR revision->>'work_id' IS DISTINCT FROM NEW.work_id::text
            OR review->>'kind' IS DISTINCT FROM 'review'
            OR review->>'schema_version' IS DISTINCT FROM 'ml-feature-source-review/1.0.0'
            OR review->>'hash_status' IS DISTINCT FROM 'verified'
            OR review->>'record_sha256' IS DISTINCT FROM NEW.review_artifact_sha256
            OR review->'metadata'->'ml_feature_source_review'->>'base_manifest_sha256' IS DISTINCT FROM NEW.base_manifest_sha256
            OR review->'metadata'->'ml_feature_source_review'->'pins'->'input'->>'row_id' IS DISTINCT FROM NEW.example_input_id::text
            OR review->'metadata'->'ml_feature_source_review'->>'source_revision_id' IS DISTINCT FROM NEW.source_revision_id::text
            OR review->'metadata'->'ml_feature_source_review'->>'capture_id' IS DISTINCT FROM NEW.capture_id::text
            OR review->'metadata'->'ml_feature_source_review'->'locator' IS DISTINCT FROM NEW.locator
            OR review->'metadata'->'ml_feature_source_review'->'binding_verified' IS DISTINCT FROM 'true'::jsonb THEN
            RAISE EXCEPTION 'ml_feature_exact_source_review_required' USING ERRCODE='23514'; END IF;
          NEW.created_at:=clock_timestamp();
          NEW.record_sha256:=public.sclib_ml_feature_binding_hash_v1(to_jsonb(NEW));
          RETURN NEW;
        END $$
    """, """
        CREATE OR REPLACE FUNCTION public.sclib_ml_feature_binding_immutable_v1() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
          RAISE EXCEPTION 'ml feature source bindings are append-only' USING ERRCODE='55000'; END $$
    """]


def register(metadata):
    def uid(name, target=None, nullable=False):
        args = [sa.ForeignKey(target, ondelete="RESTRICT", onupdate="RESTRICT")] if target else []
        return sa.Column(name, UUID(as_uuid=True), *args, nullable=nullable)
    columns = [uid("id"), uid("base_release_id", "research_releases.id"),
        sa.Column("base_manifest_sha256", sa.String(64), nullable=False),
        uid("example_input_id", "ml_example_inputs.id"), uid("source_revision_id"), uid("capture_id"), uid("work_id"),
        sa.Column("locator", JSONB, nullable=False), sa.Column("locator_sha256", sa.String(64), nullable=False),
        uid("review_artifact_id"), sa.Column("review_artifact_kind", sa.String(30), nullable=False, server_default="review"),
        sa.Column("review_artifact_sha256", sa.String(64), nullable=False),
        sa.Column("record_sha256", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())]
    columns[0].server_default = sa.DefaultClause(sa.text("gen_random_uuid()"))
    relation = sa.Table(TABLE_NAME, metadata, *columns, sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["source_revision_id", "work_id"], ["source_revisions.id", "source_revisions.work_id"],
                                ondelete="RESTRICT", onupdate="RESTRICT", name="fk_mf64_revision_work"),
        sa.ForeignKeyConstraint(["capture_id", "source_revision_id"], ["source_captures.id", "source_captures.source_revision_id"],
                                ondelete="RESTRICT", onupdate="RESTRICT", name="fk_mf64_capture_revision"),
        sa.ForeignKeyConstraint(["review_artifact_id", "review_artifact_kind"], ["evidence_artifacts.id", "evidence_artifacts.kind"],
                                ondelete="RESTRICT", onupdate="RESTRICT", name="fk_mf64_review_kind"),
        sa.UniqueConstraint("base_release_id", "example_input_id", "capture_id", "locator_sha256", name="uq_mf64_exact_occurrence"),
        sa.CheckConstraint("review_artifact_kind='review'", name="ck_mf64_review"),
        sa.CheckConstraint("jsonb_typeof(locator)='object' AND locator<>'{}'::jsonb AND octet_length(locator::text)<=16384", name="ck_mf64_locator"),
        sa.CheckConstraint("isfinite(created_at)", name="ck_mf64_time"),
        *(sa.CheckConstraint(f"{name} ~ '^[0-9a-f]{{64}}$'", name="ck_mf64_" + name) for name in
          ("base_manifest_sha256", "locator_sha256", "review_artifact_sha256", "record_sha256")),
        sa.Index("idx_mf64_release", "base_release_id"))
    for sql in statements():
        sa.event.listen(relation, "after_create", sa.DDL(sql).execute_if(dialect="postgresql"))
    for name, event, function in (("insert", "BEFORE INSERT", "insert"), ("immutable", "BEFORE UPDATE OR DELETE", "immutable")):
        sa.event.listen(relation, "after_create", sa.DDL(f"CREATE TRIGGER mf64_{name} {event} ON {TABLE_NAME} FOR EACH ROW EXECUTE FUNCTION public.sclib_ml_feature_binding_{function}_v1()").execute_if(dialect="postgresql"))
    sa.event.listen(relation, "after_create", sa.DDL(f"CREATE TRIGGER mf64_truncate BEFORE TRUNCATE ON {TABLE_NAME} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_ml_feature_binding_immutable_v1()").execute_if(dialect="postgresql"))
    return relation
