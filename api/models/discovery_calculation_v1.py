"""0090 immutable private native files; SQL verifies custody, not PWSCF physics.

Only API-derived readings are served, reconstructed from these original bytes.
The SQL receipt stores a reading digest, never caller-supplied scientific values.
"""
import re

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

TABLE_ORDER = ("discovery_calculation_returns_v1", "discovery_calculation_files_v1")
FUNCTION_SIGNATURES = (("sclib_discovery_calculation_design_v1", "jsonb,uuid,uuid,bigint"),
    ("sclib_discovery_calculation_insert_v1", ""), ("sclib_discovery_calculation_file_v1", ""),
    ("sclib_discovery_calculation_complete_v1", ""), ("sclib_discovery_calculation_immutable_v1", ""))


def guard_statements():
    definitions = r"""
CREATE FUNCTION public.sclib_discovery_calculation_design_v1(p jsonb,u uuid,g uuid,s bigint) RETURNS void
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE r public.discovery_design_revisions_v1%ROWTYPE; head_id uuid; c text; BEGIN
 PERFORM public.sclib_discovery_design_lock_v1();
 IF s NOT BETWEEN 0 AND 9007199254740991 OR public.sclib_research_distribution_role_v1(u,g,'curator') IS DISTINCT FROM true
  OR NOT EXISTS(SELECT 1 FROM public.users WHERE id=u AND session_version=s) THEN
  RAISE EXCEPTION 'calculation_live_actor_required' USING ERRCODE='42501'; END IF;
 IF NOT public.sclib_material_field_closed_v1(p,ARRAY['design_id','revision_id','record_sha256','next_action_sha256']) THEN
  RAISE EXCEPTION 'calculation_design_pin_required' USING ERRCODE='23514'; END IF;
 SELECT * INTO r FROM public.discovery_design_revisions_v1 WHERE id=(p->>'revision_id')::uuid;
 SELECT id INTO head_id FROM public.discovery_design_revisions_v1 WHERE design_id=r.design_id ORDER BY revision DESC LIMIT 1;
 IF r.id IS NULL OR r.id IS DISTINCT FROM head_id OR r.actor_user_id IS DISTINCT FROM u OR r.operation='withdraw'
  OR r.design->'next_action'->>'kind' IS DISTINCT FROM 'calculation'
  OR p IS DISTINCT FROM jsonb_build_object('design_id',r.design_id::text,'revision_id',r.id::text,'record_sha256',r.record_sha256,
   'next_action_sha256',public.sclib_source_property_hash_v1(public.sclib_scientific_import_canonical_v1(r.design->'next_action'))) THEN
  RAISE EXCEPTION 'calculation_current_design_required' USING ERRCODE='23514'; END IF;
 IF r.baseline->>'kind'='unanchored' THEN
  c:=public.sclib_discovery_design_context_v1(r.baseline);
  IF r.context_json IS DISTINCT FROM c OR r.context_sha256 IS DISTINCT FROM public.sclib_source_property_hash_v1(c) THEN
   RAISE EXCEPTION 'calculation_design_context_changed' USING ERRCODE='23514'; END IF;
 ELSE
  PERFORM public.sclib_discovery_condition_batch_parent_v1(jsonb_build_object('design_id',r.design_id::text,
   'revision_id',r.id::text,'revision',r.revision,'record_sha256',r.record_sha256),u,g,s);
 END IF;
END $$;
CREATE FUNCTION public.sclib_discovery_calculation_insert_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE q jsonb; f jsonb; v jsonb; preview jsonb; total bigint:=0; i integer:=0; prior text:=''; key text; BEGIN
 q:=NEW.request_json::jsonb;
 IF NOT public.sclib_material_field_closed_v1(q,ARRAY['version','request_key','design','files','findings','decision','reason','unknowns','association'])
  OR q->>'version' IS DISTINCT FROM 'discovery-calculation-operation/1.0.0'
  OR q->>'request_key' IS DISTINCT FROM NEW.request_key OR jsonb_typeof(q->'request_key') IS DISTINCT FROM 'string'
  OR q->>'association' IS DISTINCT FROM 'researcher_linked_unverified'
  OR NEW.request_json IS DISTINCT FROM public.sclib_scientific_import_canonical_v1(q)
  OR NEW.request_sha256 IS DISTINCT FROM public.sclib_source_property_hash_v1(NEW.request_json)
  OR q->'design' IS DISTINCT FROM NEW.design_ref OR NEW.design_revision_id::text IS DISTINCT FROM q->'design'->>'revision_id'
  OR q->'files' IS DISTINCT FROM NEW.files OR jsonb_typeof(q->'files') IS DISTINCT FROM 'array'
  OR NOT public.sclib_discovery_design_text_v1(q->'findings',4000)
  OR NOT public.sclib_discovery_design_text_v1(q->'reason',2000)
  OR jsonb_typeof(q->'decision') IS DISTINCT FROM 'string' OR q->>'decision' NOT IN ('continue','stop','redirect')
  OR jsonb_typeof(q->'unknowns') IS DISTINCT FROM 'array' THEN
  RAISE EXCEPTION 'calculation_closed_request_required' USING ERRCODE='23514'; END IF;
 IF jsonb_array_length(q->'unknowns')>16 THEN RAISE EXCEPTION 'calculation_unknowns_bound' USING ERRCODE='23514'; END IF;
 FOR v IN SELECT value FROM jsonb_array_elements(q->'unknowns') LOOP
  IF NOT public.sclib_discovery_design_text_v1(v,1000) THEN RAISE EXCEPTION 'calculation_unknown_text' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF (SELECT count(DISTINCT value) FROM jsonb_array_elements(q->'unknowns'))<>jsonb_array_length(q->'unknowns') THEN
  RAISE EXCEPTION 'calculation_duplicate_unknown' USING ERRCODE='23514'; END IF;
 IF jsonb_array_length(NEW.files) NOT BETWEEN 4 AND 11 THEN RAISE EXCEPTION 'calculation_file_count' USING ERRCODE='23514'; END IF;
 FOR f IN SELECT value FROM jsonb_array_elements(NEW.files) LOOP
  IF NOT public.sclib_material_field_closed_v1(f,ARRAY['role','name','sha256','size_bytes'])
   OR jsonb_typeof(f->'role') IS DISTINCT FROM 'string' OR f->>'role' NOT IN ('input','xml','stdout','upf')
   OR jsonb_typeof(f->'name') IS DISTINCT FROM 'string' OR f->>'name' !~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$'
   OR strpos(f->>'name','..')>0 OR jsonb_typeof(f->'sha256') IS DISTINCT FROM 'string' OR f->>'sha256' !~ '^[a-f0-9]{64}$'
   OR jsonb_typeof(f->'size_bytes') IS DISTINCT FROM 'number' OR f->>'size_bytes' !~ '^[1-9][0-9]{0,6}$' THEN
   RAISE EXCEPTION 'calculation_file_metadata' USING ERRCODE='23514'; END IF;
  IF (f->>'size_bytes')::bigint > (CASE WHEN f->>'role'='input' THEN 1048576 ELSE 8388608 END) THEN
   RAISE EXCEPTION 'calculation_file_size' USING ERRCODE='23514'; END IF;
  key:=(f->>'role')||':'||(f->>'name');
  IF key COLLATE "C" <= prior COLLATE "C" THEN RAISE EXCEPTION 'calculation_file_order' USING ERRCODE='23514'; END IF;
  prior:=key; total:=total+(f->>'size_bytes')::bigint; i:=i+1;
 END LOOP;
 IF total>84934656 OR EXISTS(SELECT 1 FROM unnest(ARRAY['input','xml','stdout']) roles(required_role)
  WHERE (SELECT count(*) FROM jsonb_array_elements(NEW.files) item WHERE item->>'role'=roles.required_role)<>1) THEN
  RAISE EXCEPTION 'calculation_required_inventory' USING ERRCODE='23514'; END IF;
 PERFORM public.sclib_discovery_calculation_design_v1(NEW.design_ref,NEW.actor_user_id,NEW.actor_grant_id,NEW.actor_session_version);
 preview:=jsonb_build_object('version','discovery-calculation-return/1.0.0','receipt_id',NEW.id::text,
  'actor',jsonb_build_object('actor_user_id',NEW.actor_user_id::text,'actor_grant_id',NEW.actor_grant_id::text,
   'actor_session_version',NEW.actor_session_version),'request_sha256',NEW.request_sha256,
  'report_sha256',NEW.report_sha256,'report_version',NEW.report_version,'design',NEW.design_ref);
 IF NEW.preview_json IS DISTINCT FROM public.sclib_scientific_import_canonical_v1(preview)
  OR NEW.preview_sha256 IS DISTINCT FROM public.sclib_source_property_hash_v1(NEW.preview_json)
  OR NEW.record_sha256 IS DISTINCT FROM public.sclib_source_property_hash_v1(public.sclib_scientific_import_canonical_v1(
    to_jsonb(NEW)-ARRAY['created_at','record_sha256'])) THEN
  RAISE EXCEPTION 'calculation_exact_receipt_required' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION public.sclib_discovery_calculation_file_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE r public.discovery_calculation_returns_v1%ROWTYPE; f jsonb; BEGIN
 SELECT * INTO r FROM public.discovery_calculation_returns_v1 WHERE id=NEW.return_id;
 f:=r.files->NEW.ordinal;
 IF r.id IS NULL OR f IS NULL OR NEW.ordinal<0 OR NEW.ordinal>=jsonb_array_length(r.files)
  OR octet_length(NEW.original_bytes) IS DISTINCT FROM (f->>'size_bytes')::integer
  OR encode(sha256(NEW.original_bytes),'hex') IS DISTINCT FROM f->>'sha256' THEN
  RAISE EXCEPTION 'calculation_exact_original_bytes_required' USING ERRCODE='23514'; END IF;
 PERFORM public.sclib_discovery_calculation_design_v1(r.design_ref,r.actor_user_id,r.actor_grant_id,r.actor_session_version);
 RETURN NEW;
END $$;
CREATE FUNCTION public.sclib_discovery_calculation_complete_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE rid uuid; expected integer; actual integer; BEGIN
 rid:=CASE WHEN TG_TABLE_NAME='discovery_calculation_returns_v1' THEN (to_jsonb(NEW)->>'id')::uuid ELSE (to_jsonb(NEW)->>'return_id')::uuid END;
 SELECT jsonb_array_length(files) INTO expected FROM public.discovery_calculation_returns_v1 WHERE id=rid;
 SELECT count(*) INTO actual FROM public.discovery_calculation_files_v1 WHERE return_id=rid;
 IF expected IS NULL OR actual<>expected THEN RAISE EXCEPTION 'calculation_incomplete_original_inventory' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION public.sclib_discovery_calculation_immutable_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 RAISE EXCEPTION 'Private calculation history is append-only' USING ERRCODE='55000'; END $$;
"""
    statements = re.split(r";\n(?=CREATE FUNCTION)", definitions.strip())
    for name in TABLE_ORDER:
        function = "insert" if name == TABLE_ORDER[0] else "file"
        statements.extend([
            f"CREATE TRIGGER {name}_insert BEFORE INSERT ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_discovery_calculation_{function}_v1()",
            f"CREATE CONSTRAINT TRIGGER {name}_complete AFTER INSERT ON public.{name} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.sclib_discovery_calculation_complete_v1()",
            f"CREATE TRIGGER {name}_immutable BEFORE UPDATE OR DELETE ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_discovery_calculation_immutable_v1()",
            f"CREATE TRIGGER {name}_truncate BEFORE TRUNCATE ON public.{name} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_discovery_calculation_immutable_v1()"])
    return statements


