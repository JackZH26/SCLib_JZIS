"""Private source-expression history; never canonical properties or approval.

Initial admission is two exact published metadata snapshots. The received bytes
are retained with each receipt, rather than copied into a new package resource.
PostgreSQL independently checks source identity, live grant, pending authority,
complete atomic inventories and append-only history. No sample/state is invented.
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

TABLE_ORDER = ("source_property_import_receipts", "source_property_observation_revisions",
               "source_property_review_appends")
PARENTS = ("users", "research_role_grants")
LOCK_FUNCTION = "sclib_source_property_lock_v1"
LOCK_KEY = 820017026
# This 0082 replay contract is immutable. A future source registry gets a new
# module, migration and SQL function namespace, never this v1 definition.
EXPECTED_REGISTRY_SHA256 = "021e7bcbf53bb43afd2116dfd6ce750270a1d23aeca5e1d8283f1d6de4eb316e"
FUNCTION_SIGNATURES = ((LOCK_FUNCTION, ""), ("sclib_source_property_hash_v1", "text"),
                       ("sclib_source_property_immutable_v1", ""),
                       ("sclib_source_property_pointer_v1", "jsonb, text"),
                       ("sclib_source_property_values_v1", "jsonb, text, text, jsonb, jsonb"),
                       ("sclib_source_property_insert_v1", ""),
                       ("sclib_source_property_complete_v1", ""))
_SQL = "LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp SET TimeZone='UTC'"


def guard_statements():
    from services.source_property_contract import (
        COMPONENT_ROLES,
        FIELD_PROFILES,
        RANGE_UNITS,
        REGISTRY_SHA256,
        SNAPSHOT_ENTRY_PINS,
    )

    if REGISTRY_SHA256 != EXPECTED_REGISTRY_SHA256:
        raise RuntimeError("Frozen 0082 source-property registry changed; use an additive v2 migration")

    profiles = json.dumps(FIELD_PROFILES, separators=(",", ":"))
    pins = json.dumps(SNAPSHOT_ENTRY_PINS, separators=(",", ":"))
    roles = json.dumps(COMPONENT_ROLES, separators=(",", ":"))
    ranges = json.dumps(RANGE_UNITS, separators=(",", ":"))
    statements = [f"""
      CREATE OR REPLACE FUNCTION public.{LOCK_FUNCTION}() RETURNS void {_SQL} AS $$
      BEGIN
        IF current_setting('transaction_isolation')<>'serializable' THEN
          RAISE EXCEPTION 'source_property_serializable_required' USING ERRCODE='25000'; END IF;
        PERFORM public.sclib_research_publication_lock_v1();
        IF NOT pg_try_advisory_xact_lock({LOCK_KEY}) THEN
          RAISE EXCEPTION 'source_property_busy_retry' USING ERRCODE='55P03'; END IF;
      END $$
    """, """
      CREATE OR REPLACE FUNCTION public.sclib_source_property_hash_v1(body text) RETURNS text
      LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
        SELECT encode(public.digest(convert_to(body,'UTF8'),'sha256'),'hex')
      $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_source_property_immutable_v1() RETURNS trigger {_SQL} AS $$
      BEGIN RAISE EXCEPTION 'source property history is append-only' USING ERRCODE='55000'; END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_source_property_pointer_v1(body jsonb, pointer text) RETURNS jsonb
      {_SQL} IMMUTABLE AS $$
      DECLARE segment text;
      BEGIN
        IF length(pointer)>512 OR pointer !~ '^/entries/[0-9]{{1,2}}(/[^/]+)*$' THEN
          RAISE EXCEPTION 'source_property_bounded_pointer_required' USING ERRCODE='23514'; END IF;
        FOREACH segment IN ARRAY string_to_array(substring(pointer FROM 2),'/') LOOP
          segment:=replace(replace(segment,'~1','/'),'~0','~');
          IF jsonb_typeof(body)='array' THEN
            IF segment !~ '^[0-9]{{1,3}}$' THEN RETURN NULL; END IF;
            body:=body->segment::integer;
          ELSIF jsonb_typeof(body)='object' THEN body:=body->segment;
          ELSE RETURN NULL; END IF;
        END LOOP;
        RETURN body;
      END $$
    """, """
      CREATE OR REPLACE FUNCTION public.sclib_source_property_values_v1(
        entry jsonb, prefix text, profile text, roles jsonb, ranges jsonb) RETURNS jsonb
      LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
        WITH RECURSIVE walk(path,value) AS (
          SELECT '/'||key,value FROM jsonb_each(entry) WHERE key IN ('value','source_window','source_subject')
          UNION ALL
          SELECT w.path||'/'||replace(replace(c.key,'~','~0'),'/','~1'),c.value
          FROM walk w CROSS JOIN LATERAL (
            SELECT key,value FROM jsonb_each(CASE WHEN jsonb_typeof(w.value)='object'
              AND NOT w.value ?& ARRAY['raw_value','value','unit'] THEN w.value ELSE '{}'::jsonb END)
            UNION ALL
            SELECT (ordinal-1)::text,value FROM jsonb_array_elements(CASE WHEN jsonb_typeof(w.value)='array'
              AND NOT COALESCE(ranges ? w.path,false) THEN w.value ELSE '[]'::jsonb END)
              WITH ORDINALITY AS a(value,ordinal)
          ) c
        )
        SELECT jsonb_build_object('kind',profile,
          'quantities',COALESCE((SELECT jsonb_agg(jsonb_build_object('json_pointer',prefix||path,
            'component_role',roles->path,'quantity',value) ORDER BY path) FROM walk
            WHERE jsonb_typeof(value)='object' AND value ?& ARRAY['raw_value','value','unit']),'[]'::jsonb),
          'ranges',COALESCE((SELECT jsonb_agg(jsonb_build_object('json_pointer',prefix||path,
            'component_role',roles->path,'unit',ranges->path,'values',value) ORDER BY path) FROM walk
            WHERE jsonb_typeof(value)='array' AND ranges ? path),'[]'::jsonb),
          'statements',COALESCE((SELECT jsonb_agg(jsonb_build_object('json_pointer',prefix||path,
            'scalar_kind',CASE WHEN jsonb_typeof(value)='string' THEN 'text' ELSE jsonb_typeof(value) END,
            'value',value) ORDER BY path) FROM walk WHERE jsonb_typeof(value) IN ('string','number','boolean','null')),'[]'::jsonb),
          'sites',CASE WHEN profile='cif_atomic_sites' THEN (SELECT jsonb_agg(jsonb_build_object(
              'json_pointer',prefix||'/value/'||(ordinal-1)::text,'value',value) ORDER BY ordinal)
              FROM jsonb_array_elements(entry->'value') WITH ORDINALITY AS a(value,ordinal)) ELSE '[]'::jsonb END,
          'operations',CASE WHEN profile='cif_declared_operations' THEN CASE WHEN jsonb_typeof(entry->'value')='array'
            THEN entry->'value' ELSE entry->'value'->'operations_raw' END ELSE '[]'::jsonb END)
      $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_source_property_insert_v1() RETURNS trigger {_SQL} AS $$
      DECLARE p public.source_property_import_receipts%ROWTYPE;
        o public.source_property_observation_revisions%ROWTYPE;
        h public.source_property_review_appends%ROWTYPE;
        body jsonb; entry jsonb; item jsonb; idx integer; needed text; hash_body jsonb;
        profiles jsonb:='{profiles}'::jsonb; pins jsonb:='{pins}'::jsonb;
        roles jsonb:='{roles}'::jsonb; ranges jsonb:='{ranges}'::jsonb;
        values_body jsonb; expected_provenance jsonb; normalized_values jsonb; expected_summary jsonb;
        expected_request jsonb; expected_preview jsonb;
      BEGIN
        PERFORM public.{LOCK_FUNCTION}();
        needed:=CASE WHEN TG_TABLE_NAME='source_property_review_appends' THEN 'reviewer' ELSE 'curator' END;
        IF NOT public.sclib_research_distribution_role_v1(NEW.actor_user_id,NEW.actor_grant_id,needed)
          OR NOT EXISTS(SELECT 1 FROM public.users u WHERE u.id=NEW.actor_user_id
                        AND u.session_version=NEW.actor_session_version) THEN
          RAISE EXCEPTION 'source_property_live_actor_required' USING ERRCODE='42501'; END IF;
        IF TG_TABLE_NAME='source_property_import_receipts' THEN
          IF octet_length(NEW.source_public_json)>1048576
            OR public.sclib_source_property_hash_v1(NEW.source_public_json)<>NEW.source_json_sha256
            OR NEW.registry_sha256<>'{REGISTRY_SHA256}'
            OR NEW.batch_id<>'source-property-batch:'||NEW.source_json_sha256
            OR (NEW.source_json_sha256,NEW.original_batch_sha256,NEW.observation_count) NOT IN (
              ('ac144451b2f03ca2e0e3dbd9ec27748e8257e1cac86473f384d6e5c34ea5f43e',
               '947e13d7947f27d9d291a3783ad262308babcec14c186de0e5fbf1c70b8a884f',15),
              ('c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8',
               'af823526b7c2764c75c116c2d42e48fde3746feac8e5d6635fecaa34f7a41615',34)) THEN
            RAISE EXCEPTION 'source_property_unsupported_snapshot' USING ERRCODE='23514'; END IF;
          body:=NEW.source_public_json::jsonb;
          IF jsonb_typeof(body->'entries') IS DISTINCT FROM 'array'
            OR jsonb_array_length(body->'entries')<>NEW.observation_count
            OR body->>'original_batch_sha256' IS DISTINCT FROM NEW.original_batch_sha256
            OR jsonb_typeof(NEW.observation_manifest) IS DISTINCT FROM 'array'
            OR jsonb_array_length(NEW.observation_manifest)<>NEW.observation_count THEN
            RAISE EXCEPTION 'source_property_exact_inventory_required' USING ERRCODE='23514'; END IF;
          expected_summary:=jsonb_build_object('source_task_count',NEW.observation_count,
            'source_expression_count',CASE NEW.observation_count WHEN 15 THEN 15 ELSE 31 END,
            'source_unavailable_count',CASE NEW.observation_count WHEN 15 THEN 0 ELSE 3 END,
            'source_group_count',CASE NEW.observation_count WHEN 15 THEN 3 ELSE 8 END,
            'quantity_component_count',CASE NEW.observation_count WHEN 15 THEN 22 ELSE 69 END,
            'quantity_component_scope','includes source value, repeated subject and conditional context',
            'independent_experiments',NULL,'counts_are_independent_experiments',false,
            'canonical_promotions',0,'scientific_acceptance',false,
            'selected_result_association','unestablished','status','pending');
          expected_request:=jsonb_build_object('version','source-property-pending/1.0.0',
            'source_json_sha256',NEW.source_json_sha256,'original_batch_sha256',NEW.original_batch_sha256,
            'registry_sha256',NEW.registry_sha256);
          expected_preview:=jsonb_build_object('version','source-property-pending/1.0.0',
            'request_key',NEW.request_key,'request_sha256',NEW.request_sha256,
            'actor',jsonb_build_object('actor_user_id',NEW.actor_user_id,'actor_grant_id',NEW.actor_grant_id,
                                       'actor_session_version',NEW.actor_session_version),
            'summary',expected_summary,'observation_manifest',NEW.observation_manifest);
          IF NEW.summary IS DISTINCT FROM expected_summary
            OR NEW.request_sha256<>public.sclib_source_property_hash_v1(
                public.sclib_scientific_import_canonical_v1(expected_request))
            OR NEW.preview_sha256<>public.sclib_source_property_hash_v1(
                public.sclib_scientific_import_canonical_v1(expected_preview)) THEN
            RAISE EXCEPTION 'source_property_exact_pending_receipt_required' USING ERRCODE='23514'; END IF;
          NEW.assembly_xid:=txid_current();
        ELSIF TG_TABLE_NAME='source_property_observation_revisions' THEN
          SELECT * INTO p FROM public.source_property_import_receipts WHERE id=NEW.import_receipt_id;
          IF p.id IS NULL OR p.assembly_xid<>txid_current()
            OR NEW.actor_user_id<>p.actor_user_id OR NEW.actor_grant_id<>p.actor_grant_id
            OR NEW.actor_session_version<>p.actor_session_version
            OR NEW.source_json_sha256<>p.source_json_sha256 OR NEW.original_batch_sha256<>p.original_batch_sha256
            OR NEW.registry_sha256<>p.registry_sha256 OR NEW.predecessor_id IS NOT NULL OR NEW.revision_number<>1 THEN
            RAISE EXCEPTION 'source_property_atomic_initial_revision_required' USING ERRCODE='23514'; END IF;
          IF NEW.source_json_pointer !~ '^/entries/[0-9]{{1,2}}$' THEN
            RAISE EXCEPTION 'source_property_entry_pointer_required' USING ERRCODE='23514'; END IF;
          idx:=split_part(NEW.source_json_pointer,'/',3)::integer;
          entry:=p.source_public_json::jsonb->'entries'->idx;
          body:=NEW.projection_json::jsonb;
          IF entry IS NULL OR entry->>'id' IS DISTINCT FROM NEW.source_entry_id
            OR (entry->>'source_group')||':'||(entry->>'field') IS DISTINCT FROM NEW.field_id
            OR body->'source_entry' IS DISTINCT FROM entry
            OR body->>'source_entry_id' IS DISTINCT FROM NEW.source_entry_id
            OR body->>'source_json_pointer' IS DISTINCT FROM NEW.source_json_pointer
            OR body->>'entry_sha256' IS DISTINCT FROM NEW.entry_sha256
            OR body->>'field_id' IS DISTINCT FROM NEW.field_id
            OR body->>'profile' IS DISTINCT FROM NEW.profile
            OR body->'subject' IS DISTINCT FROM entry->'source_subject'
            OR body->'window' IS DISTINCT FROM entry->'source_window'
            OR body->>'source_role' IS DISTINCT FROM entry->>'source_role'
            OR body->>'status' IS DISTINCT FROM 'pending'
            OR body->'display_context_material_id' IS DISTINCT FROM 'null'::jsonb
            OR body->'authority' IS DISTINCT FROM '{{"scope":"source_preparation","scientific_acceptance":false,"formal_human_review":false,"formal_scientific_review":false,"sample_identity_established":false,"phase_identity_established":false,"selected_result_association":"unestablished","ml_training_approved":false,"database_changed":false,"canonical_promotions":0}}'::jsonb
            OR profiles->>NEW.field_id IS DISTINCT FROM NEW.profile
            OR pins->NEW.source_json_sha256->>NEW.source_entry_id IS DISTINCT FROM NEW.entry_sha256
            OR public.sclib_source_property_hash_v1(NEW.projection_json)<>NEW.projection_sha256
            OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p.observation_manifest) m
                          WHERE m->>'source_entry_id'=NEW.source_entry_id
                            AND m->>'entry_sha256'=NEW.entry_sha256
                            AND m->>'projection_sha256'=NEW.projection_sha256) THEN
            RAISE EXCEPTION 'source_property_exact_pending_projection_required' USING ERRCODE='23514'; END IF;
          IF body-ARRAY['source_entry_id','source_json_pointer','entry_sha256','field_id','profile','subject',
              'window','source_role','provenance','values','source_entry','status','authority','display_context_material_id']<>'{{}}'::jsonb
            OR NOT body ?& ARRAY['source_entry_id','source_json_pointer','entry_sha256','field_id','profile',
              'subject','window','source_role','provenance','values','source_entry','status','authority','display_context_material_id'] THEN
            RAISE EXCEPTION 'source_property_closed_projection_required' USING ERRCODE='23514'; END IF;
          expected_provenance:=jsonb_build_object(
            'sources',CASE WHEN entry ? 'source' THEN jsonb_build_array(entry->'source') ELSE entry->'sources' END,
            'field_locators',CASE WHEN entry ? 'field_locator' THEN jsonb_build_array(entry->'field_locator') ELSE entry->'field_locators' END);
          values_body:=body->'values';
          IF body->'provenance' IS DISTINCT FROM expected_provenance
            OR values_body IS DISTINCT FROM jsonb_build_object('kind',NEW.profile,
              'quantities',values_body->'quantities','ranges',values_body->'ranges',
              'statements',values_body->'statements','sites',values_body->'sites','operations',values_body->'operations')
            OR jsonb_typeof(values_body->'quantities') IS DISTINCT FROM 'array'
            OR jsonb_typeof(values_body->'ranges') IS DISTINCT FROM 'array'
            OR jsonb_typeof(values_body->'statements') IS DISTINCT FROM 'array'
            OR jsonb_typeof(values_body->'sites') IS DISTINCT FROM 'array'
            OR jsonb_typeof(values_body->'operations') IS DISTINCT FROM 'array'
            OR jsonb_array_length(values_body->'quantities')>100
            OR jsonb_array_length(values_body->'statements')>500
            OR jsonb_array_length(values_body->'ranges')>32
            OR jsonb_array_length(values_body->'sites')>32
            OR jsonb_array_length(values_body->'operations')>192 THEN
            RAISE EXCEPTION 'source_property_typed_values_required' USING ERRCODE='23514'; END IF;
          normalized_values:=jsonb_build_object('kind',values_body->'kind',
            'quantities',(SELECT COALESCE(jsonb_agg(value ORDER BY value->>'json_pointer'),'[]'::jsonb)
              FROM jsonb_array_elements(values_body->'quantities')),
            'ranges',(SELECT COALESCE(jsonb_agg(value ORDER BY value->>'json_pointer'),'[]'::jsonb)
              FROM jsonb_array_elements(values_body->'ranges')),
            'statements',(SELECT COALESCE(jsonb_agg(value ORDER BY value->>'json_pointer'),'[]'::jsonb)
              FROM jsonb_array_elements(values_body->'statements')),
            'sites',(SELECT COALESCE(jsonb_agg(value ORDER BY value->>'json_pointer'),'[]'::jsonb)
              FROM jsonb_array_elements(values_body->'sites')),'operations',values_body->'operations');
          IF normalized_values IS DISTINCT FROM public.sclib_source_property_values_v1(
             entry,NEW.source_json_pointer,NEW.profile,roles->NEW.field_id,COALESCE(ranges->NEW.field_id,'{{}}'::jsonb)) THEN
            RAISE EXCEPTION 'source_property_registered_typed_projection_required' USING ERRCODE='23514'; END IF;
          FOR item IN SELECT value FROM jsonb_array_elements(values_body->'quantities') LOOP
            IF item IS DISTINCT FROM jsonb_build_object('json_pointer',item->'json_pointer',
               'component_role',item->'component_role','quantity',item->'quantity')
              OR left(item->>'json_pointer',length(NEW.source_json_pointer)+1)<>NEW.source_json_pointer||'/'
              OR item->'quantity' IS DISTINCT FROM public.sclib_source_property_pointer_v1(
                  p.source_public_json::jsonb,item->>'json_pointer')
              OR jsonb_typeof(item->'quantity') IS DISTINCT FROM 'object' THEN
              RAISE EXCEPTION 'source_property_exact_quantity_pointer_required' USING ERRCODE='23514'; END IF;
          END LOOP;
          FOR item IN SELECT value FROM jsonb_array_elements(values_body->'statements') LOOP
            IF item IS DISTINCT FROM jsonb_build_object('json_pointer',item->'json_pointer',
                'scalar_kind',item->'scalar_kind','value',item->'value')
              OR left(item->>'json_pointer',length(NEW.source_json_pointer)+1)<>NEW.source_json_pointer||'/'
              OR item->'value' IS DISTINCT FROM public.sclib_source_property_pointer_v1(
                 p.source_public_json::jsonb,item->>'json_pointer')
              OR jsonb_typeof(item->'value') NOT IN ('string','number','boolean','null')
              OR item->>'scalar_kind' IS DISTINCT FROM (CASE WHEN jsonb_typeof(item->'value')='string'
                    THEN 'text' ELSE jsonb_typeof(item->'value') END) THEN
              RAISE EXCEPTION 'source_property_exact_statement_pointer_required' USING ERRCODE='23514'; END IF;
          END LOOP;
          FOR item IN SELECT value FROM jsonb_array_elements(values_body->'sites') LOOP
            IF item IS DISTINCT FROM jsonb_build_object('json_pointer',item->'json_pointer','value',item->'value')
              OR left(item->>'json_pointer',length(NEW.source_json_pointer)+1)<>NEW.source_json_pointer||'/'
              OR item->'value' IS DISTINCT FROM public.sclib_source_property_pointer_v1(
                  p.source_public_json::jsonb,item->>'json_pointer') THEN
              RAISE EXCEPTION 'source_property_exact_site_pointer_required' USING ERRCODE='23514'; END IF;
          END LOOP;
          IF NEW.profile='cif_declared_operations' AND values_body->'operations' IS DISTINCT FROM
              (CASE WHEN jsonb_typeof(entry->'value')='array' THEN entry->'value' ELSE entry->'value'->'operations_raw' END)
            OR NEW.profile<>'cif_declared_operations' AND values_body->'operations'<>'[]'::jsonb THEN
            RAISE EXCEPTION 'source_property_exact_declared_operations_required' USING ERRCODE='23514'; END IF;
        ELSE
          SELECT * INTO o FROM public.source_property_observation_revisions WHERE id=NEW.observation_id;
          SELECT * INTO h FROM public.source_property_review_appends WHERE observation_id=NEW.observation_id
            ORDER BY review_number DESC LIMIT 1;
          IF NEW.action='withdraw_note' AND (h.id IS NULL OR h.actor_user_id<>NEW.actor_user_id OR h.action='withdraw_note') THEN
            RAISE EXCEPTION 'source_property_withdraw_own_preceding_note_required' USING ERRCODE='23514'; END IF;
          body:=NEW.review_json::jsonb;
          IF o.id IS NULL OR o.record_sha256<>NEW.observation_sha256
            OR NEW.predecessor_id IS DISTINCT FROM h.id
            OR NEW.predecessor_sha256 IS DISTINCT FROM h.record_sha256
            OR NEW.review_number<>COALESCE(h.review_number,0)+1
            OR body->>'scope' IS DISTINCT FROM 'source_expression_fidelity_note'
            OR body->>'action' IS DISTINCT FROM NEW.action
            OR body->>'observation_id' IS DISTINCT FROM NEW.observation_id::text
            OR body->>'observation_sha256' IS DISTINCT FROM NEW.observation_sha256
            OR body->'source_inspection_attested' IS DISTINCT FROM 'true'::jsonb
            OR jsonb_typeof(body->'checks') IS DISTINCT FROM 'array'
            OR jsonb_array_length(body->'checks') NOT BETWEEN 1 AND 6
            OR (SELECT count(DISTINCT value) FROM jsonb_array_elements(body->'checks'))<>jsonb_array_length(body->'checks')
            OR EXISTS(SELECT 1 FROM jsonb_array_elements(body->'checks') item(value)
                      WHERE jsonb_typeof(value) IS DISTINCT FROM 'string'
                        OR value #>> '{{}}' NOT IN ('source_expression','source_locator','raw_units','source_subject',
                                                   'source_window','derivation_role'))
            OR jsonb_typeof(body->'note') IS DISTINCT FROM 'string'
            OR length(body->>'note') NOT BETWEEN 1 AND 2000
            OR btrim(body->>'note') IS DISTINCT FROM body->>'note' OR body->>'note' ~ '[[:cntrl:]]'
            OR body-ARRAY['scope','action','observation_id','observation_sha256','source_inspection_attested',
                          'checks','note']<>'{{}}'::jsonb
            OR public.sclib_source_property_hash_v1(NEW.review_json)<>NEW.review_sha256 THEN
            RAISE EXCEPTION 'source_property_exact_review_note_required' USING ERRCODE='23514'; END IF;
          expected_request:=body||jsonb_build_object('request_key',NEW.request_key,
            'expected_previous_review_id',NEW.predecessor_id,'expected_previous_review_sha256',NEW.predecessor_sha256);
          expected_preview:=jsonb_build_object('version','source-property-pending/1.0.0',
            'actor',jsonb_build_object('actor_user_id',NEW.actor_user_id,'actor_grant_id',NEW.actor_grant_id,
                                      'actor_session_version',NEW.actor_session_version),
            'request_sha256',NEW.request_sha256,'observation_sha256',NEW.observation_sha256,
            'previous_review_sha256',NEW.predecessor_sha256);
          IF NEW.request_sha256<>public.sclib_source_property_hash_v1(
              public.sclib_scientific_import_canonical_v1(expected_request))
            OR NEW.preview_sha256<>public.sclib_source_property_hash_v1(
              public.sclib_scientific_import_canonical_v1(expected_preview)) THEN
            RAISE EXCEPTION 'source_property_exact_review_preview_required' USING ERRCODE='23514'; END IF;
        END IF;
        hash_body:=to_jsonb(NEW)-ARRAY['record_sha256','created_at','assembly_xid'];
        IF NEW.record_sha256<>public.sclib_source_property_hash_v1(
          public.sclib_scientific_import_canonical_v1(hash_body)) THEN
          RAISE EXCEPTION 'source_property_record_hash_required' USING ERRCODE='23514'; END IF;
        RETURN NEW;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_source_property_complete_v1() RETURNS trigger {_SQL} AS $$
      DECLARE p public.source_property_import_receipts%ROWTYPE; item jsonb;
      BEGIN
        IF TG_TABLE_NAME='source_property_import_receipts' THEN p:=NEW;
        ELSE SELECT * INTO p FROM public.source_property_import_receipts WHERE id=NEW.import_receipt_id; END IF;
        IF (SELECT count(*) FROM public.source_property_observation_revisions WHERE import_receipt_id=p.id)
          <>p.observation_count THEN
          RAISE EXCEPTION 'source_property_complete_inventory_required' USING ERRCODE='23514'; END IF;
        FOR item IN SELECT value FROM jsonb_array_elements(p.observation_manifest) LOOP
          IF NOT EXISTS(SELECT 1 FROM public.source_property_observation_revisions o WHERE o.import_receipt_id=p.id
            AND o.source_entry_id=item->>'source_entry_id' AND o.entry_sha256=item->>'entry_sha256'
            AND o.projection_sha256=item->>'projection_sha256') THEN
            RAISE EXCEPTION 'source_property_complete_exact_projection_required' USING ERRCODE='23514'; END IF;
        END LOOP;
        RETURN NULL;
      END $$
    """]
    for name in TABLE_ORDER:
        statements.extend([
            f"CREATE TRIGGER sp82_insert BEFORE INSERT ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_source_property_insert_v1()",
            f"CREATE TRIGGER sp82_immutable BEFORE UPDATE OR DELETE ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_source_property_immutable_v1()",
            f"CREATE TRIGGER sp82_truncate BEFORE TRUNCATE ON public.{name} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_source_property_immutable_v1()",
        ])
    for name in TABLE_ORDER[:2]:
        statements.append(f"CREATE CONSTRAINT TRIGGER sp82_complete AFTER INSERT ON public.{name} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.sclib_source_property_complete_v1()")
    return statements


def register(metadata):
    tables = {}

    def col(name, kind, *, nullable=False, default=None):
        return sa.Column(name, kind, nullable=nullable, server_default=default)

    def uid(name, target=None, *, nullable=False):
        refs = [sa.ForeignKey(target, ondelete="RESTRICT", onupdate="RESTRICT")] if target else []
        return sa.Column(name, UUID(as_uuid=True), *refs, nullable=nullable)

    def actor():
        return (uid("actor_user_id", "users.id"), uid("actor_grant_id", "research_role_grants.id"),
                col("actor_session_version", sa.Integer))

    def table(name, *items):
        short = str(TABLE_ORDER.index(name))
        checks = [sa.CheckConstraint(f"{item.name} IS NULL OR {item.name} ~ '^[0-9a-f]{{64}}$'",
                  name="ck_sp82_" + short + "_" + item.name)
                  for item in items if isinstance(item, sa.Column) and item.name.endswith("sha256")]
        tables[name] = sa.Table(name, metadata, uid("id"), *actor(), *items,
            col("record_sha256", sa.String(64)),
            col("created_at", sa.DateTime(timezone=True), default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"), *checks,
            sa.CheckConstraint("record_sha256 ~ '^[0-9a-f]{64}$'", name="ck_sp82_" + short + "_record"),
            sa.CheckConstraint("actor_session_version>=0 AND isfinite(created_at)", name="ck_sp82_" + short + "_actor"))

    table(TABLE_ORDER[0], col("request_key", sa.String(160)), col("request_sha256", sa.String(64)),
        col("preview_sha256", sa.String(64)), col("source_json_sha256", sa.String(64)),
        col("original_batch_sha256", sa.String(64)), col("registry_sha256", sa.String(64)),
        col("batch_id", sa.String(100)), col("source_public_json", sa.Text),
        col("observation_manifest", JSONB), col("summary", JSONB), col("observation_count", sa.Integer),
        col("assembly_xid", sa.BigInteger, default=sa.text("txid_current()")),
        sa.UniqueConstraint("actor_user_id", "request_key", name="uq_sp82_import_request"),
        sa.UniqueConstraint("source_json_sha256", name="uq_sp82_snapshot"),
        sa.CheckConstraint("request_key ~ '^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$' AND observation_count IN (15,34) AND octet_length(source_public_json) BETWEEN 2 AND 1048576", name="ck_sp82_import_bounds"))
    table(TABLE_ORDER[1], uid("import_receipt_id", TABLE_ORDER[0] + ".id"),
        col("source_entry_id", sa.String(180)), col("source_json_pointer", sa.String(40)),
        col("source_json_sha256", sa.String(64)), col("original_batch_sha256", sa.String(64)),
        col("registry_sha256", sa.String(64)), col("entry_sha256", sa.String(64)),
        col("field_id", sa.String(160)), col("profile", sa.String(60)),
        col("revision_number", sa.Integer), uid("predecessor_id", TABLE_ORDER[1] + ".id", nullable=True),
        col("status", sa.String(20), default="pending"),
        col("association_status", sa.String(30), default="unestablished"),
        col("scientific_acceptance", sa.Boolean, default=sa.false()),
        col("display_context_material_id", sa.String(100), nullable=True),
        col("projection_json", sa.Text), col("projection_sha256", sa.String(64)),
        sa.UniqueConstraint("source_json_sha256", "source_entry_id", "revision_number", name="uq_sp82_entry_revision"),
        sa.UniqueConstraint("predecessor_id", name="uq_sp82_single_successor"),
        sa.CheckConstraint("revision_number=1 AND predecessor_id IS NULL AND status='pending' AND association_status='unestablished' AND scientific_acceptance=false AND display_context_material_id IS NULL", name="ck_sp82_pending_only"),
        sa.CheckConstraint("octet_length(projection_json) BETWEEN 2 AND 131072", name="ck_sp82_projection_bound"),
        sa.Index("idx_sp82_field", "field_id", "source_json_sha256", "source_entry_id"))
    table(TABLE_ORDER[2], uid("observation_id", TABLE_ORDER[1] + ".id"),
        col("observation_sha256", sa.String(64)), col("request_key", sa.String(160)),
        col("request_sha256", sa.String(64)), col("preview_sha256", sa.String(64)),
        col("review_number", sa.Integer), uid("predecessor_id", TABLE_ORDER[2] + ".id", nullable=True),
        col("predecessor_sha256", sa.String(64), nullable=True), col("action", sa.String(40)),
        col("review_json", sa.Text), col("review_sha256", sa.String(64)),
        sa.UniqueConstraint("actor_user_id", "request_key", name="uq_sp82_review_request"),
        sa.UniqueConstraint("observation_id", "review_number", name="uq_sp82_review_number"),
        sa.UniqueConstraint("predecessor_id", name="uq_sp82_review_successor"),
        sa.CheckConstraint("request_key ~ '^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$' AND review_number>0 AND action IN ('matches_inspected_source','requires_clarification','source_mismatch','withdraw_note') AND octet_length(review_json) BETWEEN 2 AND 16384 AND ((predecessor_id IS NULL AND predecessor_sha256 IS NULL AND review_number=1) OR (predecessor_id IS NOT NULL AND predecessor_sha256 IS NOT NULL AND review_number>1))", name="ck_sp82_review_bounds"))
    last = tables[TABLE_ORDER[-1]]
    for name in (*PARENTS, *TABLE_ORDER[:-1], "research_publication_epoch"):
        last.add_is_dependent_on(metadata.tables[name])
    for statement in guard_statements():
        sa.event.listen(last, "after_create", sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"))
    return tables
