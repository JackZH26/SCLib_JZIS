"""Additive 0061 text-free, immutable provider-response observations.

Receipts assert only that a trusted writer checked a complete embedding
response. They are not cryptographic provider attestations, vector-upload or
index-activation receipts, source permissions, or scientific acceptance.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

TABLE_NAME = "embedding_completion_receipts"
FUNCTION_SIGNATURES = (
    ("sclib_embedding_receipt_hash_v1", "jsonb"),
    ("sclib_embedding_metadata_valid_v1", "jsonb, text, text"),
    ("sclib_embedding_receipt_insert_v1", ""),
    ("sclib_embedding_receipt_immutable_v1", ""),
)
_SQL = "LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp SET TimeZone='UTC'"


def guard_statements():
    fields = "'version','provider','model','task_type','output_dimensionality','content_sha256','vector_sha256','local_count_method','local_count','local_input_limit','local_request_limit','provider_token_count','provider_input_token_limit','provider_request_token_limit','provider_truncated','auto_truncate','completeness_status'"
    return ["""
      CREATE OR REPLACE FUNCTION public.sclib_embedding_receipt_hash_v1(body jsonb)
      RETURNS text LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
        SELECT encode(public.digest(convert_to((body-ARRAY['created_at','record_sha256'])::text,'UTF8'),'sha256'),'hex')
      $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_embedding_metadata_valid_v1(body jsonb, content_hash text, vector_hash text)
      RETURNS boolean {_SQL} IMMUTABLE AS $$
      DECLARE field text; limit_input integer; limit_request integer;
      BEGIN
        IF jsonb_typeof(body) IS DISTINCT FROM 'object' OR octet_length(body::text)>4096
          OR body-ARRAY[{fields}]<>'{{}}'::jsonb OR NOT body ?& ARRAY[{fields}]
          OR body->>'version' IS DISTINCT FROM 'sclib-embedding-completeness/1.0.0'
          OR body->>'provider' IS DISTINCT FROM 'google-vertex-ai'
          OR body->>'model' IS DISTINCT FROM 'text-embedding-005'
          OR body->>'task_type' IS DISTINCT FROM 'RETRIEVAL_DOCUMENT'
          OR body->>'content_sha256' IS DISTINCT FROM content_hash
          OR body->>'vector_sha256' IS DISTINCT FROM vector_hash
          OR body->'provider_truncated' IS DISTINCT FROM 'false'::jsonb
          OR body->'auto_truncate' IS DISTINCT FROM 'false'::jsonb
          OR body->>'completeness_status' IS DISTINCT FROM 'provider_reported_complete' THEN RETURN false; END IF;
        FOREACH field IN ARRAY ARRAY['version','provider','model','task_type','content_sha256','vector_sha256',
          'local_count_method','completeness_status'] LOOP
          IF jsonb_typeof(body->field) IS DISTINCT FROM 'string' THEN RETURN false; END IF;
        END LOOP;
        FOREACH field IN ARRAY ARRAY['output_dimensionality','local_count','local_input_limit','local_request_limit',
          'provider_token_count','provider_input_token_limit','provider_request_token_limit'] LOOP
          IF jsonb_typeof(body->field) IS DISTINCT FROM 'number' THEN RETURN false; END IF;
          IF (body->>field)::numeric<1 OR (body->>field)::numeric>20000
            OR trunc((body->>field)::numeric)<>(body->>field)::numeric THEN RETURN false; END IF;
        END LOOP;
        IF (body->>'output_dimensionality')::integer<>768
          OR (body->>'provider_input_token_limit')::integer<>2048
          OR (body->>'provider_request_token_limit')::integer<>20000
          OR (body->>'provider_token_count')::integer>2048 THEN RETURN false; END IF;
        IF body->>'local_count_method'='tiktoken-cl100k_base/1' THEN limit_input:=1536; limit_request:=14000;
        ELSIF body->>'local_count_method'='utf8-bytes/1' THEN limit_input:=8192; limit_request:=8192;
        ELSE RETURN false; END IF;
        RETURN (body->>'local_count')::integer<=(body->>'local_input_limit')::integer
          AND (body->>'local_input_limit')::integer<=limit_input
          AND (body->>'local_input_limit')::integer<=(body->>'local_request_limit')::integer
          AND (body->>'local_request_limit')::integer<=limit_request;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_embedding_receipt_insert_v1() RETURNS trigger {_SQL} AS $$
      DECLARE evidence public.rag_evidence_revisions%ROWTYPE; chunk jsonb; source_hash text; pointer uuid;
      BEGIN
        PERFORM public.sclib_research_integrity_lock_v1();
        SELECT to_jsonb(c) INTO chunk FROM public.chunks c WHERE c.id=NEW.chunk_key FOR KEY SHARE;
        SELECT evidence_revision_id INTO pointer FROM public.chunk_evidence_current WHERE chunk_id=NEW.chunk_key;
        SELECT * INTO evidence FROM public.rag_evidence_revisions WHERE id=NEW.evidence_revision_id;
        SELECT public.sclib_source_lifecycle_snapshot_hash_v1('paper',to_jsonb(p)) INTO source_hash
          FROM public.papers p WHERE p.id=chunk->>'paper_id';
        IF chunk IS NULL OR evidence.id IS NULL OR pointer IS DISTINCT FROM evidence.id
          OR evidence.chunk_key<>NEW.chunk_key OR evidence.paper_id<>chunk->>'paper_id'
          OR evidence.record_sha256<>NEW.evidence_record_sha256
          OR evidence.record_sha256<>public.sclib_rag_evidence_record_hash_v1(to_jsonb(evidence))
          OR evidence.source_snapshot_sha256 IS DISTINCT FROM source_hash
          OR evidence.chunk_binding_sha256<>NEW.chunk_binding_sha256
          OR NEW.chunk_binding_sha256<>public.sclib_rag_chunk_hash_v1(chunk)
          OR evidence.content_sha256<>NEW.content_sha256
          OR NEW.content_sha256<>encode(public.digest(convert_to(chunk->>'text','UTF8'),'sha256'),'hex') THEN
          RAISE EXCEPTION 'embedding_receipt_exact_current_chunk_evidence_required' USING ERRCODE='23514'; END IF;
        IF NOT public.sclib_embedding_metadata_valid_v1(NEW.metadata_json,NEW.content_sha256,NEW.vector_sha256) THEN
          RAISE EXCEPTION 'embedding_receipt_complete_document_metadata_required' USING ERRCODE='23514'; END IF;
        NEW.created_at:=clock_timestamp();
        NEW.record_sha256:=public.sclib_embedding_receipt_hash_v1(to_jsonb(NEW));
        RETURN NEW;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_embedding_receipt_immutable_v1() RETURNS trigger {_SQL} AS $$
      BEGIN RAISE EXCEPTION 'embedding receipt history is append-only' USING ERRCODE='55000'; END $$
    """,
        f"CREATE TRIGGER er61_insert BEFORE INSERT ON public.{TABLE_NAME} FOR EACH ROW EXECUTE FUNCTION public.sclib_embedding_receipt_insert_v1()",
        f"CREATE TRIGGER er61_immutable BEFORE UPDATE OR DELETE ON public.{TABLE_NAME} FOR EACH ROW EXECUTE FUNCTION public.sclib_embedding_receipt_immutable_v1()",
        f"CREATE TRIGGER er61_truncate BEFORE TRUNCATE ON public.{TABLE_NAME} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_embedding_receipt_immutable_v1()"]


def register(metadata):
    table = sa.Table(TABLE_NAME, metadata,
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("chunk_key", sa.String(200), nullable=False),
        sa.Column("evidence_revision_id", UUID(as_uuid=True), sa.ForeignKey(
            "rag_evidence_revisions.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False),
        *[sa.Column(name, sa.String(64), nullable=False) for name in (
            "evidence_record_sha256", "chunk_binding_sha256", "content_sha256", "vector_sha256")],
        sa.Column("metadata_json", JSONB, nullable=False),
        sa.Column("completion_scope", sa.String(40), nullable=False, server_default="embedding_response_only"),
        sa.Column("record_sha256", sa.String(64), nullable=False, server_default="0" * 64),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.clock_timestamp()),
        sa.CheckConstraint("btrim(chunk_key)<>'' AND completion_scope='embedding_response_only'", name="ck_er61_scope"),
        *[sa.CheckConstraint(name + " ~ '^[0-9a-f]{64}$'", name="ck_er61_" + name) for name in (
            "evidence_record_sha256", "chunk_binding_sha256", "content_sha256", "vector_sha256", "record_sha256")],
        sa.Index("idx_er61_chunk", "chunk_key"), sa.Index("idx_er61_evidence", "evidence_revision_id"))
    for statement in guard_statements():
        sa.event.listen(table, "after_create", sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"))
    return table
