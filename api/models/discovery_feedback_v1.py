"""0089 independent owner-private archival returns and saved follow-up links.

SQL re-admits live owners, exact heads, source closure, field projection and
role/session pins. Existing frozen parser-policy admission remains additionally
enforced by HTTP; conservative SQL governance is not claimed as parser parity.
"""
import re

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

TABLE_ORDER = ("discovery_evidence_returns_v1", "discovery_feedback_follow_ups_v1")
LOCK_FUNCTION = "sclib_discovery_feedback_lock_v1"
FUNCTION_SIGNATURES = ((LOCK_FUNCTION, ""),
    ("sclib_discovery_feedback_scalar_v1", "jsonb,integer"),
    ("sclib_discovery_feedback_projection_v1", "text"),
    ("sclib_discovery_feedback_source_v1", "jsonb"),
    ("sclib_discovery_feedback_design_v1", "jsonb,uuid,uuid,bigint"),
    ("sclib_discovery_feedback_insert_v1", ""),
    ("sclib_discovery_feedback_immutable_v1", ""))


def guard_statements():
    definitions = r"""
CREATE FUNCTION public.sclib_discovery_feedback_lock_v1() RETURNS void
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 PERFORM public.sclib_discovery_condition_batch_lock_v1();
 IF NOT pg_try_advisory_xact_lock(890017026) THEN
  RAISE EXCEPTION 'feedback_busy_retry' USING ERRCODE='55P03'; END IF;
END $$;
CREATE FUNCTION public.sclib_discovery_feedback_scalar_v1(v jsonb,n integer) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE t text; f double precision; BEGIN
 IF v IS NULL OR v='null'::jsonb THEN RETURN 'null'::jsonb; END IF;
 IF jsonb_typeof(v)='string' THEN
  t:=v#>>'{}';
  IF length(t)<=n AND t !~ '[[:cntrl:]]' THEN RETURN v; END IF;
 ELSIF jsonb_typeof(v)='number' AND octet_length(v::text)<=80 THEN
  f:=(v#>>'{}')::double precision;
  IF f NOT IN ('Infinity'::double precision,'-Infinity'::double precision,'NaN'::double precision)
   AND NOT (f=0 AND v<>to_jsonb(0)) THEN RETURN v; END IF;
 END IF;
 RETURN 'null'::jsonb;
 EXCEPTION WHEN numeric_value_out_of_range OR invalid_text_representation THEN RETURN 'null'::jsonb;
END $$;
CREATE FUNCTION public.sclib_discovery_feedback_projection_v1(c text) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE b jsonb; p jsonb; r jsonb:='{}'::jsonb; fields jsonb:='[]'::jsonb; key text;
 raw jsonb; value jsonb; sv jsonb; sv_out jsonb:='{}'::jsonb; item jsonb; item_out jsonb; subkey text;
 output jsonb; BEGIN
 b:=c::jsonb; p:=b->'base'->'result';
 IF b->>'kind' IS DISTINCT FROM 'retained_result' OR jsonb_typeof(p) IS DISTINCT FROM 'object' THEN
  RAISE EXCEPTION 'feedback_retained_projection_required' USING ERRCODE='23514'; END IF;
 FOR key IN SELECT unnest(ARRAY['id','paper_id','knowledge_origin','evidence_type','tc_kelvin','tc_type','tc_definition',
  'tc_criterion','criterion','measurement','measurement_method','method_statement','pressure_gpa',
  'pressure_status','pressure_kind','pressure_conditions','hc2_tesla','hc2_tesla_unit','hc2_conditions',
  'hc2_direction','field_orientation','magnetic_field_orientation']) LOOP
  raw:=p->key;
  value:=public.sclib_discovery_feedback_scalar_v1(raw,CASE WHEN key='hc2_tesla_unit' THEN 40 ELSE 2000 END);
  r:=r||jsonb_build_object(key,value);
  IF raw IS NOT NULL AND raw<>'null'::jsonb AND value='null'::jsonb THEN fields:=fields||jsonb_build_array(key); END IF;
 END LOOP;
 sv:=p->'scientific_values';
 IF sv IS NOT NULL AND sv<>'null'::jsonb THEN
  IF jsonb_typeof(sv) IS DISTINCT FROM 'object' THEN
   fields:=fields||jsonb_build_array('scientific_values');
   -- An invalid proposal container must not expose stale scalar fallbacks.
   sv_out:=jsonb_build_object('hc2_tesla',jsonb_build_object('raw_value',NULL,'input_unit',NULL,'raw_unit',NULL,
    'normalized_value',NULL,'normalized_unit',NULL,'status',NULL),'tc_kelvin',jsonb_build_object(
    'raw_value',NULL,'input_unit',NULL,'raw_unit',NULL,'normalized_value',NULL,'normalized_unit',NULL,'status',NULL));
  ELSE
   FOR key IN SELECT unnest(ARRAY['tc_kelvin','hc2_tesla']) LOOP
    IF NOT sv ? key THEN CONTINUE; END IF;
    item:=sv->key; item_out:='{}'::jsonb;
    FOR subkey IN SELECT unnest(ARRAY['raw_value','input_unit','raw_unit','normalized_value','normalized_unit','status']) LOOP
     raw:=CASE WHEN jsonb_typeof(item)='object' THEN item->subkey ELSE 'null'::jsonb END;
     value:=public.sclib_discovery_feedback_scalar_v1(raw,CASE WHEN subkey IN ('input_unit','raw_unit','normalized_unit') THEN 40 ELSE 500 END);
     item_out:=item_out||jsonb_build_object(subkey,value);
     IF raw IS NOT NULL AND raw<>'null'::jsonb AND value='null'::jsonb THEN
      fields:=fields||jsonb_build_array('scientific_values.'||key||'.'||subkey); END IF;
    END LOOP;
    IF jsonb_typeof(item) IS DISTINCT FROM 'object' THEN fields:=fields||jsonb_build_array('scientific_values.'||key); END IF;
    sv_out:=sv_out||jsonb_build_object(key,item_out);
   END LOOP;
  END IF;
 END IF;
 r:=r||jsonb_build_object('scientific_values',CASE WHEN sv_out='{}'::jsonb THEN 'null'::jsonb ELSE sv_out END);
 output:=jsonb_build_object('kind','retained_result','material_id',b->'base'->'material_id',
  'formula',public.sclib_discovery_feedback_scalar_v1(b->'base'->'material'->'formula',500),
  'record_index',b->'base'->'record_index','source_snapshot_sha256',public.sclib_source_property_hash_v1(c),
  'record',r,'withheld_fields',fields,'physical_association','unestablished');
 IF octet_length(public.sclib_scientific_import_canonical_v1(output))>16384 THEN
  RAISE EXCEPTION 'feedback_projection_bound' USING ERRCODE='23514'; END IF;
 RETURN output;
END $$;
CREATE FUNCTION public.sclib_discovery_feedback_source_v1(b jsonb) RETURNS text
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE c text; x jsonb; BEGIN
 IF b->>'kind' IS DISTINCT FROM 'retained_result' THEN
  RAISE EXCEPTION 'feedback_retained_evidence_required' USING ERRCODE='23514'; END IF;
 c:=public.sclib_discovery_design_context_v1(b); x:=c::jsonb;
 IF b->>'expected_context_sha256' IS DISTINCT FROM public.sclib_source_property_hash_v1(c) THEN
  RAISE EXCEPTION 'feedback_evidence_source_pin_changed' USING ERRCODE='23514'; END IF;
 PERFORM public.sclib_discovery_condition_batch_governance_v1(x);
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(x->'sources') item WHERE item->'lifecycle'<>'null'::jsonb
  OR lower(coalesce(item->'row'->>'status',item->'row'->>'publication_status','')) IN ('retracted','withdrawn','corrected','disputed')) THEN
  RAISE EXCEPTION 'feedback_current_source_hold' USING ERRCODE='23514'; END IF;
 RETURN c;
END $$;
CREATE FUNCTION public.sclib_discovery_feedback_design_v1(p jsonb,u uuid,g uuid,s bigint) RETURNS jsonb
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE r public.discovery_design_revisions_v1%ROWTYPE; checked jsonb; expected jsonb; BEGIN
 PERFORM public.sclib_discovery_feedback_lock_v1();
 IF NOT public.sclib_material_field_closed_v1(p,ARRAY['design_id','revision_id','record_sha256','next_action_sha256'])
  OR jsonb_typeof(p->'design_id') IS DISTINCT FROM 'string' OR jsonb_typeof(p->'revision_id') IS DISTINCT FROM 'string'
  OR (p->>'design_id')::uuid::text IS DISTINCT FROM p->>'design_id'
  OR (p->>'revision_id')::uuid::text IS DISTINCT FROM p->>'revision_id'
  OR jsonb_typeof(p->'record_sha256') IS DISTINCT FROM 'string' OR p->>'record_sha256' !~ '^[a-f0-9]{64}$'
  OR jsonb_typeof(p->'next_action_sha256') IS DISTINCT FROM 'string' OR p->>'next_action_sha256' !~ '^[a-f0-9]{64}$' THEN
  RAISE EXCEPTION 'feedback_design_pin_required' USING ERRCODE='23514'; END IF;
 SELECT * INTO r FROM public.discovery_design_revisions_v1 WHERE id=(p->>'revision_id')::uuid;
 IF r.id IS NULL OR r.baseline->>'kind' IS DISTINCT FROM 'retained_result'
  OR r.design->'next_action'->>'kind' IS DISTINCT FROM 'source_review' THEN
  RAISE EXCEPTION 'feedback_retained_source_review_required' USING ERRCODE='23514'; END IF;
 expected:=jsonb_build_object('design_id',r.design_id::text,'revision_id',r.id::text,'record_sha256',r.record_sha256,
  'next_action_sha256',public.sclib_source_property_hash_v1(public.sclib_scientific_import_canonical_v1(r.design->'next_action')));
 IF p IS DISTINCT FROM expected THEN RAISE EXCEPTION 'feedback_design_pin_conflict' USING ERRCODE='23514'; END IF;
 checked:=public.sclib_discovery_condition_batch_parent_v1(jsonb_build_object('design_id',r.design_id::text,
  'revision_id',r.id::text,'revision',r.revision,'record_sha256',r.record_sha256),u,g,s);
 RETURN checked;
END $$;
CREATE FUNCTION public.sclib_discovery_feedback_immutable_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 RAISE EXCEPTION 'Discovery evidence return history is append-only' USING ERRCODE='55000'; END $$;
CREATE FUNCTION public.sclib_discovery_feedback_insert_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE q jsonb; p jsonb; r jsonb; x jsonb; c text; preview jsonb; expected text;
 feedback public.discovery_evidence_returns_v1%ROWTYPE; child public.discovery_design_revisions_v1%ROWTYPE;
 head_id uuid; child_pin jsonb; parent_pin jsonb; BEGIN
 PERFORM public.sclib_discovery_feedback_lock_v1();
 IF NEW.actor_session_version NOT BETWEEN 0 AND 9007199254740991
  OR public.sclib_research_distribution_role_v1(NEW.actor_user_id,NEW.actor_grant_id,'curator') IS DISTINCT FROM true
  OR NOT EXISTS(SELECT 1 FROM public.users WHERE id=NEW.actor_user_id AND session_version=NEW.actor_session_version) THEN
  RAISE EXCEPTION 'feedback_live_actor_required' USING ERRCODE='42501'; END IF;
 IF EXISTS(SELECT 1 FROM public.discovery_evidence_returns_v1 WHERE actor_user_id=NEW.actor_user_id AND request_key=NEW.request_key)
  OR EXISTS(SELECT 1 FROM public.discovery_feedback_follow_ups_v1 WHERE actor_user_id=NEW.actor_user_id AND request_key=NEW.request_key) THEN
  RAISE EXCEPTION 'feedback_request_already_retained' USING ERRCODE='23514'; END IF;
 q:=NEW.request_json::jsonb; p:=q->'payload';
 IF NOT public.sclib_material_field_closed_v1(q,ARRAY['version','request_key','operation','payload'])
  OR q->>'version' IS DISTINCT FROM 'discovery-feedback-operation/1.0.0'
  OR jsonb_typeof(q->'request_key') IS DISTINCT FROM 'string'
  OR q->>'request_key' IS DISTINCT FROM NEW.request_key OR q->>'operation' IS DISTINCT FROM NEW.operation
  OR q->'payload' IS DISTINCT FROM NEW.payload
  OR NEW.request_json IS DISTINCT FROM public.sclib_scientific_import_canonical_v1(q)
  OR NEW.request_sha256 IS DISTINCT FROM public.sclib_source_property_hash_v1(NEW.request_json) THEN
  RAISE EXCEPTION 'feedback_exact_request_required' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='discovery_evidence_returns_v1' THEN
  IF NEW.operation<>'return_evidence'
   OR NOT public.sclib_material_field_closed_v1(p,ARRAY['design','evidence','findings','decision','reason','unknowns'])
   OR NOT public.sclib_discovery_design_text_v1(p->'findings',4000)
   OR NOT public.sclib_discovery_design_text_v1(p->'reason',2000)
   OR jsonb_typeof(p->'decision') IS DISTINCT FROM 'string' OR p->>'decision' NOT IN ('continue','stop','redirect')
   OR jsonb_typeof(p->'unknowns') IS DISTINCT FROM 'array' THEN
   RAISE EXCEPTION 'feedback_return_shape_required' USING ERRCODE='23514'; END IF;
  IF jsonb_array_length(p->'unknowns')>16 THEN RAISE EXCEPTION 'feedback_unknowns_bound' USING ERRCODE='23514'; END IF;
  FOR x IN SELECT value FROM jsonb_array_elements(p->'unknowns') LOOP
   IF NOT public.sclib_discovery_design_text_v1(x,1000) THEN RAISE EXCEPTION 'feedback_unknown_text_required' USING ERRCODE='23514'; END IF;
  END LOOP;
  IF (SELECT count(DISTINCT value) FROM jsonb_array_elements(p->'unknowns'))<>jsonb_array_length(p->'unknowns') THEN
   RAISE EXCEPTION 'feedback_distinct_unknowns_required' USING ERRCODE='23514'; END IF;
  r:=public.sclib_discovery_feedback_design_v1(p->'design',NEW.actor_user_id,NEW.actor_grant_id,NEW.actor_session_version);
  c:=public.sclib_discovery_feedback_source_v1(p->'evidence');
  IF NEW.design_ref IS DISTINCT FROM p->'design' OR NEW.design_revision_id::text IS DISTINCT FROM p->'design'->>'revision_id'
   OR NEW.evidence IS DISTINCT FROM p->'evidence' OR NEW.findings IS DISTINCT FROM p->>'findings'
   OR NEW.decision IS DISTINCT FROM p->>'decision' OR NEW.reason IS DISTINCT FROM p->>'reason'
   OR NEW.unknowns IS DISTINCT FROM p->'unknowns' OR NEW.context_json IS DISTINCT FROM c
   OR NEW.context_sha256 IS DISTINCT FROM public.sclib_source_property_hash_v1(c)
   OR NEW.projection IS DISTINCT FROM public.sclib_discovery_feedback_projection_v1(c)
   OR NEW.projection_sha256 IS DISTINCT FROM public.sclib_source_property_hash_v1(public.sclib_scientific_import_canonical_v1(NEW.projection)) THEN
   RAISE EXCEPTION 'feedback_exact_source_return_required' USING ERRCODE='23514'; END IF;
  preview:=jsonb_build_object('version','discovery-feedback/1.0.0','actor',jsonb_build_object(
   'actor_user_id',NEW.actor_user_id::text,'actor_grant_id',NEW.actor_grant_id::text,'actor_session_version',NEW.actor_session_version),
   'request_sha256',NEW.request_sha256,'receipt_id',NEW.id::text,'feedback_id',NEW.id::text,'design',NEW.design_ref,
   'context_sha256',NEW.context_sha256,'projection_sha256',NEW.projection_sha256);
  expected:=public.sclib_source_property_hash_v1(public.sclib_scientific_import_canonical_v1(to_jsonb(NEW)-ARRAY['created_at','record_sha256','context_json','projection']));
 ELSE
  IF NEW.operation<>'link_follow_up' OR NOT public.sclib_material_field_closed_v1(p,ARRAY['feedback','child'])
   OR NOT public.sclib_material_field_closed_v1(p->'feedback',ARRAY['id','record_sha256'])
   OR NOT public.sclib_material_field_closed_v1(p->'child',ARRAY['design_id','revision_id','record_sha256']) THEN
   RAISE EXCEPTION 'feedback_follow_up_shape_required' USING ERRCODE='23514'; END IF;
  SELECT * INTO feedback FROM public.discovery_evidence_returns_v1 WHERE id=NEW.feedback_id;
  IF feedback.id IS NULL OR feedback.actor_user_id IS DISTINCT FROM NEW.actor_user_id
   OR p->'feedback' IS DISTINCT FROM jsonb_build_object('id',feedback.id::text,'record_sha256',feedback.record_sha256)
   OR NEW.feedback_record_sha256 IS DISTINCT FROM feedback.record_sha256 THEN
   RAISE EXCEPTION 'feedback_exact_owner_return_required' USING ERRCODE='23514'; END IF;
  r:=public.sclib_discovery_feedback_design_v1(feedback.design_ref,NEW.actor_user_id,NEW.actor_grant_id,NEW.actor_session_version);
  c:=public.sclib_discovery_feedback_source_v1(feedback.evidence);
  IF feedback.context_json IS DISTINCT FROM c OR feedback.projection IS DISTINCT FROM public.sclib_discovery_feedback_projection_v1(c) THEN
   RAISE EXCEPTION 'feedback_return_source_changed' USING ERRCODE='23514'; END IF;
  SELECT * INTO child FROM public.discovery_design_revisions_v1 WHERE id=NEW.child_revision_id;
  SELECT id INTO head_id FROM public.discovery_design_revisions_v1 WHERE design_id=child.design_id ORDER BY revision DESC LIMIT 1;
  child_pin:=jsonb_build_object('design_id',child.design_id::text,'revision_id',child.id::text,'record_sha256',child.record_sha256);
  parent_pin:=feedback.design_ref-'next_action_sha256';
  IF child.id IS NULL OR child.actor_user_id IS DISTINCT FROM NEW.actor_user_id OR child.revision<>1 OR child.operation<>'propose'
   OR child.id IS DISTINCT FROM head_id OR child.parent IS DISTINCT FROM parent_pin
   OR p->'child' IS DISTINCT FROM child_pin OR NEW.child IS DISTINCT FROM child_pin THEN
   RAISE EXCEPTION 'feedback_initial_linked_child_required' USING ERRCODE='23514'; END IF;
  r:=public.sclib_discovery_condition_batch_parent_v1(jsonb_build_object('design_id',child.design_id::text,
   'revision_id',child.id::text,'revision',child.revision,'record_sha256',child.record_sha256),
   NEW.actor_user_id,NEW.actor_grant_id,NEW.actor_session_version);
  IF (SELECT count(*) FROM public.discovery_feedback_follow_ups_v1 WHERE feedback_id=feedback.id)>=8 THEN
   RAISE EXCEPTION 'feedback_follow_up_inventory_bound' USING ERRCODE='23514'; END IF;
  preview:=jsonb_build_object('version','discovery-feedback/1.0.0','actor',jsonb_build_object(
   'actor_user_id',NEW.actor_user_id::text,'actor_grant_id',NEW.actor_grant_id::text,'actor_session_version',NEW.actor_session_version),
   'request_sha256',NEW.request_sha256,'receipt_id',NEW.id::text,'feedback_id',feedback.id::text,
   'feedback_record_sha256',feedback.record_sha256,'child',NEW.child);
  expected:=public.sclib_source_property_hash_v1(public.sclib_scientific_import_canonical_v1(to_jsonb(NEW)-ARRAY['created_at','record_sha256']));
 END IF;
 IF NEW.scientific_acceptance OR NEW.ml_training_approved OR NEW.public_release OR NEW.calculation_executed
  OR NEW.experiment_executed OR NEW.physical_association_established OR NEW.canonical_promotions<>0
  OR NEW.preview_json IS DISTINCT FROM public.sclib_scientific_import_canonical_v1(preview)
  OR NEW.preview_sha256 IS DISTINCT FROM public.sclib_source_property_hash_v1(NEW.preview_json)
  OR NEW.record_sha256 IS DISTINCT FROM expected THEN
  RAISE EXCEPTION 'feedback_exact_no_authority_receipt_required' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
"""
    return [*re.split(r";\n(?=CREATE FUNCTION)", definitions.strip()), *[
        f"CREATE TRIGGER df89_{suffix} {event} ON public.{name} {scope} EXECUTE FUNCTION public.{function}()"
        for name in TABLE_ORDER
        for suffix, event, scope, function in (
            ("insert", "BEFORE INSERT", "FOR EACH ROW", "sclib_discovery_feedback_insert_v1"),
            ("immutable", "BEFORE UPDATE OR DELETE", "FOR EACH ROW", "sclib_discovery_feedback_immutable_v1"),
            ("truncate", "BEFORE TRUNCATE", "FOR EACH STATEMENT", "sclib_discovery_feedback_immutable_v1"))]]


