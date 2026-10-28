"""0096: source-scoped composition, procedure and component assertions.

Only explicitly selected immutable revisions belong to an event. Unselected
later assertions do not silently change its scientific context. This storage
contract grants no review, normalization, promotion or release authority.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

VERSION = "materials-context/1"
TABLE_ORDER = ("sample_compositions", "research_protocols", "sample_relations")
TABLE_FIELDS = {
    "sample_compositions": ("id", "sample_id", "revision", "supersedes_id", "formula_raw",
        "composition_basis", "composition_schema_version", "composition_payload", "source_artifact_id",
        "record_sha256", "created_at"),
    "research_protocols": ("id", "work_id", "revision", "supersedes_id", "method_class", "method_raw",
        "observable", "details_raw", "protocol_schema_version", "parameters", "source_artifact_id",
        "record_sha256", "created_at"),
    "sample_relations": ("id", "from_sample_id", "to_sample_id", "revision", "supersedes_id", "relation_kind",
        "relation_raw", "relation_schema_version", "source_artifact_id", "record_sha256", "created_at"),
}
FKS = {
    "sample_compositions": (("sample_id", "research_samples"), ("supersedes_id", "sample_compositions"),
        ("source_artifact_id", "evidence_artifacts")),
    "research_protocols": (("work_id", "works"), ("supersedes_id", "research_protocols"),
        ("source_artifact_id", "evidence_artifacts")),
    "sample_relations": (("from_sample_id", "research_samples"), ("to_sample_id", "research_samples"),
        ("supersedes_id", "sample_relations"), ("source_artifact_id", "evidence_artifacts")),
}
FUNCTION_SIGNATURES = (
    ("sclib_materials_text_v1", "jsonb,integer,boolean"),
    ("sclib_materials_quantity_v1", "jsonb"),
    ("sclib_materials_composition_v1", "jsonb"),
    ("sclib_materials_parameters_v1", "jsonb"),
    ("sclib_materials_context_shape_v1", "jsonb"),
    ("sclib_materials_context_immutable_v1", ""),
    ("sclib_materials_context_insert_v1", ""),
    ("sclib_materials_context_event_v1", ""),
    ("sclib_materials_context_owner_v1", ""),
    ("sclib_materials_context_legacy_gate_v1", ""),
)


def register_tables(metadata):
    tables = {}

    def uid(name, target, required=True):
        return sa.Column(name, UUID(as_uuid=True), sa.ForeignKey(f"{target}.id", ondelete="RESTRICT",
            onupdate="RESTRICT"), nullable=not required)

    def text(name, required=True):
        return sa.Column(name, sa.Text, nullable=not required)

    def table(name, *columns):
        result = sa.Table(name, metadata,
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("revision", sa.Integer, nullable=False, server_default="1"),
            uid("supersedes_id", name, False), *columns,
            uid("source_artifact_id", "evidence_artifacts"),
            sa.Column("record_sha256", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("supersedes_id", name=f"uq_mc96_{name}_successor"),
            sa.CheckConstraint("(revision=1 AND supersedes_id IS NULL) OR (revision>1 AND supersedes_id IS NOT NULL)",
                name=f"ck_mc96_{name}_revision"),
            sa.CheckConstraint("id IS DISTINCT FROM supersedes_id AND record_sha256 ~ '^[a-f0-9]{64}$'",
                name=f"ck_mc96_{name}_identity"))
        tables[name] = result
        return result

    table("sample_compositions", uid("sample_id", "research_samples"), text("formula_raw"), text("composition_basis"),
        text("composition_schema_version"), sa.Column("composition_payload", JSONB, nullable=False))
    table("research_protocols", uid("work_id", "works"), text("method_class"), text("method_raw", False),
        text("observable", False), text("details_raw", False), text("protocol_schema_version"),
        sa.Column("parameters", JSONB, nullable=False))
    table("sample_relations", uid("from_sample_id", "research_samples"), uid("to_sample_id", "research_samples"),
        text("relation_kind"), text("relation_raw"), text("relation_schema_version"),
        sa.CheckConstraint("from_sample_id<>to_sample_id", name="ck_mc96_relation_self"))
    for name, column in (("sample_compositions", "sample_id"), ("research_protocols", "work_id"),
                         ("sample_relations", "from_sample_id"), ("sample_relations", "to_sample_id")):
        sa.Index(f"ix_mc96_{name}_{column}", tables[name].c[column])
    return tables


def functions():
    return [r"""
