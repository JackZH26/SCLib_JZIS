"""Exact-property review overlay; no frozen fact, source rights or ML grant.

The database captures its own bounded forward scientific basis. Extra source
rows are retained snapshots, not invented foreign keys or a new source registry.
The trusted caller authenticates the declared reviewer; SQL checks the current
account/grant and exact request. It cannot establish expertise or human identity.
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from services.research_release_spec import FKS, SPEC

TABLE_ORDER = ("scientific_result_subjects", "scientific_adjudication_requests", "scientific_result_decisions")
PARENTS = ("event_properties", "research_events", "materials", "material_states", "research_samples",
           "structure_records", "research_runs", "scientific_import_outcomes", "users", "research_role_grants")
LOCK_FUNCTION = "sclib_scientific_adjudication_lock_v1"
LOCK_KEY = 670017026
CATALOGUE_TABLES = ("materials", "papers", "works", "paper_work_map")
# Forward captured rows and exact reverse-impact inventories only. No epoch or
# new ledger trigger is replaced. These checks protect this transaction's new
# decisions; later transactions remain free to change sources and make them stale.
ASSEMBLY_WRITER_TABLES = tuple(sorted(set(SPEC) | {
    "research_release_pins", "research_releases", "research_publication_proposals",
    "research_distribution_dependencies", "research_distribution_packages",
    "scientific_import_outcomes", "scientific_import_attempts", "scientific_import_packages",
    "scientific_import_files", "source_lifecycle_events", "users", "research_role_grants", "research_role_revocations",
}))
SUBJECT_VERSION = "scientific-result-subject/1.0.0"
REQUEST_VERSION = "scientific-result-adjudication/1.0.0"
LIMITATIONS = ("conditions_remain_as_reported", "no_automatic_ml_or_publication_authority",
              "not_a_full_zone_stability_assessment", "review_does_not_establish_upstream_execution",
              "scope_is_sampled_q_points_only")
PROFILES = {
    "native-sampled-frequency-extraction/1.0.0": ("extraction_fidelity", "retained_native_sampled_frequency_minimum"),
    "recorded-sampled-frequency-fidelity/1.0.0": ("extraction_fidelity", "recorded_sampled_frequency_minimum"),
    "sampled-phonon-minimum-review/1.0.0": ("scientific_result", "sampled_frequency_minimum_only"),
}
FUNCTION_SIGNATURES = (
    ("sclib_scientific_adjudication_canonical_v1", "jsonb"),
    ("sclib_scientific_adjudication_text_hash_v1", "text"),
    ("sclib_scientific_adjudication_record_hash_v1", "jsonb"),
    ("sclib_scientific_adjudication_read_guard_v1", ""), (LOCK_FUNCTION, ""),
    ("sclib_scientific_adjudication_catalogue_writer_v1", ""),
    ("sclib_scientific_subject_projection_v1", "text, text"),
    ("sclib_scientific_subject_capture_v1", "uuid"),
    ("sclib_scientific_result_impact_capture_v1", "uuid"),
    ("sclib_scientific_adjudication_item_v1", "jsonb"),
    ("sclib_scientific_adjudication_complete_v1", "uuid"),
    ("sclib_scientific_adjudication_current_v1", "uuid"),
    ("sclib_scientific_adjudication_transaction_v1", ""),
    ("sclib_scientific_adjudication_assembly_writer_v1", ""),
    ("sclib_scientific_adjudication_deferred_v1", ""),
    ("sclib_scientific_adjudication_insert_v1", ""),
    ("sclib_scientific_adjudication_immutable_v1", ""),
)
_SQL = "LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp SET TimeZone='UTC'"
_MATERIAL = ("id", "formula", "formula_normalized", "composition_status", "composition_data", "parent_material_id",
             "formula_substrate", "formula_overlayer", "layer_thickness_nm")
_PAPER = ("id", "source", "arxiv_id", "doi", "external_id", "id_scheme", "related_paper_id", "title", "authors",
          "date_submitted", "date_published")
_WORK = ("id", "canonical_title", "canonical_doi", "canonical_arxiv_id", "identity_metadata")


def _literal(value):
    return "'" + json.dumps(value, separators=(",", ":")).replace("'", "''") + "'::jsonb"


def guard_statements():
    fields = {name: sorted(spec["fields"]) for name, spec in SPEC.items()}
    fields["materials"], fields["papers"], fields["works"] = list(_MATERIAL), list(_PAPER), list(_WORK)
    fields["research_events"] = [key for key in fields["research_events"]
        if key not in {"review_status", "validity_status", "decision_artifact_id", "record_sha256", "updated_at"}]
    # Mutable permission declarations are current read gates, not scientific identity.
    fields["evidence_artifacts"] = [key for key in fields["evidence_artifacts"] if key not in {"access", "license"}]
    fk_rules = {name: [[child, target, parent] for child, target, parent in rules
                      if all(key in fields[name] for key in child)] for name, rules in FKS.items()}
    return [f"""
      CREATE OR REPLACE FUNCTION public.sclib_scientific_adjudication_canonical_v1(body jsonb) RETURNS text
      {_SQL} IMMUTABLE AS $$ DECLARE result text; BEGIN
        IF jsonb_typeof(body)='object' THEN
          SELECT '{{'||COALESCE(string_agg(to_jsonb(key)::text||':'||public.sclib_scientific_adjudication_canonical_v1(value),
            ',' ORDER BY key COLLATE "C"),'')||'}}' INTO result FROM jsonb_each(body);
        ELSIF jsonb_typeof(body)='array' THEN
          SELECT '['||COALESCE(string_agg(public.sclib_scientific_adjudication_canonical_v1(value),',' ORDER BY n),'')||']'
            INTO result FROM jsonb_array_elements(body) WITH ORDINALITY a(value,n);
        ELSE result:=body::text; END IF; RETURN result;
      END $$
    """, """
      CREATE OR REPLACE FUNCTION public.sclib_scientific_adjudication_text_hash_v1(body text) RETURNS text
      LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
        SELECT encode(public.digest(convert_to(body,'UTF8'),'sha256'),'hex')
      $$
    """, """
      CREATE OR REPLACE FUNCTION public.sclib_scientific_adjudication_record_hash_v1(body jsonb) RETURNS text
      LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
        SELECT public.sclib_scientific_adjudication_text_hash_v1(public.sclib_scientific_adjudication_canonical_v1(
          body-ARRAY['created_at','record_sha256','basis_json','request_json','assembly_xid']))
      $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_scientific_adjudication_read_guard_v1() RETURNS void {_SQL} AS $$ BEGIN
        IF current_setting('transaction_isolation') NOT IN ('repeatable read','serializable')
          OR current_setting('TimeZone')<>'UTC'
          OR (SELECT setting::bigint NOT BETWEEN 1 AND 10000 FROM pg_settings WHERE name='statement_timeout') THEN
          RAISE EXCEPTION 'scientific_adjudication_bounded_snapshot_required' USING ERRCODE='25000'; END IF;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.{LOCK_FUNCTION}() RETURNS void {_SQL} AS $$ BEGIN
        PERFORM public.sclib_scientific_adjudication_read_guard_v1();
        PERFORM public.sclib_research_integrity_lock_v1();
        PERFORM public.sclib_research_publication_lock_v1();
        PERFORM public.sclib_source_lifecycle_lock_v1();
        IF NOT pg_try_advisory_xact_lock({LOCK_KEY}) THEN
          RAISE EXCEPTION 'scientific_adjudication_busy_retry' USING ERRCODE='55P03'; END IF;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_scientific_adjudication_catalogue_writer_v1() RETURNS trigger {_SQL} AS $$ BEGIN
        -- A read-committed catalogue writer must conflict with an old review
        -- snapshot, without freezing catalogue rows or inventing a review.
        PERFORM public.sclib_research_integrity_lock_v1(); RETURN NULL;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_scientific_subject_projection_v1(target text,identifier text)
      RETURNS jsonb {_SQL} STABLE AS $$
      DECLARE fields jsonb:={_literal(fields)}; expression text; result jsonb; size bigint; key text;
      BEGIN
        IF NOT fields ? target THEN RAISE EXCEPTION 'scientific_subject_unsupported_table' USING ERRCODE='23514'; END IF;
        key:=CASE WHEN target='paper_work_map' THEN 'paper_id' ELSE 'id' END;
        SELECT 'jsonb_build_object('||string_agg(quote_literal(value)||',t.'||quote_ident(value),',' ORDER BY value COLLATE "C")||')'
          INTO expression FROM jsonb_array_elements_text(fields->target);
        EXECUTE format('SELECT octet_length((%s)::text) FROM public.%I t WHERE %I::text=$1',expression,target,key) INTO size USING identifier;
        IF size IS NULL THEN RAISE EXCEPTION 'scientific_subject_source_unavailable' USING ERRCODE='23514'; END IF;
        IF size>8388608 THEN RAISE EXCEPTION 'scientific_subject_byte_limit' USING ERRCODE='54000'; END IF;
        EXECUTE format('SELECT %s FROM public.%I t WHERE %I::text=$1',expression,target,key) INTO result USING identifier;
        RETURN result;
      END $$
    """, _subject_capture(fk_rules), _impact_capture(), _item_guard(), _complete_guard(), *_current_guard(),
    f"""
      CREATE OR REPLACE FUNCTION public.sclib_scientific_adjudication_deferred_v1() RETURNS trigger {_SQL} AS $$ BEGIN
        IF TG_TABLE_NAME='scientific_adjudication_requests' THEN
          PERFORM public.sclib_scientific_adjudication_complete_v1(NEW.id);
          PERFORM public.sclib_scientific_adjudication_transaction_v1();
        ELSE PERFORM public.sclib_scientific_adjudication_complete_v1(NEW.request_id); END IF;
        RETURN NULL;
      END $$
    """, _insert_guard(), f"""
      CREATE OR REPLACE FUNCTION public.sclib_scientific_adjudication_immutable_v1() RETURNS trigger {_SQL} AS $$ BEGIN
        RAISE EXCEPTION 'scientific adjudication history is append-only' USING ERRCODE='55000'; END $$
    """, *[statement for name in TABLE_ORDER for statement in (
        f"CREATE TRIGGER sa67_insert BEFORE INSERT ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_scientific_adjudication_insert_v1()",
        f"CREATE TRIGGER sa67_immutable BEFORE UPDATE OR DELETE ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_scientific_adjudication_immutable_v1()",
        f"CREATE TRIGGER sa67_truncate BEFORE TRUNCATE ON public.{name} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_scientific_adjudication_immutable_v1()",
    )], *[f"CREATE CONSTRAINT TRIGGER sa67_complete AFTER INSERT ON public.{name} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.sclib_scientific_adjudication_deferred_v1()"
           for name in TABLE_ORDER[1:]], *[
        f"CREATE TRIGGER sa67_catalogue_writer BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.{name} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_scientific_adjudication_catalogue_writer_v1()"
        for name in CATALOGUE_TABLES], *[
        f"CREATE TRIGGER sa67_assembly_writer AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.{name} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_scientific_adjudication_assembly_writer_v1()"
        for name in ASSEMBLY_WRITER_TABLES]]


def _subject_capture(fk_rules):
    return f"""
      CREATE OR REPLACE FUNCTION public.sclib_scientific_subject_capture_v1(identifier uuid) RETURNS text {_SQL} STABLE AS $$
      DECLARE pending jsonb:=jsonb_build_array(jsonb_build_object('table','event_properties','row_id',identifier::text));
        seen jsonb:='{{}}'; records jsonb:='[]'; artifacts jsonb:='[]'; support jsonb; current jsonb; snapshot jsonb;
        target text; row_id text; key text; rule jsonb; child text; parent_id text; relation text; extra record;
        rules jsonb:={_literal(fk_rules)}; property jsonb; event jsonb; state jsonb; run jsonb;
        native jsonb; outcome public.scientific_import_outcomes%ROWTYPE; package public.scientific_import_packages%ROWTYPE;
        file_count bigint; file_size bigint; n integer:=0; size bigint:=0; body text;
      BEGIN
        PERFORM public.sclib_scientific_adjudication_read_guard_v1();
        SELECT o.* INTO outcome FROM public.scientific_import_outcomes o WHERE o.property_id=identifier AND o.outcome='success_pending' LIMIT 1;
        IF outcome.id IS NOT NULL THEN
          SELECT p.* INTO package FROM public.scientific_import_packages p JOIN public.scientific_import_attempts a ON a.package_id=p.id WHERE a.id=outcome.attempt_id;
          FOR extra IN SELECT f.artifact_id FROM public.scientific_import_files f WHERE f.package_id=package.id LIMIT 20 LOOP
            pending:=pending||jsonb_build_array(jsonb_build_object('table','evidence_artifacts','row_id',extra.artifact_id::text));
          END LOOP;
        END IF;
        WHILE jsonb_array_length(pending)>0 LOOP
          current:=pending->0; pending:=pending-0; target:=current->>'table'; row_id:=current->>'row_id'; key:=target||':'||row_id;
          IF seen ? key THEN CONTINUE; END IF;
          n:=n+1; IF n>1000 THEN RAISE EXCEPTION 'scientific_subject_row_limit' USING ERRCODE='54000'; END IF;
          snapshot:=public.sclib_scientific_subject_projection_v1(target,row_id);
          size:=size+octet_length(snapshot::text)+octet_length(row_id)+octet_length(target)+100;
          IF size>8388608 THEN RAISE EXCEPTION 'scientific_subject_byte_limit' USING ERRCODE='54000'; END IF;
          seen:=seen||jsonb_build_object(key,true);
          records:=records||jsonb_build_array(jsonb_build_object('table',target,'row_id',row_id,'snapshot',snapshot));
          IF target='event_properties' AND row_id=identifier::text THEN property:=snapshot; END IF;
          FOR rule IN SELECT value FROM jsonb_array_elements(COALESCE(rules->target,'[]'::jsonb)) LOOP
            child:=rule->0->>0; parent_id:=snapshot->>child; relation:=rule->>1;
            IF parent_id IS NOT NULL THEN
              pending:=pending||jsonb_build_array(jsonb_build_object('table',relation,'row_id',parent_id)); END IF;
          END LOOP;
          IF target='research_events' THEN
            FOR extra IN SELECT id,'event_evidence' AS tab FROM public.event_evidence WHERE event_id=row_id::uuid
              UNION ALL SELECT id,'snapshot_event_memberships' FROM public.snapshot_event_memberships WHERE event_id=row_id::uuid
              LIMIT 1001 LOOP
              pending:=pending||jsonb_build_array(jsonb_build_object('table',extra.tab,'row_id',extra.id::text));
            END LOOP;
          ELSIF target='material_claims' THEN
            FOR extra IN SELECT id FROM public.claim_source_occurrences WHERE claim_id=row_id::uuid LIMIT 1001 LOOP
              pending:=pending||jsonb_build_array(jsonb_build_object('table','claim_source_occurrences','row_id',extra.id::text)); END LOOP;
          ELSIF target='papers' THEN
            IF EXISTS(SELECT 1 FROM public.paper_work_map WHERE paper_id=row_id) THEN
              pending:=pending||jsonb_build_array(jsonb_build_object('table','paper_work_map','row_id',row_id)); END IF;
          END IF;
          IF jsonb_array_length(pending)+n>3000 THEN RAISE EXCEPTION 'scientific_subject_reference_limit' USING ERRCODE='54000'; END IF;
          IF target='evidence_artifacts' THEN
            artifacts:=artifacts||jsonb_build_array(jsonb_build_object('artifact_id',row_id,'bytes_sha256',snapshot->'bytes_sha256','hash_status',snapshot->'hash_status'));
            IF jsonb_array_length(artifacts)>200 THEN RAISE EXCEPTION 'scientific_subject_artifact_limit' USING ERRCODE='54000'; END IF;
          END IF;
        END LOOP;
        SELECT value->'snapshot' INTO event FROM jsonb_array_elements(records) WHERE value->>'table'='research_events' AND value->>'row_id'=property->>'event_id';
        SELECT value->'snapshot' INTO state FROM jsonb_array_elements(records) WHERE value->>'table'='material_states' AND value->>'row_id'=event->>'state_id';
        SELECT value->'snapshot' INTO run FROM jsonb_array_elements(records) WHERE value->>'table'='research_runs' AND value->>'row_id'=event->>'producer_run_id';
        IF property->>'property_key' IN ('tc','tc_kelvin') OR left(property->>'property_key',4)='rps_'
          OR event->>'event_type'='priority_assessment' THEN RAISE EXCEPTION 'scientific_subject_unsupported_property' USING ERRCODE='23514'; END IF;
        SELECT o.* INTO outcome FROM public.scientific_import_outcomes o WHERE o.property_id=identifier AND o.outcome='success_pending' LIMIT 1;
        IF outcome.id IS NOT NULL THEN
          SELECT p.* INTO package FROM public.scientific_import_packages p JOIN public.scientific_import_attempts a ON a.package_id=p.id WHERE a.id=outcome.attempt_id;
          SELECT count(*),COALESCE(sum(octet_length(artifact_id::text)+octet_length(sha256)+64),0) INTO file_count,file_size
            FROM public.scientific_import_files WHERE package_id=package.id;
          IF file_count>19 OR file_size>65536 THEN RAISE EXCEPTION 'scientific_subject_native_source_limit' USING ERRCODE='54000'; END IF;
          SELECT jsonb_build_object('outcome_id',outcome.id,'outcome_sha256',outcome.record_sha256,'package_id',package.id,
            'package_sha256',package.record_sha256,'source_files',COALESCE(jsonb_agg(jsonb_build_object('file_id',f.id,
            'artifact_id',f.artifact_id,'sha256',f.sha256,'size_bytes',f.size_bytes) ORDER BY f.id),'[]'::jsonb))
            INTO native FROM public.scientific_import_files f WHERE f.package_id=package.id;
        END IF;
        SELECT COALESCE(jsonb_agg(to_jsonb(id) ORDER BY id),'[]'::jsonb) INTO support FROM (
          SELECT artifact_id::text AS id FROM public.event_evidence WHERE event_id=(event->>'id')::uuid AND artifact_id IS NOT NULL
          UNION SELECT state->>'source_artifact_id' UNION SELECT run->>'input_manifest_id' UNION SELECT run->>'output_manifest_id'
        ) q WHERE id IS NOT NULL;
        SELECT jsonb_agg(value ORDER BY value->>'table' COLLATE "C",value->>'row_id' COLLATE "C") INTO records FROM jsonb_array_elements(records);
        SELECT COALESCE(jsonb_agg(value ORDER BY value->>'artifact_id'),'[]'::jsonb) INTO artifacts FROM jsonb_array_elements(artifacts);
        body:=public.sclib_scientific_adjudication_canonical_v1(jsonb_build_object('version','{SUBJECT_VERSION}',
          'target',jsonb_build_object('property_id',identifier,'event_id',event->'id','event_revision',event->'revision',
          'material_id',event->'material_id','state_id',event->'state_id','sample_id',state->'sample_id','structure_id',event->'structure_id',
          'producer_run_id',event->'producer_run_id','native_outcome_id',outcome.id),
          'rows',records,'artifacts',artifacts,'support_artifact_ids',support,'native_import',native));
        IF octet_length(body)>8388608 THEN RAISE EXCEPTION 'scientific_subject_byte_limit' USING ERRCODE='54000'; END IF;
        RETURN body;
      END $$
    """


def _impact_capture():
    # Fixed copies of the bounded reader's declared scope, not an expansion of it.
    scope = ("exact_target_property_event_pair", "direct_ml_input_property_and_event_references",
        "owning_ml_examples_and_dataset_snapshots", "direct_event_snapshot_memberships",
        "one_hop_derives_from_input_event_references", "reached_row_frozen_pins_and_release_references",
        "exact_release_publication_proposal_references", "exact_distribution_dependency_and_capsule_release_references")
    tables = ("event_properties", "research_events", "ml_example_inputs", "ml_examples", "ml_dataset_snapshots",
        "snapshot_event_memberships", "source_snapshots", "event_evidence", "research_release_pins", "research_releases",
        "research_publication_proposals", "research_distribution_dependencies", "research_distribution_packages")
    unsupported = ("transitive_event_and_feature_dependencies", "property_specific_causality_of_event_context_or_sibling_results",
        "label_claims_not_reached_through_explicit_ml_inputs", "unregistered_json_text_formula_or_sample_name_matches",
        "file_backed_releases_cached_answers_and_external_vector_state", "scientific_validity_refresh_completion_or_current_distribution_authorization",
        "dependencies_created_after_this_database_snapshot")
    return f"""
      CREATE OR REPLACE FUNCTION public.sclib_scientific_result_impact_capture_v1(identifier uuid) RETURNS text {_SQL} STABLE AS $$
      DECLARE event_id uuid; items jsonb:='[]'; nodes jsonb; releases uuid[]; counts jsonb; body text; item record;
        query text; phase integer; batch integer; name text;
      BEGIN
        PERFORM public.sclib_scientific_adjudication_read_guard_v1();
        SELECT p.event_id INTO event_id FROM public.event_properties p WHERE p.id=identifier;
        IF event_id IS NULL THEN RAISE EXCEPTION 'scientific_impact_target_unavailable' USING ERRCODE='23514'; END IF;
        items:=jsonb_build_array(jsonb_build_object('table','event_properties','row_id',identifier::text,'relation','target_property','via_table','research_events','via_id',event_id::text),
          jsonb_build_object('table','research_events','row_id',event_id::text,'relation','target_event','via_table','research_events','via_id',event_id::text));
        FOR phase IN 1..6 LOOP
          SELECT COALESCE(jsonb_agg(x),'[]'::jsonb) INTO nodes FROM (SELECT DISTINCT value->>'table' AS table_name,value->>'row_id' AS row_id FROM jsonb_array_elements(items)) x;
          SELECT array_agg(DISTINCT (value->>'row_id')::uuid) INTO releases FROM jsonb_array_elements(items) WHERE value->>'table'='research_releases';
          query:=CASE phase
          WHEN 1 THEN 'SELECT i.id,i.input_property_id,i.input_event_id,x.id AS example_id,d.id AS dataset_id FROM public.ml_example_inputs i JOIN public.ml_examples x ON x.id=i.example_id JOIN public.ml_dataset_snapshots d ON d.id=x.dataset_snapshot_id WHERE i.input_event_id=$1 LIMIT 1001'
          WHEN 2 THEN 'SELECT id,snapshot_id FROM public.snapshot_event_memberships WHERE event_id=$1 LIMIT 1001'
          WHEN 3 THEN 'SELECT id,event_id,input_property_id FROM public.event_evidence WHERE input_event_id=$1 AND link_type=''derives_from'' LIMIT 1001'
          WHEN 4 THEN 'SELECT p.id,p.release_id,p.table_name,p.row_id FROM public.research_release_pins p JOIN jsonb_to_recordset($2) x(table_name text,row_id text) ON x.table_name=p.table_name AND x.row_id=p.row_id LIMIT 1001'
          WHEN 5 THEN 'SELECT id,release_id FROM public.research_publication_proposals WHERE release_id=ANY($3) LIMIT 1001'
          WHEN 6 THEN 'SELECT d.id,d.package_id,d.table_name,d.row_id FROM public.research_distribution_dependencies d JOIN jsonb_to_recordset($2) x(table_name text,row_id text) ON x.table_name=d.table_name AND x.row_id=d.row_id LIMIT 1001' END;
          batch:=0;
          FOR item IN EXECUTE query USING event_id,nodes,releases LOOP
            batch:=batch+1; IF batch>1000 THEN RAISE EXCEPTION 'scientific_impact_query_limit' USING ERRCODE='54000'; END IF;
            IF phase=1 THEN
              IF item.input_property_id=identifier THEN items:=items||jsonb_build_array(jsonb_build_object('table','ml_example_inputs','row_id',item.id::text,'relation','input_property_reference','via_table','event_properties','via_id',identifier::text)); END IF;
              items:=items||jsonb_build_array(jsonb_build_object('table','ml_example_inputs','row_id',item.id::text,'relation','input_event_reference','via_table','research_events','via_id',event_id::text),
                jsonb_build_object('table','ml_examples','row_id',item.example_id::text,'relation','input_owner','via_table','ml_example_inputs','via_id',item.id::text),
                jsonb_build_object('table','ml_dataset_snapshots','row_id',item.dataset_id::text,'relation','example_dataset_membership','via_table','ml_examples','via_id',item.example_id::text));
            ELSIF phase=2 THEN items:=items||jsonb_build_array(
              jsonb_build_object('table','snapshot_event_memberships','row_id',item.id::text,'relation','event_membership','via_table','research_events','via_id',event_id::text),
              jsonb_build_object('table','source_snapshots','row_id',item.snapshot_id::text,'relation','membership_snapshot','via_table','snapshot_event_memberships','via_id',item.id::text));
            ELSIF phase=3 THEN
              items:=items||jsonb_build_array(jsonb_build_object('table','event_evidence','row_id',item.id::text,'relation','derives_from_input_event','via_table','research_events','via_id',event_id::text),
                jsonb_build_object('table','research_events','row_id',item.event_id::text,'relation','one_hop_derivation_output','via_table','event_evidence','via_id',item.id::text));
              IF item.input_property_id=identifier THEN items:=items||jsonb_build_array(jsonb_build_object('table','event_evidence','row_id',item.id::text,'relation','derives_from_input_property','via_table','event_properties','via_id',identifier::text)); END IF;
            ELSIF phase=4 THEN items:=items||jsonb_build_array(
              jsonb_build_object('table','research_release_pins','row_id',item.id::text,'relation','historical_exact_row_pin','via_table',item.table_name,'via_id',item.row_id),
              jsonb_build_object('table','research_releases','row_id',item.release_id::text,'relation','historical_pin_release','via_table','research_release_pins','via_id',item.id::text));
            ELSIF phase=5 THEN items:=items||jsonb_build_array(jsonb_build_object('table','research_publication_proposals','row_id',item.id::text,'relation','historical_release_proposal','via_table','research_releases','via_id',item.release_id::text));
            ELSE items:=items||jsonb_build_array(
              jsonb_build_object('table','research_distribution_dependencies','row_id',item.id::text,'relation','historical_exact_row_dependency','via_table',item.table_name,'via_id',item.row_id),
              jsonb_build_object('table','research_distribution_packages','row_id',item.package_id::text,'relation','historical_dependency_package','via_table','research_distribution_dependencies','via_id',item.id::text)); END IF;
            IF jsonb_array_length(items)>8000 OR octet_length(items::text)>2097152 THEN RAISE EXCEPTION 'scientific_impact_graph_limit' USING ERRCODE='54000'; END IF;
          END LOOP;
          SELECT jsonb_agg(value) INTO items FROM (SELECT DISTINCT value FROM jsonb_array_elements(items)) q;
          IF jsonb_array_length(items)>4000 THEN RAISE EXCEPTION 'scientific_impact_graph_limit' USING ERRCODE='54000'; END IF;
        END LOOP;
        batch:=0;
        FOR item IN SELECT id,package_id,ARRAY[capsule_release_0,capsule_release_1,capsule_release_2,capsule_release_3,capsule_release_4,capsule_release_5,capsule_release_6,capsule_release_7] AS capsules
          FROM public.research_distribution_dependencies WHERE capsule_release_0=ANY(releases) OR capsule_release_1=ANY(releases)
          OR capsule_release_2=ANY(releases) OR capsule_release_3=ANY(releases) OR capsule_release_4=ANY(releases)
          OR capsule_release_5=ANY(releases) OR capsule_release_6=ANY(releases) OR capsule_release_7=ANY(releases) LIMIT 1001 LOOP
          batch:=batch+1; IF batch>1000 THEN RAISE EXCEPTION 'scientific_impact_query_limit' USING ERRCODE='54000'; END IF;
          FOR name IN SELECT DISTINCT value::text FROM unnest(item.capsules) value WHERE value=ANY(releases) LOOP
            items:=items||jsonb_build_array(jsonb_build_object('table','research_distribution_dependencies','row_id',item.id::text,'relation','historical_capsule_reference','via_table','research_releases','via_id',name)); END LOOP;
          items:=items||jsonb_build_array(jsonb_build_object('table','research_distribution_packages','row_id',item.package_id::text,'relation','historical_dependency_package','via_table','research_distribution_dependencies','via_id',item.id::text));
          IF jsonb_array_length(items)>16000 OR octet_length(items::text)>4194304 THEN RAISE EXCEPTION 'scientific_impact_graph_limit' USING ERRCODE='54000'; END IF;
        END LOOP;
        SELECT jsonb_agg(value ORDER BY value->>'table' COLLATE "C",value->>'row_id' COLLATE "C",value->>'relation' COLLATE "C",value->>'via_table' COLLATE "C",value->>'via_id' COLLATE "C") INTO items FROM (SELECT DISTINCT value FROM jsonb_array_elements(items)) q;
        SELECT jsonb_object_agg(t.name,(SELECT count(DISTINCT value->>'row_id') FROM jsonb_array_elements(items) WHERE value->>'table'=t.name)) INTO counts FROM jsonb_array_elements_text({_literal(tables)}) t(name);
        counts:=counts||jsonb_build_object('total_relations',jsonb_array_length(items),'total_nodes',(SELECT count(*) FROM (SELECT DISTINCT value->>'table',value->>'row_id' FROM jsonb_array_elements(items)) x));
        IF (counts->>'total_nodes')::int>2000 OR (counts->>'total_relations')::int>4000 THEN RAISE EXCEPTION 'scientific_impact_graph_limit' USING ERRCODE='54000'; END IF;
        body:=public.sclib_scientific_adjudication_canonical_v1(jsonb_build_object('version','scientific-result-impact/1.0.0','scope',{_literal(scope)},
          'unsupported_scopes',{_literal(unsupported)},'complete_for_scope',true,'counts',counts,'items',items));
        IF octet_length(body)>1048576 THEN RAISE EXCEPTION 'scientific_impact_byte_limit' USING ERRCODE='54000'; END IF; RETURN body;
      END $$
    """


def _item_guard():
    keys = ("decision_id", "subject_id", "property_id", "scope", "profile_version", "expected_subject_sha256",
        "expected_previous_decision_id", "expected_impact_sha256", "decision", "reason_code", "rationale", "proposition",
        "limitations", "checks", "evidence_refs", "source_inspection_attested", "resolves_decision_id", "extraction_decision_id")
    return f"""
      CREATE OR REPLACE FUNCTION public.sclib_scientific_adjudication_item_v1(item jsonb) RETURNS void {_SQL} AS $$
      DECLARE keys text[]:=ARRAY[{','.join(repr(key) for key in keys)}]; key text; profile jsonb:={_literal(PROFILES)}; ref jsonb;
      BEGIN
        IF jsonb_typeof(item) IS DISTINCT FROM 'object' OR NOT(item ?& keys) OR item-keys<>'{{}}'::jsonb THEN
          RAISE EXCEPTION 'scientific_adjudication_exact_item_required' USING ERRCODE='23514'; END IF;
        FOREACH key IN ARRAY ARRAY['decision_id','subject_id','property_id','expected_previous_decision_id','resolves_decision_id','extraction_decision_id'] LOOP
          IF key IN ('expected_previous_decision_id','resolves_decision_id','extraction_decision_id') AND item->key='null'::jsonb THEN CONTINUE; END IF;
          IF jsonb_typeof(item->key) IS DISTINCT FROM 'string' OR item->>key !~ '^[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}$' THEN
            RAISE EXCEPTION 'scientific_adjudication_canonical_uuid_required' USING ERRCODE='23514'; END IF;
        END LOOP;
        FOREACH key IN ARRAY ARRAY['expected_subject_sha256','expected_impact_sha256'] LOOP
          IF jsonb_typeof(item->key) IS DISTINCT FROM 'string' OR item->>key !~ '^[0-9a-f]{{64}}$' THEN
            RAISE EXCEPTION 'scientific_adjudication_hash_required' USING ERRCODE='23514'; END IF;
        END LOOP;
        FOREACH key IN ARRAY ARRAY['scope','profile_version','decision','reason_code','proposition','rationale'] LOOP
          IF jsonb_typeof(item->key) IS DISTINCT FROM 'string' THEN RAISE EXCEPTION 'scientific_adjudication_text_required' USING ERRCODE='23514'; END IF; END LOOP;
        IF NOT profile ? (item->>'profile_version') OR profile->(item->>'profile_version')->>0 IS DISTINCT FROM item->>'scope'
          OR profile->(item->>'profile_version')->>1 IS DISTINCT FROM item->>'proposition'
          OR item->'limitations' IS DISTINCT FROM {_literal(LIMITATIONS)}
          OR char_length(item->>'rationale') NOT BETWEEN 20 AND 2000
          OR char_length(btrim(item->>'rationale',E' \\n\\r\\t'||chr(160)||chr(5760)||chr(8192)||chr(8193)||chr(8194)||chr(8195)||chr(8196)||chr(8197)||chr(8198)||chr(8199)||chr(8200)||chr(8201)||chr(8202)||chr(8232)||chr(8233)||chr(8239)||chr(8287)||chr(12288)))<20
          OR regexp_replace(item->>'rationale',E'[\\n\\t]','','g') ~ '[[:cntrl:]]'
          OR EXISTS(SELECT 1 FROM regexp_split_to_table(item->>'rationale','') ch WHERE ascii(ch) BETWEEN 127 AND 159)
          OR jsonb_typeof(item->'source_inspection_attested') IS DISTINCT FROM 'boolean'
          OR jsonb_typeof(item->'checks') IS DISTINCT FROM 'object'
          OR NOT(item->'checks' ?& ARRAY['source_match','quantity_and_units','state_association','method_and_scope'])
          OR (item->'checks')-ARRAY['source_match','quantity_and_units','state_association','method_and_scope']<>'{{}}'::jsonb
          OR jsonb_typeof(item->'evidence_refs') IS DISTINCT FROM 'array'
          OR jsonb_array_length(item->'evidence_refs')>50 THEN
          RAISE EXCEPTION 'scientific_adjudication_profile_shape_required' USING ERRCODE='23514'; END IF;
        FOR key IN SELECT jsonb_object_keys(item->'checks') LOOP
          IF jsonb_typeof(item->'checks'->key) IS DISTINCT FROM 'string' OR item->'checks'->>key NOT IN ('satisfied','not_applicable','unresolved') THEN
            RAISE EXCEPTION 'scientific_adjudication_check_state_required' USING ERRCODE='23514'; END IF; END LOOP;
        IF NOT ((item->>'decision'='accept' AND item->>'reason_code'='evidence_and_scope_match')
          OR (item->>'decision'='reject' AND item->>'reason_code' IN ('source_mismatch','quantity_or_unit_mismatch','state_association_mismatch','method_or_scope_mismatch','scientific_concern'))
          OR (item->>'decision'='request_clarification' AND item->>'reason_code' IN ('insufficient_evidence','unresolved_state','unresolved_method','conflicting_evidence'))) THEN
          RAISE EXCEPTION 'scientific_adjudication_decision_reason_required' USING ERRCODE='23514'; END IF;
        IF item->>'decision'='accept' AND (item->'source_inspection_attested'<>'true'::jsonb OR jsonb_array_length(item->'evidence_refs')=0
          OR EXISTS(SELECT 1 FROM jsonb_each_text(item->'checks') WHERE value<>'satisfied')) THEN
          RAISE EXCEPTION 'scientific_adjudication_acceptance_checks_required' USING ERRCODE='23514'; END IF;
        FOR ref IN SELECT value FROM jsonb_array_elements(item->'evidence_refs') LOOP
          IF jsonb_typeof(ref) IS DISTINCT FROM 'object' OR NOT(ref ?& ARRAY['artifact_id','bytes_sha256']) OR ref-ARRAY['artifact_id','bytes_sha256']<>'{{}}'::jsonb
            OR jsonb_typeof(ref->'artifact_id') IS DISTINCT FROM 'string' OR jsonb_typeof(ref->'bytes_sha256') IS DISTINCT FROM 'string'
            OR ref->>'artifact_id' !~ '^[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}$'
            OR ref->>'bytes_sha256' !~ '^[0-9a-f]{{64}}$' THEN RAISE EXCEPTION 'scientific_adjudication_exact_evidence_required' USING ERRCODE='23514'; END IF;
        END LOOP;
        IF (SELECT count(DISTINCT value->>'artifact_id') FROM jsonb_array_elements(item->'evidence_refs'))<>jsonb_array_length(item->'evidence_refs')
          OR item->'evidence_refs' IS DISTINCT FROM (SELECT COALESCE(jsonb_agg(value ORDER BY value->>'artifact_id'),'[]'::jsonb) FROM jsonb_array_elements(item->'evidence_refs')) THEN
          RAISE EXCEPTION 'scientific_adjudication_sorted_unique_evidence_required' USING ERRCODE='23514'; END IF;
      END $$
    """


def _complete_guard():
    return f"""
      CREATE OR REPLACE FUNCTION public.sclib_scientific_adjudication_complete_v1(identifier uuid) RETURNS void {_SQL} AS $$
      DECLARE request public.scientific_adjudication_requests%ROWTYPE;
      BEGIN
        SELECT * INTO request FROM public.scientific_adjudication_requests WHERE id=identifier;
        IF request.id IS NULL OR request.assembly_xid<>txid_current()
          OR (SELECT count(*) FROM public.scientific_result_decisions WHERE request_id=identifier)<>request.item_count
          OR EXISTS(SELECT 1 FROM jsonb_array_elements(request.request_json::jsonb->'items') WITH ORDINALITY i(item,n)
            WHERE NOT EXISTS(SELECT 1 FROM public.scientific_result_decisions d WHERE d.request_id=identifier AND d.item_index=i.n-1
              AND d.id=(i.item->>'decision_id')::uuid AND d.item_sha256=public.sclib_scientific_adjudication_text_hash_v1(public.sclib_scientific_adjudication_canonical_v1(i.item))))
          OR (SELECT COALESCE(sum(octet_length(s.basis_json)),0) FROM public.scientific_result_subjects s
              WHERE s.id IN (SELECT subject_id FROM public.scientific_result_decisions WHERE request_id=identifier))>16777216 THEN
          RAISE EXCEPTION 'scientific_adjudication_complete_atomic_request_required' USING ERRCODE='23514'; END IF;
      END $$
    """


def _current_guard():
    return [f"""
      CREATE OR REPLACE FUNCTION public.sclib_scientific_adjudication_current_v1(identifier uuid) RETURNS void {_SQL} AS $$
      DECLARE request public.scientific_adjudication_requests%ROWTYPE; subject record; body text; impact text;
      BEGIN
        SELECT * INTO request FROM public.scientific_adjudication_requests WHERE id=identifier;
        IF request.id IS NULL OR request.assembly_xid<>txid_current() THEN
          RAISE EXCEPTION 'scientific_adjudication_assembly_required' USING ERRCODE='23514'; END IF;
        IF NOT public.sclib_research_distribution_role_v1(request.actor_user_id,request.actor_grant_id,'reviewer') THEN
          RAISE EXCEPTION 'scientific_adjudication_current_reviewer_required' USING ERRCODE='42501'; END IF;
        IF EXISTS(SELECT 1 FROM public.scientific_result_decisions d
          LEFT JOIN public.scientific_result_decisions x ON x.id=d.extraction_decision_id
          WHERE d.request_id=identifier AND d.scope='scientific_result' AND d.decision='accept'
            AND (x.id IS NULL OR x.subject_id<>d.subject_id OR x.scope<>'extraction_fidelity' OR x.decision<>'accept'
              OR EXISTS(SELECT 1 FROM public.scientific_result_decisions WHERE predecessor_id=x.id)
              OR NOT public.sclib_research_distribution_role_v1(x.actor_user_id,x.actor_grant_id,'reviewer'))) THEN
          RAISE EXCEPTION 'scientific_adjudication_current_fidelity_required' USING ERRCODE='23514'; END IF;
        FOR subject IN SELECT DISTINCT s.id,s.property_id,s.basis_json FROM public.scientific_result_subjects s
          JOIN public.scientific_result_decisions d ON d.subject_id=s.id WHERE d.request_id=identifier LOOP
          body:=public.sclib_scientific_subject_capture_v1(subject.property_id);
          impact:=public.sclib_scientific_result_impact_capture_v1(subject.property_id);
          IF body IS DISTINCT FROM subject.basis_json OR EXISTS(
            SELECT 1 FROM jsonb_array_elements(request.request_json::jsonb->'items') i
            WHERE i->>'subject_id'=subject.id::text
              AND i->>'expected_impact_sha256' IS DISTINCT FROM public.sclib_scientific_adjudication_text_hash_v1(impact)) THEN
            RAISE EXCEPTION 'scientific_adjudication_assembly_changed' USING ERRCODE='23514'; END IF;
          IF EXISTS(SELECT 1 FROM public.scientific_result_decisions WHERE request_id=identifier AND subject_id=subject.id AND decision='accept')
            AND (EXISTS(SELECT 1 FROM jsonb_array_elements(body::jsonb->'rows') r JOIN public.source_lifecycle_events l
                ON (r->>'table'='papers' AND l.paper_id=r->>'row_id') OR (r->>'table'='works' AND l.work_id::text=r->>'row_id'))
              OR EXISTS(SELECT 1 FROM jsonb_array_elements(body::jsonb->'rows') r JOIN public.papers p ON r->>'table'='papers' AND p.id=r->>'row_id'
                WHERE lower(p.status) IN ('retracted','withdrawn','corrected','disputed'))
              OR EXISTS(SELECT 1 FROM jsonb_array_elements(body::jsonb->'rows') r JOIN public.works w ON r->>'table'='works' AND w.id::text=r->>'row_id'
                WHERE lower(w.publication_status) IN ('retracted','withdrawn','corrected','disputed'))
              OR EXISTS(SELECT 1 FROM jsonb_array_elements(body::jsonb->'rows') r JOIN public.research_events e ON r->>'table'='research_events' AND e.id::text=r->>'row_id'
                WHERE e.validity_status IN ('disputed','retracted','excluded') OR e.review_status='rejected')
              OR EXISTS(SELECT 1 FROM jsonb_array_elements(body::jsonb->'rows') r JOIN public.material_claims c ON r->>'table'='material_claims' AND c.id::text=r->>'row_id'
                WHERE c.validity_status IN ('disputed','retracted','excluded'))) THEN
            RAISE EXCEPTION 'scientific_adjudication_source_held' USING ERRCODE='23514'; END IF;
        END LOOP;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_scientific_adjudication_transaction_v1() RETURNS void {_SQL} AS $$
      DECLARE identifier uuid; amount integer:=0;
      BEGIN
        FOR identifier IN SELECT r.id FROM public.scientific_adjudication_requests r
          WHERE r.assembly_xid=txid_current() AND r.item_count=(SELECT count(*)
            FROM public.scientific_result_decisions d WHERE d.request_id=r.id) LIMIT 21 LOOP
          amount:=amount+1;
          IF amount>20 THEN RAISE EXCEPTION 'scientific_adjudication_transaction_request_limit' USING ERRCODE='54000'; END IF;
          PERFORM public.sclib_scientific_adjudication_current_v1(identifier);
        END LOOP;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_scientific_adjudication_assembly_writer_v1() RETURNS trigger {_SQL} AS $$ BEGIN
        PERFORM public.sclib_scientific_adjudication_transaction_v1(); RETURN NULL;
      END $$
    """]


def _insert_guard():
    return f"""
      CREATE OR REPLACE FUNCTION public.sclib_scientific_adjudication_insert_v1() RETURNS trigger {_SQL} AS $$
      DECLARE body text; snapshot jsonb; target jsonb; property jsonb; item jsonb; ref jsonb; amount integer; native_rows jsonb;
        request public.scientific_adjudication_requests%ROWTYPE; subject public.scientific_result_subjects%ROWTYPE;
        prior public.scientific_result_decisions%ROWTYPE; dependency public.scientific_result_decisions%ROWTYPE;
      BEGIN
        PERFORM public.{LOCK_FUNCTION}();
        IF TG_TABLE_NAME='scientific_result_subjects' THEN
          body:=public.sclib_scientific_subject_capture_v1(NEW.property_id); snapshot:=body::jsonb; target:=snapshot->'target';
          SELECT value->'snapshot' INTO property FROM jsonb_array_elements(snapshot->'rows') WHERE value->>'table'='event_properties' AND value->>'row_id'=NEW.property_id::text;
          IF NEW.basis_json IS DISTINCT FROM body OR NEW.subject_sha256 IS DISTINCT FROM public.sclib_scientific_adjudication_text_hash_v1(body)
            OR NEW.property_row_sha256 IS DISTINCT FROM public.sclib_scientific_adjudication_text_hash_v1(public.sclib_scientific_adjudication_canonical_v1(property))
            OR NEW.subject_version IS DISTINCT FROM '{SUBJECT_VERSION}'
            OR NEW.event_id::text IS DISTINCT FROM target->>'event_id' OR NEW.event_revision IS DISTINCT FROM (target->>'event_revision')::int
            OR NEW.material_id IS DISTINCT FROM target->>'material_id' OR NEW.state_id::text IS DISTINCT FROM target->>'state_id'
            OR NEW.sample_id::text IS DISTINCT FROM target->>'sample_id' OR NEW.structure_id::text IS DISTINCT FROM target->>'structure_id'
            OR NEW.producer_run_id::text IS DISTINCT FROM target->>'producer_run_id' OR NEW.native_outcome_id::text IS DISTINCT FROM target->>'native_outcome_id' THEN
            RAISE EXCEPTION 'scientific_adjudication_exact_subject_required' USING ERRCODE='23514'; END IF;
        ELSIF TG_TABLE_NAME='scientific_adjudication_requests' THEN
          IF NOT public.sclib_research_distribution_role_v1(NEW.actor_user_id,NEW.actor_grant_id,'reviewer') THEN
            RAISE EXCEPTION 'scientific_adjudication_current_reviewer_required' USING ERRCODE='42501'; END IF;
          IF octet_length(NEW.request_json)>131072 THEN RAISE EXCEPTION 'scientific_adjudication_request_limit' USING ERRCODE='54000'; END IF;
          snapshot:=NEW.request_json::jsonb;
          IF jsonb_typeof(snapshot) IS DISTINCT FROM 'object' OR NOT(snapshot ?& ARRAY['version','request_key','items'])
            OR snapshot-ARRAY['version','request_key','items']<>'{{}}'::jsonb OR snapshot->>'version' IS DISTINCT FROM '{REQUEST_VERSION}'
            OR jsonb_typeof(snapshot->'request_key') IS DISTINCT FROM 'string' OR snapshot->>'request_key' IS DISTINCT FROM NEW.request_key
            OR jsonb_typeof(snapshot->'items') IS DISTINCT FROM 'array'
            OR NEW.request_version IS DISTINCT FROM '{REQUEST_VERSION}'
            OR NEW.request_sha256 IS DISTINCT FROM public.sclib_scientific_adjudication_text_hash_v1(NEW.request_json)
            OR NEW.request_json IS DISTINCT FROM public.sclib_scientific_adjudication_canonical_v1(snapshot) THEN
            RAISE EXCEPTION 'scientific_adjudication_exact_request_required' USING ERRCODE='23514'; END IF;
          amount:=jsonb_array_length(snapshot->'items');
          IF amount NOT BETWEEN 1 AND 20 OR NEW.item_count<>amount
            OR (SELECT count(DISTINCT (value->>'property_id',value->>'scope')) FROM jsonb_array_elements(snapshot->'items'))<>amount
            OR (SELECT count(DISTINCT value->>'decision_id') FROM jsonb_array_elements(snapshot->'items'))<>amount THEN
            RAISE EXCEPTION 'scientific_adjudication_unique_bounded_items_required' USING ERRCODE='23514'; END IF;
          amount:=0;
          FOR item IN SELECT value FROM jsonb_array_elements(snapshot->'items') LOOP
            PERFORM public.sclib_scientific_adjudication_item_v1(item); amount:=amount+jsonb_array_length(item->'evidence_refs');
          END LOOP;
          IF amount>200 THEN RAISE EXCEPTION 'scientific_adjudication_reference_limit' USING ERRCODE='54000'; END IF;
          NEW.assembly_xid:=txid_current();
        ELSE
          IF NOT public.sclib_research_distribution_role_v1(NEW.actor_user_id,NEW.actor_grant_id,'reviewer') THEN
            RAISE EXCEPTION 'scientific_adjudication_current_reviewer_required' USING ERRCODE='42501'; END IF;
          SELECT * INTO request FROM public.scientific_adjudication_requests WHERE id=NEW.request_id;
          IF request.id IS NULL OR request.assembly_xid<>txid_current() OR NEW.item_index NOT BETWEEN 0 AND request.item_count-1
            OR NEW.actor_user_id<>request.actor_user_id OR NEW.actor_grant_id<>request.actor_grant_id THEN
            RAISE EXCEPTION 'scientific_adjudication_request_actor_required' USING ERRCODE='23514'; END IF;
          item:=request.request_json::jsonb->'items'->NEW.item_index;
          IF NEW.id::text IS DISTINCT FROM item->>'decision_id' OR NEW.subject_id::text IS DISTINCT FROM item->>'subject_id'
            OR NEW.property_id::text IS DISTINCT FROM item->>'property_id' OR NEW.scope IS DISTINCT FROM item->>'scope'
            OR NEW.profile_version IS DISTINCT FROM item->>'profile_version' OR NEW.decision IS DISTINCT FROM item->>'decision'
            OR NEW.reason_code IS DISTINCT FROM item->>'reason_code' OR NEW.predecessor_id::text IS DISTINCT FROM item->>'expected_previous_decision_id'
            OR NEW.resolves_decision_id::text IS DISTINCT FROM item->>'resolves_decision_id'
            OR NEW.extraction_decision_id::text IS DISTINCT FROM item->>'extraction_decision_id'
            OR NEW.item_sha256 IS DISTINCT FROM public.sclib_scientific_adjudication_text_hash_v1(public.sclib_scientific_adjudication_canonical_v1(item)) THEN
            RAISE EXCEPTION 'scientific_adjudication_exact_request_item_required' USING ERRCODE='23514'; END IF;
          SELECT * INTO subject FROM public.scientific_result_subjects WHERE id=NEW.subject_id;
          IF subject.id IS NULL OR subject.property_id<>NEW.property_id OR subject.event_id<>NEW.event_id
            OR subject.subject_sha256 IS DISTINCT FROM item->>'expected_subject_sha256'
            OR subject.basis_json IS DISTINCT FROM public.sclib_scientific_subject_capture_v1(NEW.property_id)
            OR item->>'expected_impact_sha256' IS DISTINCT FROM public.sclib_scientific_adjudication_text_hash_v1(public.sclib_scientific_result_impact_capture_v1(NEW.property_id)) THEN
            RAISE EXCEPTION 'scientific_adjudication_preview_changed' USING ERRCODE='23514'; END IF;
          SELECT d.* INTO prior FROM public.scientific_result_decisions d WHERE d.property_id=NEW.property_id AND d.scope=NEW.scope
            AND NOT EXISTS(SELECT 1 FROM public.scientific_result_decisions successor WHERE successor.predecessor_id=d.id) LIMIT 1;
          IF NEW.predecessor_id IS DISTINCT FROM prior.id OR (NEW.resolves_decision_id IS NOT NULL AND NEW.resolves_decision_id IS DISTINCT FROM prior.id)
            OR (NEW.decision='accept' AND prior.subject_id=NEW.subject_id AND prior.decision IN ('reject','request_clarification')
              AND (NEW.actor_user_id=prior.actor_user_id OR NEW.resolves_decision_id IS DISTINCT FROM prior.id)) THEN
            RAISE EXCEPTION 'scientific_adjudication_exact_current_head_required' USING ERRCODE='23514'; END IF;
          snapshot:=subject.basis_json::jsonb;
          SELECT value->'snapshot' INTO property FROM jsonb_array_elements(snapshot->'rows') WHERE value->>'table'='event_properties' AND value->>'row_id'=NEW.property_id::text;
          IF property->>'property_key' IS DISTINCT FROM 'phonon_min_frequency' OR property->>'unit' IS DISTINCT FROM 'THz' THEN
            RAISE EXCEPTION 'scientific_adjudication_unsupported_profile_quantity' USING ERRCODE='23514'; END IF;
          FOR ref IN SELECT value FROM jsonb_array_elements(item->'evidence_refs') LOOP
            IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(snapshot->'artifacts') a WHERE a->>'artifact_id'=ref->>'artifact_id'
                AND a->>'bytes_sha256'=ref->>'bytes_sha256' AND a->>'hash_status'='verified') THEN
              RAISE EXCEPTION 'scientific_adjudication_subject_evidence_required' USING ERRCODE='23514'; END IF;
          END LOOP;
          IF NEW.profile_version='native-sampled-frequency-extraction/1.0.0' AND subject.native_outcome_id IS NULL THEN
            RAISE EXCEPTION 'scientific_adjudication_native_outcome_required' USING ERRCODE='23514'; END IF;
          IF NEW.decision='accept' THEN
            SELECT value->'snapshot' INTO property FROM jsonb_array_elements(snapshot->'rows') WHERE value->>'table'='event_properties' AND value->>'row_id'=NEW.property_id::text;
            IF property->>'relation' IS DISTINCT FROM 'exact' THEN RAISE EXCEPTION 'scientific_adjudication_exact_quantity_required' USING ERRCODE='23514'; END IF;
            IF EXISTS(SELECT 1 FROM jsonb_array_elements(snapshot->'rows') r JOIN public.source_lifecycle_events l
                ON (r->>'table'='papers' AND l.paper_id=r->>'row_id') OR (r->>'table'='works' AND l.work_id::text=r->>'row_id'))
              OR EXISTS(SELECT 1 FROM jsonb_array_elements(snapshot->'rows') r JOIN public.papers p ON r->>'table'='papers' AND p.id=r->>'row_id'
                WHERE lower(p.status) IN ('retracted','withdrawn','corrected','disputed'))
              OR EXISTS(SELECT 1 FROM jsonb_array_elements(snapshot->'rows') r JOIN public.works w ON r->>'table'='works' AND w.id::text=r->>'row_id'
                WHERE lower(w.publication_status) IN ('retracted','withdrawn','corrected','disputed'))
              OR EXISTS(SELECT 1 FROM jsonb_array_elements(snapshot->'rows') r JOIN public.research_events e ON r->>'table'='research_events' AND e.id::text=r->>'row_id'
                WHERE e.validity_status IN ('disputed','retracted','excluded') OR e.review_status='rejected')
              OR EXISTS(SELECT 1 FROM jsonb_array_elements(snapshot->'rows') r JOIN public.material_claims c ON r->>'table'='material_claims' AND c.id::text=r->>'row_id'
                WHERE c.validity_status IN ('disputed','retracted','excluded')) THEN
              RAISE EXCEPTION 'scientific_adjudication_source_held' USING ERRCODE='23514'; END IF;
            IF subject.native_outcome_id IS NOT NULL THEN
              SELECT row_snapshots_json::jsonb INTO native_rows FROM public.scientific_import_outcomes WHERE id=subject.native_outcome_id;
              IF native_rows->'property' IS DISTINCT FROM property
                OR (native_rows->'event')-ARRAY['review_status','validity_status','decision_artifact_id','record_sha256','updated_at'] IS DISTINCT FROM
                  (SELECT r->'snapshot' FROM jsonb_array_elements(snapshot->'rows') r WHERE r->>'table'='research_events' AND r->>'row_id'=NEW.event_id::text)
                OR EXISTS(SELECT 1 FROM (VALUES ('state','material_states',subject.state_id),('structure','structure_records',subject.structure_id),
                    ('run','research_runs',subject.producer_run_id)) x(role,tab,identifier)
                  WHERE native_rows->x.role IS DISTINCT FROM (SELECT r->'snapshot' FROM jsonb_array_elements(snapshot->'rows') r WHERE r->>'table'=x.tab AND r->>'row_id'=x.identifier::text)) THEN
                RAISE EXCEPTION 'scientific_adjudication_native_snapshot_changed' USING ERRCODE='23514'; END IF;
            END IF;
            IF subject.native_outcome_id IS NOT NULL AND EXISTS(SELECT 1 FROM public.scientific_import_outcomes o
              JOIN public.scientific_import_attempts a ON a.id=o.attempt_id JOIN public.scientific_import_packages p ON p.id=a.package_id
              WHERE o.id=subject.native_outcome_id AND NEW.actor_user_id IN (o.actor_user_id,a.actor_user_id,p.actor_user_id)) THEN
              RAISE EXCEPTION 'scientific_adjudication_independent_import_reviewer_required' USING ERRCODE='42501'; END IF;
            IF NEW.profile_version='native-sampled-frequency-extraction/1.0.0' THEN
              IF EXISTS(SELECT 1 FROM jsonb_array_elements(snapshot->'native_import'->'source_files') f
                WHERE NOT EXISTS(SELECT 1 FROM jsonb_array_elements(item->'evidence_refs') r WHERE r->>'artifact_id'=f->>'artifact_id' AND r->>'bytes_sha256'=f->>'sha256')) THEN
                RAISE EXCEPTION 'scientific_adjudication_complete_native_sources_required' USING ERRCODE='23514'; END IF;
            ELSIF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(item->'evidence_refs') r WHERE snapshot->'support_artifact_ids' ? (r->>'artifact_id')) THEN
              RAISE EXCEPTION 'scientific_adjudication_direct_result_source_required' USING ERRCODE='23514'; END IF;
          END IF;
          IF NEW.scope='scientific_result' AND NEW.decision='accept' THEN
            SELECT * INTO dependency FROM public.scientific_result_decisions WHERE id=NEW.extraction_decision_id;
            IF dependency.id IS NULL OR dependency.subject_id<>NEW.subject_id OR dependency.scope<>'extraction_fidelity' OR dependency.decision<>'accept'
              OR (dependency.request_id=NEW.request_id AND dependency.item_index>=NEW.item_index)
              OR EXISTS(SELECT 1 FROM public.scientific_result_decisions WHERE predecessor_id=dependency.id)
              OR NOT public.sclib_research_distribution_role_v1(dependency.actor_user_id,dependency.actor_grant_id,'reviewer') THEN
              RAISE EXCEPTION 'scientific_adjudication_current_fidelity_required' USING ERRCODE='23514'; END IF;
          ELSIF NEW.extraction_decision_id IS NOT NULL THEN
            RAISE EXCEPTION 'scientific_adjudication_unexpected_fidelity_dependency' USING ERRCODE='23514'; END IF;
        END IF;
        NEW.created_at:=clock_timestamp();
        NEW.record_sha256:=public.sclib_scientific_adjudication_record_hash_v1(to_jsonb(NEW)); RETURN NEW;
      END $$
    """


def register(metadata):
    tables = {}
    def uid(name, target=None, nullable=False):
        return sa.Column(name, UUID(as_uuid=True), *([sa.ForeignKey(target, ondelete="RESTRICT", onupdate="RESTRICT")] if target else []), nullable=nullable)
    def col(name, kind, *, nullable=False, default=None):
        return sa.Column(name, kind, nullable=nullable, server_default=default)
    def actor():
        return uid("actor_user_id", "users.id"), uid("actor_grant_id", "research_role_grants.id")
    def table(name, *columns):
        tables[name] = sa.Table(name, metadata, col("id", UUID(as_uuid=True), default=sa.text("gen_random_uuid()")), *columns,
            col("record_sha256", sa.String(64), default=""), col("created_at", sa.DateTime(timezone=True), default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"), sa.CheckConstraint("isfinite(created_at)", name="ck_sa67_"+name+"_time"),
            sa.CheckConstraint("record_sha256 ~ '^[0-9a-f]{64}$'", name="ck_sa67_"+name+"_record"),
            *(sa.CheckConstraint(f"{column.name} ~ '^[0-9a-f]{{64}}$'", name="ck_sa67_"+name+"_"+column.name)
              for column in columns if isinstance(column, sa.Column) and column.name.endswith("sha256")))
    table("scientific_result_subjects", uid("property_id"), uid("event_id"), col("event_revision", sa.Integer),
        col("material_id", sa.String(100)), uid("state_id", "material_states.id"), uid("sample_id", "research_samples.id", True),
        uid("structure_id", "structure_records.id", True), uid("producer_run_id", "research_runs.id", True),
        uid("native_outcome_id", "scientific_import_outcomes.id", True), col("subject_version", sa.String(80), default=SUBJECT_VERSION),
        col("property_row_sha256", sa.String(64)), col("basis_json", sa.Text), col("subject_sha256", sa.String(64)),
        sa.ForeignKeyConstraint(["property_id","event_id"],["event_properties.id","event_properties.event_id"], ondelete="RESTRICT",onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["event_id","event_revision"],["research_events.id","research_events.revision"],ondelete="RESTRICT",onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["material_id"],["materials.id"],ondelete="RESTRICT",onupdate="RESTRICT"),
        sa.UniqueConstraint("property_id","subject_sha256",name="uq_sa67_subject"),
        sa.CheckConstraint("octet_length(basis_json) BETWEEN 2 AND 8388608",name="ck_sa67_basis_bound"))
    table("scientific_adjudication_requests", *actor(), col("request_key", sa.String(160)),
        col("request_version", sa.String(80), default=REQUEST_VERSION), col("request_json", sa.Text), col("request_sha256", sa.String(64)),
        col("item_count", sa.Integer), col("assembly_xid", sa.BigInteger, default=sa.text("txid_current()")),
        sa.CheckConstraint("item_count BETWEEN 1 AND 20 AND octet_length(request_json) BETWEEN 2 AND 131072",name="ck_sa67_request_bound"),
        sa.CheckConstraint("request_key ~ '^[A-Za-z0-9][A-Za-z0-9._:+@-]{0,159}$'",name="ck_sa67_request_key"),
        sa.Index("idx_sa67_assembly_xid", "assembly_xid"),
        sa.UniqueConstraint("actor_user_id","request_key",name="uq_sa67_actor_request"))
    table("scientific_result_decisions", uid("request_id","scientific_adjudication_requests.id"), col("item_index",sa.Integer),
        uid("subject_id","scientific_result_subjects.id"), uid("property_id"), uid("event_id"), col("scope",sa.String(30)),
        col("profile_version",sa.String(80)), col("decision",sa.String(30)), col("reason_code",sa.String(60)),
        uid("predecessor_id","scientific_result_decisions.id",True), uid("resolves_decision_id","scientific_result_decisions.id",True),
        uid("extraction_decision_id","scientific_result_decisions.id",True), *actor(), col("item_sha256",sa.String(64)),
        sa.ForeignKeyConstraint(["property_id","event_id"],["event_properties.id","event_properties.event_id"],ondelete="RESTRICT",onupdate="RESTRICT"),
        sa.CheckConstraint("item_index BETWEEN 0 AND 19 AND scope IN ('extraction_fidelity','scientific_result') AND decision IN ('accept','reject','request_clarification')",name="ck_sa67_decision_shape"),
        sa.CheckConstraint("predecessor_id IS NULL OR predecessor_id<>id",name="ck_sa67_not_self"),
        sa.UniqueConstraint("request_id","item_index",name="uq_sa67_item"),
        sa.UniqueConstraint("predecessor_id",name="uq_sa67_successor"),
        sa.Index("uq_sa67_initial_head","property_id","scope",unique=True,postgresql_where=sa.text("predecessor_id IS NULL")),
        sa.Index("idx_sa67_target_head","property_id","scope"), sa.Index("idx_sa67_subject","subject_id"))
    last = tables[TABLE_ORDER[-1]]
    for name in (*PARENTS, *TABLE_ORDER[:-1]):
        last.add_is_dependent_on(metadata.tables[name])
    for name in ASSEMBLY_WRITER_TABLES:
        if name in metadata.tables:
            last.add_is_dependent_on(metadata.tables[name])
    for statement in guard_statements():
        sa.event.listen(last, "after_create", sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"))
    return tables
