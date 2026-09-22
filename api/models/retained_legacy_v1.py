"""Retained legacy bytes and exact new windows; no historical parser assertion.

The frozen paper/source bodies are normalized to avoid copying a multi-megabyte
source into every retained. Existing source chunks remain untouched. Replayed
windows have new identities, unresolved original roots and unresolved rights.
"""

import sqlalchemy as sa

TABLE_ORDER = ("legacy_index_papers", "legacy_index_sources", "legacy_index_windows")
KIND = "retained_legacy_snapshot"
RENDERER = "sclib-legacy-input-pack/1.0.0"
PARSER = "sclib-retained-snapshot-reader/1.0.0"
FUNCTION_SIGNATURES = (("sclib_legacy_index_insert_v1", ""), ("sclib_legacy_evidence_v1", ""))
_SQL = "LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp SET TimeZone='UTC'"


def kind_constraints(include=True):
    kinds = "'original_passage','abstract'" + (",'retained_legacy_snapshot'" if include else "")
    return [
        "ALTER TABLE public.rag_evidence_revisions DROP CONSTRAINT ck_re60_kind",
        "ALTER TABLE public.rag_evidence_revisions ADD CONSTRAINT ck_re60_kind CHECK "
        f"(version='rag-evidence/1.0.0' AND btrim(chunk_key)<>'' AND chunk_kind IN ({kinds},'derived_fact'))",
        "ALTER TABLE public.rag_evidence_revisions DROP CONSTRAINT ck_re60_parent",
        "ALTER TABLE public.rag_evidence_revisions ADD CONSTRAINT ck_re60_parent CHECK "
        "((chunk_kind='derived_fact' AND parent_extraction_revision_id IS NOT NULL AND extraction_version IS NOT NULL "
        "AND btrim(extraction_version)<>'' AND rendering_version IS NOT NULL AND btrim(rendering_version)<>'') OR "
        f"(chunk_kind IN ({kinds}) AND parent_extraction_revision_id IS NULL AND extraction_version IS NULL "
        "AND (rendering_version IS NULL OR btrim(rendering_version)<>'')))",
    ]


