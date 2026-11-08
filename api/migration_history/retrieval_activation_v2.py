"""Short v2 activation CAS, retained local rollback and explicit operator gates.

Artifact references are operator attestations, not SQL proof of scientific
review or image signatures. Only the separate publisher group can admit them.
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

GATES = ("english_relevance_240", "english_filtered", "ask_60", "similar_60",
    "peak_load_2x", "site_integrity", "native_new_paper", "native_correction",
    "queue_replay", "roles", "restore", "standby", "signed_image")
TABLE_ORDER = ("retrieval_acceptances_v2", "retrieval_activation_events_v2", "retrieval_active_pointer_v2")
FUNCTION_SIGNATURES = (("sclib_retrieval_require_publisher_v2", ""),
    ("sclib_retrieval_activation_insert_v2", ""), ("sclib_retrieval_activate_v2", ""),
    ("sclib_retrieval_pointer_v2", ""), ("sclib_retrieval_block_v1_activation_v2", ""))
_SQL = "LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp SET TimeZone='UTC' SET bytea_output='hex'"


def guard_statements():
    gates = json.dumps(sorted(GATES))
    statements = [f"""
      CREATE FUNCTION public.sclib_retrieval_require_publisher_v2() RETURNS void {_SQL} AS $$
      BEGIN
        IF NOT coalesce((SELECT pg_has_role(current_user,r.oid,'MEMBER') FROM pg_roles r
            WHERE r.rolname='sclib_retrieval_publisher'),false) THEN
          RAISE EXCEPTION 'retrieval_separate_publisher_role_required' USING ERRCODE='42501'; END IF;
      END $$
    """, f"""
      CREATE FUNCTION public.sclib_retrieval_activation_insert_v2() RETURNS trigger {_SQL} AS $$
      DECLARE build public.retrieval_backend_builds_v2%ROWTYPE;
        validation public.retrieval_backend_validations_v2%ROWTYPE;
        content public.retrieval_contents_v2%ROWTYPE; seal public.retrieval_content_seals_v2%ROWTYPE;
        physical public.retrieval_projection_seals_v2%ROWTYPE;
        acceptance public.retrieval_acceptances_v2%ROWTYPE;
        prior public.retrieval_activation_events_v2%ROWTYPE;
        old_pointer public.index_active_pointer%ROWTYPE; old_generation public.index_generations%ROWTYPE;
        old_event public.index_activation_events%ROWTYPE; qualified text; guards integer;
      BEGIN
        PERFORM public.sclib_retrieval_require_publisher_v2();
        SELECT * INTO build FROM public.retrieval_backend_builds_v2 WHERE id=NEW.build_id;
        SELECT * INTO validation FROM public.retrieval_backend_validations_v2 WHERE id=NEW.validation_id;
        SELECT * INTO content FROM public.retrieval_contents_v2 WHERE id=build.content_id;
        SELECT * INTO seal FROM public.retrieval_content_seals_v2 WHERE content_id=content.id;
        SELECT * INTO physical FROM public.retrieval_projection_seals_v2 WHERE build_id=build.id;
        IF build.id IS NULL OR content.id IS NULL OR seal.content_id IS NULL OR physical.build_id IS NULL
          OR validation.id IS NULL OR validation.build_id<>build.id OR validation.outcome<>'validated'
          OR build.record_sha256<>public.sclib_retrieval_record_hash_v2(to_jsonb(build))
          OR content.record_sha256<>public.sclib_retrieval_record_hash_v2(to_jsonb(content))
          OR seal.record_sha256<>public.sclib_retrieval_record_hash_v2(to_jsonb(seal))
          OR physical.record_sha256<>public.sclib_retrieval_record_hash_v2(to_jsonb(physical))
          OR validation.record_sha256<>public.sclib_retrieval_record_hash_v2(to_jsonb(validation))
          OR validation.table_oid<>physical.table_oid OR validation.index_oid<>physical.index_oid
          OR NOT public.sclib_index_validation_fresh_v1(validation.created_at,clock_timestamp())
          OR seal.manifest_sha256<>build.content_manifest_sha256
          OR seal.member_count<>build.expected_member_count THEN
          RAISE EXCEPTION 'retrieval_fresh_exact_build_validation_required' USING ERRCODE='23514'; END IF;
        -- Short catalog checks only. Full corpus readback happened outside the
        -- global source/index fence in the separately committed validation.
        qualified:=format('%I.%I','retrieval_projection','b_'||replace(build.id::text,'-',''));
        EXECUTE 'LOCK TABLE '||qualified||' IN ACCESS SHARE MODE';
        SELECT count(*) INTO guards FROM pg_trigger WHERE tgrelid=physical.table_oid
          AND NOT tgisinternal AND tgenabled='O'
          AND tgfoid='public.sclib_retrieval_projection_write_v2()'::regprocedure::oid AND tgnargs=1
          AND tgargs=convert_to(build.id::text,'UTF8')||decode('00','hex')
          AND ((tgname='retrieval_projection_write_v2' AND tgtype=30)
            OR (tgname='retrieval_projection_truncate_v2' AND tgtype=34));
        IF to_regclass(qualified)::oid IS DISTINCT FROM physical.table_oid OR guards<>2
          OR NOT EXISTS(SELECT 1 FROM pg_index i WHERE i.indexrelid=physical.index_oid
            AND i.indrelid=physical.table_oid AND i.indisvalid AND i.indisready) THEN
          RAISE EXCEPTION 'retrieval_sealed_physical_build_unavailable' USING ERRCODE='23514'; END IF;
        IF TG_TABLE_NAME='retrieval_acceptances_v2' THEN
          IF jsonb_typeof(NEW.evidence)<>'object'
            OR (SELECT jsonb_agg(key ORDER BY key) FROM jsonb_object_keys(NEW.evidence) key)<>'{gates}'::jsonb
            OR EXISTS(SELECT 1 FROM jsonb_each(NEW.evidence) e WHERE jsonb_typeof(e.value)<>'string'
              OR e.value#>>'{{}}' !~ '^[0-9a-f]{{64}}$')
            OR NEW.attestation<>'operator-reviewed-artifact-references/1.0.0' THEN
            RAISE EXCEPTION 'retrieval_complete_operator_evidence_references_required' USING ERRCODE='23514'; END IF;
          NEW.content_id:=content.id; NEW.manifest_sha256:=seal.manifest_sha256;
          NEW.policy_artifact_sha256:=build.policy_artifact_sha256;
          NEW.image_digest:=build.image_digest;
        ELSE
          PERFORM public.sclib_index_lock_v1();
          SELECT e.* INTO prior FROM public.retrieval_active_pointer_v2 p
            JOIN public.retrieval_activation_events_v2 e ON e.id=p.activation_event_id
            WHERE p.logical_index=NEW.logical_index;
          SELECT * INTO acceptance FROM public.retrieval_acceptances_v2 WHERE id=NEW.acceptance_id;
          IF NEW.logical_index<>content.logical_index OR acceptance.id IS NULL OR acceptance.build_id<>build.id
            OR acceptance.content_id<>content.id OR acceptance.manifest_sha256<>seal.manifest_sha256
            OR acceptance.policy_artifact_sha256<>build.policy_artifact_sha256
            OR acceptance.image_digest<>build.image_digest
            OR acceptance.record_sha256<>public.sclib_retrieval_record_hash_v2(to_jsonb(acceptance))
            OR NEW.predecessor_id IS DISTINCT FROM prior.id THEN
            RAISE EXCEPTION 'retrieval_activation_cas_or_acceptance_failed' USING ERRCODE='23514'; END IF;
          IF prior.id IS NULL THEN
            SELECT * INTO old_pointer FROM public.index_active_pointer WHERE logical_index=NEW.logical_index;
            SELECT * INTO old_generation FROM public.index_generations WHERE id=old_pointer.generation_id;
            SELECT * INTO old_event FROM public.index_activation_events WHERE id=old_pointer.activation_event_id;
            IF NEW.action<>'promote' OR content.source_generation_id IS NULL OR old_pointer.generation_id IS NULL
              OR content.source_generation_id<>old_pointer.generation_id
              OR NEW.expected_v1_generation_id IS DISTINCT FROM old_pointer.generation_id
              OR NEW.expected_v1_event_id IS DISTINCT FROM old_pointer.activation_event_id
              OR NEW.expected_v1_manifest_sha256 IS DISTINCT FROM old_generation.manifest_sha256
              OR old_event.generation_id<>old_generation.id OR old_event.logical_index<>NEW.logical_index
              OR old_event.record_sha256<>public.sclib_index_record_hash_v1(to_jsonb(old_event))
              OR old_generation.record_sha256<>public.sclib_index_record_hash_v1(to_jsonb(old_generation)) THEN
              RAISE EXCEPTION 'retrieval_initial_exact_v1_predecessor_required' USING ERRCODE='23514'; END IF;
          ELSE
            IF NEW.expected_v1_generation_id IS NOT NULL OR NEW.expected_v1_event_id IS NOT NULL
              OR NEW.expected_v1_manifest_sha256 IS NOT NULL
              OR prior.record_sha256<>public.sclib_retrieval_record_hash_v2(to_jsonb(prior)) THEN
              RAISE EXCEPTION 'retrieval_exact_v2_predecessor_required' USING ERRCODE='23514'; END IF;
            IF NEW.action='promote' AND content.id<>prior.content_id
                AND content.base_content_id IS DISTINCT FROM prior.content_id THEN
              RAISE EXCEPTION 'retrieval_forward_content_must_extend_current' USING ERRCODE='23514'; END IF;
            IF NEW.action='rollback' AND NOT EXISTS(SELECT 1 FROM public.retrieval_activation_events_v2
                WHERE logical_index=NEW.logical_index AND build_id=build.id) THEN
              RAISE EXCEPTION 'retrieval_rollback_requires_previously_active_local_build' USING ERRCODE='23514'; END IF;
          END IF;
          NEW.event_number:=coalesce(prior.event_number,0)+1;
          NEW.content_id:=content.id; NEW.manifest_sha256:=seal.manifest_sha256;
          NEW.build_record_sha256:=build.record_sha256; NEW.validation_record_sha256:=validation.record_sha256;
          NEW.acceptance_record_sha256:=acceptance.record_sha256;
        END IF;
        NEW.operator_role:=current_user; NEW.created_at:=clock_timestamp();
        NEW.record_sha256:=public.sclib_retrieval_record_hash_v2(to_jsonb(NEW)); RETURN NEW;
      END $$
    """, f"""
      CREATE FUNCTION public.sclib_retrieval_activate_v2() RETURNS trigger {_SQL} AS $$
      BEGIN
        INSERT INTO public.retrieval_active_pointer_v2(logical_index,activation_event_id,build_id,content_id)
          VALUES(NEW.logical_index,NEW.id,NEW.build_id,NEW.content_id)
          ON CONFLICT(logical_index) DO UPDATE SET activation_event_id=EXCLUDED.activation_event_id,
            build_id=EXCLUDED.build_id,content_id=EXCLUDED.content_id;
        RETURN NULL;
      END $$
    """, f"""
      CREATE FUNCTION public.sclib_retrieval_pointer_v2() RETURNS trigger {_SQL} AS $$
      BEGIN
        IF TG_OP IN ('DELETE','TRUNCATE') OR pg_trigger_depth()<2 THEN
          RAISE EXCEPTION 'retrieval_pointer_requires_activation_event' USING ERRCODE='55000'; END IF;
        IF NOT EXISTS(SELECT 1 FROM public.retrieval_activation_events_v2 e
          WHERE e.id=NEW.activation_event_id AND e.logical_index=NEW.logical_index
            AND e.build_id=NEW.build_id AND e.content_id=NEW.content_id
            AND e.event_number=(SELECT max(event_number) FROM public.retrieval_activation_events_v2
              WHERE logical_index=NEW.logical_index)) THEN
          RAISE EXCEPTION 'retrieval_pointer_head_required' USING ERRCODE='23514'; END IF;
        RETURN NEW;
      END $$
    """, f"""
      CREATE FUNCTION public.sclib_retrieval_block_v1_activation_v2() RETURNS trigger {_SQL} AS $$
      BEGIN
        -- The existing global epoch also fences stale repeatable-read writers.
        -- This new trigger leaves the original v1 function/history untouched.
        PERFORM public.sclib_index_lock_v1();
        IF EXISTS(SELECT 1 FROM public.retrieval_active_pointer_v2 WHERE logical_index=NEW.logical_index) THEN
          RAISE EXCEPTION 'retrieval_v2_authority_blocks_v1_activation' USING ERRCODE='55000'; END IF;
        RETURN NEW;
      END $$
    """]
    for name in TABLE_ORDER[:2]:
        statements.extend([
            f"CREATE TRIGGER retrieval_activation_v2_insert BEFORE INSERT ON public.{name} "
            "FOR EACH ROW EXECUTE FUNCTION public.sclib_retrieval_activation_insert_v2()",
            f"CREATE TRIGGER retrieval_activation_v2_immutable BEFORE UPDATE OR DELETE ON public.{name} "
            "FOR EACH ROW EXECUTE FUNCTION public.sclib_retrieval_native_immutable_v2()",
            f"CREATE TRIGGER retrieval_activation_v2_no_truncate BEFORE TRUNCATE ON public.{name} "
            "FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_retrieval_native_immutable_v2()"])
    statements.extend([
        "CREATE TRIGGER retrieval_activation_v2_pointer AFTER INSERT ON public.retrieval_activation_events_v2 "
        "FOR EACH ROW EXECUTE FUNCTION public.sclib_retrieval_activate_v2()",
        "CREATE TRIGGER retrieval_pointer_v2_row BEFORE INSERT OR UPDATE OR DELETE ON public.retrieval_active_pointer_v2 "
        "FOR EACH ROW EXECUTE FUNCTION public.sclib_retrieval_pointer_v2()",
        "CREATE TRIGGER retrieval_pointer_v2_truncate BEFORE TRUNCATE ON public.retrieval_active_pointer_v2 "
        "FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_retrieval_pointer_v2()",
        "CREATE TRIGGER aa_retrieval_v2_blocks_v1 BEFORE INSERT ON public.index_activation_events "
        "FOR EACH ROW EXECUTE FUNCTION public.sclib_retrieval_block_v1_activation_v2()"])
    return statements


def register(metadata):
    def col(name, kind, nullable=False, default=None):
        return sa.Column(name, kind, nullable=nullable, server_default=default)

    def uid(name, target=None, nullable=False):
        return sa.Column(name, UUID(as_uuid=True), *([sa.ForeignKey(target, ondelete='RESTRICT', onupdate='RESTRICT')] if target else []),
                         nullable=nullable)

    def history(name, *fields):
        return sa.Table(name, metadata, *fields, col('operator_role', sa.String(160)),
            col('record_sha256', sa.String(64), default='0' * 64),
            col('created_at', sa.DateTime(timezone=True), default=sa.func.clock_timestamp()),
            sa.CheckConstraint("record_sha256 ~ '^[0-9a-f]{64}$'", name='ck_' + name + '_hash'))

    accepted = history(TABLE_ORDER[0], uid('id'), uid('build_id', 'retrieval_backend_builds_v2.id'),
        uid('validation_id', 'retrieval_backend_validations_v2.id'), uid('content_id', 'retrieval_contents_v2.id'),
        col('manifest_sha256', sa.String(64)), col('policy_artifact_sha256', sa.String(64)),
        col('image_digest', sa.String(71)), col('attestation', sa.String(80)), col('evidence', JSONB), sa.PrimaryKeyConstraint('id'))
    events = history(TABLE_ORDER[1], uid('id'), col('logical_index', sa.String(160)),
        uid('build_id', 'retrieval_backend_builds_v2.id'), uid('validation_id', 'retrieval_backend_validations_v2.id'),
        uid('acceptance_id', TABLE_ORDER[0] + '.id'), uid('content_id', 'retrieval_contents_v2.id'),
        uid('predecessor_id', TABLE_ORDER[1] + '.id', nullable=True), col('event_number', sa.BigInteger),
        col('action', sa.String(20)), col('idempotency_key', sa.String(160)),
        uid('expected_v1_generation_id', 'index_generations.id', nullable=True),
        uid('expected_v1_event_id', 'index_activation_events.id', nullable=True),
        col('expected_v1_manifest_sha256', sa.String(64), nullable=True), col('manifest_sha256', sa.String(64)),
        *[col(name, sa.String(64)) for name in ('build_record_sha256', 'validation_record_sha256', 'acceptance_record_sha256')],
        sa.PrimaryKeyConstraint('id'), sa.UniqueConstraint('logical_index', 'event_number'),
        sa.UniqueConstraint('logical_index', 'idempotency_key'), sa.CheckConstraint(
            "event_number>0 AND action IN ('promote','rollback') AND idempotency_key ~ '^[A-Za-z0-9._:-]{1,160}$'",
            name='ck_retrieval_activation_v2_event'))
    pointer = sa.Table(TABLE_ORDER[2], metadata, col('logical_index', sa.String(160)),
        uid('activation_event_id', TABLE_ORDER[1] + '.id'), uid('build_id', 'retrieval_backend_builds_v2.id'),
        uid('content_id', 'retrieval_contents_v2.id'), sa.PrimaryKeyConstraint('logical_index'))
    for table in (accepted, events, metadata.tables['index_activation_events']):
        pointer.add_is_dependent_on(table)
    for statement in guard_statements():
        sa.event.listen(pointer, 'after_create', sa.DDL(statement.replace('%', '%%')).execute_if(dialect='postgresql'))
    return {table.name: table for table in (accepted, events, pointer)}
