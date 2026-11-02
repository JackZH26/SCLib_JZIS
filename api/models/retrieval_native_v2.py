"""Native input/revision history, independent of any ANN provider resource.

Legacy generation rows remain under their original contracts. A native row
cannot relabel a retained legacy window or turn an input-file observation into
source-use permission, an original publisher root or scientific acceptance.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from models.index_generations_v1 import guard_statements as frozen_pilot_guards

TABLE_ORDER = ("retrieval_input_receipts_v2", "retrieval_native_revisions_v2")
HISTORY_TABLES = TABLE_ORDER
FUNCTION_SIGNATURES = (
    ("sclib_retrieval_native_hash_v2", "jsonb"),
    ("sclib_retrieval_record_hash_v2", "jsonb"),
    ("sclib_retrieval_native_immutable_v2", ""),
    ("sclib_retrieval_input_insert_v2", ""),
    ("sclib_retrieval_native_insert_v2", ""),
)
_SQL = "LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp SET TimeZone='UTC'"


def _replace_once(body, before, after):
    if body.count(before) != 1:
        raise ValueError("Frozen native member admission no longer matches the reviewed source")
    return body.replace(before, after, 1)


def _native_member_admission():
    """Reuse all actual current chunk/evidence/receipt/float32 checks verbatim.

    Remove only the old provider-generation membership and pilot-size checks.
    Native identities additionally bind an observed input receipt. This does
    not modify or weaken the original 0062 trigger/function.
    """
    original = next(sql for sql in frozen_pilot_guards()
                    if "CREATE OR REPLACE FUNCTION public.sclib_index_insert_v1()" in sql)
    body = original.split("        ELSIF TG_TABLE_NAME='index_generation_members' THEN", 1)[1].split(
        "        ELSIF TG_TABLE_NAME='index_generation_validations' THEN", 1)[0]
    first = body.index("          SELECT * INTO g FROM public.index_generations")
    last = body.index("          SELECT to_jsonb(c),to_jsonb(p)", first)
    body = body[:first] + body[last:]
    body = body[:body.index("          SELECT count(*),COALESCE(sum(")]
    body = _replace_once(body, "IF g.id IS NULL OR actual IS NULL", "IF actual IS NULL")
    body = _replace_once(body,
        "public.sclib_index_revision_hash_v1(to_jsonb(NEW))",
        "public.sclib_retrieval_native_hash_v2(to_jsonb(NEW))")
    body = _replace_once(body,
        "NEW.vector_id<>'ig62_'||replace(NEW.generation_id::text,'-','')||'_'||NEW.chunk_revision_sha256",
        "NEW.vector_id<>'rv2_'||NEW.chunk_revision_sha256")
    if "NEW.generation_id" in body or "g.id" in body:
        raise ValueError("A native revision must not require a provider generation")
    return body


def guard_statements():
    statements = ["""
      CREATE OR REPLACE FUNCTION public.sclib_retrieval_native_hash_v2(body jsonb) RETURNS text
      LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
        SELECT public.sclib_index_hash_v1(jsonb_build_object(
          'version','native-retrieval-revision/2.0.0',
          'source_revision_sha256',public.sclib_index_revision_hash_v1(body),
          'input_receipt_id',body->'input_receipt_id',
          'input_receipt_record_sha256',body->'input_receipt_record_sha256'))
      $$
    """, """
      CREATE OR REPLACE FUNCTION public.sclib_retrieval_record_hash_v2(body jsonb) RETURNS text
      LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
        SELECT public.sclib_index_record_hash_v1(CASE WHEN body ? 'vector_bytes' THEN
          body||jsonb_build_object('vector_bytes',encode((body->>'vector_bytes')::bytea,'hex')) ELSE body END)
      $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_retrieval_native_immutable_v2() RETURNS trigger {_SQL} AS $$
      BEGIN RAISE EXCEPTION 'retrieval input/revision history is append-only' USING ERRCODE='55000'; END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_retrieval_input_insert_v2() RETURNS trigger {_SQL} AS $$
      DECLARE paper jsonb;
      BEGIN
        PERFORM public.sclib_index_lock_v1();
        SELECT to_jsonb(p) INTO paper FROM public.papers p WHERE p.id=NEW.paper_id;
        IF paper IS NULL OR NEW.source_snapshot_sha256 IS DISTINCT FROM
             public.sclib_source_lifecycle_snapshot_hash_v1('paper',paper)
          OR NEW.capture_method<>'regular-file-full-read/1'
          OR NEW.parser_version !~ '^[A-Za-z0-9][A-Za-z0-9._:/+@-]{{0,159}}$'
          OR lower(NEW.parser_version) IN ('unknown','legacy_unknown','unrecorded')
          OR NEW.chunker_version !~ '^[A-Za-z0-9][A-Za-z0-9._:/+@-]{{0,159}}$'
          OR lower(NEW.chunker_version) IN ('unknown','legacy_unknown','unrecorded')
          OR NEW.archive_relative_path ~ '(^/|(^|/)[.][.](/|$)|[[:cntrl:]])'
          OR btrim(NEW.archive_relative_path)='' OR btrim(NEW.source_uri)=''
          OR NEW.source_uri ~ '[[:cntrl:]]' OR btrim(NEW.media_type)=''
          OR NEW.observed_at !~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}T[0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}}[.][0-9]{{6}}Z$'
          OR NOT isfinite(NEW.observed_at::timestamptz)
          OR to_char(NEW.observed_at::timestamptz AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"')<>NEW.observed_at
          OR NEW.observed_at::timestamptz>clock_timestamp()+interval '30 seconds'
          OR NEW.expected_bytes IS NOT NULL AND NEW.expected_bytes<>NEW.representation_bytes
          OR NEW.provider_sha256 IS NOT NULL AND NEW.provider_sha256<>NEW.representation_sha256 THEN
          RAISE EXCEPTION 'retrieval_exact_observed_input_required' USING ERRCODE='23514'; END IF;
        NEW.created_at:=clock_timestamp();
        NEW.record_sha256:=public.sclib_retrieval_record_hash_v2(to_jsonb(NEW));
        RETURN NEW;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_retrieval_native_insert_v2() RETURNS trigger {_SQL} AS $$
      DECLARE e public.rag_evidence_revisions%ROWTYPE;
        r public.embedding_completion_receipts%ROWTYPE;
        input public.retrieval_input_receipts_v2%ROWTYPE;
        actual jsonb; paper jsonb; source_hash text; total integer;
      BEGIN
        PERFORM public.sclib_index_lock_v1();
        {_native_member_admission()}
        SELECT * INTO input FROM public.retrieval_input_receipts_v2 WHERE id=NEW.input_receipt_id;
        IF input.id IS NULL OR input.record_sha256 IS DISTINCT FROM NEW.input_receipt_record_sha256
          OR input.record_sha256 IS DISTINCT FROM public.sclib_retrieval_record_hash_v2(to_jsonb(input))
          OR input.paper_id IS DISTINCT FROM NEW.paper_id
          OR input.source_snapshot_sha256 IS DISTINCT FROM NEW.source_snapshot_sha256
          OR input.parser_version IS DISTINCT FROM NEW.parser_version
          OR input.chunker_version IS DISTINCT FROM NEW.chunker_version
          OR input.source_scope IS DISTINCT FROM (CASE e.chunk_kind
             WHEN 'abstract' THEN 'abstract' WHEN 'original_passage' THEN 'full_text'
             WHEN 'derived_fact' THEN 'structured_record' ELSE 'inadmissible' END) THEN
          RAISE EXCEPTION 'retrieval_native_input_binding_required' USING ERRCODE='23514'; END IF;
        NEW.created_at:=clock_timestamp();
        NEW.record_sha256:=public.sclib_retrieval_record_hash_v2(to_jsonb(NEW));
        RETURN NEW;
      END $$
    """]
    for table, insert in ((TABLE_ORDER[0], "sclib_retrieval_input_insert_v2"),
                          (TABLE_ORDER[1], "sclib_retrieval_native_insert_v2")):
        statements.extend([
            f"CREATE TRIGGER native_v2_insert BEFORE INSERT ON public.{table} "
            f"FOR EACH ROW EXECUTE FUNCTION public.{insert}()",
            f"CREATE TRIGGER native_v2_immutable BEFORE UPDATE OR DELETE ON public.{table} "
            "FOR EACH ROW EXECUTE FUNCTION public.sclib_retrieval_native_immutable_v2()",
            f"CREATE TRIGGER native_v2_no_truncate BEFORE TRUNCATE ON public.{table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_retrieval_native_immutable_v2()",
        ])
    return statements


def register(metadata):
    def column(name, kind, *, required=True, default=None):
        return sa.Column(name, kind, nullable=not required, server_default=default)

    def uid(name, target=None):
        return column(name, UUID(as_uuid=True)) if target is None else sa.Column(
            name, UUID(as_uuid=True), sa.ForeignKey(target, ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False)

    def history(name, *fields):
        return sa.Table(name, metadata, *fields,
            column("record_sha256", sa.String(64), default="0" * 64),
            column("created_at", sa.DateTime(timezone=True), default=sa.func.clock_timestamp()),
            sa.CheckConstraint("record_sha256 ~ '^[0-9a-f]{64}$'", name="ck_" + name + "_hash"))

    inputs = history(TABLE_ORDER[0], uid("id"), column("paper_id", sa.String(100)),
        column("version", sa.String(40), default="retrieval-input/2.0.0"),
        column("source_scope", sa.String(30)), column("source_uri", sa.String(2048)),
        column("archive_relative_path", sa.String(2048)), column("media_type", sa.String(128)),
        column("representation_sha256", sa.String(64)), column("representation_bytes", sa.BigInteger),
        column("expected_bytes", sa.BigInteger, required=False),
        column("provider_sha256", sa.String(64), required=False),
        column("source_snapshot_sha256", sa.String(64)),
        column("parser_version", sa.String(160)), column("chunker_version", sa.String(160)),
        column("capture_method", sa.String(64)), column("observed_at", sa.String(27)),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("version='retrieval-input/2.0.0' AND source_scope IN ('abstract','full_text','structured_record') "
            "AND representation_bytes BETWEEN 1 AND 134217728 AND representation_sha256 ~ '^[0-9a-f]{64}$' "
            "AND source_snapshot_sha256 ~ '^[0-9a-f]{64}$' "
            "AND (provider_sha256 IS NULL OR provider_sha256 ~ '^[0-9a-f]{64}$')", name="ck_retrieval_input_v2"),
        sa.Index("idx_retrieval_input_v2_paper", "paper_id"))
    revisions = history(TABLE_ORDER[1], uid("id"), column("vector_id", sa.String(120)),
        uid("input_receipt_id", TABLE_ORDER[0] + ".id"), column("input_receipt_record_sha256", sa.String(64)),
        column("chunk_key", sa.String(200)), column("paper_id", sa.String(100)),
        column("snapshot_json", JSONB), column("paper_snapshot_json", JSONB),
        column("vector_bytes", sa.LargeBinary), uid("evidence_revision_id", "rag_evidence_revisions.id"),
        uid("receipt_id", "embedding_completion_receipts.id"),
        *[column(name, sa.String(64)) for name in ("snapshot_sha256", "chunk_revision_sha256",
          "evidence_record_sha256", "receipt_record_sha256", "source_snapshot_sha256", "content_sha256", "vector_sha256")],
        column("parser_version", sa.String(160)), column("chunker_version", sa.String(160)),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("vector_id", name="uq_retrieval_native_v2_vector"),
        sa.UniqueConstraint("chunk_revision_sha256", name="uq_retrieval_native_v2_revision"),
        sa.CheckConstraint("octet_length(vector_bytes)=3072 AND jsonb_typeof(snapshot_json)='object' "
            "AND jsonb_typeof(paper_snapshot_json)='object'", name="ck_retrieval_native_v2_payload"),
        sa.Index("idx_retrieval_native_v2_paper", "paper_id"))
    revisions.add_is_dependent_on(metadata.tables["index_active_pointer"])
    for statement in guard_statements():
        sa.event.listen(revisions, "after_create", sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"))
    return {inputs.name: inputs, revisions.name: revisions}