CREATE FUNCTION public.sclib_materials_text_v1(j jsonb,b integer,optional boolean) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT (optional AND j='null'::jsonb) OR COALESCE(jsonb_typeof(j)='string'
  AND length(btrim(j#>>'{}')) BETWEEN 1 AND b,false)
$$""", r"""
CREATE FUNCTION public.sclib_materials_quantity_v1(q jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE shape text; k text; u jsonb; BEGIN
 IF NOT public.sclib_materials_closed_object_v1(q,ARRAY['status','raw','relation','value','lower','upper','unit','approximate','uncertainty'])
  OR jsonb_typeof(q->'status') IS DISTINCT FROM 'string'
  OR q->>'status' NOT IN ('reported','not_reported','not_accessible','not_extracted','ambiguous','conflicted','not_applicable')
  OR jsonb_typeof(q->'approximate') IS DISTINCT FROM 'boolean'
  OR NOT public.sclib_materials_text_v1(q->'raw',2000,true)
  OR NOT public.sclib_materials_text_v1(q->'unit',60,true) THEN RETURN false; END IF;
 IF q->>'status'<>'reported' THEN
  RETURN q->'relation'='null'::jsonb AND q->'value'='null'::jsonb AND q->'lower'='null'::jsonb
   AND q->'upper'='null'::jsonb AND q->'uncertainty'='null'::jsonb;
 END IF;
 shape:=q->>'relation';
 IF shape IS NULL OR shape NOT IN ('exact','interval','lt','le','gt','ge')
  OR NOT public.sclib_materials_text_v1(q->'raw',2000,false)
  OR NOT public.sclib_materials_text_v1(q->'unit',60,false) THEN RETURN false; END IF;
 FOREACH k IN ARRAY ARRAY['value','lower','upper'] LOOP
  IF (k='value' AND shape='exact') OR (k='lower' AND shape IN ('interval','gt','ge'))
   OR (k='upper' AND shape IN ('interval','lt','le')) THEN
   IF jsonb_typeof(q->k) IS DISTINCT FROM 'number' THEN RETURN false; END IF;
  ELSIF q->k IS DISTINCT FROM 'null'::jsonb THEN RETURN false; END IF;
 END LOOP;
 IF shape='interval' AND (q->>'lower')::numeric>(q->>'upper')::numeric THEN RETURN false; END IF;
 u:=q->'uncertainty';
 IF u<>'null'::jsonb THEN
  IF NOT public.sclib_materials_closed_object_v1(u,ARRAY['kind','minus','plus','level','raw'])
   OR jsonb_typeof(u->'kind') IS DISTINCT FROM 'string'
   OR u->>'kind' NOT IN ('standard_deviation','standard_error','confidence_interval','resolution','reported_unspecified')
   OR jsonb_typeof(u->'minus') IS DISTINCT FROM 'number' OR jsonb_typeof(u->'plus') IS DISTINCT FROM 'number'
   OR NOT public.sclib_materials_text_v1(u->'raw',1000,false) THEN RETURN false; END IF;
  IF (u->>'minus')::numeric<0 OR (u->>'plus')::numeric<0 THEN RETURN false; END IF;
  IF u->'level'<>'null'::jsonb THEN
   IF jsonb_typeof(u->'level') IS DISTINCT FROM 'number' THEN RETURN false; END IF;
   IF (u->>'level')::numeric<=0 OR (u->>'level')::numeric>=1 THEN RETURN false; END IF;
  END IF;
 END IF;
 RETURN true;
END $$""", r"""
CREATE FUNCTION public.sclib_materials_composition_v1(j jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE v jsonb; seen text[]:='{}'; key text; BEGIN
 IF NOT public.sclib_materials_closed_object_v1(j,ARRAY['variables','isotopes'])
  OR jsonb_typeof(j->'variables') IS DISTINCT FROM 'array' OR jsonb_typeof(j->'isotopes') IS DISTINCT FROM 'array'
  THEN RETURN false; END IF;
 IF jsonb_array_length(j->'variables')>32 OR jsonb_array_length(j->'isotopes')>32 THEN RETURN false; END IF;
 FOR v IN SELECT value FROM jsonb_array_elements(j->'variables') LOOP
  IF NOT public.sclib_materials_closed_object_v1(v,ARRAY['symbol','site','basis','amount'])
   OR NOT public.sclib_materials_text_v1(v->'symbol',80,false)
   OR NOT public.sclib_materials_text_v1(v->'site',200,true)
   OR jsonb_typeof(v->'basis') IS DISTINCT FROM 'string'
   OR v->>'basis' NOT IN ('nominal','measured','refined','calculation_input','unresolved')
   OR NOT public.sclib_materials_quantity_v1(v->'amount') THEN RETURN false; END IF;
  key:=jsonb_build_array(v->'symbol',v->'site')::text;
  IF key=ANY(seen) THEN RETURN false; END IF; seen:=array_append(seen,key);
 END LOOP;
 seen:='{}';
 FOR v IN SELECT value FROM jsonb_array_elements(j->'isotopes') LOOP
  IF NOT public.sclib_materials_closed_object_v1(v,ARRAY['element','mass_number','fraction'])
   OR jsonb_typeof(v->'element') IS DISTINCT FROM 'string' OR v->>'element' !~ '^[A-Z][a-z]?$'
   OR jsonb_typeof(v->'mass_number') IS DISTINCT FROM 'number' OR v->>'mass_number' !~ '^[1-9][0-9]{0,2}$'
   OR NOT public.sclib_materials_quantity_v1(v->'fraction') THEN RETURN false; END IF;
  key:=jsonb_build_array(v->'element',v->'mass_number')::text;
  IF key=ANY(seen) THEN RETURN false; END IF; seen:=array_append(seen,key);
  IF v->'fraction'->>'status'='reported' THEN
   IF v->'fraction'->>'unit' NOT IN ('1','%') THEN RETURN false; END IF;
   IF EXISTS(SELECT 1 FROM jsonb_each(v->'fraction') q WHERE q.key IN ('value','lower','upper')
    AND q.value<>'null'::jsonb AND ((q.value::text)::numeric<0 OR (q.value::text)::numeric>
     CASE WHEN v->'fraction'->>'unit'='%' THEN 100 ELSE 1 END)) THEN RETURN false; END IF;
  END IF;
 END LOOP;
 RETURN true;
END $$""", r"""
CREATE FUNCTION public.sclib_materials_parameters_v1(j jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE p jsonb; BEGIN
 IF jsonb_typeof(j) IS DISTINCT FROM 'array' THEN RETURN false; END IF;
 IF jsonb_array_length(j)>32 THEN RETURN false; END IF;
 FOR p IN SELECT value FROM jsonb_array_elements(j) LOOP
  IF NOT public.sclib_materials_closed_object_v1(p,ARRAY['kind','name_raw','quantity'])
   OR jsonb_typeof(p->'kind') IS DISTINCT FROM 'string'
   OR p->>'kind' NOT IN ('frequency','magnetic_flux_density','magnetic_field_strength','coulomb_pseudopotential')
   OR NOT public.sclib_materials_text_v1(p->'name_raw',300,false)
   OR NOT public.sclib_materials_quantity_v1(p->'quantity') THEN RETURN false; END IF;
  IF p->'quantity'->>'status'='reported' AND NOT (
    (p->>'kind'='frequency' AND p->'quantity'->>'unit' IN ('Hz','kHz','MHz','GHz','THz'))
    OR (p->>'kind'='magnetic_flux_density' AND p->'quantity'->>'unit' IN ('T','mT','uT','µT','μT','G'))
    OR (p->>'kind'='magnetic_field_strength' AND p->'quantity'->>'unit' IN ('A/m','kA/m','Oe'))
    OR (p->>'kind'='coulomb_pseudopotential' AND p->'quantity'->>'unit'='1')) THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
END $$""", r"""
CREATE FUNCTION public.sclib_materials_context_shape_v1(j jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE k text; v jsonb; seen text[]; pattern text:='^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'; BEGIN
 IF NOT public.sclib_materials_closed_object_v1(j,ARRAY['version','composition_ids','protocol_id','relation_ids'])
  OR j->>'version' IS DISTINCT FROM 'materials-context/1' THEN RETURN false; END IF;
 FOREACH k IN ARRAY ARRAY['composition_ids','relation_ids'] LOOP
  IF jsonb_typeof(j->k) IS DISTINCT FROM 'array' THEN RETURN false; END IF;
  IF jsonb_array_length(j->k)>32 THEN RETURN false; END IF;
  seen:='{}';
  FOR v IN SELECT value FROM jsonb_array_elements(j->k) LOOP
   IF jsonb_typeof(v) IS DISTINCT FROM 'string' OR v#>>'{}' !~ pattern OR (v#>>'{}')=ANY(seen) THEN RETURN false; END IF;
   seen:=array_append(seen,v#>>'{}');
  END LOOP;
 END LOOP;
 IF j->'protocol_id'<>'null'::jsonb AND (jsonb_typeof(j->'protocol_id') IS DISTINCT FROM 'string'
  OR j->>'protocol_id' !~ pattern) THEN RETURN false; END IF;
 RETURN j->'protocol_id'<>'null'::jsonb OR jsonb_array_length(j->'composition_ids')+jsonb_array_length(j->'relation_ids')>0;
END $$""", r"""
CREATE FUNCTION public.sclib_materials_context_immutable_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 RAISE EXCEPTION 'materials_context_history_is_append_only' USING ERRCODE='55000';
END $$""", r"""
CREATE FUNCTION public.sclib_materials_context_insert_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE previous jsonb; row jsonb:=to_jsonb(NEW); cyclic boolean; BEGIN
 PERFORM public.sclib_research_integrity_lock_v1();
 IF octet_length(row::text)>65536 THEN RAISE EXCEPTION 'materials_context_row_limit' USING ERRCODE='54000'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.evidence_artifacts WHERE id=NEW.source_artifact_id AND kind='literature_locator') THEN
  RAISE EXCEPTION 'materials_context_literature_source_required' USING ERRCODE='23514'; END IF;
 IF NEW.supersedes_id IS NOT NULL THEN
  EXECUTE format('SELECT to_jsonb(t) FROM public.%I t WHERE id=$1',TG_TABLE_NAME) INTO previous USING NEW.supersedes_id;
  IF previous IS NULL OR NEW.revision IS DISTINCT FROM (previous->>'revision')::integer+1
   OR (TG_TABLE_NAME='sample_compositions' AND row->'sample_id' IS DISTINCT FROM previous->'sample_id')
   OR (TG_TABLE_NAME='research_protocols' AND row->'work_id' IS DISTINCT FROM previous->'work_id')
   OR (TG_TABLE_NAME='sample_relations' AND (row->'from_sample_id' IS DISTINCT FROM previous->'from_sample_id'
     OR row->'to_sample_id' IS DISTINCT FROM previous->'to_sample_id' OR row->'relation_kind' IS DISTINCT FROM previous->'relation_kind')) THEN
   RAISE EXCEPTION 'materials_context_revision_owner_mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='sample_compositions' THEN
  IF NEW.composition_schema_version<>'materials-composition/1'
   OR NEW.composition_basis NOT IN ('nominal','measured','refined','calculation_input','unresolved')
   OR NOT public.sclib_materials_text_v1(to_jsonb(NEW.formula_raw),1200,false)
   OR public.sclib_materials_composition_v1(NEW.composition_payload) IS DISTINCT FROM true THEN
   RAISE EXCEPTION 'materials_composition_contract' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='research_protocols' THEN
  IF NEW.protocol_schema_version<>'materials-protocol/1'
   OR NEW.method_class NOT IN ('resistivity','magnetization','specific_heat','tunneling','muon_spin','calculation','other','unspecified')
   OR NOT public.sclib_materials_text_v1(COALESCE(to_jsonb(NEW.method_raw),'null'::jsonb),2000,NEW.method_class='unspecified')
   OR NOT public.sclib_materials_text_v1(COALESCE(to_jsonb(NEW.observable),'null'::jsonb),500,true)
   OR NOT public.sclib_materials_text_v1(COALESCE(to_jsonb(NEW.details_raw),'null'::jsonb),8000,true)
   OR public.sclib_materials_parameters_v1(NEW.parameters) IS DISTINCT FROM true THEN
   RAISE EXCEPTION 'materials_protocol_contract' USING ERRCODE='23514'; END IF;
 ELSE
  IF NEW.relation_schema_version<>'materials-sample-relation/1' OR NEW.relation_kind<>'component_of'
   OR NOT public.sclib_materials_text_v1(to_jsonb(NEW.relation_raw),2000,false) THEN
   RAISE EXCEPTION 'materials_sample_relation_contract' USING ERRCODE='23514'; END IF;
  WITH RECURSIVE reachable(id) AS (SELECT NEW.to_sample_id UNION
   SELECT e.to_sample_id FROM public.sample_relations e JOIN reachable r ON e.from_sample_id=r.id)
   SELECT EXISTS(SELECT 1 FROM reachable WHERE id=NEW.from_sample_id) INTO cyclic;
  IF cyclic THEN RAISE EXCEPTION 'materials_component_cycle' USING ERRCODE='23514'; END IF;
 END IF;
 -- Hash the exact stored scientific row, independent of caller serialization.
 NEW.record_sha256:=public.sclib_scientific_adjudication_record_hash_v1(row);
 RETURN NEW;
END $$""", r"""
CREATE FUNCTION public.sclib_materials_context_event_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE j jsonb:=NEW.context->'materials_context'; sid uuid; wid uuid; linked uuid[]; connected uuid[]; BEGIN
 IF TG_OP='DELETE' THEN
  IF OLD.context ? 'materials_context' THEN
   RAISE EXCEPTION 'materials_context_requires_new_event_revision' USING ERRCODE='55000'; END IF;
  RETURN OLD;
 END IF;
 IF TG_OP='UPDATE' AND (OLD.context ? 'materials_context' OR NEW.context ? 'materials_context')
  AND (OLD.context->'materials_context' IS DISTINCT FROM j OR OLD.state_id IS DISTINCT FROM NEW.state_id
   OR OLD.material_id IS DISTINCT FROM NEW.material_id) THEN
  RAISE EXCEPTION 'materials_context_requires_new_event_revision' USING ERRCODE='55000'; END IF;
 IF NOT NEW.context ? 'materials_context' THEN RETURN NEW; END IF;
 PERFORM public.sclib_research_integrity_lock_v1();
 IF public.sclib_materials_context_shape_v1(j) IS DISTINCT FROM true THEN
  RAISE EXCEPTION 'materials_event_context_contract' USING ERRCODE='23514'; END IF;
 SELECT s.sample_id,x.work_id INTO sid,wid FROM public.material_states s
  JOIN public.research_samples x ON x.id=s.sample_id WHERE s.id=NEW.state_id AND s.material_id=NEW.material_id;
 IF sid IS NULL THEN RAISE EXCEPTION 'materials_event_sample_required' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements_text(j->'composition_ids') v
  WHERE NOT EXISTS(SELECT 1 FROM public.sample_compositions c WHERE c.id=v::uuid AND c.sample_id=sid)) THEN
  RAISE EXCEPTION 'materials_context_composition_owner' USING ERRCODE='23514'; END IF;
 IF j->'protocol_id'<>'null'::jsonb AND NOT EXISTS(SELECT 1 FROM public.research_protocols p
  WHERE p.id=(j->>'protocol_id')::uuid AND p.work_id=wid) THEN
  RAISE EXCEPTION 'materials_context_protocol_work' USING ERRCODE='23514'; END IF;
 SELECT COALESCE(array_agg(v::uuid),'{}'::uuid[]) INTO linked FROM jsonb_array_elements_text(j->'relation_ids') v;
 IF EXISTS(SELECT 1 FROM unnest(linked) k WHERE NOT EXISTS(SELECT 1 FROM public.sample_relations r WHERE r.id=k)) THEN
  RAISE EXCEPTION 'materials_context_relation_missing' USING ERRCODE='23514'; END IF;
 WITH RECURSIVE reach(id) AS (SELECT sid UNION SELECT CASE WHEN r.from_sample_id=e.id THEN r.to_sample_id ELSE r.from_sample_id END
  FROM public.sample_relations r JOIN reach e ON e.id IN (r.from_sample_id,r.to_sample_id) WHERE r.id=ANY(linked))
  SELECT array_agg(id) INTO connected FROM reach;
 IF EXISTS(SELECT 1 FROM public.sample_relations r WHERE r.id=ANY(linked)
  AND NOT (r.from_sample_id=ANY(connected) AND r.to_sample_id=ANY(connected))) THEN
  RAISE EXCEPTION 'materials_context_unrelated_component' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$""", r"""
CREATE FUNCTION public.sclib_materials_context_owner_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE held boolean; BEGIN
 PERFORM public.sclib_research_integrity_lock_v1();
 IF TG_TABLE_NAME='research_samples' THEN
  SELECT EXISTS(SELECT 1 FROM public.sample_compositions WHERE sample_id=OLD.id)
   OR EXISTS(SELECT 1 FROM public.sample_relations WHERE from_sample_id=OLD.id OR to_sample_id=OLD.id)
   OR EXISTS(SELECT 1 FROM public.material_states s JOIN public.research_events e ON e.state_id=s.id
    WHERE s.sample_id=OLD.id AND e.context ? 'materials_context') INTO held;
 ELSE
  SELECT EXISTS(SELECT 1 FROM public.research_events WHERE state_id=OLD.id AND context ? 'materials_context') INTO held;
 END IF;
 IF held AND (TG_OP='DELETE' OR to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD)) THEN
  RAISE EXCEPTION 'materials_context_owner_revision_required' USING ERRCODE='55000'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END $$""", r"""
CREATE FUNCTION public.sclib_materials_context_legacy_gate_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 IF TG_TABLE_NAME='research_release_pins' THEN
  IF NEW.table_name='research_events' AND NEW.row_data->'context' ? 'materials_context' THEN
   RAISE EXCEPTION 'materials_context_release_contract_required' USING ERRCODE='23514'; END IF;
 ELSE
  IF EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.basis_json::jsonb->'rows') r
   WHERE r->>'table'='research_events' AND r->'snapshot'->'context' ? 'materials_context') THEN
   RAISE EXCEPTION 'materials_context_review_contract_required' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$"""]


def guard_statements():
    statements = functions()
    for name in TABLE_ORDER:
        statements += [f"CREATE TRIGGER mc96_insert BEFORE INSERT ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_materials_context_insert_v1()",
            f"CREATE TRIGGER mc96_immutable BEFORE UPDATE OR DELETE ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_materials_context_immutable_v1()",
            f"CREATE TRIGGER mc96_truncate BEFORE TRUNCATE ON public.{name} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_materials_context_immutable_v1()"]
    statements += ["CREATE TRIGGER mc96_event BEFORE INSERT OR UPDATE OR DELETE ON public.research_events FOR EACH ROW EXECUTE FUNCTION public.sclib_materials_context_event_v1()"]
    for name in ("research_samples", "material_states"):
        statements.append(f"CREATE TRIGGER mc96_owner BEFORE UPDATE OR DELETE ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_materials_context_owner_v1()")
    for name in ("research_release_pins", "scientific_result_subjects"):
        statements.append(f"CREATE TRIGGER aa_mc96_legacy BEFORE INSERT ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_materials_context_legacy_gate_v1()")
    return statements


def preflight():
    return ["LOCK TABLE public.research_events IN ACCESS EXCLUSIVE MODE", """DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.research_events WHERE context ? 'materials_context') THEN
  RAISE EXCEPTION 'materials_context_reserved_member_collision' USING ERRCODE='23514'; END IF;
END $$"""]


def downgrade_statements():
    return ["LOCK TABLE public.research_events,public.sample_compositions,public.research_protocols,public.sample_relations IN ACCESS EXCLUSIVE MODE", """DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.sample_compositions) OR EXISTS(SELECT 1 FROM public.research_protocols)
  OR EXISTS(SELECT 1 FROM public.sample_relations) OR EXISTS(SELECT 1 FROM public.research_events WHERE context ? 'materials_context') THEN
  RAISE EXCEPTION 'materials_context_retained_history_refuses_downgrade' USING ERRCODE='23514'; END IF;
END $$""", "DROP TRIGGER mc96_event ON public.research_events",
        *[f"DROP TRIGGER mc96_owner ON public.{name}" for name in ("research_samples", "material_states")],
        *[f"DROP TRIGGER aa_mc96_legacy ON public.{name}" for name in ("research_release_pins", "scientific_result_subjects")],
        *[f"DROP TABLE public.{name}" for name in reversed(TABLE_ORDER)],
        *[f"DROP FUNCTION public.{name}({args})" for name, args in reversed(FUNCTION_SIGNATURES)]]


def register(metadata):
    register_tables(metadata)
    for sql in guard_statements():
        sa.event.listen(metadata, "after_create", sa.DDL(sql.replace("%", "%%")).execute_if(dialect="postgresql"))
    for name, args in reversed(FUNCTION_SIGNATURES):
        sa.event.listen(metadata, "after_drop", sa.DDL(f"DROP FUNCTION IF EXISTS public.{name}({args})").execute_if(dialect="postgresql"))