def guard_statements():
    statements = kind_constraints() + [
        f"""
      CREATE OR REPLACE FUNCTION public.sclib_legacy_index_insert_v1() RETURNS trigger {_SQL} AS $$
      DECLARE body jsonb; actual jsonb; paper public.legacy_index_papers%ROWTYPE;
        source public.legacy_index_sources%ROWTYPE; source_chunk jsonb; input text; first integer; last integer;
      BEGIN
        PERFORM public.sclib_research_integrity_lock_v1();
        body:=NEW.body_raw::jsonb;
        IF octet_length(NEW.body_raw)>16777216 OR jsonb_typeof(body)<>'object' THEN
          RAISE EXCEPTION 'legacy_retention_size_or_kind' USING ERRCODE='23514'; END IF;
        IF TG_TABLE_NAME='legacy_index_papers' THEN
          SELECT to_jsonb(p) INTO actual FROM public.papers p WHERE p.id=NEW.paper_id;
          IF actual IS NULL OR body IS DISTINCT FROM public.sclib_index_paper_snapshot_v1(actual)
            OR NEW.paper_sha256<>public.sclib_answer_evidence_text_hash_v1(NEW.body_raw)
            OR NEW.source_snapshot_sha256<>public.sclib_source_lifecycle_snapshot_hash_v1('paper',actual) THEN
            RAISE EXCEPTION 'legacy_exact_paper_required' USING ERRCODE='23514'; END IF;
        ELSIF TG_TABLE_NAME='legacy_index_sources' THEN
          SELECT * INTO paper FROM public.legacy_index_papers WHERE paper_sha256=NEW.paper_sha256;
          SELECT to_jsonb(c) INTO actual FROM public.chunks c WHERE c.id=NEW.source_key;
          IF paper.paper_sha256 IS NULL OR actual IS NULL OR actual->>'paper_id'<>paper.paper_id
            OR body IS DISTINCT FROM jsonb_build_object('chunk',actual,'paper_sha256',NEW.paper_sha256)
            OR NEW.source_sha256<>public.sclib_answer_evidence_text_hash_v1(NEW.body_raw) THEN
            RAISE EXCEPTION 'legacy_exact_source_required' USING ERRCODE='23514'; END IF;
        ELSE
          SELECT * INTO source FROM public.legacy_index_sources WHERE source_sha256=NEW.source_sha256;
          SELECT to_jsonb(c) INTO actual FROM public.chunks c WHERE c.id=NEW.chunk_key;
          source_chunk:=(source.body_raw::jsonb)->'chunk';
          NEW.source_key:=source.source_key;
          first:=(body->>'char_start')::integer; last:=(body->>'char_end')::integer;
          IF source.source_sha256 IS NULL OR actual IS NULL
            OR body-ARRAY['id','source_sha256','char_start','char_end','prefix','content_sha256','local_tokens',
              'input_characters','input_utf8_bytes','embedding_input_admissible']<>'{{}}'::jsonb
            OR NOT body ?& ARRAY['id','source_sha256','char_start','char_end','prefix','content_sha256','local_tokens',
              'input_characters','input_utf8_bytes','embedding_input_admissible']
            OR body->>'source_sha256' IS DISTINCT FROM NEW.source_sha256
            OR body->>'id' IS DISTINCT FROM NEW.chunk_key
            OR NEW.chunk_key IS DISTINCT FROM 'ls1_'||public.sclib_answer_evidence_text_hash_v1(
                public.sclib_answer_evidence_canonical_v1((body-'id')||jsonb_build_object('version','{RENDERER}')))
            OR body->'embedding_input_admissible' IS DISTINCT FROM 'true'::jsonb
            OR jsonb_typeof(body->'prefix') IS DISTINCT FROM 'string'
            OR jsonb_typeof(body->'char_start') IS DISTINCT FROM 'number'
            OR jsonb_typeof(body->'char_end') IS DISTINCT FROM 'number'
            OR first<0 OR last<=first OR last>char_length(source_chunk->>'text')
            OR (body->>'char_start')::numeric<>first OR (body->>'char_end')::numeric<>last
            OR (body->>'local_tokens')::integer NOT BETWEEN 1 AND 1536 THEN
            RAISE EXCEPTION 'legacy_exact_window_required' USING ERRCODE='23514'; END IF;
          input:=(body->>'prefix')||substring(source_chunk->>'text' FROM first+1 FOR last-first);
          IF actual IS DISTINCT FROM (source_chunk||jsonb_build_object('id',NEW.chunk_key,'text',input))
            OR body->>'content_sha256' IS DISTINCT FROM public.sclib_answer_evidence_text_hash_v1(input)
            OR (body->>'input_characters')::numeric<>char_length(input)
            OR (body->>'input_utf8_bytes')::numeric<>octet_length(input) OR octet_length(input)>1048576 THEN
            RAISE EXCEPTION 'legacy_window_bytes_mismatch' USING ERRCODE='23514'; END IF;
        END IF;
        NEW.created_at:=clock_timestamp(); NEW.record_sha256:=public.sclib_index_record_hash_v1(to_jsonb(NEW));
        RETURN NEW;
      END $$
    """,
        f"""
      CREATE OR REPLACE FUNCTION public.sclib_legacy_evidence_v1() RETURNS trigger {_SQL} AS $$
      DECLARE retained public.legacy_index_windows%ROWTYPE; source public.legacy_index_sources%ROWTYPE;
        paper public.legacy_index_papers%ROWTYPE; body jsonb;
      BEGIN
        IF NEW.chunk_kind<>'{KIND}' THEN RETURN NEW; END IF;
        SELECT * INTO retained FROM public.legacy_index_windows WHERE chunk_key=NEW.chunk_key;
        SELECT * INTO source FROM public.legacy_index_sources WHERE source_sha256=retained.source_sha256;
        SELECT * INTO paper FROM public.legacy_index_papers WHERE paper_sha256=source.paper_sha256;
        body:=retained.body_raw::jsonb;
        IF retained.chunk_key IS NULL OR source.source_sha256 IS NULL OR paper.paper_sha256 IS NULL
          OR NEW.paper_id<>paper.paper_id OR NEW.content_sha256<>body->>'content_sha256'
          OR NEW.source_snapshot_sha256<>paper.source_snapshot_sha256
          OR NEW.rendering_version IS DISTINCT FROM '{RENDERER}' OR NEW.extraction_version IS NOT NULL
          OR NEW.parent_extraction_revision_id IS NOT NULL OR NEW.source_capture_id IS NOT NULL
          OR NEW.unresolved_reason<>'legacy_unresolved' OR NEW.permission_status NOT IN ('unresolved','restricted')
          OR NEW.source_locator IS DISTINCT FROM jsonb_build_object('char_start',body->'char_start','char_end',body->'char_end') THEN
          RAISE EXCEPTION 'legacy_retained_evidence_binding_required' USING ERRCODE='23514'; END IF;
        RETURN NEW;
      END $$
    """,
        "CREATE TRIGGER re79_legacy BEFORE INSERT ON public.rag_evidence_revisions "
        "FOR EACH ROW EXECUTE FUNCTION public.sclib_legacy_evidence_v1()",
    ]
    for name in TABLE_ORDER:
        statements.extend(
            [
                f"CREATE TRIGGER ls79_insert BEFORE INSERT ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_legacy_index_insert_v1()",
                f"CREATE TRIGGER ls79_immutable BEFORE UPDATE OR DELETE ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_index_immutable_v1()",
                f"CREATE TRIGGER ls79_truncate BEFORE TRUNCATE ON public.{name} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_index_immutable_v1()",
            ]
        )
    return statements


