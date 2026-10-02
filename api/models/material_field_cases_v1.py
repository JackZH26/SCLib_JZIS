"""Additive 0084 private pending field cases; frozen after release."""
import sqlalchemy as sa
import re
from sqlalchemy.dialects.postgresql import JSONB, UUID

TABLE_ORDER = ("material_field_targets_v1", "material_field_associations_v1", "material_field_attempts_v1")
FUNCTION_SIGNATURES = (("sclib_material_field_lock_v1", ""),
    ("sclib_material_field_closed_v1", "jsonb,text[]"),
    ("sclib_material_field_context_v1", "jsonb"),
    ("sclib_material_field_insert_v1", ""), ("sclib_material_field_immutable_v1", ""))


def guard_statements():
    from services.material_field_case_contract import FIELDS, OUTCOMES, REASONS
    from services.research_release_manifest import canonical
    values = lambda seq: "ARRAY[" + ",".join("'" + v + "'" for v in seq) + "]"
    definitions = r"""
CREATE FUNCTION public.sclib_material_field_lock_v1() RETURNS void
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 IF current_setting('transaction_isolation')<>'serializable' THEN
  RAISE EXCEPTION 'field_case_serializable_required' USING ERRCODE='25000'; END IF;
 PERFORM public.sclib_research_integrity_lock_v1();
 PERFORM public.sclib_research_publication_lock_v1();
 PERFORM public.sclib_source_lifecycle_lock_v1();
 PERFORM public.sclib_source_expression_lock_v2();
 IF NOT pg_try_advisory_xact_lock(840017026) THEN
  RAISE EXCEPTION 'field_case_busy_retry' USING ERRCODE='55P03'; END IF;
END $$;
CREATE FUNCTION public.sclib_material_field_closed_v1(v jsonb,k text[]) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT jsonb_typeof(v)='object' AND v ?& k AND v-k='{}'::jsonb
$$;
CREATE FUNCTION public.sclib_material_field_context_v1(t jsonb) RETURNS text
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE m public.materials%ROWTYPE; r jsonb; e jsonb; s jsonb; a jsonb; n integer; k text; BEGIN
 IF NOT public.sclib_material_field_closed_v1(t,ARRAY['kind','material_id','record_index','entity_id','expected_context_sha256'])
  OR jsonb_typeof(t->'material_id') IS DISTINCT FROM 'string' OR length(t->>'material_id') NOT BETWEEN 1 AND 100
  OR t->>'material_id'<>trim(t->>'material_id') OR t->>'material_id' ~ '[[:cntrl:]]'
  OR jsonb_typeof(t->'kind') IS DISTINCT FROM 'string'
  OR t->>'kind' NOT IN ('retained_result','tc_claim','event_property')
  OR jsonb_typeof(t->'expected_context_sha256') IS DISTINCT FROM 'string'
  OR t->>'expected_context_sha256' !~ '^[a-f0-9]{64}$' THEN
  RAISE EXCEPTION 'field_case_target_selector' USING ERRCODE='23514'; END IF;
 SELECT * INTO m FROM public.materials WHERE id=t->>'material_id';
 IF m.id IS NULL OR jsonb_typeof(m.records) IS DISTINCT FROM 'array' OR jsonb_array_length(m.records)>5000
  OR octet_length(m.records::text)>4194304 THEN
  RAISE EXCEPTION 'field_case_material_unavailable' USING ERRCODE='23514'; END IF;
 k:=t->>'kind';
 IF k='retained_result' THEN
  IF jsonb_typeof(t->'record_index') IS DISTINCT FROM 'number' OR t->>'record_index' !~ '^[0-9]{1,4}$'
   OR t->'entity_id'<>'null'::jsonb THEN RAISE EXCEPTION 'field_case_record_selector' USING ERRCODE='23514'; END IF;
  n:=(t->>'record_index')::integer; r:=m.records->n;
  IF r IS NULL OR jsonb_typeof(r) IS DISTINCT FROM 'object' THEN RAISE EXCEPTION 'field_case_record_unavailable' USING ERRCODE='23514'; END IF;
 ELSE
  IF t->'record_index' IS DISTINCT FROM 'null'::jsonb OR jsonb_typeof(t->'entity_id') IS DISTINCT FROM 'string'
   OR (t->>'entity_id')::uuid::text<>t->>'entity_id' THEN
   RAISE EXCEPTION 'field_case_native_selector' USING ERRCODE='23514'; END IF;
  IF k='tc_claim' THEN
   SELECT to_jsonb(c) INTO r FROM public.material_claims c WHERE c.id=(t->>'entity_id')::uuid AND c.material_id=m.id;
   IF r->>'event_id' IS NOT NULL THEN SELECT to_jsonb(x) INTO e FROM public.research_events x WHERE x.id=(r->>'event_id')::uuid; END IF;
  ELSE
   SELECT to_jsonb(p) INTO r FROM public.event_properties p WHERE p.id=(t->>'entity_id')::uuid;
   SELECT to_jsonb(x) INTO e FROM public.research_events x WHERE x.id=(r->>'event_id')::uuid AND x.material_id=m.id;
  END IF;
  IF r IS NULL OR ((k='event_property' OR r->>'event_id' IS NOT NULL) AND e IS NULL)
   OR (e IS NOT NULL AND e->>'material_id' IS DISTINCT FROM m.id) THEN
   RAISE EXCEPTION 'field_case_native_closure_unavailable' USING ERRCODE='23514'; END IF;
  IF e IS NOT NULL THEN
   SELECT to_jsonb(x) INTO s FROM public.material_states x WHERE x.id=(e->>'state_id')::uuid AND x.material_id=m.id;
   IF s IS NULL THEN RAISE EXCEPTION 'field_case_state_closure_unavailable' USING ERRCODE='23514'; END IF;
   IF s->>'sample_id' IS NOT NULL THEN
    SELECT to_jsonb(x) INTO a FROM public.research_samples x WHERE x.id=(s->>'sample_id')::uuid AND x.material_id=m.id;
    IF a IS NULL THEN RAISE EXCEPTION 'field_case_sample_closure_unavailable' USING ERRCODE='23514'; END IF;
   END IF;
  END IF;
 END IF;
 RETURN public.sclib_scientific_import_canonical_v1(jsonb_build_object('kind',k,'material_id',m.id,
  'record_index',t->'record_index','entity_id',t->'entity_id','material',to_jsonb(m)-'records',
  'result',r,'event',e,'state',s,'sample',a));
END $$;
CREATE FUNCTION public.sclib_material_field_immutable_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 RAISE EXCEPTION 'material field cases are append-only' USING ERRCODE='55000'; END $$;
CREATE FUNCTION public.sclib_material_field_insert_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE q jsonb; p jsonb; t public.material_field_targets_v1%ROWTYPE; x public.source_expression_revisions_v2%ROWTYPE;
 c public.source_expression_captures_v2%ROWTYPE; receipt public.source_expression_imports_v2%ROWTYPE;
 previous jsonb; pin jsonb; expected text; preview jsonb; identity jsonb; v text; field text; BEGIN
 PERFORM public.sclib_material_field_lock_v1();
 IF NOT public.sclib_research_distribution_role_v1(NEW.actor_user_id,NEW.actor_grant_id,'curator')
  OR NOT EXISTS(SELECT 1 FROM public.users WHERE id=NEW.actor_user_id AND session_version=NEW.actor_session_version) THEN
  RAISE EXCEPTION 'field_case_live_actor_required' USING ERRCODE='42501'; END IF;
 q:=NEW.request_json::jsonb; p:=q->'payload';
 IF EXISTS(SELECT 1 FROM public.material_field_targets_v1 WHERE actor_user_id=NEW.actor_user_id AND request_key=NEW.request_key)
  OR EXISTS(SELECT 1 FROM public.material_field_associations_v1 WHERE actor_user_id=NEW.actor_user_id AND request_key=NEW.request_key)
  OR EXISTS(SELECT 1 FROM public.material_field_attempts_v1 WHERE actor_user_id=NEW.actor_user_id AND request_key=NEW.request_key) THEN
  RAISE EXCEPTION 'field_case_request_key_already_bound' USING ERRCODE='23505'; END IF;
 IF NOT public.sclib_material_field_closed_v1(q,ARRAY['version','request_key','operation','payload'])
  OR jsonb_typeof(q->'version') IS DISTINCT FROM 'string'
  OR jsonb_typeof(q->'request_key') IS DISTINCT FROM 'string'
  OR jsonb_typeof(q->'operation') IS DISTINCT FROM 'string'
  OR q->>'version' IS DISTINCT FROM 'material-field-case-operation/1.0.0' OR q->>'request_key' IS DISTINCT FROM NEW.request_key
  OR q->>'operation' IS DISTINCT FROM NEW.operation OR p IS DISTINCT FROM NEW.payload
  OR NEW.request_json IS DISTINCT FROM public.sclib_scientific_import_canonical_v1(q)
  OR NEW.request_sha256 IS DISTINCT FROM public.sclib_source_property_hash_v1(NEW.request_json)
  OR NEW.operation IS DISTINCT FROM (CASE TG_TABLE_NAME WHEN 'material_field_targets_v1' THEN 'target'
   WHEN 'material_field_associations_v1' THEN 'association' ELSE 'attempt' END) THEN
  RAISE EXCEPTION 'field_case_exact_request_required' USING ERRCODE='23514'; END IF;
 IF NEW.operation='target' THEN
  IF NOT public.sclib_material_field_closed_v1(p,ARRAY['field_id','target'])
   OR jsonb_typeof(p->'field_id') IS DISTINCT FROM 'string' OR p->>'field_id' NOT IN (SELECT unnest(FIELDS))
   OR NEW.target_id IS NOT NULL OR NEW.chain_key IS NOT NULL OR NEW.predecessor_id IS NOT NULL
   OR NEW.expression_revision_id IS NOT NULL OR NEW.expression_record_sha256 IS NOT NULL THEN
   RAISE EXCEPTION 'field_case_target_shape' USING ERRCODE='23514'; END IF;
  expected:=public.sclib_material_field_context_v1(p->'target');
  IF NEW.context_json IS DISTINCT FROM expected OR NEW.context_sha256 IS DISTINCT FROM p->'target'->>'expected_context_sha256' THEN
   RAISE EXCEPTION 'field_case_target_fingerprint_changed' USING ERRCODE='23514'; END IF;
 ELSE
  SELECT * INTO t FROM public.material_field_targets_v1 WHERE id=NEW.target_id;
  IF t.id IS NULL OR jsonb_typeof(p->'target_id') IS DISTINCT FROM 'string'
   OR jsonb_typeof(p->'target_sha256') IS DISTINCT FROM 'string'
   OR p->>'target_id' IS DISTINCT FROM t.id::text OR p->>'target_sha256' IS DISTINCT FROM t.record_sha256
   OR NEW.context_json IS DISTINCT FROM t.context_json OR NEW.field_id IS DISTINCT FROM t.field_id THEN
   RAISE EXCEPTION 'field_case_exact_target_required' USING ERRCODE='23514'; END IF;
  IF NEW.operation='association' THEN
   IF NOT public.sclib_material_field_closed_v1(p,ARRAY['target_id','target_sha256','expression_revision_id','expression_record_sha256','source_identity','action','predecessor'])
    OR jsonb_typeof(p->'action') IS DISTINCT FROM 'string' OR p->>'action' NOT IN ('propose','withdraw')
    OR jsonb_typeof(p->'expression_revision_id') IS DISTINCT FROM 'string'
    OR jsonb_typeof(p->'expression_record_sha256') IS DISTINCT FROM 'string'
    OR NOT public.sclib_material_field_closed_v1(p->'source_identity',ARRAY['paper_id','work_id'])
    OR (jsonb_typeof(p->'source_identity'->'paper_id') IS DISTINCT FROM 'null'
        AND jsonb_typeof(p->'source_identity'->'paper_id') IS DISTINCT FROM 'string')
    OR (jsonb_typeof(p->'source_identity'->'work_id') IS DISTINCT FROM 'null'
        AND jsonb_typeof(p->'source_identity'->'work_id') IS DISTINCT FROM 'string') THEN
    RAISE EXCEPTION 'field_case_association_shape' USING ERRCODE='23514'; END IF;
   identity:=p->'source_identity';
   IF (identity->>'paper_id' IS NOT NULL AND (length(identity->>'paper_id') NOT BETWEEN 1 AND 100
      OR identity->>'paper_id'<>trim(identity->>'paper_id') OR identity->>'paper_id' ~ '[[:cntrl:]]'))
    OR (identity->>'work_id' IS NOT NULL AND (identity->>'work_id')::uuid::text<>identity->>'work_id') THEN
    RAISE EXCEPTION 'field_case_source_identity_shape' USING ERRCODE='23514'; END IF;
   IF (identity->>'paper_id' IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.papers WHERE id=identity->>'paper_id'))
    OR (identity->>'work_id' IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.works WHERE id=(identity->>'work_id')::uuid)) THEN
    RAISE EXCEPTION 'field_case_source_identity_unavailable' USING ERRCODE='23514'; END IF;
   SELECT * INTO x FROM public.source_expression_revisions_v2 WHERE id=NEW.expression_revision_id;
   IF x.id IS NULL OR p->>'expression_revision_id' IS DISTINCT FROM x.id::text
    OR p->>'expression_record_sha256' IS DISTINCT FROM x.record_sha256
    OR NEW.expression_record_sha256 IS DISTINCT FROM x.record_sha256 THEN
    RAISE EXCEPTION 'field_case_exact_expression_required' USING ERRCODE='23514'; END IF;
   SELECT * INTO c FROM public.source_expression_captures_v2 WHERE id=x.capture_id;
   SELECT * INTO receipt FROM public.source_expression_imports_v2 WHERE id=x.import_receipt_id;
   IF x.record_sha256 IS DISTINCT FROM public.sclib_source_property_hash_v1(public.sclib_scientific_import_canonical_v1(to_jsonb(x)-ARRAY['created_at','record_sha256']))
    OR c.record_sha256 IS DISTINCT FROM public.sclib_source_property_hash_v1(public.sclib_scientific_import_canonical_v1(to_jsonb(c)-ARRAY['created_at','record_sha256']))
    OR receipt.record_sha256 IS DISTINCT FROM x.import_receipt_sha256
    OR x.projection_json::jsonb IS DISTINCT FROM public.sclib_source_expression_project_v2(c.source_metadata,c.source_text,(receipt.package_json::jsonb->'expressions')->x.entry_index) THEN
    RAISE EXCEPTION 'field_case_expression_integrity_unavailable' USING ERRCODE='23514'; END IF;
   field:=CASE NEW.field_id WHEN 'measurement_method' THEN 'method_statement' WHEN 'sample_form' THEN 'sample_form_statement'
    WHEN 'space_group' THEN 'structure_statement' WHEN 'crystal_structure' THEN 'structure_statement'
    WHEN 'pairing_symmetry' THEN 'classification_statement' WHEN 'gap_structure' THEN 'classification_statement'
    WHEN 'is_unconventional' THEN 'classification_statement' WHEN 'competing_order' THEN 'classification_statement' ELSE NEW.field_id END;
   IF x.field_id IS DISTINCT FROM field AND NOT (NEW.field_id='tc_criterion' AND x.field_id='tc_kelvin'
    AND EXISTS(SELECT 1 FROM jsonb_array_elements(x.projection_json::jsonb->'conditions') z WHERE z->>'field_id'='criterion_statement' AND z->>'role'='reported_result_condition')) THEN
    RAISE EXCEPTION 'field_case_expression_field_mismatch' USING ERRCODE='23514'; END IF;
   IF NEW.chain_key IS DISTINCT FROM public.sclib_source_property_hash_v1(public.sclib_scientific_import_canonical_v1(jsonb_build_array(t.id::text,x.expression_key))) THEN
    RAISE EXCEPTION 'field_case_association_chain_required' USING ERRCODE='23514'; END IF;
   SELECT to_jsonb(a) INTO previous FROM public.material_field_associations_v1 a WHERE a.chain_key=NEW.chain_key
    AND NOT EXISTS(SELECT 1 FROM public.material_field_associations_v1 successor WHERE successor.predecessor_id=a.id);
   IF p->>'action'='propose' AND (public.sclib_material_field_context_v1(t.payload->'target') IS DISTINCT FROM t.context_json
    OR EXISTS(SELECT 1 FROM public.source_expression_revisions_v2 newer WHERE newer.expression_key=x.expression_key AND newer.revision_number>x.revision_number)) THEN
    RAISE EXCEPTION 'field_case_current_inputs_required' USING ERRCODE='23514'; END IF;
   IF p->>'action'='withdraw' AND (previous IS NULL OR previous->'payload'->>'action' IS DISTINCT FROM 'propose'
    OR previous->>'actor_user_id' IS DISTINCT FROM NEW.actor_user_id::text) THEN
    RAISE EXCEPTION 'field_case_own_proposal_withdrawal_required' USING ERRCODE='23514'; END IF;
  ELSE
   IF NOT public.sclib_material_field_closed_v1(p,ARRAY['target_id','target_sha256','outcome','reason_codes','checked_scope','expression_pins','predecessor'])
    OR jsonb_typeof(p->'outcome') IS DISTINCT FROM 'string'
    OR p->>'outcome' NOT IN (SELECT unnest(OUTCOMES)) OR jsonb_typeof(p->'reason_codes') IS DISTINCT FROM 'array'
    OR jsonb_array_length(p->'reason_codes') NOT BETWEEN 1 AND 16
    OR EXISTS(SELECT 1 FROM jsonb_array_elements(p->'reason_codes') z WHERE jsonb_typeof(z) IS DISTINCT FROM 'string' OR z#>>'{}' NOT IN (SELECT unnest(REASONS)))
    OR (SELECT count(DISTINCT z) FROM jsonb_array_elements(p->'reason_codes') z)<>jsonb_array_length(p->'reason_codes')
    OR NOT public.sclib_material_field_closed_v1(p->'checked_scope',ARRAY['source_ids','fulltext_checked','supplement_checked','scope_label'])
    OR jsonb_typeof(p->'checked_scope'->'source_ids') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'checked_scope'->'source_ids')>8
    OR EXISTS(SELECT 1 FROM jsonb_array_elements(p->'checked_scope'->'source_ids') z WHERE jsonb_typeof(z) IS DISTINCT FROM 'string' OR length(z#>>'{}') NOT BETWEEN 1 AND 160 OR z#>>'{}' ~ '[[:cntrl:]]' OR z#>>'{}'<>trim(z#>>'{}'))
    OR (SELECT count(DISTINCT z) FROM jsonb_array_elements(p->'checked_scope'->'source_ids') z)<>jsonb_array_length(p->'checked_scope'->'source_ids')
    OR jsonb_typeof(p->'checked_scope'->'fulltext_checked') IS DISTINCT FROM 'boolean' OR jsonb_typeof(p->'checked_scope'->'supplement_checked') IS DISTINCT FROM 'boolean'
    OR jsonb_typeof(p->'checked_scope'->'scope_label') IS DISTINCT FROM 'string' OR length(p->'checked_scope'->>'scope_label') NOT BETWEEN 1 AND 500
    OR p->'checked_scope'->>'scope_label'<>trim(p->'checked_scope'->>'scope_label') OR p->'checked_scope'->>'scope_label' ~ '[[:cntrl:]]'
    OR (jsonb_array_length(p->'checked_scope'->'source_ids')=0 AND (p->'checked_scope'->'fulltext_checked'='true'::jsonb OR p->'checked_scope'->'supplement_checked'='true'::jsonb))
    OR jsonb_typeof(p->'expression_pins') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'expression_pins')>8
    OR (p->>'outcome'='pending_expression_available' AND jsonb_array_length(p->'expression_pins')=0)
    OR NEW.chain_key IS DISTINCT FROM t.id::text OR NEW.expression_revision_id IS NOT NULL OR NEW.expression_record_sha256 IS NOT NULL THEN
    RAISE EXCEPTION 'field_case_attempt_shape' USING ERRCODE='23514'; END IF;
   FOR pin IN SELECT value FROM jsonb_array_elements(p->'expression_pins') LOOP
    IF NOT public.sclib_material_field_closed_v1(pin,ARRAY['revision_id','record_sha256'])
     OR jsonb_typeof(pin->'revision_id') IS DISTINCT FROM 'string'
     OR jsonb_typeof(pin->'record_sha256') IS DISTINCT FROM 'string'
     OR (pin->>'revision_id')::uuid::text<>pin->>'revision_id' OR pin->>'record_sha256' !~ '^[a-f0-9]{64}$' OR NOT EXISTS(
     SELECT 1 FROM public.source_expression_revisions_v2 WHERE id=(pin->>'revision_id')::uuid AND record_sha256=pin->>'record_sha256') THEN
     RAISE EXCEPTION 'field_case_attempt_expression_pin' USING ERRCODE='23514'; END IF;
   END LOOP;
   IF (SELECT count(DISTINCT z->>'revision_id') FROM jsonb_array_elements(p->'expression_pins') z)<>jsonb_array_length(p->'expression_pins') THEN
    RAISE EXCEPTION 'field_case_duplicate_expression_pin' USING ERRCODE='23514'; END IF;
   SELECT to_jsonb(a) INTO previous FROM public.material_field_attempts_v1 a WHERE a.target_id=t.id
    AND NOT EXISTS(SELECT 1 FROM public.material_field_attempts_v1 successor WHERE successor.predecessor_id=a.id);
  END IF;
  IF NEW.predecessor_id IS DISTINCT FROM (previous->>'id')::uuid OR NEW.predecessor_sha256 IS DISTINCT FROM previous->>'record_sha256'
   OR p->'predecessor' IS DISTINCT FROM (CASE WHEN previous IS NULL THEN 'null'::jsonb ELSE jsonb_build_object('id',previous->>'id','record_sha256',previous->>'record_sha256') END) THEN
   RAISE EXCEPTION 'field_case_exact_predecessor_required' USING ERRCODE='23514'; END IF;
 END IF;
 IF NEW.context_sha256 IS DISTINCT FROM public.sclib_source_property_hash_v1(NEW.context_json)
  OR NEW.field_id IS DISTINCT FROM (CASE NEW.operation WHEN 'target' THEN p->>'field_id' ELSE t.field_id END) THEN
  RAISE EXCEPTION 'field_case_context_integrity' USING ERRCODE='23514'; END IF;
 preview:=jsonb_build_object('version','material-field-case/1.0.0','actor',jsonb_build_object('actor_user_id',NEW.actor_user_id::text,
  'actor_grant_id',NEW.actor_grant_id::text,'actor_session_version',NEW.actor_session_version),
  'request_sha256',NEW.request_sha256,'receipt_id',NEW.id::text,'context_sha256',NEW.context_sha256);
 IF NEW.preview_json IS DISTINCT FROM public.sclib_scientific_import_canonical_v1(preview)
  OR NEW.preview_sha256 IS DISTINCT FROM public.sclib_source_property_hash_v1(NEW.preview_json)
  OR NEW.record_sha256 IS DISTINCT FROM public.sclib_source_property_hash_v1(public.sclib_scientific_import_canonical_v1(to_jsonb(NEW)-ARRAY['created_at','record_sha256'])) THEN
  RAISE EXCEPTION 'field_case_exact_receipt_required' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
"""
    definitions = definitions.replace("unnest(FIELDS)", "unnest(" + values(FIELDS) + ")").replace("unnest(OUTCOMES)", "unnest(" + values(OUTCOMES) + ")").replace("unnest(REASONS)", "unnest(" + values(REASONS) + ")")
    return [*re.split(r";\n(?=CREATE FUNCTION)", definitions.strip()), *[sql for name in TABLE_ORDER for sql in (
        f"CREATE TRIGGER fc84_insert BEFORE INSERT ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_material_field_insert_v1()",
        f"CREATE TRIGGER fc84_immutable BEFORE UPDATE OR DELETE ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_material_field_immutable_v1()",
        f"CREATE TRIGGER fc84_truncate BEFORE TRUNCATE ON public.{name} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_material_field_immutable_v1()")]]


