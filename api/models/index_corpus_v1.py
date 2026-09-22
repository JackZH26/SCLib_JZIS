"""Partition-sealed corpus generations; bounded member and observation batches.

0062 records and hashes remain unchanged. Corpus membership reuses the exact
receipt/evidence checks, with a separate bounded partition plan and seal. The
root hashes those seals instead of constructing a million-element JSON array.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from models.index_generations_v1 import guard_statements as pilot_guards
from models.retained_legacy_v1 import PARSER

TABLE_ORDER = (
    "index_corpora",
    "index_corpus_partitions",
    "index_corpus_member_routes",
    "index_corpus_formula_terms",
    "index_corpus_seals",
    "index_corpus_observations",
)
_SQL = "LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp SET TimeZone='UTC'"


def _replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError("Frozen 0062 guard no longer matches the reviewed corpus extension")
    return text.replace(old, new, 1)


def _pilot_insert():
    return next(
        sql
        for sql in pilot_guards()
        if "CREATE OR REPLACE FUNCTION public.sclib_index_insert_v1()" in sql
    )


def _adapted_guards():
    """Reuse frozen current-source/hash checks verbatim, replacing only scope.

    Original bounded generations continue through the original trigger body.
    This explicit extension avoids weakening the original 1000-member API.
    """
    original = _pilot_insert()
    declarations = original.split("      DECLARE ", 1)[1].split("      BEGIN", 1)[0]
    member = original.split("        ELSIF TG_TABLE_NAME='index_generation_members' THEN", 1)[
        1
    ].split("        ELSIF TG_TABLE_NAME='index_generation_validations' THEN", 1)[0]
    member = _replace_once(
        member,
        "SELECT count(*),COALESCE(sum(octet_length(snapshot_json::text)+octet_length(paper_snapshot_json::text)),0)\n"
        "            INTO total,bytes FROM public.index_generation_members WHERE generation_id=g.id;",
        "SELECT ordinal-1,cumulative_snapshot_bytes-snapshot_bytes INTO total,bytes "
        "FROM public.index_corpus_member_routes WHERE generation_id=g.id AND chunk_key=NEW.chunk_key;",
    )
    member = _replace_once(
        member,
        "total>=g.expected_member_count",
        "total>=(SELECT expected_member_count "
        "FROM public.index_corpus_partitions WHERE generation_id=g.id AND partition_id=(SELECT partition_id "
        "FROM public.index_corpus_member_routes WHERE generation_id=g.id AND chunk_key=NEW.chunk_key))",
    )
    member_preamble = f"""
        IF NOT EXISTS(SELECT 1 FROM public.index_corpus_member_routes route JOIN public.index_corpus_partitions part
          USING(generation_id,partition_id) WHERE route.generation_id=NEW.generation_id AND route.chunk_key=NEW.chunk_key
          AND route.snapshot_bytes=octet_length(NEW.snapshot_json::text)+octet_length(NEW.paper_snapshot_json::text)
          AND NOT EXISTS(SELECT 1 FROM public.index_corpus_seals seal WHERE seal.generation_id=route.generation_id
            AND seal.partition_id=route.partition_id)) OR NEW.parser_version<>'{PARSER}'
          OR NOT EXISTS(SELECT 1 FROM public.rag_evidence_revisions retained_evidence JOIN public.legacy_index_windows w
            ON w.chunk_key=retained_evidence.chunk_key JOIN public.legacy_index_sources s ON s.source_sha256=w.source_sha256
            JOIN public.index_corpora c ON c.generation_id=NEW.generation_id AND c.pack_sha256=s.pack_sha256
            WHERE retained_evidence.id=NEW.evidence_revision_id AND retained_evidence.chunk_kind='retained_legacy_snapshot') THEN
          RAISE EXCEPTION 'corpus_exact_planned_retained_member_required' USING ERRCODE='23514'; END IF;
    """
    observation = original.split(
        "        ELSIF TG_TABLE_NAME='index_generation_validations' THEN", 1
    )[1].split("        ELSE\n          SELECT * INTO g FROM public.index_generations", 1)[0]
    observation = _replace_once(
        observation,
        "expected:=public.sclib_index_manifest_v1(g.id);",
        "expected:=public.sclib_corpus_partition_manifest_v1(g.id,NEW.partition_id);",
    )
    observation = _replace_once(
        observation,
        "jsonb_array_length(expected)<>g.expected_member_count OR public.sclib_index_manifest_hash_v1(expected)<>g.manifest_sha256",
        "NOT EXISTS(SELECT 1 FROM public.index_corpus_seals seal JOIN public.index_corpus_partitions part "
        "USING(generation_id,partition_id) WHERE seal.generation_id=g.id AND seal.partition_id=NEW.partition_id "
        "AND jsonb_array_length(expected)=part.expected_member_count "
        "AND public.sclib_index_manifest_hash_v1(expected)=part.manifest_sha256)",
    )
    activation = original.split(
        "        ELSE\n          SELECT * INTO g FROM public.index_generations", 1
    )[1].split("        END IF;\n        NEW.created_at", 1)[0]
    activation = "SELECT * INTO g FROM public.index_generations" + activation
    activation = _replace_once(
        activation,
        "public.sclib_index_manifest_hash_v1(public.sclib_index_manifest_v1(g.id))<>g.manifest_sha256",
        "public.sclib_corpus_root_v1(g.id) IS DISTINCT FROM g.manifest_sha256",
    )
    # Retained held text stays in the reproducible corpus, but remains excluded
    # by current retrieval admission. An activation cannot claim rights or
    # rewrite the held paper. Any source snapshot drift still blocks activation.
    start = activation.index("          IF EXISTS(SELECT 1 FROM public.index_generation_members m")
    activation = (
        activation[:start]
        + """
          IF EXISTS(SELECT 1 FROM public.legacy_index_papers retained
            JOIN public.index_corpora corpus ON corpus.generation_id=g.id
            LEFT JOIN public.papers live_paper ON live_paper.id=retained.paper_id
            WHERE EXISTS(SELECT 1 FROM public.legacy_index_sources source WHERE source.paper_sha256=retained.paper_sha256
              AND source.pack_sha256=corpus.pack_sha256)
            AND (live_paper.id IS NULL OR retained.source_snapshot_sha256 IS DISTINCT FROM
              public.sclib_source_lifecycle_snapshot_hash_v1('paper',to_jsonb(live_paper)))) THEN
            RAISE EXCEPTION 'corpus_current_source_snapshot_changed' USING ERRCODE='23514'; END IF;
    """
    )
    statements = []
    for name, table, body in (
        ("member", "index_generation_members", member_preamble + member),
        ("observation", "index_corpus_observations", observation),
        ("activation", "index_activation_events", activation),
    ):
        statements.append(f"""CREATE OR REPLACE FUNCTION public.sclib_corpus_{name}_v1(NEW public.{table})
          RETURNS public.{table} {_SQL} AS $$ DECLARE {declarations} BEGIN
          {body}
          NEW.created_at:=clock_timestamp(); NEW.record_sha256:=public.sclib_index_record_hash_v1(to_jsonb(NEW));
          RETURN NEW; END $$""")
    hook = """
        IF EXISTS(SELECT 1 FROM public.index_corpora WHERE generation_id=(to_jsonb(NEW)->>'generation_id')::uuid) THEN
          IF TG_TABLE_NAME='index_generation_members' THEN RETURN public.sclib_corpus_member_v1(NEW);
          ELSIF TG_TABLE_NAME='index_generation_validations' THEN RETURN public.sclib_corpus_validation_v1(NEW);
          ELSIF TG_TABLE_NAME='index_activation_events' THEN RETURN public.sclib_corpus_activation_v1(NEW); END IF;
        END IF;
    """
    original = _replace_once(
        original,
        "OR NEW.resource->>'feature_norm' IS DISTINCT FROM 'NONE'",
        "OR COALESCE(NEW.resource->>'feature_norm','') NOT IN ('NONE','UNIT_L2_NORM')",
    )
    statements.append(
        _replace_once(
            original,
            "        PERFORM public.sclib_index_lock_v1();",
            "        PERFORM public.sclib_index_lock_v1();" + hook,
        )
    )
    return statements


def guard_statements():
    statements = [
        "CREATE INDEX IF NOT EXISTS idx_ic80_fulltext ON public.index_generation_members USING gin "
        "(to_tsvector('english'::regconfig,coalesce(snapshot_json->>'title','')||' '||(snapshot_json->>'text')))",
        "ALTER TABLE public.index_generations DROP CONSTRAINT ck_ig62_generation",
        "ALTER TABLE public.index_generations ADD CONSTRAINT ck_ig62_generation CHECK "
        "(btrim(logical_index)<>'' AND expected_member_count BETWEEN 1 AND 2000000 AND manifest_sha256 ~ '^[0-9a-f]{64}$')",
        """CREATE OR REPLACE FUNCTION public.sclib_corpus_partition_manifest_v1(identifier uuid, part integer) RETURNS jsonb
          LANGUAGE sql STABLE SET search_path=pg_catalog,public,pg_temp AS $$
          SELECT COALESCE(jsonb_agg(jsonb_build_object('vector_id',m.vector_id,'content_sha256',m.content_sha256,
            'vector_sha256',m.vector_sha256) ORDER BY m.vector_id COLLATE "C"),'[]'::jsonb)
          FROM public.index_corpus_member_routes r JOIN public.index_generation_members m
            ON m.generation_id=r.generation_id AND m.chunk_key=r.chunk_key
          WHERE r.generation_id=identifier AND r.partition_id=part
        $$""",
        """
        CREATE OR REPLACE FUNCTION public.sclib_corpus_root_v1(identifier uuid) RETURNS text
          LANGUAGE sql STABLE SET search_path=pg_catalog,public,pg_temp AS $$
          SELECT CASE WHEN count(*)=c.expected_partitions AND sum(p.expected_member_count)=g.expected_member_count
            THEN public.sclib_answer_evidence_text_hash_v1(string_agg(p.partition_id::text||E'\\t'||
              p.expected_member_count::text||E'\\t'||p.snapshot_bytes::text||E'\\t'||p.manifest_sha256||E'\\n','' ORDER BY p.partition_id))
            ELSE NULL END FROM public.index_corpora c JOIN public.index_generations g ON g.id=c.generation_id
            JOIN public.index_corpus_partitions p ON p.generation_id=c.generation_id
            JOIN public.index_corpus_seals s ON s.generation_id=p.generation_id AND s.partition_id=p.partition_id
            AND s.manifest_sha256=p.manifest_sha256 WHERE c.generation_id=identifier
            GROUP BY c.expected_partitions,g.expected_member_count
        $$""",
        f"""
        CREATE OR REPLACE FUNCTION public.sclib_corpus_validation_v1(NEW public.index_generation_validations)
          RETURNS public.index_generation_validations {_SQL} AS $$
          DECLARE g public.index_generations%ROWTYPE; c public.index_corpora%ROWTYPE; body jsonb;
            count_parts integer; started timestamptz; checked timestamptz; ids jsonb; good boolean;
          BEGIN
            SELECT * INTO g FROM public.index_generations WHERE id=NEW.generation_id;
            SELECT * INTO c FROM public.index_corpora WHERE generation_id=g.id;
            body:=NEW.observation; ids:=body->'partition_observation_ids';
            IF g.id IS NULL OR c.generation_id IS NULL OR jsonb_typeof(body) IS DISTINCT FROM 'object'
              OR octet_length(body::text)>1048576 OR body-ARRAY['version','observation_id','observed_at','started_at',
                'resource','profile','adapter_version','partition_observation_ids','full_inventory_observed']<>'{{}}'::jsonb
              OR NOT body ?& ARRAY['version','observation_id','observed_at','started_at','resource','profile',
                'adapter_version','partition_observation_ids','full_inventory_observed']
              OR body->>'version' IS DISTINCT FROM 'sclib-corpus-observation/1.0.0'
              OR body->'resource' IS DISTINCT FROM g.resource OR body->'profile' IS DISTINCT FROM g.profile
              OR body->'full_inventory_observed' IS DISTINCT FROM 'false'::jsonb
              OR body->>'adapter_version' IS DISTINCT FROM 'sclib-corpus-vector-adapter/1.0.0'
              OR jsonb_typeof(ids) IS DISTINCT FROM 'array' OR jsonb_array_length(ids)<>c.expected_partitions
              OR public.sclib_corpus_root_v1(g.id) IS DISTINCT FROM g.manifest_sha256 THEN
              RAISE EXCEPTION 'corpus_closed_complete_observation_required' USING ERRCODE='23514'; END IF;
            started:=(body->>'started_at')::timestamptz; checked:=(body->>'observed_at')::timestamptz;
            IF NOT public.sclib_index_observation_fresh_v1(checked,clock_timestamp()) OR NOT isfinite(started)
              OR started>checked OR started<checked-interval '6 hours' THEN
              RAISE EXCEPTION 'corpus_observation_window_invalid' USING ERRCODE='23514'; END IF;
            SELECT count(DISTINCT p.partition_id),bool_and(o.outcome='validated'
              AND o.observed_manifest_sha256=p.manifest_sha256 AND o.observed_at>=started
              AND o.observed_at<=checked+interval '30 seconds'
              AND o.record_sha256=public.sclib_index_record_hash_v1(to_jsonb(o))) INTO count_parts,good
              FROM jsonb_array_elements_text(ids) item
              JOIN public.index_corpus_observations o ON o.id=item::uuid AND o.generation_id=g.id
              JOIN public.index_corpus_partitions p USING(generation_id,partition_id);
            IF count_parts<>c.expected_partitions OR good IS DISTINCT FROM true THEN
              RAISE EXCEPTION 'corpus_partition_observation_incomplete' USING ERRCODE='23514'; END IF;
            NEW.observation_id:=(body->>'observation_id')::uuid; NEW.observed_at:=checked;
            NEW.outcome:='validated'; NEW.observed_manifest_sha256:=g.manifest_sha256;
            NEW.created_at:=clock_timestamp(); NEW.record_sha256:=public.sclib_index_record_hash_v1(to_jsonb(NEW));
            RETURN NEW;
          END $$
        """,
        f"""
        CREATE OR REPLACE FUNCTION public.sclib_corpus_insert_v1() RETURNS trigger {_SQL} AS $$
          DECLARE g public.index_generations%ROWTYPE; c public.index_corpora%ROWTYPE;
            part public.index_corpus_partitions%ROWTYPE; total integer; bytes bigint; manifest text;
          BEGIN
            PERFORM public.sclib_index_lock_v1();
            SELECT * INTO g FROM public.index_generations WHERE id=NEW.generation_id;
            IF TG_TABLE_NAME='index_corpora' THEN
              IF g.id IS NULL OR EXISTS(SELECT 1 FROM public.index_generation_members WHERE generation_id=g.id)
                OR EXISTS(SELECT 1 FROM public.index_generation_validations WHERE generation_id=g.id)
                OR NEW.expected_partitions>g.expected_member_count
                OR NEW.expected_sources>g.expected_member_count THEN
                RAISE EXCEPTION 'corpus_new_empty_generation_required' USING ERRCODE='23514'; END IF;
            ELSE
              SELECT * INTO c FROM public.index_corpora WHERE generation_id=g.id;
              IF c.generation_id IS NULL THEN RAISE EXCEPTION 'corpus_registration_required' USING ERRCODE='23514'; END IF;
              IF TG_TABLE_NAME='index_corpus_partitions' THEN
                IF NEW.partition_id>c.expected_partitions OR EXISTS(SELECT 1 FROM public.index_corpus_seals WHERE generation_id=g.id) THEN
                  RAISE EXCEPTION 'corpus_partition_plan_sealed' USING ERRCODE='23514'; END IF;
              ELSE
                SELECT * INTO part FROM public.index_corpus_partitions WHERE generation_id=g.id AND partition_id=NEW.partition_id;
                IF part.generation_id IS NULL THEN RAISE EXCEPTION 'corpus_planned_partition_required' USING ERRCODE='23514'; END IF;
                IF TG_TABLE_NAME='index_corpus_member_routes' THEN
                  IF EXISTS(SELECT 1 FROM public.index_corpus_seals WHERE generation_id=g.id AND partition_id=NEW.partition_id)
                    OR NEW.ordinal>part.expected_member_count
                    OR NEW.cumulative_snapshot_bytes>part.snapshot_bytes
                    OR NEW.cumulative_snapshot_bytes IS DISTINCT FROM NEW.snapshot_bytes+(CASE WHEN NEW.ordinal=1 THEN 0 ELSE
                      (SELECT previous.cumulative_snapshot_bytes FROM public.index_corpus_member_routes previous
                        WHERE previous.generation_id=g.id AND previous.partition_id=NEW.partition_id
                          AND previous.ordinal=NEW.ordinal-1) END)
                    OR (NEW.ordinal=part.expected_member_count AND NEW.cumulative_snapshot_bytes<>part.snapshot_bytes) THEN
                    RAISE EXCEPTION 'corpus_route_limit_or_sealed' USING ERRCODE='23514'; END IF;
                ELSIF TG_TABLE_NAME='index_corpus_formula_terms' THEN
                  IF cardinality(NEW.terms)>2048 OR NEW.producer_version<>'sclib-formula-navigation/1.0.0'
                    OR EXISTS(SELECT 1 FROM unnest(NEW.terms) term WHERE term IS NULL OR length(term) NOT BETWEEN 1 AND 200)
                    OR cardinality(NEW.terms)<>(SELECT count(DISTINCT term) FROM unnest(NEW.terms) term)
                    OR EXISTS(SELECT 1 FROM public.index_corpus_seals WHERE generation_id=g.id AND partition_id=NEW.partition_id)
                    OR NOT EXISTS(SELECT 1 FROM public.index_generation_members member
                      JOIN public.index_corpus_member_routes route ON route.generation_id=member.generation_id
                        AND route.chunk_key=member.chunk_key WHERE member.generation_id=g.id AND member.vector_id=NEW.vector_id
                        AND route.partition_id=NEW.partition_id AND member.content_sha256=NEW.content_sha256) THEN
                    RAISE EXCEPTION 'corpus_formula_navigation_binding_required' USING ERRCODE='23514'; END IF;
                ELSIF TG_TABLE_NAME='index_corpus_seals' THEN
                  SELECT count(*),COALESCE(sum(octet_length(m.snapshot_json::text)+octet_length(m.paper_snapshot_json::text)),0)
                    INTO total,bytes FROM public.index_corpus_member_routes r JOIN public.index_generation_members m
                    ON m.generation_id=r.generation_id AND m.chunk_key=r.chunk_key
                    JOIN public.index_corpus_formula_terms formulas ON formulas.generation_id=m.generation_id
                      AND formulas.vector_id=m.vector_id AND formulas.content_sha256=m.content_sha256
                    WHERE r.generation_id=g.id AND r.partition_id=NEW.partition_id;
                  manifest:=public.sclib_index_manifest_hash_v1(public.sclib_corpus_partition_manifest_v1(g.id,NEW.partition_id));
                  IF total<>part.expected_member_count OR bytes<>part.snapshot_bytes OR manifest<>part.manifest_sha256
                    OR NEW.manifest_sha256<>manifest THEN
                    RAISE EXCEPTION 'corpus_partition_seal_incomplete' USING ERRCODE='23514'; END IF;
                ELSE RETURN public.sclib_corpus_observation_v1(NEW);
                END IF;
              END IF;
            END IF;
            NEW.created_at:=clock_timestamp(); NEW.record_sha256:=public.sclib_index_record_hash_v1(to_jsonb(NEW));
            RETURN NEW;
          END $$
        """,
    ]
    statements.extend(_adapted_guards())
    for name in TABLE_ORDER:
        statements.extend(
            [
                f"CREATE TRIGGER ic80_insert BEFORE INSERT ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_corpus_insert_v1()",
                f"CREATE TRIGGER ic80_immutable BEFORE UPDATE OR DELETE ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_index_immutable_v1()",
                f"CREATE TRIGGER ic80_truncate BEFORE TRUNCATE ON public.{name} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_index_immutable_v1()",
            ]
        )
    return statements


def remove_statements():
    statements = [_pilot_insert(), "DROP INDEX IF EXISTS public.idx_ic80_fulltext"]
    for name in TABLE_ORDER:
        for trigger in ("ic80_insert", "ic80_immutable", "ic80_truncate"):
            statements.append(f"DROP TRIGGER IF EXISTS {trigger} ON public.{name}")
    for name, args in (
        ("insert", ""),
        ("member", "public.index_generation_members"),
        ("observation", "public.index_corpus_observations"),
        ("validation", "public.index_generation_validations"),
        ("activation", "public.index_activation_events"),
        ("root", "uuid"),
        ("partition_manifest", "uuid, integer"),
    ):
        statements.append(f"DROP FUNCTION IF EXISTS public.sclib_corpus_{name}_v1({args})")
    return statements


def register(metadata):
    tables = {}
    sa.Index(
        "idx_ic80_fulltext",
        sa.text(
            "to_tsvector('english'::regconfig,coalesce(snapshot_json->>'title','')||' '||(snapshot_json->>'text'))"
        ),
        _table=metadata.tables["index_generation_members"],
        postgresql_using="gin",
    )

    def col(name, kind, default=None):
        return sa.Column(name, kind, nullable=False, server_default=default)

    def generation():
        return sa.Column(
            "generation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("index_generations.id", ondelete="RESTRICT"),
            nullable=False,
        )

    def part_fk():
        return sa.ForeignKeyConstraint(
            ["generation_id", "partition_id"],
            ["index_corpus_partitions.generation_id", "index_corpus_partitions.partition_id"],
            ondelete="RESTRICT",
        )

    def history(name, *fields):
        tables[name] = sa.Table(
            name,
            metadata,
            *fields,
            col("record_sha256", sa.String(64), "0" * 64),
            col("created_at", sa.DateTime(timezone=True), sa.func.clock_timestamp()),
        )

    history(
        TABLE_ORDER[0],
        generation(),
        col("pack_sha256", sa.String(64)),
        col("expected_partitions", sa.Integer),
        col("expected_sources", sa.Integer),
        col("input_manifest_sha256", sa.String(64)),
        sa.PrimaryKeyConstraint("generation_id"),
        sa.CheckConstraint(
            "expected_partitions BETWEEN 1 AND 20000 "
            "AND expected_sources BETWEEN 1 AND 2000000 AND pack_sha256 ~ '^[0-9a-f]{64}$' "
            "AND input_manifest_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_ic80_corpus",
        ),
    )
    history(
        TABLE_ORDER[1],
        generation(),
        col("partition_id", sa.Integer),
        col("expected_member_count", sa.Integer),
        col("snapshot_bytes", sa.BigInteger),
        col("manifest_sha256", sa.String(64)),
        sa.PrimaryKeyConstraint("generation_id", "partition_id"),
        sa.CheckConstraint(
            "partition_id BETWEEN 1 AND 20000 "
            "AND expected_member_count BETWEEN 1 AND 1000 AND snapshot_bytes BETWEEN 1 AND 16777216 "
            "AND manifest_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_ic80_partition",
        ),
    )
    history(
        TABLE_ORDER[2],
        generation(),
        col("chunk_key", sa.String(200)),
        col("partition_id", sa.Integer),
        col("ordinal", sa.Integer),
        col("snapshot_bytes", sa.BigInteger),
        col("cumulative_snapshot_bytes", sa.BigInteger),
        sa.UniqueConstraint(
            "generation_id", "partition_id", "ordinal", name="uq_ic80_route_ordinal"
        ),
        sa.CheckConstraint(
            "ordinal BETWEEN 1 AND 1000 AND snapshot_bytes BETWEEN 1 AND 16777216 "
            "AND cumulative_snapshot_bytes BETWEEN snapshot_bytes AND 16777216",
            name="ck_ic80_route_budget",
        ),
        part_fk(),
        sa.PrimaryKeyConstraint("generation_id", "chunk_key"),
        sa.ForeignKeyConstraint(
            ["generation_id", "chunk_key"],
            ["index_generation_members.generation_id", "index_generation_members.chunk_key"],
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.Index("idx_ic80_route_partition", "generation_id", "partition_id"),
    )
    history(
        "index_corpus_formula_terms",
        generation(),
        col("partition_id", sa.Integer),
        col("vector_id", sa.String(120)),
        col("content_sha256", sa.String(64)),
        col("terms", sa.ARRAY(sa.Text)),
        col("producer_version", sa.String(80)),
        sa.PrimaryKeyConstraint("generation_id", "vector_id"),
        part_fk(),
        sa.ForeignKeyConstraint(
            ["generation_id", "vector_id"],
            ["index_generation_members.generation_id", "index_generation_members.vector_id"],
            ondelete="RESTRICT",
        ),
        sa.Index("idx_ic80_formula_terms", "terms", postgresql_using="gin"),
    )
    history(
        "index_corpus_seals",
        generation(),
        col("partition_id", sa.Integer),
        col("manifest_sha256", sa.String(64)),
        sa.PrimaryKeyConstraint("generation_id", "partition_id"),
        part_fk(),
    )
    history(
        "index_corpus_observations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        generation(),
        col("partition_id", sa.Integer),
        col("observation_id", UUID(as_uuid=True)),
        col("observed_at", sa.DateTime(timezone=True)),
        col("observation", JSONB),
        col("outcome", sa.String(20), "unverified"),
        col("observed_manifest_sha256", sa.String(64), "0" * 64),
        part_fk(),
        sa.UniqueConstraint("observation_id", name="uq_ic80_observation"),
        sa.CheckConstraint(
            "outcome IN ('unverified','validated','rejected')", name="ck_ic80_observation"
        ),
    )
    for name in (*TABLE_ORDER[:-1], "legacy_index_windows", "index_active_pointer"):
        tables[TABLE_ORDER[-1]].add_is_dependent_on(metadata.tables[name])
    for statement in guard_statements():
        sa.event.listen(
            tables[TABLE_ORDER[-1]],
            "after_create",
            sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"),
        )
    for statement in remove_statements():
        sa.event.listen(
            tables[TABLE_ORDER[-1]],
            "before_drop",
            sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"),
        )
    return tables
