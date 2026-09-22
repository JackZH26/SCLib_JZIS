"""Additive, exact scientific Discovery disclosure; not scientific/ML authority.

The authenticated service builds the payload and rechecks its typed scientific
projection. Native guards independently protect immutable targets, complete new
scope permissions, role separation, current exact review heads and transactions.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

VERSION = "discovery-projection-governance/1.0.0"
SCOPE = "discovery_scientific_projection"
TABLE_ORDER = ("discovery_projection_packages", "discovery_projection_reviews", "discovery_projection_actions")
PARENTS = ("research_distribution_packages", "users", "research_role_grants")
MAX_BYTES = 32 * 1024 * 1024
MAX_DEPENDENCIES = 20000
FUNCTION_SIGNATURES = (
    ("sclib_discovery_projection_hash_v1", "jsonb"),
    ("sclib_discovery_projection_science_v1", "uuid, jsonb, boolean"),
    ("sclib_discovery_projection_rights_v1", "uuid, jsonb"),
    ("sclib_discovery_projection_base_v1", "uuid"),
    ("sclib_discovery_projection_insert_v1", ""),
    ("sclib_discovery_projection_immutable_v1", ""),
)
_SQL = "LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp SET TimeZone='UTC'"


def guard_statements():
    return ["""
      CREATE OR REPLACE FUNCTION public.sclib_discovery_projection_hash_v1(body jsonb) RETURNS text
      LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
        SELECT public.sclib_research_distribution_record_hash_v1(body-ARRAY[
          'payload_json','public_bundle_json','selection_json','dependency_ids_json','scientific_pins_json','rights_json'])
      $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_discovery_projection_science_v1(
        distribution_id uuid,pins jsonb,positive boolean) RETURNS void {_SQL} AS $$
      DECLARE item record; scope_item jsonb; head record; current_subject text; accepted integer:=0;
        extraction_id text; actual_scopes text[];
      BEGIN
        IF jsonb_typeof(pins) IS DISTINCT FROM 'object' OR (SELECT count(*) FROM jsonb_object_keys(pins))>100 THEN
          RAISE EXCEPTION 'discovery_scientific_inventory_invalid' USING ERRCODE='23514'; END IF;
        FOR item IN SELECT key,value FROM jsonb_each(pins) LOOP
          IF item.key !~ '^[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}$'
            OR jsonb_typeof(item.value) IS DISTINCT FROM 'object'
            OR NOT (item.value ?& ARRAY['version','property_id','subject_sha256','scopes','ml_training_approved','public_release_authorized','revision_sha256'])
            OR item.value-ARRAY['version','property_id','subject_sha256','scopes','ml_training_approved','public_release_authorized','revision_sha256']<>'{{}}'::jsonb
            OR item.value->>'version' IS DISTINCT FROM 'scientific-result-review-status/1.0.0'
            OR jsonb_typeof(item.value->'subject_sha256') IS DISTINCT FROM 'string'
            OR jsonb_typeof(item.value->'revision_sha256') IS DISTINCT FROM 'string'
            OR item.value->>'subject_sha256' !~ '^[0-9a-f]{{64}}$'
            OR item.value->>'revision_sha256' !~ '^[0-9a-f]{{64}}$'
            OR item.value->>'property_id' IS DISTINCT FROM item.key
            OR jsonb_typeof(item.value->'scopes') IS DISTINCT FROM 'array'
            OR jsonb_array_length(item.value->'scopes')<>2
            OR item.value->'ml_training_approved' IS DISTINCT FROM 'false'::jsonb
            OR item.value->'public_release_authorized' IS DISTINCT FROM 'false'::jsonb
            OR NOT EXISTS(SELECT 1 FROM public.research_distribution_dependencies d
              WHERE d.package_id=distribution_id AND d.table_name='event_properties' AND d.row_id=item.key) THEN
            RAISE EXCEPTION 'discovery_exact_scientific_target_required' USING ERRCODE='23514'; END IF;
          SELECT array_agg(s->>'scope' ORDER BY s->>'scope') INTO actual_scopes FROM jsonb_array_elements(item.value->'scopes') s;
          IF actual_scopes IS DISTINCT FROM ARRAY['extraction_fidelity','scientific_result'] THEN
            RAISE EXCEPTION 'discovery_exact_review_scopes_required' USING ERRCODE='23514'; END IF;
          current_subject:=public.sclib_scientific_subject_capture_v1(item.key::uuid);
          IF item.value->>'subject_sha256' IS DISTINCT FROM public.sclib_scientific_adjudication_text_hash_v1(current_subject) THEN
            RAISE EXCEPTION 'discovery_scientific_subject_changed' USING ERRCODE='23514'; END IF;
          extraction_id:=NULL;
          FOR scope_item IN SELECT s FROM jsonb_array_elements(item.value->'scopes') s ORDER BY s->>'scope' LOOP
            IF jsonb_typeof(scope_item) IS DISTINCT FROM 'object'
              OR NOT (scope_item ?& ARRAY['scope','profile_version','decision_id','decision_sha256','decision','effective_status','reason_codes','scientific_scope_accepted'])
              OR scope_item-ARRAY['scope','profile_version','decision_id','decision_sha256','decision','effective_status','reason_codes','scientific_scope_accepted']<>'{{}}'::jsonb
              OR scope_item->'reason_codes' IS DISTINCT FROM '[]'::jsonb
              OR (scope_item->>'scope'='extraction_fidelity' AND scope_item->'scientific_scope_accepted' IS DISTINCT FROM 'false'::jsonb) THEN
              RAISE EXCEPTION 'discovery_closed_review_status_required' USING ERRCODE='23514'; END IF;
            SELECT d.*,s.subject_sha256 INTO head FROM public.scientific_result_decisions d
              JOIN public.scientific_result_subjects s ON s.id=d.subject_id
              WHERE d.property_id=item.key::uuid AND d.scope=scope_item->>'scope'
                AND NOT EXISTS(SELECT 1 FROM public.scientific_result_decisions n WHERE n.predecessor_id=d.id);
            IF head.id IS NULL THEN
              IF scope_item->'decision_id' IS DISTINCT FROM 'null'::jsonb OR scope_item->>'effective_status' IS DISTINCT FROM 'unreviewed'
                OR scope_item->'decision_sha256' IS DISTINCT FROM 'null'::jsonb
                OR scope_item->'decision' IS DISTINCT FROM 'null'::jsonb OR scope_item->'profile_version' IS DISTINCT FROM 'null'::jsonb
                OR scope_item->'scientific_scope_accepted' IS DISTINCT FROM 'false'::jsonb THEN
                RAISE EXCEPTION 'discovery_unreviewed_status_required' USING ERRCODE='23514'; END IF;
            ELSE
              IF scope_item->>'decision_id' IS DISTINCT FROM head.id::text
                OR scope_item->>'decision_sha256' IS DISTINCT FROM head.record_sha256
                OR scope_item->>'decision' IS DISTINCT FROM head.decision
                OR scope_item->>'profile_version' IS DISTINCT FROM head.profile_version
                OR scope_item->>'effective_status' IS DISTINCT FROM 'accepted'
                OR head.decision<>'accept' OR head.subject_sha256<>item.value->>'subject_sha256'
                OR NOT public.sclib_research_distribution_role_v1(head.actor_user_id,head.actor_grant_id,'reviewer') THEN
                RAISE EXCEPTION 'discovery_current_exact_scientific_review_required' USING ERRCODE='23514'; END IF;
              IF head.scope='extraction_fidelity' THEN extraction_id:=head.id::text;
              ELSE
                IF head.extraction_decision_id::text IS DISTINCT FROM extraction_id
                  OR scope_item->'scientific_scope_accepted' IS DISTINCT FROM 'true'::jsonb THEN
                  RAISE EXCEPTION 'discovery_exact_extraction_head_required' USING ERRCODE='23514'; END IF;
                accepted:=accepted+1;
              END IF;
            END IF;
          END LOOP;
        END LOOP;
        IF positive AND accepted=0 THEN
          RAISE EXCEPTION 'discovery_reviewed_scientific_cell_required' USING ERRCODE='23514'; END IF;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_discovery_projection_rights_v1(
        identifier uuid,rights jsonb) RETURNS void {_SQL} AS $$
      DECLARE p public.discovery_projection_packages%ROWTYPE; item jsonb; ids jsonb;
      BEGIN
        SELECT * INTO p FROM public.discovery_projection_packages WHERE id=identifier;
        IF p.id IS NULL OR jsonb_typeof(rights) IS DISTINCT FROM 'array'
          OR jsonb_array_length(rights)>20000 THEN
          RAISE EXCEPTION 'discovery_rights_inventory_required' USING ERRCODE='23514'; END IF;
        SELECT jsonb_agg(x->>'dependency_id' ORDER BY x->>'dependency_id') INTO ids FROM jsonb_array_elements(rights) x;
        IF ids IS DISTINCT FROM p.dependency_ids_json::jsonb THEN
          RAISE EXCEPTION 'discovery_complete_new_scope_rights_required' USING ERRCODE='23514'; END IF;
        FOR item IN SELECT value FROM jsonb_array_elements(rights) LOOP
          IF jsonb_typeof(item) IS DISTINCT FROM 'object'
            OR NOT item ?& ARRAY['dependency_id','row_sha256','license_code','basis_code']
            OR item-ARRAY['dependency_id','row_sha256','license_code','basis_code']<>'{{}}'::jsonb
            OR jsonb_typeof(item->'license_code') IS DISTINCT FROM 'string'
            OR jsonb_typeof(item->'basis_code') IS DISTINCT FROM 'string'
            OR item->>'license_code' NOT IN ('CC0-1.0','CC-BY-4.0','CC-BY-SA-4.0','permission-on-file')
            OR item->>'basis_code' !~ '^[a-z][a-z0-9_]{{0,159}}$'
            OR NOT EXISTS(SELECT 1 FROM public.research_distribution_dependencies d
              WHERE d.package_id=p.distribution_package_id AND d.dependency_id=item->>'dependency_id'
                AND d.row_sha256=item->>'row_sha256') THEN
            RAISE EXCEPTION 'discovery_exact_rights_target_required' USING ERRCODE='23514'; END IF;
        END LOOP;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_discovery_projection_base_v1(identifier uuid) RETURNS void {_SQL} AS $$
      DECLARE p public.research_distribution_packages%ROWTYPE;
        a public.research_distribution_actions%ROWTYPE; r public.research_distribution_reviews%ROWTYPE;
      BEGIN
        SELECT * INTO p FROM public.research_distribution_packages WHERE id=identifier;
        SELECT * INTO a FROM public.research_distribution_actions WHERE package_id=identifier AND kind='publish';
        SELECT * INTO r FROM public.research_distribution_reviews WHERE id=a.review_id;
        IF p.id IS NULL OR a.id IS NULL OR r.id IS NULL OR r.package_id<>p.id
          OR a.inventory_sha256<>p.inventory_sha256 OR r.inventory_sha256<>p.inventory_sha256
          OR NOT r.disclosure_approved OR r.scientific_acceptance OR r.ml_training_approved
          OR p.actor_user_id=r.actor_user_id OR p.actor_user_id=a.actor_user_id OR r.actor_user_id=a.actor_user_id
          OR EXISTS(SELECT 1 FROM public.research_distribution_actions WHERE package_id=identifier AND kind='withdraw')
          OR EXISTS(SELECT 1 FROM public.research_distribution_reviews WHERE package_id=identifier AND NOT disclosure_approved)
          OR NOT public.sclib_research_distribution_role_v1(p.actor_user_id,p.actor_grant_id,'curator')
          OR NOT public.sclib_research_distribution_role_v1(r.actor_user_id,r.actor_grant_id,'reviewer')
          OR NOT public.sclib_research_distribution_role_v1(a.actor_user_id,a.actor_grant_id,'publisher') THEN
          RAISE EXCEPTION 'discovery_base_publication_required' USING ERRCODE='23514'; END IF;
        PERFORM public.sclib_research_distribution_current_v1(identifier);
        PERFORM public.sclib_research_distribution_permissions_v1(identifier,r.permission_manifest);
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_discovery_projection_insert_v1() RETURNS trigger {_SQL} AS $$
      DECLARE p public.discovery_projection_packages%ROWTYPE; r public.discovery_projection_reviews%ROWTYPE;
        original public.research_distribution_packages%ROWTYPE; ids jsonb; role_name text;
      BEGIN
        PERFORM public.sclib_research_distribution_lock_v1();
        PERFORM public.sclib_scientific_adjudication_read_guard_v1();
        role_name:=CASE TG_TABLE_NAME WHEN 'discovery_projection_packages' THEN 'curator'
          WHEN 'discovery_projection_reviews' THEN 'reviewer' ELSE 'publisher' END;
        IF NOT public.sclib_research_distribution_role_v1(NEW.actor_user_id,NEW.actor_grant_id,role_name) THEN
          RAISE EXCEPTION 'discovery_explicit_current_role_required' USING ERRCODE='42501'; END IF;
        IF TG_TABLE_NAME='discovery_projection_packages' THEN
          SELECT * INTO original FROM public.research_distribution_packages WHERE id=NEW.distribution_package_id;
          SELECT jsonb_agg(dependency_id ORDER BY dependency_id COLLATE "C") INTO ids
            FROM public.research_distribution_dependencies WHERE package_id=NEW.distribution_package_id;
          IF original.id IS NULL OR NEW.distribution_record_sha256<>original.record_sha256
            OR NEW.inventory_sha256<>original.inventory_sha256 OR ids IS DISTINCT FROM NEW.dependency_ids_json::jsonb
            OR NEW.payload_json::jsonb->>'version' IS DISTINCT FROM 'discovery-scientific-projection/1.0.0'
            OR NEW.payload_json::jsonb->'scientific_acceptance' IS DISTINCT FROM 'false'::jsonb
            OR NEW.payload_json::jsonb->'ml_training_approved' IS DISTINCT FROM 'false'::jsonb
            OR NEW.payload_json::jsonb->'public_release_authorized' IS DISTINCT FROM 'false'::jsonb
            OR NEW.payload_sha256<>public.sclib_research_distribution_text_hash_v1(NEW.payload_json)
            OR NEW.public_bundle_text_sha256<>public.sclib_research_distribution_text_hash_v1(NEW.public_bundle_json)
            OR NEW.selection_sha256<>public.sclib_research_distribution_text_hash_v1(NEW.selection_json)
            OR NEW.public_bundle_json::jsonb->>'bundle_sha256' IS DISTINCT FROM original.public_bundle_sha256
            OR NEW.public_bundle_json::jsonb->'release'->>'manifest_sha256' IS DISTINCT FROM original.release_manifest_sha256
            OR NEW.selection_json::jsonb->>'public_bundle_sha256' IS DISTINCT FROM original.public_bundle_sha256
            OR NEW.selection_json::jsonb->>'release_manifest_sha256' IS DISTINCT FROM original.release_manifest_sha256
            OR NEW.payload_json::jsonb->'selection' IS DISTINCT FROM NEW.selection_json::jsonb
            OR NEW.payload_json::jsonb->>'selection_sha256' IS DISTINCT FROM NEW.selection_sha256
            OR NEW.payload_json::jsonb->'base'->>'distribution_package_id' IS DISTINCT FROM NEW.distribution_package_id::text
            OR NEW.payload_json::jsonb->'base'->>'distribution_record_sha256' IS DISTINCT FROM NEW.distribution_record_sha256
            OR NEW.payload_json::jsonb->'base'->>'inventory_sha256' IS DISTINCT FROM NEW.inventory_sha256
            OR NEW.dependency_ids_sha256<>public.sclib_research_distribution_text_hash_v1(NEW.dependency_ids_json)
            OR NEW.scientific_pins_sha256<>public.sclib_research_distribution_text_hash_v1(NEW.scientific_pins_json) THEN
            RAISE EXCEPTION 'discovery_exact_package_required' USING ERRCODE='23514'; END IF;
          PERFORM public.sclib_research_distribution_current_v1(NEW.distribution_package_id);
          PERFORM public.sclib_discovery_projection_science_v1(NEW.distribution_package_id,NEW.scientific_pins_json::jsonb,false);
        ELSE
          SELECT * INTO p FROM public.discovery_projection_packages WHERE id=NEW.package_id;
          IF p.id IS NULL OR NEW.payload_sha256<>p.payload_sha256 OR NEW.selection_sha256<>p.selection_sha256
            OR NEW.actor_user_id=p.actor_user_id THEN
            RAISE EXCEPTION 'discovery_exact_independent_package_required' USING ERRCODE='23514'; END IF;
          IF TG_TABLE_NAME='discovery_projection_reviews' THEN
            IF NEW.rights_sha256<>public.sclib_research_distribution_text_hash_v1(NEW.rights_json) THEN
              RAISE EXCEPTION 'discovery_rights_hash_required' USING ERRCODE='23514'; END IF;
            IF NEW.decision='approve' THEN
              PERFORM public.sclib_discovery_projection_rights_v1(p.id,NEW.rights_json::jsonb);
              IF NOT public.sclib_research_distribution_role_v1(p.actor_user_id,p.actor_grant_id,'curator') THEN
                RAISE EXCEPTION 'discovery_current_curator_required' USING ERRCODE='42501'; END IF;
              PERFORM public.sclib_research_distribution_current_v1(p.distribution_package_id);
              PERFORM public.sclib_discovery_projection_science_v1(p.distribution_package_id,p.scientific_pins_json::jsonb,false);
            END IF;
          ELSE
            SELECT * INTO r FROM public.discovery_projection_reviews WHERE id=NEW.review_id;
            IF r.id IS NULL OR r.package_id<>p.id OR r.payload_sha256<>p.payload_sha256
              OR r.selection_sha256<>p.selection_sha256 OR r.decision<>'approve'
              OR NEW.actor_user_id=r.actor_user_id THEN
              RAISE EXCEPTION 'discovery_exact_independent_review_required' USING ERRCODE='23514'; END IF;
            IF NEW.kind='publish' THEN
              IF EXISTS(SELECT 1 FROM public.discovery_projection_reviews WHERE package_id=p.id AND decision='reject')
                OR EXISTS(SELECT 1 FROM public.discovery_projection_actions WHERE package_id=p.id AND kind='withdraw')
                OR NOT public.sclib_research_distribution_role_v1(p.actor_user_id,p.actor_grant_id,'curator')
                OR NOT public.sclib_research_distribution_role_v1(r.actor_user_id,r.actor_grant_id,'reviewer') THEN
                RAISE EXCEPTION 'discovery_publication_held' USING ERRCODE='23514'; END IF;
              PERFORM public.sclib_discovery_projection_base_v1(p.distribution_package_id);
              PERFORM public.sclib_discovery_projection_rights_v1(p.id,r.rights_json::jsonb);
              PERFORM public.sclib_discovery_projection_science_v1(p.distribution_package_id,p.scientific_pins_json::jsonb,true);
            END IF;
          END IF;
        END IF;
        NEW.created_at:=clock_timestamp();
        NEW.record_sha256:=public.sclib_discovery_projection_hash_v1(to_jsonb(NEW));
        RETURN NEW;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_discovery_projection_immutable_v1() RETURNS trigger {_SQL} AS $$
      BEGIN RAISE EXCEPTION 'discovery_projection_append_only' USING ERRCODE='55000'; END $$
    """, *[statement for name in TABLE_ORDER for statement in (
        f"CREATE TRIGGER dp69_insert BEFORE INSERT ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_discovery_projection_insert_v1()",
        f"CREATE TRIGGER dp69_immutable BEFORE UPDATE OR DELETE ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_discovery_projection_immutable_v1()",
        f"CREATE TRIGGER dp69_truncate BEFORE TRUNCATE ON public.{name} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_discovery_projection_immutable_v1()",
    )]]


def register(metadata):
    tables = {}

    def col(name, kind, default=None):
        return sa.Column(name, kind, nullable=False, server_default=default)

    def uid(name, target=None):
        args = [sa.ForeignKey(target, ondelete="RESTRICT", onupdate="RESTRICT")] if target else []
        return sa.Column(name, UUID(as_uuid=True), *args, nullable=False)

    def check(value, name):
        return sa.CheckConstraint(value, name="ck_dp69_" + name)

    def history(name, *fields):
        tables[name] = sa.Table(name, metadata,
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            *fields, uid("actor_user_id", "users.id"), uid("actor_grant_id", "research_role_grants.id"),
            col("request_key", sa.String(160)), col("request_sha256", sa.String(64)),
            col("scope", sa.String(50), SCOPE),
            col("record_sha256", sa.String(64), "0" * 64),
            col("created_at", sa.DateTime(timezone=True), sa.func.clock_timestamp()),
            check("scope='discovery_scientific_projection' AND request_key ~ '^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$'", "request_scope"),
            check("request_sha256 ~ '^[0-9a-f]{64}$' AND record_sha256 ~ '^[0-9a-f]{64}$' AND isfinite(created_at)", "identity"),
            *[check(f"{item.name} ~ '^[0-9a-f]{{64}}$'", item.name) for item in fields if item.name.endswith("sha256")],
            sa.UniqueConstraint("actor_user_id", "request_key"))

    history(TABLE_ORDER[0], uid("distribution_package_id", "research_distribution_packages.id"),
        col("distribution_record_sha256", sa.String(64)), col("inventory_sha256", sa.String(64)),
        col("payload_json", sa.Text), col("payload_sha256", sa.String(64)), col("selection_sha256", sa.String(64)),
        col("public_bundle_json", sa.Text), col("public_bundle_text_sha256", sa.String(64)), col("selection_json", sa.Text),
        col("dependency_ids_json", sa.Text), col("dependency_ids_sha256", sa.String(64)),
        col("scientific_pins_json", sa.Text), col("scientific_pins_sha256", sa.String(64)))
    tables[TABLE_ORDER[0]].append_constraint(check(
        f"octet_length(payload_json)+octet_length(public_bundle_json)+octet_length(selection_json)+octet_length(dependency_ids_json)+octet_length(scientific_pins_json)<={MAX_BYTES} "
        "AND octet_length(public_bundle_json)<=16777216 AND octet_length(payload_json)<=4194304 AND octet_length(selection_json)<=4194304 "
        "AND jsonb_typeof(payload_json::jsonb)='object' AND jsonb_typeof(dependency_ids_json::jsonb)='array' "
        "AND jsonb_array_length(dependency_ids_json::jsonb) BETWEEN 1 AND 20000 "
        "AND jsonb_typeof(scientific_pins_json::jsonb)='object'", "package_bounds"))
    history(TABLE_ORDER[1], uid("package_id", TABLE_ORDER[0] + ".id"), col("payload_sha256", sa.String(64)),
        col("selection_sha256", sa.String(64)), col("rights_json", sa.Text), col("rights_sha256", sa.String(64)),
        col("decision", sa.String(20)), col("representative_selection_approved", sa.Boolean),
        col("disclosure_approved", sa.Boolean), col("reason_code", sa.String(160)))
    tables[TABLE_ORDER[1]].append_constraint(check(
        "decision IN ('approve','reject') AND (decision<>'approve' OR (representative_selection_approved AND disclosure_approved)) "
        "AND octet_length(rights_json)<=8388608 AND jsonb_typeof(rights_json::jsonb)='array' "
        "AND (decision<>'reject' OR rights_json='[]') AND reason_code ~ '^[a-z][a-z0-9_]{0,159}$'", "review"))
    tables[TABLE_ORDER[1]].append_constraint(sa.UniqueConstraint("id", "package_id", "payload_sha256", "selection_sha256"))
    history(TABLE_ORDER[2], uid("package_id", TABLE_ORDER[0] + ".id"), uid("review_id"),
        col("payload_sha256", sa.String(64)), col("selection_sha256", sa.String(64)),
        col("kind", sa.String(20)), col("reason_code", sa.String(160)))
    tables[TABLE_ORDER[2]].append_constraint(sa.ForeignKeyConstraint(
        ["review_id", "package_id", "payload_sha256", "selection_sha256"],
        [TABLE_ORDER[1] + "." + name for name in ("id", "package_id", "payload_sha256", "selection_sha256")],
        ondelete="RESTRICT", onupdate="RESTRICT"))
    tables[TABLE_ORDER[2]].append_constraint(sa.UniqueConstraint("package_id", "kind"))
    tables[TABLE_ORDER[2]].append_constraint(check("kind IN ('publish','withdraw') AND reason_code ~ '^[a-z][a-z0-9_]{0,159}$'", "action"))
    last = tables[TABLE_ORDER[-1]]
    for name in (*PARENTS, *TABLE_ORDER[:-1], "scientific_result_decisions"):
        if name in metadata.tables:
            last.add_is_dependent_on(metadata.tables[name])
    for statement in guard_statements():
        sa.event.listen(last, "after_create", sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"))
    return tables