def register(metadata):
    tables = {}
    for i, name in enumerate(TABLE_ORDER):
        def uid(n, target=None, nullable=False):
            return sa.Column(n, UUID(as_uuid=True), *([sa.ForeignKey(target, ondelete="RESTRICT", onupdate="RESTRICT")] if target else []), nullable=nullable)
        items = [uid("id"), uid("actor_user_id", "users.id"), uid("actor_grant_id", "research_role_grants.id"),
                 sa.Column("actor_session_version", sa.Integer, nullable=False),
                 sa.Column("operation", sa.String(20), nullable=False),
                 sa.Column("request_key", sa.String(160), nullable=False),
                 sa.Column("request_json", sa.Text, nullable=False), sa.Column("payload", JSONB, nullable=False),
                 sa.Column("request_sha256", sa.String(64), nullable=False),
                 sa.Column("preview_json", sa.Text, nullable=False), sa.Column("preview_sha256", sa.String(64), nullable=False),
                 sa.Column("context_json", sa.Text, nullable=False), sa.Column("context_sha256", sa.String(64), nullable=False),
                 sa.Column("field_id", sa.String(100), nullable=False),
                 uid("target_id", TABLE_ORDER[0] + ".id", nullable=True),
                 sa.Column("chain_key", sa.String(100)), uid("predecessor_id", name + ".id", nullable=True),
                 sa.Column("predecessor_sha256", sa.String(64)),
                 uid("expression_revision_id", "source_expression_revisions_v2.id", nullable=True),
                 sa.Column("expression_record_sha256", sa.String(64)),
                 sa.Column("record_sha256", sa.String(64), nullable=False),
                 sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.clock_timestamp()),
                 sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("actor_user_id", "request_key", name=f"uq_fc84_{i}_request"),
                 sa.UniqueConstraint("predecessor_id", name=f"uq_fc84_{i}_successor"),
                 sa.Index(f"idx_fc84_{i}_target", "target_id"),
                 sa.CheckConstraint("actor_session_version>=0 AND isfinite(created_at) AND octet_length(request_json) BETWEEN 2 AND 32768 AND octet_length(preview_json) BETWEEN 2 AND 4096 AND octet_length(context_json) BETWEEN 2 AND 131072", name=f"ck_fc84_{i}_bounds"),
                 sa.CheckConstraint("request_key ~ '^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$' AND (predecessor_id IS NULL)=(predecessor_sha256 IS NULL)", name=f"ck_fc84_{i}_key")]
        items += [sa.CheckConstraint(f"{n} IS NULL OR {n} ~ '^[a-f0-9]{{64}}$'", name=f"ck_fc84_{i}_{n}") for n in ("request_sha256", "preview_sha256", "context_sha256", "record_sha256", "predecessor_sha256", "expression_record_sha256")]
        if i:
            items.append(sa.Index(f"uq_fc84_{i}_root", "chain_key", unique=True, postgresql_where=sa.text("predecessor_id IS NULL")))
        tables[name] = sa.Table(name, metadata, *items)
    last = tables[TABLE_ORDER[-1]]
    for name in ("materials", "material_claims", "research_events", "material_states", "research_samples", "event_properties", "papers", "works", "research_publication_epoch", "source_lifecycle_epoch", "research_integrity_epoch", "source_expression_captures_v2", "source_expression_imports_v2", "source_expression_revisions_v2"):
        last.add_is_dependent_on(metadata.tables[name])
    for statement in guard_statements():
        sa.event.listen(last, "after_create", sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"))
    return tables