def register(metadata):
    def uid(name, target=None):
        return sa.Column(name, UUID(as_uuid=True), *([sa.ForeignKey(target, ondelete="RESTRICT")] if target else []), nullable=False)

    returns = sa.Table(TABLE_ORDER[0], metadata,
        uid("id"), uid("actor_user_id", "users.id"), uid("actor_grant_id", "research_role_grants.id"),
        sa.Column("actor_session_version", sa.BigInteger, nullable=False),
        uid("design_revision_id", "discovery_design_revisions_v1.id"), sa.Column("design_ref", JSONB, nullable=False),
        sa.Column("request_key", sa.String(160), nullable=False), sa.Column("request_json", sa.Text, nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False), sa.Column("files", JSONB, nullable=False),
        sa.Column("report_version", sa.String(64), nullable=False), sa.Column("report_sha256", sa.String(64), nullable=False),
        sa.Column("preview_json", sa.Text, nullable=False), sa.Column("preview_sha256", sa.String(64), nullable=False),
        sa.Column("record_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.clock_timestamp()),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("actor_user_id", "request_key", name="uq_dc90_request"),
        sa.CheckConstraint("actor_session_version BETWEEN 0 AND 9007199254740991 AND isfinite(created_at)", name="ck_dc90_actor"),
        sa.CheckConstraint("request_key ~ '^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$' AND octet_length(request_json) BETWEEN 2 AND 32768 AND octet_length(preview_json) BETWEEN 2 AND 4096", name="ck_dc90_bounds"),
        sa.CheckConstraint("report_version='qe-pw-native-preflight/1.0.0'", name="ck_dc90_parser"),
        *[sa.CheckConstraint(f"{key} ~ '^[a-f0-9]{{64}}$'", name=f"ck_dc90_{key}")
          for key in ("request_sha256", "report_sha256", "preview_sha256", "record_sha256")],
        sa.Index("idx_dc90_owner", "actor_user_id", "design_revision_id", "created_at", "id"))
    files = sa.Table(TABLE_ORDER[1], metadata, uid("return_id", TABLE_ORDER[0] + ".id"),
        sa.Column("ordinal", sa.SmallInteger, nullable=False), sa.Column("original_bytes", sa.LargeBinary, nullable=False),
        sa.PrimaryKeyConstraint("return_id", "ordinal"),
        sa.CheckConstraint("ordinal BETWEEN 0 AND 10 AND octet_length(original_bytes) BETWEEN 1 AND 8388608", name="ck_df90_bounds"))
    returns.add_is_dependent_on(metadata.tables["discovery_feedback_follow_ups_v1"])
    for statement in guard_statements():
        sa.event.listen(files, "after_create", sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"))
    return {TABLE_ORDER[0]: returns, TABLE_ORDER[1]: files}
