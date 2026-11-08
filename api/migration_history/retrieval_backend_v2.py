"""Private pgvector build/seal/readback history, not activation authority.

The builder role is separate from API readers. Long operations use a per-build
fence and private projection lock, never the global source write fence.
"""
from __future__ import annotations

import hashlib
import json

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

POLICY = {"version": "sclib-pgvector-query-policy/2.0.0", "m": 32, "ef_construction": 200,
    "ef_search": 1000, "iterative_scan": "relaxed_order", "candidate_pool": 1024,
    "work_mem_bytes": 8388608, "scan_mem_multiplier": 1, "max_scan_tuples": 20000,
    "statement_timeout_ms": 2000, "result_order": ["distance", "vector_id_C"], "dimension": 768,
    "distance": "cosine", "vector_encoding": "canonical-float32-big-endian"}
POLICY_SHA256 = hashlib.sha256((json.dumps(POLICY, sort_keys=True, indent=2) + "\n").encode()).hexdigest()
assert POLICY_SHA256 == "54125fcefefcd65e04898504ced5c8a2a7e5f8915c2553435e13d8e486a018f6"
TABLE_ORDER = ("retrieval_backend_builds_v2", "retrieval_backend_fences_v2",
               "retrieval_projection_seals_v2", "retrieval_backend_validations_v2")
FUNCTION_SIGNATURES = (("sclib_retrieval_require_builder_v2", ""),
    ("sclib_retrieval_build_fence_v2", "uuid"), ("sclib_retrieval_projection_write_v2", ""),
    ("sclib_retrieval_backend_fence_guard_v2", ""), ("sclib_retrieval_backend_insert_v2", ""),
    ("sclib_retrieval_backend_created_v2", ""))
_SQL = "LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp SET TimeZone='UTC' SET bytea_output='hex'"


def authority_sql():
    """Closed SQL shape. $1 is content UUID; no caller SQL/name enters it."""
    raw = "CASE m.origin_kind WHEN 'legacy_v1' THEN old.vector_bytes ELSE native.vector_bytes END"
    origin_hash = "CASE m.origin_kind WHEN 'legacy_v1' THEN old.record_sha256 ELSE native.record_sha256 END"
    intact = """CASE m.origin_kind WHEN 'legacy_v1' THEN old.record_sha256=public.sclib_index_record_hash_v1(to_jsonb(old))
      ELSE native.record_sha256=public.sclib_retrieval_record_hash_v2(to_jsonb(native)) END"""
    return f"""SELECT m.vector_id,m.paper_id,m.content_sha256,m.vector_sha256,m.chunk_revision_sha256,
      (coalesce(old.snapshot_json,native.snapshot_json)->>'year')::integer AS year,{raw} AS vector_bytes,
      coalesce(m.record_sha256=public.sclib_retrieval_record_hash_v2(to_jsonb(m)) AND {intact}
        AND m.origin_record_sha256={origin_hash}
        AND m.paper_id=coalesce(old.paper_id,native.paper_id)
        AND m.content_sha256=coalesce(old.content_sha256,native.content_sha256)
        AND m.vector_sha256=coalesce(old.vector_sha256,native.vector_sha256)
        AND m.chunk_revision_sha256=coalesce(old.chunk_revision_sha256,native.chunk_revision_sha256)
        AND octet_length({raw})=3072
        AND encode(public.digest({raw},'sha256'),'hex')=m.vector_sha256,false) AS intact
      FROM public.retrieval_content_members_v2 m
      LEFT JOIN public.index_generation_members old ON m.origin_kind='legacy_v1'
        AND old.generation_id=m.origin_generation_id AND old.vector_id=m.vector_id
      LEFT JOIN public.retrieval_native_revisions_v2 native ON m.origin_kind='native_v2'
        AND native.id=m.native_revision_id AND native.vector_id=m.vector_id
      WHERE m.content_id=$1"""