def register(metadata):
    tables = {}

    def column(name, kind):
        return sa.Column(name, kind, nullable=False)

    def history(name, *fields):
        tables[name] = sa.Table(
            name,
            metadata,
            *fields,
            sa.Column("record_sha256", sa.String(64), nullable=False, server_default="0" * 64),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.clock_timestamp(),
            ),
        )
        return tables[name]

    history(
        TABLE_ORDER[0],
        sa.Column("paper_sha256", sa.String(64), primary_key=True),
        column("paper_id", sa.String(100)),
        column("source_snapshot_sha256", sa.String(64)),
        column("body_raw", sa.Text),
        sa.CheckConstraint(
            "paper_sha256 ~ '^[0-9a-f]{64}$' AND source_snapshot_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_ls79_paper",
        ),
    )
    history(
        TABLE_ORDER[1],
        sa.Column("source_sha256", sa.String(64), primary_key=True),
        column("pack_sha256", sa.String(64)),
        column("source_seq", sa.Integer),
        column("source_key", sa.String(200)),
        column("body_raw", sa.Text),
        sa.Column(
            "paper_sha256",
            sa.String(64),
            sa.ForeignKey("legacy_index_papers.paper_sha256", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.UniqueConstraint("pack_sha256", "source_seq", name="uq_ls79_source_sequence"),
        sa.UniqueConstraint("pack_sha256", "source_key", name="uq_ls79_source_identity"),
        sa.Index("idx_ls79_paper_pack", "paper_sha256", "pack_sha256"),
        sa.CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$' AND pack_sha256 ~ '^[0-9a-f]{64}$' AND source_seq>0",
            name="ck_ls79_source",
        ),
    )
    history(
        TABLE_ORDER[2],
        sa.Column("chunk_key", sa.String(200), primary_key=True),
        column("member_seq", sa.Integer),
        column("input_partition", sa.Integer),
        column("body_raw", sa.Text),
        column("source_key", sa.String(200)),
        sa.Column(
            "source_sha256",
            sa.String(64),
            sa.ForeignKey("legacy_index_sources.source_sha256", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "chunk_key ~ '^ls1_[0-9a-f]{64}$' AND member_seq>0 AND input_partition>0",
            name="ck_ls79_window",
        ),
        sa.Index("idx_ls79_source", "source_sha256"),
    )
    for name in (
        "chunks",
        "papers",
        "rag_evidence_revisions",
        "index_active_pointer",
        "answer_evidence_receipts",
    ):
        tables[TABLE_ORDER[-1]].add_is_dependent_on(metadata.tables[name])
    for statement in guard_statements():
        sa.event.listen(
            tables[TABLE_ORDER[-1]],
            "after_create",
            sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"),
        )
    return tables