def register(metadata):
    def uid(name, target=None):
        return sa.Column(name, UUID(as_uuid=True), *([sa.ForeignKey(target, ondelete="RESTRICT", onupdate="RESTRICT")] if target else []), nullable=False)

    def common(prefix, operation):
        return [uid("id"), uid("actor_user_id", "users.id"), uid("actor_grant_id", "research_role_grants.id"),
            sa.Column("actor_session_version", sa.BigInteger, nullable=False), sa.Column("operation", sa.String(30), nullable=False),
            sa.Column("request_key", sa.String(160), nullable=False), sa.Column("request_json", sa.Text, nullable=False),
            sa.Column("payload", JSONB, nullable=False), sa.Column("request_sha256", sa.String(64), nullable=False),
            sa.Column("preview_json", sa.Text, nullable=False), sa.Column("preview_sha256", sa.String(64), nullable=False),
            *[sa.Column(key, sa.Boolean, nullable=False) for key in ("scientific_acceptance", "ml_training_approved", "public_release",
                "calculation_executed", "experiment_executed", "physical_association_established")],
            sa.Column("canonical_promotions", sa.Integer, nullable=False), sa.Column("record_sha256", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.clock_timestamp()),
            sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("actor_user_id", "request_key", name=f"uq_{prefix}_request"),
            sa.CheckConstraint(f"actor_session_version BETWEEN 0 AND 9007199254740991 AND isfinite(created_at) AND operation='{operation}'", name=f"ck_{prefix}_identity"),
            sa.CheckConstraint("NOT scientific_acceptance AND NOT ml_training_approved AND NOT public_release AND NOT calculation_executed AND NOT experiment_executed AND NOT physical_association_established AND canonical_promotions=0", name=f"ck_{prefix}_no_authority"),
            sa.CheckConstraint("request_key ~ '^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$' AND octet_length(request_json) BETWEEN 2 AND 32768 AND octet_length(preview_json) BETWEEN 2 AND 4096", name=f"ck_{prefix}_bounds"),
            *[sa.CheckConstraint(f"{key} ~ '^[a-f0-9]{{64}}$'", name=f"ck_{prefix}_{key}") for key in ("request_sha256", "preview_sha256", "record_sha256")]]

    result = sa.Table(TABLE_ORDER[0], metadata, *common("dr89", "return_evidence"),
        uid("design_revision_id", "discovery_design_revisions_v1.id"), sa.Column("design_ref", JSONB, nullable=False),
        sa.Column("evidence", JSONB, nullable=False), sa.Column("findings", sa.Text, nullable=False),
        sa.Column("decision", sa.String(20), nullable=False), sa.Column("reason", sa.Text, nullable=False),
        sa.Column("unknowns", JSONB, nullable=False), sa.Column("context_json", sa.Text, nullable=False),
        sa.Column("context_sha256", sa.String(64), nullable=False), sa.Column("projection", JSONB, nullable=False),
        sa.Column("projection_sha256", sa.String(64), nullable=False),
        sa.CheckConstraint("octet_length(context_json) BETWEEN 2 AND 9437184 AND octet_length(projection::text)<=32768 AND decision IN ('continue','stop','redirect')", name="ck_dr89_source_bounds"),
        *[sa.CheckConstraint(f"{key} ~ '^[a-f0-9]{{64}}$'", name=f"ck_dr89_{key}") for key in ("context_sha256", "projection_sha256")],
        sa.Index("idx_dr89_owner", "actor_user_id", "design_revision_id", "created_at", "id"))
    link = sa.Table(TABLE_ORDER[1], metadata, *common("dl89", "link_follow_up"),
        uid("feedback_id", TABLE_ORDER[0] + ".id"), sa.Column("feedback_record_sha256", sa.String(64), nullable=False),
        uid("child_revision_id", "discovery_design_revisions_v1.id"), sa.Column("child", JSONB, nullable=False),
        sa.UniqueConstraint("child_revision_id", name="uq_dl89_child"),
        sa.CheckConstraint("feedback_record_sha256 ~ '^[a-f0-9]{64}$'", name="ck_dl89_feedback_sha"),
        sa.Index("idx_dl89_owner", "actor_user_id", "feedback_id", "created_at", "id"))
    result.add_is_dependent_on(metadata.tables["discovery_design_revisions_v1"])
    result.add_is_dependent_on(metadata.tables["discovery_condition_child_links_v1"])
    link.add_is_dependent_on(result)
    for statement in guard_statements():
        sa.event.listen(link, "after_create", sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"))
    return {TABLE_ORDER[0]: result, TABLE_ORDER[1]: link}