def guard_statements():
    source = authority_sql()
    statements = ["""
      DO $$ BEGIN
        IF EXISTS(SELECT 1 FROM pg_namespace n WHERE n.nspname='retrieval_projection'
          AND (n.nspowner<>(SELECT oid FROM pg_roles WHERE rolname=current_user)
            OR EXISTS(SELECT 1 FROM pg_class WHERE relnamespace=n.oid))) THEN
          RAISE EXCEPTION 'retrieval_projection_reserved_schema_already_used'; END IF;
      END $$
    """, "CREATE SCHEMA IF NOT EXISTS retrieval_projection", """
      DO $$ BEGIN
        IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='sclib_retrieval_builder') THEN
          GRANT USAGE,CREATE ON SCHEMA retrieval_projection TO sclib_retrieval_builder;
        END IF;
      END $$
    """, f"""
      CREATE FUNCTION public.sclib_retrieval_require_builder_v2() RETURNS void {_SQL} AS $$
      BEGIN
        IF NOT coalesce((SELECT pg_has_role(current_user,r.oid,'MEMBER') FROM pg_roles r
            WHERE r.rolname='sclib_retrieval_builder'),false) THEN
          RAISE EXCEPTION 'retrieval_separate_builder_role_required' USING ERRCODE='42501'; END IF;
      END $$
    """, f"""
      CREATE FUNCTION public.sclib_retrieval_build_fence_v2(identifier uuid) RETURNS void {_SQL} AS $$
      BEGIN
        PERFORM public.sclib_retrieval_require_builder_v2();
        UPDATE public.retrieval_backend_fences_v2 SET epoch=epoch+1 WHERE build_id=identifier;
        IF NOT FOUND THEN RAISE EXCEPTION 'retrieval_build_fence_missing' USING ERRCODE='55000'; END IF;
      END $$
    """, f"""
      CREATE FUNCTION public.sclib_retrieval_projection_write_v2() RETURNS trigger {_SQL} AS $$
      DECLARE identifier uuid:=TG_ARGV[0]::uuid;
      BEGIN
        IF TG_TABLE_SCHEMA<>'retrieval_projection' OR TG_TABLE_NAME<>'b_'||replace(identifier::text,'-','') THEN
          RAISE EXCEPTION 'retrieval_projection_name_mismatch' USING ERRCODE='23514'; END IF;
        -- One fence update per statement, not per million-vector row. A stale
        -- repeatable-read writer cannot miss a seal committed while it waited.
        PERFORM public.sclib_retrieval_build_fence_v2(identifier);
        IF EXISTS(SELECT 1 FROM public.retrieval_projection_seals_v2 WHERE build_id=identifier) THEN
          RAISE EXCEPTION 'retrieval_projection_sealed' USING ERRCODE='55000'; END IF;
        RETURN NULL;
      END $$
    """, f"""
      CREATE FUNCTION public.sclib_retrieval_backend_fence_guard_v2() RETURNS trigger {_SQL} AS $$
      BEGIN
        PERFORM public.sclib_retrieval_require_builder_v2();
        IF TG_OP='INSERT' THEN
          IF NEW.epoch<>0 THEN RAISE EXCEPTION 'retrieval_fence_starts_at_zero' USING ERRCODE='23514'; END IF;
        ELSIF TG_OP='UPDATE' THEN
          IF NEW.build_id IS DISTINCT FROM OLD.build_id OR NEW.epoch<>OLD.epoch+1 THEN
            RAISE EXCEPTION 'retrieval_fence_monotonic' USING ERRCODE='23514'; END IF;
        ELSE RAISE EXCEPTION 'retrieval_fence_history_required' USING ERRCODE='55000'; END IF;
        RETURN NEW;
      END $$
    """, f"""
      CREATE FUNCTION public.sclib_retrieval_backend_created_v2() RETURNS trigger {_SQL} AS $$
      BEGIN
        INSERT INTO public.retrieval_backend_fences_v2(build_id,epoch) VALUES(NEW.id,0);
        RETURN NEW;
      END $$
    """, f"""
      CREATE FUNCTION public.sclib_retrieval_backend_insert_v2() RETURNS trigger {_SQL} AS $$
      DECLARE build public.retrieval_backend_builds_v2%ROWTYPE;
        content public.retrieval_contents_v2%ROWTYPE; content_seal public.retrieval_content_seals_v2%ROWTYPE;
        projection_seal public.retrieval_projection_seals_v2%ROWTYPE;
        identifier uuid; qualified text; physical oid; graph oid; columns text[]; guards integer;
        source_count bigint; actual_count bigint; missing_count bigint; extra_count bigint; mismatch_count bigint;
      BEGIN
        PERFORM public.sclib_retrieval_require_builder_v2();
        IF TG_TABLE_NAME='retrieval_backend_builds_v2' THEN
          SELECT * INTO content FROM public.retrieval_contents_v2 WHERE id=NEW.content_id;
          SELECT * INTO content_seal FROM public.retrieval_content_seals_v2 WHERE content_id=NEW.content_id;
          IF content.id IS NULL OR content_seal.content_id IS NULL
            OR content.record_sha256<>public.sclib_retrieval_record_hash_v2(to_jsonb(content))
            OR content_seal.record_sha256<>public.sclib_retrieval_record_hash_v2(to_jsonb(content_seal))
            OR content_seal.manifest_sha256 IS DISTINCT FROM public.sclib_retrieval_content_root_v2(content.id)
            OR NEW.policy IS DISTINCT FROM '{json.dumps(POLICY)}'::jsonb
            OR NEW.policy_artifact_sha256<>'{POLICY_SHA256}'
            OR NOT EXISTS(SELECT 1 FROM pg_extension WHERE extname='vector' AND extversion='0.8.7')
            OR current_setting('server_version_num')::integer NOT BETWEEN 160000 AND 169999 THEN
            RAISE EXCEPTION 'retrieval_sealed_content_supported_runtime_policy_required' USING ERRCODE='23514'; END IF;
          NEW.content_record_sha256:=content.record_sha256; NEW.content_manifest_sha256:=content_seal.manifest_sha256;
          NEW.profile:=content.profile; NEW.expected_member_count:=content_seal.member_count;
          NEW.postgres_version_num:=current_setting('server_version_num')::integer;
          NEW.extension_version:='0.8.7'; NEW.operator_role:=current_user;
        ELSE
          identifier:=NEW.build_id;
          PERFORM public.sclib_retrieval_build_fence_v2(identifier);
          SELECT * INTO build FROM public.retrieval_backend_builds_v2 WHERE id=identifier;
          qualified:=format('%I.%I','retrieval_projection','b_'||replace(identifier::text,'-',''));
          physical:=to_regclass(qualified)::oid;
          IF physical IS NULL THEN RAISE EXCEPTION 'retrieval_physical_projection_required' USING ERRCODE='23514'; END IF;
          EXECUTE 'LOCK TABLE '||qualified||' IN SHARE MODE';
          IF to_regclass(qualified)::oid<>physical OR EXISTS(SELECT 1 FROM pg_class WHERE oid=physical
              AND (relkind<>'r' OR relispartition OR relrowsecurity OR relforcerowsecurity))
            OR EXISTS(SELECT 1 FROM pg_inherits WHERE inhrelid=physical OR inhparent=physical) THEN
            RAISE EXCEPTION 'retrieval_standalone_unfiltered_projection_required' USING ERRCODE='23514'; END IF;
          SELECT array_agg(attname||':'||format_type(atttypid,atttypmod) ORDER BY attnum) INTO columns
            FROM pg_attribute WHERE attrelid=physical AND attnum>0 AND NOT attisdropped;
          IF columns IS DISTINCT FROM ARRAY['vector_id:text','paper_id:text','year:integer','content_sha256:text',
              'vector_sha256:text','chunk_revision_sha256:text','embedding:vector(768)']
            OR EXISTS(SELECT 1 FROM pg_attribute WHERE attrelid=physical AND attnum>0 AND attname<>'year' AND NOT attnotnull)
            OR NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid=physical AND contype='p' AND conkey=ARRAY[1]::smallint[]) THEN
            RAISE EXCEPTION 'retrieval_exact_projection_columns_required' USING ERRCODE='23514'; END IF;
          SELECT i.indexrelid INTO graph FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
            JOIN pg_am a ON a.oid=c.relam JOIN pg_opclass op ON op.oid=i.indclass[0]
            WHERE i.indrelid=physical AND i.indisvalid AND i.indisready AND i.indnatts=1
              AND i.indkey[0]=7 AND i.indpred IS NULL AND i.indexprs IS NULL
              AND a.amname='hnsw' AND op.opcname='vector_cosine_ops'
              AND c.relname='hnsw_b_'||replace(identifier::text,'-','')
              AND c.reloptions @> ARRAY['m=32','ef_construction=200'] AND cardinality(c.reloptions)=2;
          SELECT count(*) INTO guards FROM pg_trigger WHERE tgrelid=physical AND NOT tgisinternal AND tgenabled='O'
            AND tgfoid='public.sclib_retrieval_projection_write_v2()'::regprocedure::oid AND tgnargs=1
            AND tgargs=convert_to(identifier::text,'UTF8')||decode('00','hex')
            AND ((tgname='retrieval_projection_write_v2' AND tgtype=30)
              OR (tgname='retrieval_projection_truncate_v2' AND tgtype=34));
          IF graph IS NULL OR guards<>2 THEN
            RAISE EXCEPTION 'retrieval_valid_cosine_graph_and_statement_guards_required' USING ERRCODE='23514'; END IF;
          IF TG_TABLE_NAME='retrieval_projection_seals_v2' THEN
            IF EXISTS(SELECT 1 FROM public.retrieval_projection_seals_v2 WHERE build_id=identifier) THEN
              RAISE EXCEPTION 'retrieval_projection_already_sealed' USING ERRCODE='23514'; END IF;
            NEW.table_oid:=physical; NEW.index_oid:=graph;
          ELSE
            SELECT * INTO projection_seal FROM public.retrieval_projection_seals_v2 WHERE build_id=identifier;
            IF projection_seal.build_id IS NULL OR projection_seal.table_oid<>physical OR projection_seal.index_oid<>graph THEN
              RAISE EXCEPTION 'retrieval_same_sealed_physical_objects_required' USING ERRCODE='23514'; END IF;
            EXECUTE format($readback$
              WITH authority AS NOT MATERIALIZED ({source})
              SELECT count(a.vector_id),count(p.vector_id),count(*) FILTER(WHERE p.vector_id IS NULL),
                count(*) FILTER(WHERE a.vector_id IS NULL),count(*) FILTER(WHERE a.vector_id IS NOT NULL
                  AND p.vector_id IS NOT NULL AND (NOT a.intact OR p.paper_id IS DISTINCT FROM a.paper_id
                  OR p.year IS DISTINCT FROM a.year OR p.content_sha256 IS DISTINCT FROM a.content_sha256
                  OR p.vector_sha256 IS DISTINCT FROM a.vector_sha256
                  OR p.chunk_revision_sha256 IS DISTINCT FROM a.chunk_revision_sha256
                  OR substring(vector_send(p.embedding) FROM 5) IS DISTINCT FROM a.vector_bytes))
              FROM authority a FULL JOIN %s p USING(vector_id)
            $readback$,qualified) INTO source_count,actual_count,missing_count,extra_count,mismatch_count USING build.content_id;
            NEW.source_member_count:=source_count; NEW.projection_member_count:=actual_count;
            NEW.missing_count:=missing_count; NEW.extra_count:=extra_count; NEW.mismatch_count:=mismatch_count;
            NEW.content_manifest_intact:=NOT EXISTS(SELECT 1 FROM public.retrieval_content_partitions_v2 p
              WHERE p.content_id=build.content_id AND p.manifest_sha256 IS DISTINCT FROM
                public.sclib_retrieval_partition_hash_v2(p.content_id,p.partition_id));
            NEW.outcome:=CASE WHEN source_count=build.expected_member_count AND actual_count=build.expected_member_count
                AND missing_count=0 AND extra_count=0 AND mismatch_count=0 AND NEW.content_manifest_intact
                THEN 'validated' ELSE 'rejected' END;
            NEW.table_oid:=physical; NEW.index_oid:=graph;
          END IF;
        END IF;
        NEW.created_at:=clock_timestamp();
        NEW.record_sha256:=public.sclib_retrieval_record_hash_v2(to_jsonb(NEW));
        RETURN NEW;
      END $$
    """]
    for name in (TABLE_ORDER[0], TABLE_ORDER[2], TABLE_ORDER[3]):
        statements.extend([
            f"CREATE TRIGGER retrieval_backend_v2_insert BEFORE INSERT ON public.{name} "
            "FOR EACH ROW EXECUTE FUNCTION public.sclib_retrieval_backend_insert_v2()",
            f"CREATE TRIGGER retrieval_backend_v2_immutable BEFORE UPDATE OR DELETE ON public.{name} "
            "FOR EACH ROW EXECUTE FUNCTION public.sclib_retrieval_native_immutable_v2()",
            f"CREATE TRIGGER retrieval_backend_v2_no_truncate BEFORE TRUNCATE ON public.{name} "
            "FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_retrieval_native_immutable_v2()"])
    statements.extend([
        "CREATE TRIGGER retrieval_backend_v2_created AFTER INSERT ON public.retrieval_backend_builds_v2 "
        "FOR EACH ROW EXECUTE FUNCTION public.sclib_retrieval_backend_created_v2()",
        "CREATE TRIGGER retrieval_backend_v2_fence_row BEFORE INSERT OR UPDATE OR DELETE ON public.retrieval_backend_fences_v2 "
        "FOR EACH ROW EXECUTE FUNCTION public.sclib_retrieval_backend_fence_guard_v2()",
        "CREATE TRIGGER retrieval_backend_v2_fence_truncate BEFORE TRUNCATE ON public.retrieval_backend_fences_v2 "
        "FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_retrieval_backend_fence_guard_v2()"])
    return statements


