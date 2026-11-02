"""Separate immutable content receipts; never rewrite v1 history or functions."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from models.answer_evidence_v1 import RESPONSE_KEYS

VERSION='ask-answer-evidence/2.0.0'
TABLE='content_answer_evidence_receipts_v2'
PARENTS=('ask_history','answer_evidence_receipts','retrieval_contents_v2','retrieval_content_seals_v2',
    'retrieval_backend_builds_v2','retrieval_activation_events_v2','retrieval_content_members_v2',
    'retrieval_native_revisions_v2','index_generation_members','rag_evidence_revisions','rag_extraction_revisions')
FUNCTIONS=(('sclib_content_answer_parent_v2',''),('sclib_content_answer_complete_v2',''),
    ('sclib_content_answer_header_v2','uuid, uuid, uuid, jsonb'),('sclib_content_answer_insert_v2',''))
SQL="LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp SET TimeZone='UTC' SET bytea_output='hex'"
ITEM_KEYS=('kind','position','paper_id','chunk_id','content_sha256','content_member_record_sha256','origin_kind',
    'origin_generation_id','native_revision_id','origin_record_sha256','chunk_revision_sha256','vector_sha256',
    'source_snapshot_sha256','evidence_revision_id','evidence_record_sha256','parent_result_revision_id','parent_result_sha256',
    'selection_input_sha256','selection_content_pin_sha256','selection_grouping_sha256','has_evidence_pin')


def array(values):return 'ARRAY['+','.join("'"+value+"'" for value in values)+']'


def statements():
    return [f"""
    CREATE FUNCTION public.sclib_content_answer_parent_v2() RETURNS trigger {SQL} AS $$ BEGIN
      IF TG_OP='UPDATE' AND (OLD.content_evidence_receipt_version IS NOT NULL
        OR NEW.content_evidence_receipt_version IS DISTINCT FROM OLD.content_evidence_receipt_version) THEN
        RAISE EXCEPTION 'content_answer_history_immutable' USING ERRCODE='55000'; END IF;
      IF NEW.content_evidence_receipt_version IS NOT NULL THEN
        IF NEW.content_evidence_receipt_version<>'{VERSION}' OR NEW.evidence_receipt_version IS NOT NULL THEN
          RAISE EXCEPTION 'content_answer_exact_version_required' USING ERRCODE='23514'; END IF;
        NEW.created_at:=clock_timestamp();
      END IF; RETURN NEW;
    END $$
    """,f"""
    CREATE FUNCTION public.sclib_content_answer_complete_v2() RETURNS trigger {SQL} AS $$ BEGIN
      IF EXISTS(SELECT 1 FROM public.ask_history WHERE id=NEW.id AND content_evidence_receipt_version IS NOT NULL)
        AND NOT EXISTS(SELECT 1 FROM public.{TABLE} WHERE history_id=NEW.id AND version='{VERSION}') THEN
        RAISE EXCEPTION 'content_answer_complete_receipt_required' USING ERRCODE='23514'; END IF;
      RETURN NULL;
    END $$
    """,f"""
    CREATE FUNCTION public.sclib_content_answer_header_v2(content uuid,build uuid,event uuid,bindings jsonb)
    RETURNS boolean {SQL} STABLE AS $$ DECLARE actual jsonb; intact boolean; BEGIN
      SELECT jsonb_build_object('version','index-read/2.0.0','mode','content_snapshot',
        'content_id',c.id::text,'build_id',b.id::text,'activation_event_id',e.id::text,
        'manifest_sha256',s.manifest_sha256,'policy_artifact_sha256',b.policy_artifact_sha256,'profile',b.profile),
        c.record_sha256=public.sclib_retrieval_record_hash_v2(to_jsonb(c))
          AND s.record_sha256=public.sclib_retrieval_record_hash_v2(to_jsonb(s))
          AND b.record_sha256=public.sclib_retrieval_record_hash_v2(to_jsonb(b))
          AND e.record_sha256=public.sclib_retrieval_record_hash_v2(to_jsonb(e))
          AND c.logical_index=bindings->>'logical_index' AND c.logical_index=e.logical_index
          AND b.content_record_sha256=c.record_sha256 AND b.content_manifest_sha256=s.manifest_sha256
          AND b.profile=c.profile AND e.manifest_sha256=s.manifest_sha256 AND e.build_record_sha256=b.record_sha256
        INTO actual,intact
        FROM public.retrieval_contents_v2 c JOIN public.retrieval_content_seals_v2 s ON s.content_id=c.id
        JOIN public.retrieval_backend_builds_v2 b ON b.content_id=c.id AND b.id=build
        JOIN public.retrieval_activation_events_v2 e ON e.content_id=c.id AND e.build_id=b.id AND e.id=event
        WHERE c.id=content;
      RETURN coalesce(intact AND actual=bindings->'read',false);
    END $$
    """,f"""
    CREATE FUNCTION public.sclib_content_answer_insert_v2() RETURNS trigger {SQL} AS $$
    DECLARE request jsonb; response jsonb; bindings jsonb; item jsonb; origin jsonb; output jsonb; descriptor jsonb;
      h public.ask_history%ROWTYPE; m public.retrieval_content_members_v2%ROWTYPE;
      e public.rag_evidence_revisions%ROWTYPE; x public.rag_extraction_revisions%ROWTYPE;
      field text; total integer; sources integer:=0; results integer:=0; position integer; seen text[]:=ARRAY[]::text[];
      result_started boolean:=false; digest text; original_intact boolean;
    BEGIN
      IF NEW.version<>'{VERSION}' OR octet_length(NEW.request_json)+octet_length(NEW.response_json)+octet_length(NEW.bindings_json)>1048576 THEN
        RAISE EXCEPTION 'content_answer_payload_bound' USING ERRCODE='23514'; END IF;
      request:=NEW.request_json::jsonb; response:=NEW.response_json::jsonb; bindings:=NEW.bindings_json::jsonb;
      IF NOT public.sclib_answer_evidence_json_safe_v1(request) OR NOT public.sclib_answer_evidence_json_safe_v1(response)
        OR NOT public.sclib_answer_evidence_json_safe_v1(bindings) THEN
        RAISE EXCEPTION 'content_answer_json_bound' USING ERRCODE='23514'; END IF;
      FOREACH field IN ARRAY ARRAY['request','response','bindings'] LOOP
        IF to_jsonb(NEW)->>(field||'_json') IS DISTINCT FROM public.sclib_answer_evidence_canonical_v1(
            CASE field WHEN 'request' THEN request WHEN 'response' THEN response ELSE bindings END)
          OR to_jsonb(NEW)->>(field||'_sha256') IS DISTINCT FROM public.sclib_answer_evidence_text_hash_v1(to_jsonb(NEW)->>(field||'_json')) THEN
          RAISE EXCEPTION 'content_answer_canonical_hash_mismatch' USING ERRCODE='23514'; END IF;
      END LOOP;
      SELECT * INTO h FROM public.ask_history WHERE id=NEW.history_id FOR KEY SHARE;
      IF h.id IS NULL OR h.evidence_receipt_version IS NOT NULL OR h.content_evidence_receipt_version IS DISTINCT FROM NEW.version
        OR h.question IS DISTINCT FROM request->>'question' OR h.language IS DISTINCT FROM request->>'language'
        OR h.answer IS DISTINCT FROM response->>'answer' OR h.sources IS DISTINCT FROM response->'sources'
        OR to_jsonb(h.tokens_used) IS DISTINCT FROM NULLIF(response->'tokens_used','null'::jsonb)
        OR h.latency_ms IS DISTINCT FROM (response->>'query_time_ms')::integer THEN
        RAISE EXCEPTION 'content_answer_exact_new_history_required' USING ERRCODE='23514'; END IF;
      IF jsonb_typeof(request) IS DISTINCT FROM 'object' OR request-ARRAY['question','max_sources','language']<>'{{}}'::jsonb
        OR NOT request ?& ARRAY['question','max_sources','language'] OR jsonb_typeof(request->'question') IS DISTINCT FROM 'string'
        OR length(request->>'question') NOT BETWEEN 3 AND 2000 OR btrim(request->>'question')=''
        OR request->>'language' NOT IN ('auto','en','zh') OR jsonb_typeof(request->'max_sources') IS DISTINCT FROM 'number'
        OR (request->>'max_sources') !~ '^[0-9]+$' OR (request->>'max_sources')::numeric NOT BETWEEN 1 AND 20
        OR jsonb_typeof(response) IS DISTINCT FROM 'object' OR response-{array(RESPONSE_KEYS)}<>'{{}}'::jsonb
        OR NOT response ?& {array(RESPONSE_KEYS)}
        OR jsonb_typeof(bindings) IS DISTINCT FROM 'object' OR bindings-ARRAY['version','mode','logical_index','read','items']<>'{{}}'::jsonb
        OR NOT bindings ?& ARRAY['version','mode','logical_index','read','items'] OR bindings->>'version' IS DISTINCT FROM NEW.version
        OR jsonb_typeof(bindings->'items') IS DISTINCT FROM 'array'
        OR response->'retrieval_generation' IS DISTINCT FROM bindings->'read'
        OR public.sclib_content_answer_header_v2(NEW.content_id,NEW.build_id,NEW.activation_event_id,bindings) IS DISTINCT FROM true THEN
        RAISE EXCEPTION 'content_answer_exact_header_required' USING ERRCODE='23514'; END IF;
      total:=jsonb_array_length(bindings->'items');
      IF total>20 OR total>(request->>'max_sources')::integer
        OR jsonb_typeof(response->'sources') IS DISTINCT FROM 'array' OR jsonb_typeof(response->'scientific_results') IS DISTINCT FROM 'array'
        OR total<>jsonb_array_length(response->'sources')+jsonb_array_length(response->'scientific_results')
        OR bindings->>'mode' IS DISTINCT FROM (CASE WHEN total=0 THEN 'no_selected_evidence' ELSE 'content_bound' END) THEN
        RAISE EXCEPTION 'content_answer_complete_inventory_required' USING ERRCODE='23514'; END IF;
      digest:=public.sclib_answer_evidence_text_hash_v1(public.sclib_answer_evidence_canonical_v1(
        ((bindings->'read')-ARRAY['version','mode'])||jsonb_build_object('version','sclib-retrieval-pin/2.0.0','logical_index',bindings->>'logical_index')));
      FOR item IN SELECT value FROM jsonb_array_elements(bindings->'items') LOOP
        IF jsonb_typeof(item) IS DISTINCT FROM 'object' OR item-{array(ITEM_KEYS)}<>'{{}}'::jsonb OR NOT item ?& {array(ITEM_KEYS)}
          OR jsonb_typeof(item->'kind') IS DISTINCT FROM 'string' OR item->>'kind' NOT IN ('source','scientific_result')
          OR jsonb_typeof(item->'position') IS DISTINCT FROM 'number'
          OR (item->>'position') !~ '^[0-9]+$' OR (item->>'position')::numeric NOT BETWEEN 1 AND 20
          OR item->'has_evidence_pin' IS DISTINCT FROM 'true'::jsonb OR item->>'chunk_id'=ANY(seen)
          OR item->>'selection_content_pin_sha256' IS DISTINCT FROM digest THEN
          RAISE EXCEPTION 'content_answer_selected_identity_required' USING ERRCODE='23514'; END IF;
        FOREACH field IN ARRAY ARRAY['content_sha256','content_member_record_sha256','origin_record_sha256','chunk_revision_sha256',
            'vector_sha256','source_snapshot_sha256','evidence_record_sha256','selection_input_sha256',
            'selection_content_pin_sha256','selection_grouping_sha256'] LOOP
          IF jsonb_typeof(item->field) IS DISTINCT FROM 'string' OR (item->>field) !~ '^[0-9a-f]{{64}}$' THEN
            RAISE EXCEPTION 'content_answer_exact_hash_required' USING ERRCODE='23514'; END IF;
        END LOOP;
        seen:=array_append(seen,item->>'chunk_id');position:=(item->>'position')::integer;
        SELECT * INTO m FROM public.retrieval_content_members_v2 WHERE content_id=NEW.content_id AND vector_id=item->>'chunk_id';
        IF m.origin_kind='legacy_v1' THEN
          SELECT to_jsonb(o),o.record_sha256=public.sclib_index_record_hash_v1(to_jsonb(o))
            AND o.chunk_revision_sha256=public.sclib_index_revision_hash_v1(to_jsonb(o)) INTO origin,original_intact
            FROM public.index_generation_members o WHERE o.generation_id=m.origin_generation_id AND o.vector_id=m.vector_id;
        ELSE
          SELECT to_jsonb(o),o.record_sha256=public.sclib_retrieval_record_hash_v2(to_jsonb(o))
            AND o.chunk_revision_sha256=public.sclib_retrieval_native_hash_v2(to_jsonb(o)) INTO origin,original_intact
            FROM public.retrieval_native_revisions_v2 o WHERE o.id=m.native_revision_id AND o.vector_id=m.vector_id;
        END IF;
        IF m.vector_id IS NULL OR original_intact IS DISTINCT FROM true OR origin IS NULL
          OR m.record_sha256 IS DISTINCT FROM public.sclib_retrieval_record_hash_v2(to_jsonb(m))
          OR m.record_sha256 IS DISTINCT FROM item->>'content_member_record_sha256'
          OR m.origin_record_sha256 IS DISTINCT FROM origin->>'record_sha256'
          OR encode(public.digest(decode(substring(origin->>'vector_bytes' FROM 3),'hex'),'sha256'),'hex') IS DISTINCT FROM m.vector_sha256
          OR public.sclib_answer_evidence_text_hash_v1(origin->'snapshot_json'->>'text') IS DISTINCT FROM m.content_sha256 THEN
          RAISE EXCEPTION 'content_answer_exact_origin_required' USING ERRCODE='23514'; END IF;
        FOREACH field IN ARRAY ARRAY['paper_id','origin_kind','origin_generation_id','native_revision_id','origin_record_sha256',
            'content_sha256','vector_sha256','chunk_revision_sha256'] LOOP
          IF item->field IS DISTINCT FROM to_jsonb(m)->field THEN
            RAISE EXCEPTION 'content_answer_reference_mismatch' USING ERRCODE='23514'; END IF;
        END LOOP;
        FOREACH field IN ARRAY ARRAY['source_snapshot_sha256','evidence_revision_id','evidence_record_sha256'] LOOP
          IF item->field IS DISTINCT FROM origin->field THEN
            RAISE EXCEPTION 'content_answer_original_revision_mismatch' USING ERRCODE='23514'; END IF;
        END LOOP;
        SELECT * INTO e FROM public.rag_evidence_revisions WHERE id=(item->>'evidence_revision_id')::uuid;
        x:=NULL;
        IF e.parent_extraction_revision_id IS NOT NULL THEN
          SELECT * INTO x FROM public.rag_extraction_revisions WHERE id=e.parent_extraction_revision_id;
        END IF;
        IF e.id IS NULL OR e.record_sha256 IS DISTINCT FROM public.sclib_rag_evidence_record_hash_v1(to_jsonb(e))
          OR e.record_sha256 IS DISTINCT FROM item->>'evidence_record_sha256' OR e.paper_id IS DISTINCT FROM m.paper_id
          OR e.chunk_key IS DISTINCT FROM m.chunk_key OR e.content_sha256 IS DISTINCT FROM m.content_sha256
          OR e.source_snapshot_sha256 IS DISTINCT FROM item->>'source_snapshot_sha256'
          OR e.parent_extraction_revision_id::text IS DISTINCT FROM item->>'parent_result_revision_id'
          OR x.record_sha256 IS DISTINCT FROM item->>'parent_result_sha256'
          OR (x.id IS NOT NULL AND (x.record_sha256<>public.sclib_rag_evidence_record_hash_v1(to_jsonb(x))
            OR x.paper_id<>m.paper_id OR x.source_snapshot_sha256<>e.source_snapshot_sha256)) THEN
          RAISE EXCEPTION 'content_answer_exact_evidence_required' USING ERRCODE='23514'; END IF;
        IF item->>'kind'='source' THEN
          sources:=sources+1;output:=response->'sources'->(position-1);descriptor:=output->'evidence_provenance';
          IF result_started OR position<>sources OR output->'index' IS DISTINCT FROM item->'position'
            OR output->>'paper_id' IS DISTINCT FROM m.paper_id OR output->'packing_info'->>'chunk_id' IS DISTINCT FROM m.vector_id
            OR output->'packing_info'->>'source_snapshot_sha256' IS DISTINCT FROM item->>'source_snapshot_sha256'
            OR output->>'title' IS DISTINCT FROM origin->'paper_snapshot_json'->>'title'
            OR output->'arxiv_id' IS DISTINCT FROM origin->'paper_snapshot_json'->'arxiv_id'
            OR output->'section' IS DISTINCT FROM origin->'snapshot_json'->'section' THEN
            RAISE EXCEPTION 'content_answer_source_position_binding' USING ERRCODE='23514'; END IF;
        ELSE
          result_started:=true;results:=results+1;output:=response->'scientific_results'->(position-1);descriptor:=output->'binding';
          IF position<>results OR x.id IS NULL OR e.chunk_kind<>'derived_fact'
            OR descriptor->>'vector_id' IS DISTINCT FROM m.vector_id OR descriptor->>'content_id' IS DISTINCT FROM NEW.content_id::text
            OR descriptor->>'build_id' IS DISTINCT FROM NEW.build_id::text OR descriptor->>'activation_event_id' IS DISTINCT FROM NEW.activation_event_id::text
            OR output->'result'->'scientific_acceptance' IS DISTINCT FROM 'false'::jsonb
            OR output->'result'->'ml_training_eligible' IS DISTINCT FROM 'false'::jsonb THEN
            RAISE EXCEPTION 'content_answer_result_position_binding' USING ERRCODE='23514'; END IF;
        END IF;
        FOREACH field IN ARRAY ARRAY['content_sha256','evidence_revision_id','evidence_record_sha256','parent_result_revision_id','parent_result_sha256'] LOOP
          IF descriptor->field IS DISTINCT FROM item->field THEN
            RAISE EXCEPTION 'content_answer_output_evidence_binding' USING ERRCODE='23514'; END IF;
        END LOOP;
      END LOOP;
      IF sources<>jsonb_array_length(response->'sources') OR results<>jsonb_array_length(response->'scientific_results') THEN
        RAISE EXCEPTION 'content_answer_complete_inventory_required' USING ERRCODE='23514'; END IF;
      NEW.created_at:=clock_timestamp();NEW.record_sha256:=public.sclib_answer_evidence_record_hash_v1(to_jsonb(NEW));RETURN NEW;
    EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range OR program_limit_exceeded THEN
      RAISE EXCEPTION 'content_answer_invalid_bounded_json' USING ERRCODE='23514';
    END $$
    """,'CREATE TRIGGER cae113_parent BEFORE INSERT OR UPDATE ON public.ask_history FOR EACH ROW EXECUTE FUNCTION public.sclib_content_answer_parent_v2()',
    'CREATE CONSTRAINT TRIGGER cae113_complete AFTER INSERT ON public.ask_history DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.content_evidence_receipt_version IS NOT NULL) EXECUTE FUNCTION public.sclib_content_answer_complete_v2()',
    f'CREATE TRIGGER cae113_insert BEFORE INSERT ON public.{TABLE} FOR EACH ROW EXECUTE FUNCTION public.sclib_content_answer_insert_v2()',
    f'CREATE TRIGGER cae113_immutable BEFORE UPDATE OR DELETE ON public.{TABLE} FOR EACH ROW EXECUTE FUNCTION public.sclib_answer_evidence_immutable_v1()',
    f'CREATE TRIGGER cae113_truncate BEFORE TRUNCATE ON public.{TABLE} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_answer_evidence_immutable_v1()']


def register(metadata):
    table=sa.Table(TABLE,metadata,
      sa.Column('history_id',UUID,sa.ForeignKey('ask_history.id',ondelete='CASCADE',onupdate='RESTRICT'),primary_key=True),
      sa.Column('version',sa.String(50),nullable=False,server_default=VERSION),
      sa.Column('content_id',UUID,sa.ForeignKey('retrieval_contents_v2.id',ondelete='RESTRICT'),nullable=False),
      sa.Column('build_id',UUID,sa.ForeignKey('retrieval_backend_builds_v2.id',ondelete='RESTRICT'),nullable=False),
      sa.Column('activation_event_id',UUID,sa.ForeignKey('retrieval_activation_events_v2.id',ondelete='RESTRICT'),nullable=False),
      *[sa.Column(name+'_json',sa.Text,nullable=False) for name in ('request','response','bindings')],
      *[sa.Column(name+'_sha256',sa.String(64),nullable=False) for name in ('request','response','bindings')],
      sa.Column('record_sha256',sa.String(64),nullable=False,server_default='0'*64),
      sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.clock_timestamp()),
      sa.CheckConstraint("version='"+VERSION+"'",name='ck_cae113_version'),
      sa.CheckConstraint(' AND '.join(name+"_sha256 ~ '^[0-9a-f]{64}$'" for name in ('request','response','bindings','record')),name='ck_cae113_hashes'))
    for parent in PARENTS:table.add_is_dependent_on(metadata.tables[parent])
    for statement in statements():sa.event.listen(table,'after_create',sa.DDL(statement.replace('%','%%')).execute_if(dialect='postgresql'))
    return table
