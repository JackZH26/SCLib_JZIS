"""Additive 0063 exact RPS distribution governance, never ML/science approval.

Trusted services validate actual private bytes and root semantics. SQL guards
independently bind complete inventories, current row projections, explicit
accounts/grants and immutable permission/review/action chains. Account identity
is not human identity or legal proof. The frozen 0054/0055 contracts are unchanged.
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from services.research_release_spec import SPEC

VERSION = "research-distribution/1.0.0"
SCOPE = "rps_structured_bundle"
LOCK_KEY = 630017026
LOCK_FUNCTION = "sclib_research_distribution_lock_v1"
TABLE_ORDER = ("research_distribution_epoch", "research_distribution_packages",
               "research_distribution_dependencies", "research_distribution_permissions",
               "research_distribution_reviews", "research_distribution_actions")
HISTORY_TABLES = TABLE_ORDER[1:]
PARENT_TABLES = tuple(sorted(set(SPEC) | {"users", "research_role_grants", "research_releases"}))
IDENTITY_FIELDS = {name: "paper_id" if name == "paper_work_map" else "id" for name in SPEC}
MAX_DEPENDENCIES = 20_000
MAX_BINDINGS = 5_000
MAX_BYTES = 64 * 1024 * 1024
FUNCTION_SIGNATURES = (
    ("sclib_research_distribution_text_hash_v1", "text"),
    ("sclib_research_distribution_record_hash_v1", "jsonb"),
    ("sclib_research_distribution_role_v1", "uuid, uuid, text"),
    (LOCK_FUNCTION, ""), ("sclib_research_distribution_immutable_v1", ""),
    ("sclib_research_distribution_projection_v1", "text, text"),
    ("sclib_research_distribution_dependency_id_v1", "text, text, text"),
    ("sclib_research_distribution_root_v1", "jsonb, jsonb"),
    ("sclib_research_distribution_package_v1", "jsonb"),
    ("sclib_research_distribution_current_v1", "uuid"),
    ("sclib_research_distribution_permissions_v1", "uuid, text"),
    ("sclib_research_distribution_insert_v1", ""),
    ("sclib_research_distribution_complete_v1", ""),
)
_SQL = "LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp SET TimeZone='UTC'"


def guard_statements():
    fields = json.dumps({name: sorted(value["fields"]) for name, value in SPEC.items()}, separators=(",", ":"))
    identity_fields = json.dumps(IDENTITY_FIELDS, separators=(",", ":"))
    targets = ",".join("'target_" + name + "'" for name in sorted(SPEC))
    capsule_slots = ",".join("'capsule_release_" + str(index) + "'" for index in range(8))
    return ["""
      CREATE OR REPLACE FUNCTION public.sclib_research_distribution_text_hash_v1(body text) RETURNS text
      LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
        SELECT encode(public.digest(convert_to(body,'UTF8'),'sha256'),'hex')
      $$
    """, """
      CREATE OR REPLACE FUNCTION public.sclib_research_distribution_record_hash_v1(body jsonb) RETURNS text
      LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
        SELECT public.sclib_research_distribution_text_hash_v1('{'||COALESCE(string_agg(
          to_jsonb(key)::text||':'||value::text,',' ORDER BY key COLLATE "C"),'')||'}')
        FROM jsonb_each(body-ARRAY['created_at','record_sha256','binding_manifest','inventory_json',
          'projection_json','rights_projection_json','permission_manifest','assembly_xid'])
      $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_research_distribution_role_v1(actor uuid, actor_grant uuid, required_role text)
      RETURNS boolean {_SQL} AS $$
      BEGIN
        RETURN public.sclib_research_publication_role_v1(actor,actor_grant,required_role) AND EXISTS(
          SELECT 1 FROM public.research_role_grants g WHERE g.id=actor_grant
            AND g.record_sha256=public.sclib_research_distribution_record_hash_v1(to_jsonb(g)-'id'));
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.{LOCK_FUNCTION}() RETURNS void {_SQL} AS $$
      BEGIN
        PERFORM public.sclib_research_integrity_lock_v1();
        PERFORM public.sclib_research_publication_lock_v1();
        PERFORM public.sclib_source_lifecycle_lock_v1();
        IF NOT pg_try_advisory_xact_lock({LOCK_KEY}) THEN
          RAISE EXCEPTION 'research_distribution_busy_retry_transaction' USING ERRCODE='55P03'; END IF;
        UPDATE public.research_distribution_epoch SET epoch=epoch+1 WHERE id=1;
        IF NOT FOUND THEN RAISE EXCEPTION 'research_distribution_epoch_missing' USING ERRCODE='55000'; END IF;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_research_distribution_immutable_v1() RETURNS trigger {_SQL} AS $$
      BEGIN RAISE EXCEPTION 'research distribution history is append-only' USING ERRCODE='55000'; END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_research_distribution_projection_v1(target text, identifier text)
      RETURNS jsonb {_SQL} STABLE AS $$
      DECLARE row_value jsonb; answer jsonb; expected jsonb:='{fields}'::jsonb;
        identities jsonb:='{identity_fields}'::jsonb;
      BEGIN
        IF NOT expected ? target THEN
          RAISE EXCEPTION 'research_distribution_unsupported_target' USING ERRCODE='23514'; END IF;
        EXECUTE format('SELECT to_jsonb(t) FROM public.%I t WHERE %I::text=$1',target,identities->>target)
          INTO row_value USING identifier;
        IF row_value IS NULL THEN RETURN NULL; END IF;
        SELECT jsonb_object_agg(value,row_value->value) INTO answer
          FROM jsonb_array_elements_text(expected->target);
        RETURN answer;
      END $$
    """, """
      CREATE OR REPLACE FUNCTION public.sclib_research_distribution_dependency_id_v1(target text, identifier text, row_hash text)
      RETURNS text LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
        SELECT public.sclib_research_distribution_text_hash_v1(format(
          '{"row_id":%s,"row_sha256":%s,"table":%s,"version":"research-distribution-dependency/1.0.0"}',
          to_jsonb(identifier),to_jsonb(row_hash),to_jsonb(target)))
      $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_research_distribution_root_v1(item jsonb, dependencies jsonb)
      RETURNS void {_SQL} AS $$
      DECLARE root jsonb; identity jsonb; row_value jsonb; revision jsonb; capture jsonb; expected text[];
        key text; found boolean; expected_kind text;
      BEGIN
        root:=item->'root'; identity:=item->'identity';
        IF jsonb_typeof(item->'artifact_id') IS DISTINCT FROM 'string'
          OR item->>'artifact_id' !~ '^[A-Za-z0-9_.:-]{{1,120}}$'
          OR jsonb_typeof(item->'artifact_sha256') IS DISTINCT FROM 'string'
          OR item->>'artifact_sha256' !~ '^[0-9a-f]{{64}}$'
          OR jsonb_typeof(item->'artifact_kind') IS DISTINCT FROM 'string'
          OR item->>'artifact_kind' NOT IN ('material','state','action','profile_assignment','evidence','review','rubric','action_template','template_review')
          OR jsonb_typeof(root) IS DISTINCT FROM 'object' OR jsonb_typeof(root->'kind') IS DISTINCT FROM 'string' THEN
          RAISE EXCEPTION 'research_distribution_closed_root_required' USING ERRCODE='23514'; END IF;
        expected:=CASE root->>'kind'
          WHEN 'source_capture' THEN ARRAY['kind','source_revision_id','source_revision_record_sha256','capture_id','capture_record_sha256','bytes_sha256']
          WHEN 'frozen_result' THEN ARRAY['kind','manifest_sha256','table','row_id','row_sha256']
          WHEN 'internal_artifact' THEN ARRAY['kind','evidence_artifact_id','artifact_kind','record_sha256','bytes_sha256'] END;
        IF expected IS NULL OR NOT root ?& expected OR root-expected<>'{{}}'::jsonb THEN
          RAISE EXCEPTION 'research_distribution_closed_root_required' USING ERRCODE='23514'; END IF;
        FOREACH key IN ARRAY expected LOOP
          IF jsonb_typeof(root->key) IS DISTINCT FROM 'string' OR length(root->>key) NOT BETWEEN 1 AND 200
            OR (key LIKE '%sha256' AND root->>key !~ '^[0-9a-f]{{64}}$') THEN
            RAISE EXCEPTION 'research_distribution_closed_root_scalar' USING ERRCODE='23514'; END IF;
        END LOOP;
        IF item->>'artifact_kind' IN ('material','state') THEN
          IF jsonb_typeof(identity) IS DISTINCT FROM 'object'
            OR NOT identity ?& ARRAY['table','row_id','row_sha256'] OR identity-ARRAY['table','row_id','row_sha256']<>'{{}}'::jsonb
            OR jsonb_typeof(identity->'row_id') IS DISTINCT FROM 'string'
            OR jsonb_typeof(identity->'row_sha256') IS DISTINCT FROM 'string'
            OR identity->>'row_sha256' !~ '^[0-9a-f]{{64}}$'
            OR identity->>'table' IS DISTINCT FROM (CASE WHEN item->>'artifact_kind'='material' THEN 'materials' ELSE 'material_states' END) THEN
            RAISE EXCEPTION 'research_distribution_material_state_identity_required' USING ERRCODE='23514'; END IF;
          found:=false;
          FOR row_value IN SELECT dependencies->value FROM jsonb_array_elements_text(item->'dependency_ids') LOOP
            IF row_value->'table'=identity->'table' AND row_value->'row_id'=identity->'row_id'
              AND row_value->'row_sha256'=identity->'row_sha256' THEN found:=true; END IF;
          END LOOP;
          IF NOT found THEN RAISE EXCEPTION 'research_distribution_identity_dependency_missing' USING ERRCODE='23514'; END IF;
        ELSIF identity IS DISTINCT FROM 'null'::jsonb THEN
          RAISE EXCEPTION 'research_distribution_unexpected_identity' USING ERRCODE='23514'; END IF;
        IF root->>'kind'='internal_artifact' THEN
          expected_kind:=CASE item->>'artifact_kind' WHEN 'material' THEN 'other' WHEN 'state' THEN 'other'
            WHEN 'action' THEN 'other' WHEN 'review' THEN 'review' WHEN 'template_review' THEN 'review'
            WHEN 'profile_assignment' THEN 'policy' WHEN 'rubric' THEN 'policy' WHEN 'action_template' THEN 'policy' END;
          IF expected_kind IS NULL OR root->>'artifact_kind'<>expected_kind THEN
            RAISE EXCEPTION 'research_distribution_evidence_cannot_be_internal' USING ERRCODE='23514'; END IF;
          found:=false;
          FOR row_value IN SELECT dependencies->value FROM jsonb_array_elements_text(item->'dependency_ids') LOOP
            IF row_value->>'table'='evidence_artifacts' AND row_value->'row_id'=root->'evidence_artifact_id'
              AND row_value->'record_sha256'=root->'record_sha256' AND row_value->'bytes_sha256'=root->'bytes_sha256'
              AND row_value->'projection'->>'kind'=expected_kind
              AND row_value->'projection'->>'schema_version'='rps-artifact-record/1.0.0'
              AND row_value->'projection'->>'hash_status'='verified' THEN found:=true; END IF;
          END LOOP;
          IF NOT found THEN RAISE EXCEPTION 'research_distribution_internal_dependency_missing' USING ERRCODE='23514'; END IF;
        ELSIF root->>'kind'='source_capture' THEN
          IF item->>'artifact_kind'<>'evidence' THEN
            RAISE EXCEPTION 'research_distribution_source_root_kind' USING ERRCODE='23514'; END IF;
          FOR row_value IN SELECT dependencies->value FROM jsonb_array_elements_text(item->'dependency_ids') LOOP
            IF row_value->>'table'='source_revisions' AND row_value->'row_id'=root->'source_revision_id'
              AND row_value->'record_sha256'=root->'source_revision_record_sha256' THEN revision:=row_value; END IF;
            IF row_value->>'table'='source_captures' AND row_value->'row_id'=root->'capture_id'
              AND row_value->'record_sha256'=root->'capture_record_sha256'
              AND row_value->'bytes_sha256'=root->'bytes_sha256' THEN capture:=row_value; END IF;
          END LOOP;
          IF revision IS NULL OR capture IS NULL OR capture->'projection'->'source_revision_id' IS DISTINCT FROM revision->'row_id' THEN
            RAISE EXCEPTION 'research_distribution_exact_source_capture_dependency' USING ERRCODE='23514'; END IF;
        ELSE
          IF item->>'artifact_kind'<>'evidence' OR root->>'table' NOT IN ('material_claims','event_properties') THEN
            RAISE EXCEPTION 'research_distribution_result_root_kind' USING ERRCODE='23514'; END IF;
          found:=false;
          FOR row_value IN SELECT dependencies->value FROM jsonb_array_elements_text(item->'dependency_ids') LOOP
            IF row_value->'table'=root->'table' AND row_value->'row_id'=root->'row_id' AND row_value->'row_sha256'=root->'row_sha256'
              AND row_value->'capsule_manifest_sha256s' ? (root->>'manifest_sha256') THEN found:=true; END IF;
          END LOOP;
          IF NOT found THEN RAISE EXCEPTION 'research_distribution_result_pin_missing' USING ERRCODE='23514'; END IF;
        END IF;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_research_distribution_package_v1(row_value jsonb)
      RETURNS void {_SQL} AS $$
      DECLARE bindings jsonb; inventory jsonb; item jsonb; expected jsonb; deps jsonb;
        key text; count_items integer; binding_index jsonb; dependency_index jsonb;
      BEGIN
        IF octet_length(row_value->>'binding_manifest')+octet_length(row_value->>'inventory_json')>{MAX_BYTES}
          OR row_value->>'bindings_sha256' IS DISTINCT FROM public.sclib_research_distribution_text_hash_v1(row_value->>'binding_manifest')
          OR row_value->>'inventory_sha256' IS DISTINCT FROM public.sclib_research_distribution_text_hash_v1(row_value->>'inventory_json') THEN
          RAISE EXCEPTION 'research_distribution_inventory_bytes_or_hash' USING ERRCODE='23514'; END IF;
        bindings:=(row_value->>'binding_manifest')::jsonb;
        inventory:=(row_value->>'inventory_json')::jsonb;
        IF jsonb_typeof(bindings) IS DISTINCT FROM 'object'
          OR NOT bindings ?& ARRAY['version','release_id','release_manifest_sha256','public_bundle_sha256','bindings']
          OR bindings-ARRAY['version','release_id','release_manifest_sha256','public_bundle_sha256','bindings']<>'{{}}'::jsonb
          OR bindings->>'version' IS DISTINCT FROM 'research-distribution-bindings/1.0.0'
          OR jsonb_typeof(bindings->'bindings') IS DISTINCT FROM 'array'
          OR jsonb_typeof(inventory) IS DISTINCT FROM 'object'
          OR NOT inventory ?& ARRAY['version','release_id','release_manifest_sha256','public_bundle_sha256','bindings_sha256',
            'artifact_bindings','dependencies','scientific_acceptance','ml_training_approved','source_rights_verified',
            'current_authorization_checked','database_observation_authenticated']
          OR inventory-ARRAY['version','release_id','release_manifest_sha256','public_bundle_sha256','bindings_sha256',
            'artifact_bindings','dependencies','scientific_acceptance','ml_training_approved','source_rights_verified',
            'current_authorization_checked','database_observation_authenticated']<>'{{}}'::jsonb
          OR inventory->>'version' IS DISTINCT FROM 'research-distribution-inventory/1.0.0'
          OR inventory->>'bindings_sha256' IS DISTINCT FROM row_value->>'bindings_sha256'
          OR jsonb_typeof(inventory->'artifact_bindings') IS DISTINCT FROM 'array'
          OR jsonb_typeof(inventory->'dependencies') IS DISTINCT FROM 'array' THEN
          RAISE EXCEPTION 'research_distribution_closed_inventory_required' USING ERRCODE='23514'; END IF;
        FOREACH key IN ARRAY ARRAY['release_id','release_manifest_sha256','public_bundle_sha256'] LOOP
          IF jsonb_typeof(bindings->key) IS DISTINCT FROM 'string'
            OR bindings->key IS DISTINCT FROM row_value->key OR inventory->key IS DISTINCT FROM row_value->key THEN
            RAISE EXCEPTION 'research_distribution_exact_package_pins' USING ERRCODE='23514'; END IF;
        END LOOP;
        FOREACH key IN ARRAY ARRAY['scientific_acceptance','ml_training_approved','source_rights_verified',
          'current_authorization_checked','database_observation_authenticated'] LOOP
          IF inventory->key IS DISTINCT FROM 'false'::jsonb THEN
            RAISE EXCEPTION 'research_distribution_no_inferred_authority' USING ERRCODE='23514'; END IF;
        END LOOP;
        count_items:=jsonb_array_length(bindings->'bindings');
        IF count_items NOT BETWEEN 1 AND {MAX_BINDINGS}
          OR count_items<>jsonb_array_length(inventory->'artifact_bindings')
          OR jsonb_array_length(inventory->'dependencies') NOT BETWEEN 1 AND {MAX_DEPENDENCIES}
          OR (SELECT count(DISTINCT value->>'artifact_id') FROM jsonb_array_elements(bindings->'bindings'))<>count_items
          OR (SELECT count(DISTINCT value->>'artifact_id') FROM jsonb_array_elements(inventory->'artifact_bindings'))<>count_items
          OR (SELECT count(DISTINCT value->>'dependency_id') FROM jsonb_array_elements(inventory->'dependencies'))
              <>jsonb_array_length(inventory->'dependencies') THEN
          RAISE EXCEPTION 'research_distribution_exact_bounded_inventory' USING ERRCODE='23514'; END IF;
        SELECT jsonb_object_agg(value->>'artifact_id',value) INTO binding_index FROM jsonb_array_elements(bindings->'bindings');
        SELECT jsonb_object_agg(value->>'dependency_id',value) INTO dependency_index FROM jsonb_array_elements(inventory->'dependencies');
        FOR item IN SELECT value FROM jsonb_array_elements(inventory->'artifact_bindings') LOOP
          IF jsonb_typeof(item) IS DISTINCT FROM 'object'
            OR NOT item ?& ARRAY['artifact_id','artifact_sha256','artifact_kind','root','identity','dependency_ids']
            OR item-ARRAY['artifact_id','artifact_sha256','artifact_kind','root','identity','dependency_ids']<>'{{}}'::jsonb
            OR jsonb_typeof(item->'dependency_ids') IS DISTINCT FROM 'array'
            OR jsonb_array_length(item->'dependency_ids')=0
            OR item->'dependency_ids' IS DISTINCT FROM (SELECT jsonb_agg(value ORDER BY value COLLATE "C")
                FROM (SELECT DISTINCT value FROM jsonb_array_elements_text(item->'dependency_ids')) keys)
            OR binding_index->(item->>'artifact_id') IS DISTINCT FROM item-'dependency_ids' THEN
            RAISE EXCEPTION 'research_distribution_exact_artifact_binding' USING ERRCODE='23514'; END IF;
          FOR deps IN SELECT value FROM jsonb_array_elements(item->'dependency_ids') LOOP
            IF jsonb_typeof(deps) IS DISTINCT FROM 'string'
              OR NOT dependency_index ? (deps#>>'{{}}') THEN
              RAISE EXCEPTION 'research_distribution_root_dependency_missing' USING ERRCODE='23514'; END IF;
          END LOOP;
          PERFORM public.sclib_research_distribution_root_v1(item,dependency_index);
        END LOOP;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_research_distribution_current_v1(identifier uuid)
      RETURNS void {_SQL} AS $$
      DECLARE d public.research_distribution_dependencies%ROWTYPE; current_row jsonb; hash text;
        v_paper_id text; v_work_id uuid; v_material_id text; ancestor text; seen text[]; depth integer;
      BEGIN
        FOR d IN SELECT * FROM public.research_distribution_dependencies WHERE package_id=identifier LOOP
          current_row:=public.sclib_research_distribution_projection_v1(d.table_name,d.row_id);
          IF current_row IS NULL OR current_row IS DISTINCT FROM d.projection_json::jsonb THEN
            RAISE EXCEPTION 'research_distribution_current_dependency_changed' USING ERRCODE='23514'; END IF;
          FOR hash IN SELECT jsonb_array_elements_text(d.capsule_manifest_sha256s) LOOP
            IF EXISTS(SELECT 1 FROM public.research_releases r JOIN public.research_release_notices n ON n.release_id=r.id
                WHERE r.manifest_sha256=hash) THEN
              RAISE EXCEPTION 'research_distribution_capsule_notice_hold' USING ERRCODE='23514'; END IF;
          END LOOP;
          v_paper_id:=CASE WHEN d.table_name IN ('papers','paper_work_map') THEN d.row_id ELSE current_row->>'paper_id' END;
          IF v_paper_id IS NOT NULL AND (NOT EXISTS(SELECT 1 FROM public.papers WHERE id=v_paper_id)
            OR EXISTS(SELECT 1 FROM public.papers p WHERE p.id=v_paper_id AND lower(btrim(p.status)) IN
              ('retracted','withdrawn','corrected','disputed','excluded'))
            OR EXISTS(SELECT 1 FROM public.source_lifecycle_events e WHERE e.paper_id=v_paper_id)
            OR EXISTS(SELECT 1 FROM public.paper_work_map m JOIN public.works w ON w.id=m.work_id
                WHERE m.paper_id=v_paper_id AND m.review_status='accepted' AND
                  (lower(btrim(w.publication_status)) IN ('retracted','withdrawn','corrected','disputed','excluded')
                   OR EXISTS(SELECT 1 FROM public.source_lifecycle_events e WHERE e.work_id=w.id)))) THEN
            RAISE EXCEPTION 'research_distribution_source_lifecycle_hold' USING ERRCODE='23514'; END IF;
          v_work_id:=CASE WHEN d.table_name='works' THEN d.row_id::uuid ELSE (current_row->>'work_id')::uuid END;
          IF v_work_id IS NOT NULL AND (NOT EXISTS(SELECT 1 FROM public.works WHERE id=v_work_id)
            OR EXISTS(SELECT 1 FROM public.works w WHERE w.id=v_work_id AND lower(btrim(w.publication_status)) IN
              ('retracted','withdrawn','corrected','disputed','excluded'))
            OR EXISTS(SELECT 1 FROM public.source_lifecycle_events e WHERE e.work_id=v_work_id)) THEN
            RAISE EXCEPTION 'research_distribution_work_lifecycle_hold' USING ERRCODE='23514'; END IF;
          v_material_id:=CASE WHEN d.table_name='materials' THEN d.row_id ELSE current_row->>'material_id' END;
          seen:=ARRAY[]::text[]; depth:=0;
          WHILE v_material_id IS NOT NULL LOOP
            IF v_material_id=ANY(seen) OR depth>=33 THEN
              RAISE EXCEPTION 'research_distribution_material_ancestry_unavailable' USING ERRCODE='23514'; END IF;
            seen:=array_append(seen,v_material_id); depth:=depth+1;
            SELECT parent_material_id INTO ancestor FROM public.materials WHERE id=v_material_id
              AND needs_review IS NOT TRUE AND disputed IS NOT TRUE AND retracted IS NOT TRUE
              AND (review_reason IS NULL OR review_reason NOT LIKE 'provenance_quarantine%');
            IF NOT FOUND THEN RAISE EXCEPTION 'research_distribution_material_hold' USING ERRCODE='23514'; END IF;
            v_material_id:=ancestor;
          END LOOP;
        END LOOP;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_research_distribution_permissions_v1(identifier uuid, receipt_text text)
      RETURNS void {_SQL} AS $$
      DECLARE item jsonb; receipts jsonb; p public.research_distribution_permissions%ROWTYPE; expected integer;
      BEGIN
        receipts:=receipt_text::jsonb;
        SELECT dependency_count INTO expected FROM public.research_distribution_packages WHERE id=identifier;
        IF jsonb_typeof(receipts) IS DISTINCT FROM 'array' OR jsonb_array_length(receipts)<>expected
          OR (SELECT count(DISTINCT value->>'dependency_id') FROM jsonb_array_elements(receipts))<>expected THEN
          RAISE EXCEPTION 'research_distribution_complete_permissions_required' USING ERRCODE='23514'; END IF;
        FOR item IN SELECT value FROM jsonb_array_elements(receipts) LOOP
          IF jsonb_typeof(item) IS DISTINCT FROM 'object'
            OR NOT item ?& ARRAY['dependency_id','permission_id','permission_sha256']
            OR item-ARRAY['dependency_id','permission_id','permission_sha256']<>'{{}}'::jsonb
            OR jsonb_typeof(item->'dependency_id') IS DISTINCT FROM 'string'
            OR jsonb_typeof(item->'permission_id') IS DISTINCT FROM 'string'
            OR jsonb_typeof(item->'permission_sha256') IS DISTINCT FROM 'string' THEN
            RAISE EXCEPTION 'research_distribution_closed_permission_receipt' USING ERRCODE='23514'; END IF;
          SELECT * INTO p FROM public.research_distribution_permissions WHERE id=(item->>'permission_id')::uuid;
          IF p.id IS NULL OR p.package_id<>identifier OR p.dependency_id<>item->>'dependency_id'
            OR p.record_sha256<>item->>'permission_sha256' OR p.decision<>'allow'
            OR p.record_sha256<>public.sclib_research_distribution_record_hash_v1(to_jsonb(p))
            OR EXISTS(SELECT 1 FROM public.research_distribution_permissions WHERE supersedes_id=p.id)
            OR NOT public.sclib_research_distribution_role_v1(p.actor_user_id,p.actor_grant_id,'reviewer')
            OR p.rights_projection_json::jsonb IS DISTINCT FROM
              public.sclib_research_distribution_projection_v1('evidence_artifacts',p.rights_artifact_id::text) THEN
            RAISE EXCEPTION 'research_distribution_current_permission_required' USING ERRCODE='23514'; END IF;
        END LOOP;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_research_distribution_insert_v1() RETURNS trigger {_SQL} AS $$
      DECLARE p public.research_distribution_packages%ROWTYPE;
        previous public.research_distribution_permissions%ROWTYPE; review public.research_distribution_reviews%ROWTYPE;
        expected jsonb; item jsonb; actual jsonb; d jsonb; projection jsonb; target text; needed_role text;
        inventory jsonb; cap_hash text; cap_id uuid; index integer; count_items integer;
      BEGIN
        PERFORM public.{LOCK_FUNCTION}();
        NEW.created_at:=clock_timestamp();
        IF TG_TABLE_NAME='research_distribution_packages' THEN
          IF NOT public.sclib_research_distribution_role_v1(NEW.actor_user_id,NEW.actor_grant_id,'curator') THEN
            RAISE EXCEPTION 'research_distribution_explicit_curator_required' USING ERRCODE='42501'; END IF;
          PERFORM public.sclib_research_distribution_package_v1(to_jsonb(NEW));
          inventory:=NEW.inventory_json::jsonb;
          NEW.binding_count:=jsonb_array_length(inventory->'artifact_bindings');
          NEW.dependency_count:=jsonb_array_length(inventory->'dependencies');
          NEW.assembly_xid:=txid_current();
        ELSE
          SELECT * INTO p FROM public.research_distribution_packages WHERE id=NEW.package_id;
          IF p.id IS NULL OR p.record_sha256<>public.sclib_research_distribution_record_hash_v1(to_jsonb(p)) THEN
            RAISE EXCEPTION 'research_distribution_exact_package_required' USING ERRCODE='23514'; END IF;
          IF TG_TABLE_NAME='research_distribution_dependencies' THEN
            IF p.assembly_xid<>txid_current() THEN
              RAISE EXCEPTION 'research_distribution_registration_is_sealed' USING ERRCODE='23514'; END IF;
            IF jsonb_typeof(NEW.capsule_manifest_sha256s) IS DISTINCT FROM 'array'
              OR jsonb_array_length(NEW.capsule_manifest_sha256s)>8
              OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.capsule_manifest_sha256s) entry
                  WHERE jsonb_typeof(entry) IS DISTINCT FROM 'string' OR entry#>>'{{}}' !~ '^[0-9a-f]{{64}}$')
              OR NEW.capsule_manifest_sha256s IS DISTINCT FROM (SELECT COALESCE(jsonb_agg(value ORDER BY value COLLATE "C"),'[]'::jsonb)
                  FROM (SELECT DISTINCT value FROM jsonb_array_elements_text(NEW.capsule_manifest_sha256s)) keys) THEN
              RAISE EXCEPTION 'research_distribution_closed_capsule_inventory' USING ERRCODE='23514'; END IF;
            projection:=NEW.projection_json::jsonb;
            actual:=public.sclib_research_distribution_projection_v1(NEW.table_name,NEW.row_id);
            IF actual IS NULL OR actual IS DISTINCT FROM projection
              OR NEW.row_sha256<>public.sclib_research_distribution_text_hash_v1(NEW.projection_json)
              OR NEW.dependency_id<>public.sclib_research_distribution_dependency_id_v1(NEW.table_name,NEW.row_id,NEW.row_sha256)
              OR NEW.source_record_sha256 IS DISTINCT FROM projection->>'record_sha256'
              OR NEW.bytes_sha256 IS DISTINCT FROM (CASE WHEN NEW.table_name IN ('source_captures','evidence_artifacts')
                  THEN projection->>'bytes_sha256' ELSE NULL END) THEN
              RAISE EXCEPTION 'research_distribution_exact_dependency_projection' USING ERRCODE='23514'; END IF;
            d:=jsonb_build_object('dependency_id',NEW.dependency_id,'table',NEW.table_name,'row_id',NEW.row_id,
              'row_sha256',NEW.row_sha256,'record_sha256',NEW.source_record_sha256,'bytes_sha256',NEW.bytes_sha256,
              'projection',projection,'capsule_manifest_sha256s',NEW.capsule_manifest_sha256s);
            FOREACH target IN ARRAY ARRAY[{targets},{capsule_slots}] LOOP
              IF to_jsonb(NEW)->target IS DISTINCT FROM 'null'::jsonb THEN
                RAISE EXCEPTION 'research_distribution_derived_fk_only' USING ERRCODE='23514'; END IF;
            END LOOP;
            NEW:=jsonb_populate_record(NEW,jsonb_build_object('target_'||NEW.table_name,NEW.row_id));
            index:=0;
            FOR cap_hash IN SELECT jsonb_array_elements_text(NEW.capsule_manifest_sha256s) LOOP
              SELECT id INTO cap_id FROM public.research_releases WHERE manifest_sha256=cap_hash;
              IF cap_id IS NULL OR NOT EXISTS(SELECT 1 FROM public.research_release_pins pin WHERE pin.release_id=cap_id
                AND pin.table_name=NEW.table_name AND pin.row_id=NEW.row_id AND pin.row_sha256=NEW.row_sha256
                AND pin.row_data=projection) THEN
                RAISE EXCEPTION 'research_distribution_exact_capsule_pin_required' USING ERRCODE='23514'; END IF;
              NEW:=jsonb_populate_record(NEW,jsonb_build_object('capsule_release_'||index,cap_id));
              index:=index+1;
            END LOOP;
          ELSE
            needed_role:=CASE WHEN TG_TABLE_NAME='research_distribution_actions' THEN 'publisher' ELSE 'reviewer' END;
            IF NOT public.sclib_research_distribution_role_v1(NEW.actor_user_id,NEW.actor_grant_id,needed_role) THEN
              RAISE EXCEPTION 'research_distribution_explicit_role_required' USING ERRCODE='42501'; END IF;
            IF TG_TABLE_NAME='research_distribution_permissions' THEN
              IF NEW.supersedes_id IS NOT NULL THEN
                SELECT * INTO previous FROM public.research_distribution_permissions WHERE id=NEW.supersedes_id;
                IF previous.id IS NULL OR previous.package_id<>NEW.package_id OR previous.dependency_id<>NEW.dependency_id
                  OR previous.scope<>NEW.scope
                  OR previous.record_sha256<>public.sclib_research_distribution_record_hash_v1(to_jsonb(previous))
                  OR EXISTS(SELECT 1 FROM public.research_distribution_permissions WHERE supersedes_id=previous.id) THEN
                  RAISE EXCEPTION 'research_distribution_permission_predecessor_mismatch' USING ERRCODE='23514'; END IF;
              ELSIF NEW.decision='revoke' THEN
                RAISE EXCEPTION 'research_distribution_revoke_requires_predecessor' USING ERRCODE='23514'; END IF;
              IF NEW.decision='allow' THEN
                SELECT to_jsonb(dependency) INTO expected FROM public.research_distribution_dependencies dependency
                  WHERE dependency.package_id=p.id AND dependency.dependency_id=NEW.dependency_id;
                IF expected IS NULL OR (expected->>'projection_json')::jsonb IS DISTINCT FROM
                  public.sclib_research_distribution_projection_v1(expected->>'table_name',expected->>'row_id') THEN
                  RAISE EXCEPTION 'research_distribution_current_dependency_changed' USING ERRCODE='23514'; END IF;
                actual:=public.sclib_research_distribution_projection_v1('evidence_artifacts',NEW.rights_artifact_id::text);
                item:=jsonb_build_object('version','rps-distribution-rights/1.0.0','scope','rps_structured_bundle',
                  'package_id',p.id,'inventory_sha256',p.inventory_sha256,'dependency_id',NEW.dependency_id,
                  'dependency_row_sha256',expected->>'row_sha256','public_bundle_sha256',p.public_bundle_sha256,
                  'license_code',NEW.license_code,'basis_code',NEW.basis_code,'distribution_permitted',true,
                  'scientific_acceptance',false,'ml_training_approved',false);
                IF actual IS NULL OR actual IS DISTINCT FROM NEW.rights_projection_json::jsonb
                  OR NEW.rights_row_sha256<>public.sclib_research_distribution_text_hash_v1(NEW.rights_projection_json)
                  OR actual->>'kind' IS DISTINCT FROM 'review' OR actual->>'hash_status' IS DISTINCT FROM 'verified'
                  OR actual->>'schema_version' IS DISTINCT FROM 'rps-distribution-rights/1.0.0'
                  OR actual->'metadata' IS DISTINCT FROM jsonb_build_object('distribution_rights',item)
                  OR NEW.rights_record_sha256<>public.sclib_research_distribution_record_hash_v1(item)
                  OR NEW.rights_bytes_sha256<>NEW.rights_record_sha256
                  OR NEW.rights_record_sha256 IS DISTINCT FROM actual->>'record_sha256'
                  OR NEW.rights_bytes_sha256 IS DISTINCT FROM actual->>'bytes_sha256' THEN
                  RAISE EXCEPTION 'research_distribution_exact_rights_artifact_required' USING ERRCODE='23514'; END IF;
              ELSE
                IF NEW.license_code IS DISTINCT FROM previous.license_code
                  OR NEW.rights_artifact_id IS DISTINCT FROM previous.rights_artifact_id
                  OR NEW.rights_row_sha256 IS DISTINCT FROM previous.rights_row_sha256
                  OR NEW.rights_record_sha256 IS DISTINCT FROM previous.rights_record_sha256
                  OR NEW.rights_bytes_sha256 IS DISTINCT FROM previous.rights_bytes_sha256
                  OR NEW.rights_projection_json IS DISTINCT FROM previous.rights_projection_json THEN
                  RAISE EXCEPTION 'research_distribution_revoke_exact_predecessor_rights' USING ERRCODE='23514'; END IF;
              END IF;
            ELSE
              IF NEW.inventory_sha256<>p.inventory_sha256 OR NEW.actor_user_id=p.actor_user_id THEN
                RAISE EXCEPTION 'research_distribution_independent_exact_review_required' USING ERRCODE='42501'; END IF;
              IF TG_TABLE_NAME='research_distribution_reviews' THEN
                IF NEW.permission_manifest_sha256<>public.sclib_research_distribution_text_hash_v1(NEW.permission_manifest) THEN
                  RAISE EXCEPTION 'research_distribution_permission_manifest_hash' USING ERRCODE='23514'; END IF;
                IF NEW.disclosure_approved THEN
                  IF NOT public.sclib_research_distribution_role_v1(p.actor_user_id,p.actor_grant_id,'curator') THEN
                    RAISE EXCEPTION 'research_distribution_prior_actor_unavailable' USING ERRCODE='42501'; END IF;
                  PERFORM public.sclib_research_distribution_current_v1(p.id);
                  PERFORM public.sclib_research_distribution_permissions_v1(p.id,NEW.permission_manifest);
                END IF;
              ELSE
                SELECT * INTO review FROM public.research_distribution_reviews WHERE id=NEW.review_id;
                IF review.id IS NULL OR review.package_id<>p.id OR review.inventory_sha256<>p.inventory_sha256
                  OR review.disclosure_approved IS NOT TRUE OR review.actor_user_id=NEW.actor_user_id
                  OR review.record_sha256<>public.sclib_research_distribution_record_hash_v1(to_jsonb(review)) THEN
                  RAISE EXCEPTION 'research_distribution_third_actor_exact_approved_review' USING ERRCODE='42501'; END IF;
                IF NEW.kind='withdraw' THEN
                  IF NOT EXISTS(SELECT 1 FROM public.research_distribution_actions WHERE package_id=p.id
                    AND kind='publish' AND review_id=NEW.review_id) THEN
                    RAISE EXCEPTION 'research_distribution_withdraw_requires_publication' USING ERRCODE='23514'; END IF;
                ELSE
                  IF EXISTS(SELECT 1 FROM public.research_distribution_reviews WHERE package_id=p.id AND NOT disclosure_approved)
                    OR EXISTS(SELECT 1 FROM public.research_distribution_actions a JOIN public.research_distribution_packages other ON other.id=a.package_id
                      WHERE a.kind='publish' AND other.release_id=p.release_id AND other.release_manifest_sha256=p.release_manifest_sha256
                        AND other.public_bundle_sha256=p.public_bundle_sha256 AND NOT EXISTS(
                          SELECT 1 FROM public.research_distribution_actions withdrawn WHERE withdrawn.package_id=other.id AND withdrawn.kind='withdraw')) THEN
                    RAISE EXCEPTION 'research_distribution_review_hold_or_existing_publication' USING ERRCODE='23514'; END IF;
                  IF NOT public.sclib_research_distribution_role_v1(p.actor_user_id,p.actor_grant_id,'curator')
                    OR NOT public.sclib_research_distribution_role_v1(review.actor_user_id,review.actor_grant_id,'reviewer') THEN
                    RAISE EXCEPTION 'research_distribution_prior_actor_unavailable' USING ERRCODE='42501'; END IF;
                  PERFORM public.sclib_research_distribution_current_v1(p.id);
                  PERFORM public.sclib_research_distribution_permissions_v1(p.id,review.permission_manifest);
                END IF;
              END IF;
            END IF;
          END IF;
        END IF;
        NEW.record_sha256:=public.sclib_research_distribution_record_hash_v1(to_jsonb(NEW));
        RETURN NEW;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_research_distribution_complete_v1() RETURNS trigger {_SQL} AS $$
      DECLARE count_items integer; expected integer; declared jsonb; actual jsonb;
      BEGIN
        SELECT dependency_count,inventory_json::jsonb->'dependencies' INTO expected,declared
          FROM public.research_distribution_packages WHERE id=NEW.id;
        SELECT count(*) INTO count_items FROM public.research_distribution_dependencies WHERE package_id=NEW.id;
        IF expected IS NULL OR count_items<>expected THEN
          RAISE EXCEPTION 'research_distribution_incomplete_atomic_registration' USING ERRCODE='23514'; END IF;
        SELECT jsonb_agg(jsonb_build_object('dependency_id',d.dependency_id,'table',d.table_name,'row_id',d.row_id,
          'row_sha256',d.row_sha256,'record_sha256',d.source_record_sha256,'bytes_sha256',d.bytes_sha256,
          'projection',d.projection_json::jsonb,'capsule_manifest_sha256s',d.capsule_manifest_sha256s)
          ORDER BY d.dependency_id COLLATE "C") INTO actual
          FROM public.research_distribution_dependencies d WHERE d.package_id=NEW.id;
        IF actual IS DISTINCT FROM declared THEN
          RAISE EXCEPTION 'research_distribution_exact_atomic_inventory_required' USING ERRCODE='23514'; END IF;
        RETURN NULL;
      END $$
    """, "INSERT INTO public.research_distribution_epoch(id,epoch) VALUES (1,0)",
    *[statement for name in HISTORY_TABLES for statement in (
        f"CREATE TRIGGER rd63_insert BEFORE INSERT ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_research_distribution_insert_v1()",
        f"CREATE TRIGGER rd63_immutable_row BEFORE UPDATE OR DELETE ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_research_distribution_immutable_v1()",
        f"CREATE TRIGGER rd63_immutable_truncate BEFORE TRUNCATE ON public.{name} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_research_distribution_immutable_v1()",
    )], "CREATE CONSTRAINT TRIGGER rd63_complete AFTER INSERT ON public.research_distribution_packages "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.sclib_research_distribution_complete_v1()"]


def register(metadata):
    tables = {}

    def col(name, kind, *, nullable=False, default=None):
        return sa.Column(name, kind, nullable=nullable, server_default=default)

    def uid(name, target=None, *, nullable=False, default=None):
        args = [sa.ForeignKey(target, onupdate="RESTRICT", ondelete="RESTRICT")] if target else []
        return sa.Column(name, UUID(as_uuid=True), *args, nullable=nullable, server_default=default)

    def check(condition, name):
        return sa.CheckConstraint(condition, name="ck_rd63_" + name)

    def actor():
        return (uid("actor_user_id", "users.id"), uid("actor_grant_id", "research_role_grants.id"),
                col("request_key", sa.String(160)), check("request_key ~ '^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$'", "request_key"),
                sa.UniqueConstraint("actor_user_id", "request_key"))

    def reason():
        return col("reason_code", sa.String(160)), check("reason_code ~ '^[a-z][a-z0-9_]{0,159}$'", "reason")

    def history(name, *items):
        hash_checks = [check(f"{item.name} IS NULL OR {item.name} ~ '^[0-9a-f]{{64}}$'", item.name)
                       for item in items if isinstance(item, sa.Column) and item.name.endswith("sha256")]
        tables[name] = sa.Table(name, metadata,
            uid("id", default=sa.text("gen_random_uuid()")), *items, *hash_checks,
            col("record_sha256", sa.String(64), default="0" * 64),
            col("created_at", sa.DateTime(timezone=True), default=sa.func.clock_timestamp()),
            check("record_sha256 ~ '^[0-9a-f]{64}$' AND isfinite(created_at)", "record"), sa.PrimaryKeyConstraint("id"))

    tables[TABLE_ORDER[0]] = sa.Table(TABLE_ORDER[0], metadata, col("id", sa.Integer), col("epoch", sa.BigInteger),
        sa.PrimaryKeyConstraint("id"), check("id=1 AND epoch>=0", "epoch"))
    history("research_distribution_packages", col("release_id", sa.String(120)),
        col("release_manifest_sha256", sa.String(64)), col("public_bundle_sha256", sa.String(64)),
        col("scope", sa.String(40), default=SCOPE), col("policy_version", sa.String(80), default=VERSION),
        col("binding_manifest", sa.Text), col("bindings_sha256", sa.String(64)),
        col("inventory_json", sa.Text), col("inventory_sha256", sa.String(64)),
        col("binding_count", sa.Integer, default="0"), col("dependency_count", sa.Integer, default="0"),
        col("assembly_xid", sa.Numeric, default="0"), *actor(),
        check("scope='rps_structured_bundle' AND policy_version='research-distribution/1.0.0'", "package_scope"),
        check("release_id ~ '^[A-Za-z0-9_.:-]{1,120}$' AND release_id NOT IN ('.','..')", "release_id"),
        check(f"binding_count BETWEEN 1 AND {MAX_BINDINGS} AND dependency_count BETWEEN 1 AND {MAX_DEPENDENCIES} AND assembly_xid>0", "counts"),
        check(f"octet_length(binding_manifest)+octet_length(inventory_json)<={MAX_BYTES}", "package_bytes"),
        sa.Index("ix_rd63_release", "release_id", "release_manifest_sha256", "public_bundle_sha256"))
    target_columns = []
    for name in sorted(SPEC):
        key = IDENTITY_FIELDS[name]
        kind = UUID(as_uuid=True) if SPEC[name]["fields"][key]["type"] == "UUID" else sa.String(200)
        target_columns.append(sa.Column("target_" + name, kind,
            sa.ForeignKey(f"{name}.{key}", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True))
    target_columns.extend(uid("capsule_release_" + str(index), "research_releases.id", nullable=True) for index in range(8))
    history("research_distribution_dependencies", uid("package_id", "research_distribution_packages.id"),
        col("dependency_id", sa.String(64)), col("table_name", sa.String(100)), col("row_id", sa.String(200)),
        col("row_sha256", sa.String(64)), col("source_record_sha256", sa.String(64), nullable=True),
        col("bytes_sha256", sa.String(64), nullable=True), col("projection_json", sa.Text),
        col("capsule_manifest_sha256s", JSONB), *target_columns,
        check("dependency_id ~ '^[0-9a-f]{64}$' AND length(row_id) BETWEEN 1 AND 200", "dependency_id"),
        check("octet_length(projection_json)<=8388608 AND jsonb_typeof(projection_json::jsonb)='object'", "projection"),
        check("jsonb_typeof(capsule_manifest_sha256s)='array' AND jsonb_array_length(capsule_manifest_sha256s)<=8", "capsules"),
        sa.UniqueConstraint("package_id", "dependency_id"), sa.UniqueConstraint("package_id", "table_name", "row_id"))
    history("research_distribution_permissions", uid("package_id", "research_distribution_packages.id"),
        col("dependency_id", sa.String(64)), col("decision", sa.String(20)), col("scope", sa.String(40), default=SCOPE),
        col("license_code", sa.String(30)), uid("rights_artifact_id", "evidence_artifacts.id"),
        col("rights_row_sha256", sa.String(64)), col("rights_record_sha256", sa.String(64)),
        col("rights_bytes_sha256", sa.String(64)), col("rights_projection_json", sa.Text),
        uid("supersedes_id", "research_distribution_permissions.id", nullable=True),
        col("basis_code", sa.String(160)), *actor(), *reason(),
        check("decision IN ('allow','revoke') AND scope='rps_structured_bundle'", "permission_scope"),
        check("license_code IN ('CC0-1.0','CC-BY-4.0','CC-BY-SA-4.0','permission-on-file')", "license"),
        check("basis_code ~ '^[a-z][a-z0-9_]{0,159}$' AND (supersedes_id IS NULL OR supersedes_id<>id)", "basis"),
        check("octet_length(rights_projection_json)<=8388608 AND jsonb_typeof(rights_projection_json::jsonb)='object'", "rights_projection"),
        sa.ForeignKeyConstraint(["package_id", "dependency_id"], ["research_distribution_dependencies.package_id", "research_distribution_dependencies.dependency_id"],
                                onupdate="RESTRICT", ondelete="RESTRICT"),
        sa.UniqueConstraint("supersedes_id"),
        sa.Index("uq_rd63_permission_root", "package_id", "dependency_id", unique=True, postgresql_where=sa.text("supersedes_id IS NULL")))
    history("research_distribution_reviews", uid("package_id", "research_distribution_packages.id"),
        col("inventory_sha256", sa.String(64)), col("permission_manifest", sa.Text),
        col("permission_manifest_sha256", sa.String(64)), col("disclosure_approved", sa.Boolean),
        col("scientific_acceptance", sa.Boolean, default=sa.false()), col("ml_training_approved", sa.Boolean, default=sa.false()),
        *actor(), *reason(), check("scientific_acceptance=false AND ml_training_approved=false", "review_scope"),
        check("octet_length(permission_manifest)<=8388608 AND jsonb_typeof(permission_manifest::jsonb)='array'", "permission_manifest"))
    history("research_distribution_actions", uid("package_id", "research_distribution_packages.id"),
        uid("review_id", "research_distribution_reviews.id"), col("inventory_sha256", sa.String(64)),
        col("kind", sa.String(20)), *actor(), *reason(), check("kind IN ('publish','withdraw')", "action"),
        sa.UniqueConstraint("package_id", "kind"))
    last = tables[TABLE_ORDER[-1]]
    for name in PARENT_TABLES + TABLE_ORDER[:-1]:
        last.add_is_dependent_on(metadata.tables[name])
    for statement in guard_statements():
        sa.event.listen(last, "after_create", sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"))
    return tables