def register(metadata):
    def col(name, kind, nullable=False, default=None):
        return sa.Column(name, kind, nullable=nullable, server_default=default)

    def uid(name, target=None):
        return col(name, UUID(as_uuid=True)) if target is None else sa.Column(name, UUID(as_uuid=True),
            sa.ForeignKey(target, ondelete='RESTRICT', onupdate='RESTRICT'), nullable=False)

    def history(name, *fields):
        return sa.Table(name, metadata, *fields, col('record_sha256', sa.String(64), default='0' * 64),
            col('created_at', sa.DateTime(timezone=True), default=sa.func.clock_timestamp()),
            sa.CheckConstraint("record_sha256 ~ '^[0-9a-f]{64}$'", name='ck_' + name + '_hash'))

    builds = history(TABLE_ORDER[0], uid('id'), uid('content_id', 'retrieval_contents_v2.id'),
        col('content_record_sha256', sa.String(64)), col('content_manifest_sha256', sa.String(64)),
        col('profile', JSONB), col('policy', JSONB), col('policy_artifact_sha256', sa.String(64)),
        col('expected_member_count', sa.Integer), col('postgres_version_num', sa.Integer),
        col('extension_version', sa.String(30)), col('operator_role', sa.String(160)),
        col('image_digest', sa.String(71)), col('implementation_revision', sa.String(40)),
        sa.PrimaryKeyConstraint('id'), sa.CheckConstraint(
            "image_digest ~ '^sha256:[0-9a-f]{64}$' AND implementation_revision ~ '^[0-9a-f]{40}$' "
            "AND expected_member_count>0 AND extension_version='0.8.7'", name='ck_retrieval_backend_v2_build'))
    fences = sa.Table(TABLE_ORDER[1], metadata, uid('build_id', TABLE_ORDER[0] + '.id'),
        col('epoch', sa.BigInteger, default='0'), sa.PrimaryKeyConstraint('build_id'),
        sa.CheckConstraint('epoch>=0', name='ck_retrieval_backend_v2_fence'))
    seals = history(TABLE_ORDER[2], uid('build_id', TABLE_ORDER[0] + '.id'),
        col('table_oid', sa.BigInteger), col('index_oid', sa.BigInteger), sa.PrimaryKeyConstraint('build_id'))
    validations = history(TABLE_ORDER[3], uid('id'), uid('build_id', TABLE_ORDER[0] + '.id'),
        col('table_oid', sa.BigInteger), col('index_oid', sa.BigInteger),
        *[col(name, sa.BigInteger) for name in ('source_member_count', 'projection_member_count',
                                             'missing_count', 'extra_count', 'mismatch_count')],
        col('content_manifest_intact', sa.Boolean), col('outcome', sa.String(20)),
        sa.PrimaryKeyConstraint('id'), sa.CheckConstraint(
            "outcome IN ('validated','rejected') AND source_member_count>=0 AND projection_member_count>=0 "
            "AND missing_count>=0 AND extra_count>=0 AND mismatch_count>=0", name='ck_retrieval_backend_v2_validation'))
    for dependency in (builds, fences, seals, metadata.tables['retrieval_content_seals_v2']):
        validations.add_is_dependent_on(dependency)
    for statement in guard_statements():
        sa.event.listen(validations, 'after_create', sa.DDL(statement.replace('%', '%%')).execute_if(dialect='postgresql'))
    return {table.name: table for table in (builds, fences, seals, validations)}
