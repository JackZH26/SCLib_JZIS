"""Additive 0060 immutable retrieval lineage, not source or rights approval.

Only the disposable current pointer references mutable chunks. Original text
is never copied into immutable history; closed projections contain quantities
and controlled semantic labels. ML04 v1 capsules are intentionally unchanged.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

TABLE_ORDER = ("rag_extraction_revisions", "rag_evidence_revisions", "chunk_evidence_current")
PARENT_TABLES = ("papers", "source_captures", "chunks")
FUNCTION_SIGNATURES = (
    ("sclib_rag_evidence_record_hash_v1", "jsonb"),
    ("sclib_rag_chunk_hash_v1", "jsonb"),
    ("sclib_rag_projection_valid_v1", "jsonb"),
    ("sclib_rag_evidence_immutable_v1", ""),
    ("sclib_rag_evidence_insert_v1", ""),
    ("sclib_rag_evidence_bind_v1", ""),
    ("sclib_rag_evidence_invalidate_v1", ""),
)
_SQL = "LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp SET TimeZone = 'UTC'"


def guard_statements():
    fields = "'status','relation','value_kind','value','lower','upper','uncertainty','approximate','unit','unit_basis'"
    names = "'tc_kelvin','minimum_temperature_k','temperature_k','measurement_temperature_k','hc2_temperature_k','omega_log_k','t_cdw_k','t_sdw_k','t_afm_k','pressure_gpa','hc2_tesla','magnetic_field_t','lattice_a','lattice_b','lattice_c','lattice_alpha','lattice_beta','lattice_gamma','lambda_london_nm','xi_gl_nm','layer_thickness_nm','rho_s_mev','lambda_eph','rho_exponent','doping_level','confidence','mu_star','omega_log_source_value'"
    statements = ["""
      CREATE OR REPLACE FUNCTION public.sclib_rag_evidence_record_hash_v1(body jsonb)
      RETURNS text LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
        SELECT encode(public.digest(convert_to((body-ARRAY['created_at','record_sha256'])::text,'UTF8'),'sha256'),'hex')
      $$
    """, """
      CREATE OR REPLACE FUNCTION public.sclib_rag_chunk_hash_v1(body jsonb)
      RETURNS text LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
        SELECT encode(public.digest(convert_to(jsonb_build_object('paper_id',body->'paper_id',
          'text',body->'text','materials_mentioned',body->'materials_mentioned')::text,'UTF8'),'sha256'),'hex')
      $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_rag_projection_valid_v1(body jsonb)
      RETURNS boolean {_SQL} IMMUTABLE AS $$
      DECLARE item record; field text;
      BEGIN
        IF jsonb_typeof(body) IS DISTINCT FROM 'object' OR octet_length(body::text)>16384
          OR body-ARRAY['version','quantities','knowledge_origin','source_role','classification_status','positive_interpretation_blocked']<>'{{}}'::jsonb
          OR body->>'version' IS DISTINCT FROM 'rag-result-projection/1.0.0'
          OR jsonb_typeof(body->'quantities') IS DISTINCT FROM 'object'
          OR COALESCE(body->>'knowledge_origin','') NOT IN ('Observed','Computed','Inferred','AI-Proposed','Unknown')
          OR COALESCE(body->>'source_role','') NOT IN ('primary','cited','unknown','conflicted')
          OR COALESCE(body->>'classification_status','') NOT IN ('resolved','unknown','conflicted')
          OR jsonb_typeof(body->'positive_interpretation_blocked') IS DISTINCT FROM 'boolean'
          OR NOT body ?& ARRAY['knowledge_origin','source_role','classification_status'] THEN RETURN false; END IF;
        FOR item IN SELECT key,value FROM jsonb_each(body->'quantities') LOOP
          IF item.key NOT IN ({names}) OR jsonb_typeof(item.value) IS DISTINCT FROM 'object'
            OR item.value-ARRAY[{fields}]<>'{{}}'::jsonb OR NOT item.value ?& ARRAY[{fields}]
            OR COALESCE(item.value->>'status','') NOT IN ('parsed','invalid','unreported')
            OR COALESCE(item.value->>'relation','') NOT IN ('exact','interval','lt','le','gt','ge','unreported')
            OR COALESCE(item.value->>'value_kind','') NOT IN ('point','point_with_uncertainty','interval','upper_bound','lower_bound','unreported','invalid')
            OR COALESCE(item.value->>'unit','') NOT IN ('K','GPa','T','angstrom','nm','degree','meV','1')
            OR COALESCE(item.value->>'unit_basis','') NOT IN ('unreported','explicit','field_schema_assumption','endpoint_units','dimensionless')
            OR jsonb_typeof(item.value->'approximate') IS DISTINCT FROM 'boolean' THEN RETURN false; END IF;
          FOREACH field IN ARRAY ARRAY['value','lower','upper','uncertainty'] LOOP
            IF jsonb_typeof(item.value->field) NOT IN ('null','number') THEN RETURN false; END IF;
          END LOOP;
        END LOOP;
        RETURN true;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_rag_evidence_immutable_v1() RETURNS trigger {_SQL} AS $$
      BEGIN RAISE EXCEPTION 'rag evidence history is append-only' USING ERRCODE='55000'; END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_rag_evidence_insert_v1() RETURNS trigger {_SQL} AS $$
      DECLARE current_hash text; parent public.rag_extraction_revisions%ROWTYPE; source_paper text; coordinate record; low text; high text;
      BEGIN
        PERFORM public.sclib_research_integrity_lock_v1();
        SELECT public.sclib_source_lifecycle_snapshot_hash_v1('paper',to_jsonb(p)) INTO current_hash
          FROM public.papers p WHERE p.id=NEW.paper_id;
        IF current_hash IS NULL OR NEW.source_snapshot_sha256 IS DISTINCT FROM current_hash THEN
          RAISE EXCEPTION 'rag_evidence_current_source_required' USING ERRCODE='23514'; END IF;
        IF TG_TABLE_NAME='rag_extraction_revisions' THEN
          IF NOT public.sclib_rag_projection_valid_v1(NEW.projection_json) THEN
            RAISE EXCEPTION 'rag_evidence_closed_projection_required' USING ERRCODE='23514'; END IF;
        ELSE
          FOR coordinate IN SELECT key,value FROM jsonb_each(NEW.source_locator) LOOP
            IF coordinate.key IN ('section','table','figure','equation','xml_xpath','section_path') THEN
              IF jsonb_typeof(coordinate.value)<>'string' OR length(coordinate.value#>>'{{}}') NOT BETWEEN 1 AND 300
                OR btrim(coordinate.value#>>'{{}}')='' OR (coordinate.value#>>'{{}}') ~ '[[:cntrl:]]' THEN
                RAISE EXCEPTION 'rag_evidence_locator_invalid' USING ERRCODE='23514'; END IF;
            ELSIF jsonb_typeof(coordinate.value)<>'number' OR (coordinate.value#>>'{{}}')::numeric NOT BETWEEN 0 AND 1000000000
              OR trunc((coordinate.value#>>'{{}}')::numeric)<>(coordinate.value#>>'{{}}')::numeric THEN
              RAISE EXCEPTION 'rag_evidence_locator_invalid' USING ERRCODE='23514'; END IF;
          END LOOP;
          FOR low,high IN SELECT * FROM (VALUES ('page_start','page_end'),('char_start','char_end'),('span_start','span_end')) pairs(a,b) LOOP
            IF (NEW.source_locator ? low)<>(NEW.source_locator ? high)
              OR (NEW.source_locator ? low AND ((NEW.source_locator->>low)::numeric>(NEW.source_locator->>high)::numeric
              OR (low<>'page_start' AND NEW.source_locator->>low=NEW.source_locator->>high))) THEN
              RAISE EXCEPTION 'rag_evidence_locator_invalid' USING ERRCODE='23514'; END IF;
          END LOOP;
          IF NEW.parent_extraction_revision_id IS NOT NULL THEN
            SELECT * INTO parent FROM public.rag_extraction_revisions WHERE id=NEW.parent_extraction_revision_id;
            IF parent.id IS NULL OR parent.paper_id<>NEW.paper_id OR parent.source_snapshot_sha256<>current_hash
              OR parent.extractor_version<>NEW.extraction_version THEN
              RAISE EXCEPTION 'rag_evidence_exact_parent_required' USING ERRCODE='23514'; END IF;
          END IF;
          IF NEW.source_capture_id IS NOT NULL THEN
            SELECT r.paper_id INTO source_paper FROM public.source_captures c JOIN public.source_revisions r
              ON r.id=c.source_revision_id WHERE c.id=NEW.source_capture_id;
            IF source_paper IS DISTINCT FROM NEW.paper_id THEN
              RAISE EXCEPTION 'rag_evidence_capture_paper_mismatch' USING ERRCODE='23514'; END IF;
          END IF;
        END IF;
        NEW.created_at:=clock_timestamp();
        NEW.record_sha256:=public.sclib_rag_evidence_record_hash_v1(to_jsonb(NEW));
        RETURN NEW;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_rag_evidence_bind_v1() RETURNS trigger {_SQL} AS $$
      DECLARE evidence public.rag_evidence_revisions%ROWTYPE; chunk jsonb; source_hash text;
      BEGIN
        PERFORM public.sclib_research_integrity_lock_v1();
        SELECT to_jsonb(c) INTO chunk FROM public.chunks c WHERE c.id=NEW.chunk_id FOR KEY SHARE;
        SELECT * INTO evidence FROM public.rag_evidence_revisions WHERE id=NEW.evidence_revision_id;
        SELECT public.sclib_source_lifecycle_snapshot_hash_v1('paper',to_jsonb(p)) INTO source_hash
          FROM public.papers p WHERE p.id=chunk->>'paper_id';
        IF chunk IS NULL OR evidence.id IS NULL OR evidence.paper_id<>chunk->>'paper_id' OR evidence.chunk_key<>NEW.chunk_id
          OR evidence.source_snapshot_sha256 IS DISTINCT FROM source_hash
          OR evidence.chunk_binding_sha256<>public.sclib_rag_chunk_hash_v1(chunk)
          OR evidence.content_sha256<>encode(public.digest(convert_to(chunk->>'text','UTF8'),'sha256'),'hex') THEN
          RAISE EXCEPTION 'rag_evidence_exact_live_chunk_required' USING ERRCODE='23514'; END IF;
        NEW.bound_at:=clock_timestamp(); RETURN NEW;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_rag_evidence_invalidate_v1() RETURNS trigger {_SQL} AS $$
      BEGIN
        IF TG_OP='TRUNCATE' THEN DELETE FROM public.chunk_evidence_current; RETURN NULL; END IF;
        DELETE FROM public.chunk_evidence_current WHERE chunk_id=OLD.id; RETURN NEW;
      END $$
    """]
    for name in TABLE_ORDER[:2]:
        statements.extend([
            f"CREATE TRIGGER re60_insert BEFORE INSERT ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_rag_evidence_insert_v1()",
            f"CREATE TRIGGER re60_immutable BEFORE UPDATE OR DELETE ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_rag_evidence_immutable_v1()",
            f"CREATE TRIGGER re60_truncate BEFORE TRUNCATE ON public.{name} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_rag_evidence_immutable_v1()",
        ])
    statements.extend([
        "CREATE TRIGGER re60_bind BEFORE INSERT OR UPDATE ON public.chunk_evidence_current FOR EACH ROW EXECUTE FUNCTION public.sclib_rag_evidence_bind_v1()",
        "CREATE TRIGGER re60_invalidate BEFORE UPDATE ON public.chunks FOR EACH ROW EXECUTE FUNCTION public.sclib_rag_evidence_invalidate_v1()",
        "CREATE TRIGGER re60_invalidate_truncate BEFORE TRUNCATE ON public.chunks FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_rag_evidence_invalidate_v1()",
    ])
    return statements


def remove_parent_guards():
    return [f"DROP TRIGGER {name} ON public.chunks" for name in ("re60_invalidate", "re60_invalidate_truncate")]


def register(metadata):
    tables = {}

    def column(name, kind, required=True, default=None):
        return sa.Column(name, kind, nullable=not required, server_default=default)

    def uid(name, target=None, required=True):
        return sa.Column(name, UUID(as_uuid=True), *([sa.ForeignKey(target + ".id", ondelete="RESTRICT", onupdate="RESTRICT")] if target else []), nullable=not required)

    def immutable(name, *items):
        table = sa.Table(name, metadata, uid("id"),
            column("paper_id", sa.String(100)),
            sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="RESTRICT", onupdate="RESTRICT"),
            column("source_snapshot_sha256", sa.String(64)),
            column("record_sha256", sa.String(64), default="0" * 64),
            column("created_at", sa.DateTime(timezone=True), default=sa.func.clock_timestamp()),
            *items,
            sa.PrimaryKeyConstraint("id"),
            sa.CheckConstraint("source_snapshot_sha256 ~ '^[0-9a-f]{64}$' AND record_sha256 ~ '^[0-9a-f]{64}$'", name=f"ck_re60_{name}_hash"))
        tables[name] = table
        return table

    immutable("rag_extraction_revisions",
        column("input_record_sha256", sa.String(64)), column("extractor_version", sa.String(160)),
        column("projection_version", sa.String(50), default="rag-result-projection/1.0.0"),
        column("projection_json", JSONB), column("scientific_acceptance", sa.Boolean, default=sa.false()),
        sa.CheckConstraint("input_record_sha256 ~ '^[0-9a-f]{64}$' AND btrim(extractor_version)<>''", name="ck_re60_extraction_input"),
        sa.CheckConstraint("projection_version='rag-result-projection/1.0.0' AND scientific_acceptance=false", name="ck_re60_extraction_pending"))
    immutable("rag_evidence_revisions",
        # Retained identity only, deliberately no FK to the disposable chunk.
        column("chunk_key", sa.String(200)),
        column("version", sa.String(50), default="rag-evidence/1.0.0"), column("chunk_kind", sa.String(30)),
        column("content_sha256", sa.String(64)), column("chunk_binding_sha256", sa.String(64)),
        uid("parent_extraction_revision_id", "rag_extraction_revisions", required=False),
        uid("source_capture_id", "source_captures", required=False),
        column("source_locator", JSONB, default=sa.text("'{}'::jsonb")),
        column("extraction_version", sa.String(160), required=False), column("rendering_version", sa.String(160), required=False),
        column("root_status", sa.String(30), default="unresolved"), column("unresolved_reason", sa.String(50)),
        column("permission_status", sa.String(30), default="unresolved"),
        sa.CheckConstraint("version='rag-evidence/1.0.0' AND btrim(chunk_key)<>'' AND chunk_kind IN ('original_passage','abstract','derived_fact')", name="ck_re60_kind"),
        sa.CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$' AND chunk_binding_sha256 ~ '^[0-9a-f]{64}$'", name="ck_re60_content"),
        sa.CheckConstraint("root_status='unresolved' AND permission_status IN ('unresolved','restricted') "
                           "AND unresolved_reason IN ('legacy_unresolved','original_binding_unreviewed','missing_original_source','secondary_origin_unresolved')", name="ck_re60_unresolved"),
        sa.CheckConstraint("(chunk_kind='derived_fact' AND parent_extraction_revision_id IS NOT NULL AND extraction_version IS NOT NULL "
                           "AND btrim(extraction_version)<>'' AND rendering_version IS NOT NULL AND btrim(rendering_version)<>'') OR "
                           "(chunk_kind IN ('original_passage','abstract') AND parent_extraction_revision_id IS NULL AND extraction_version IS NULL "
                           "AND (rendering_version IS NULL OR btrim(rendering_version)<>''))", name="ck_re60_parent"),
        sa.CheckConstraint("jsonb_typeof(source_locator)='object' AND octet_length(source_locator::text)<=4096 "
                           "AND source_locator-ARRAY['section','table','figure','equation','xml_xpath','section_path','page','page_start','page_end','row','column','char_start','char_end','span_start','span_end']='{}'::jsonb", name="ck_re60_locator"),
        sa.Index("idx_re60_evidence_paper", "paper_id"), sa.Index("idx_re60_evidence_parent", "parent_extraction_revision_id"),
        sa.Index("idx_re60_evidence_chunk", "chunk_key", "created_at"),
        sa.Index("idx_re60_evidence_restricted", "chunk_key", postgresql_where=sa.text("permission_status='restricted'")))
    tables["chunk_evidence_current"] = sa.Table("chunk_evidence_current", metadata,
        sa.Column("chunk_id", sa.String(200), sa.ForeignKey("chunks.id", ondelete="CASCADE", onupdate="CASCADE"), primary_key=True),
        uid("evidence_revision_id", "rag_evidence_revisions"),
        column("bound_at", sa.DateTime(timezone=True), default=sa.func.clock_timestamp()))
    # Install only after all referenced new tables exist. The extraction
    # projection validator is an INSERT guard, not a function-backed CHECK:
    # this keeps old-head drop/recreate dependency cleanup explicit.
    statements = guard_statements()
    for statement in statements:
        sa.event.listen(tables[TABLE_ORDER[-1]], "after_create", sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"))
    return tables
