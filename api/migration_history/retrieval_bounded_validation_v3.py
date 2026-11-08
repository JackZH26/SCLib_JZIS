"""Bound full binary validation without materializing a corpus-wide bytea join.

The v2 guard function remains byte-for-byte retained. Only the validation
table's INSERT trigger moves to this versioned implementation. Its catalog,
fence, role, seal and receipt rules are inherited from the frozen v2 generator.
"""
import sqlalchemy as sa

from migration_history.retrieval_backend_v2 import authority_sql, guard_statements

FUNCTION = 'sclib_retrieval_backend_bounded_v3'
TABLE = 'retrieval_backend_validations_v2'
TRIGGER = 'retrieval_backend_v2_insert'


def statements():
    original = next(sql for sql in guard_statements() if
        'CREATE FUNCTION public.sclib_retrieval_backend_insert_v2()' in sql)
    start = original.index('            EXECUTE format($readback$')
    end = original.index('            NEW.outcome:=', start)
    source = authority_sql()
    assert source.count('WHERE m.content_id=$1') == 1
    source = source.replace('WHERE m.content_id=$1', 'WHERE m.content_id=$1 AND m.partition_id=$2')
    replacement = f'''            -- Count the complete ID universe with narrow rows. Never hash/sort
            -- both complete 3-KiB vectors for all 1.18 million members at once.
            EXECUTE format($inventory$
              WITH authority AS NOT MATERIALIZED (
                SELECT vector_id FROM public.retrieval_content_members_v2 WHERE content_id=$1)
              SELECT count(a.vector_id),count(p.vector_id),
                count(*) FILTER(WHERE p.vector_id IS NULL),count(*) FILTER(WHERE a.vector_id IS NULL)
              FROM authority a FULL JOIN (SELECT vector_id FROM %s) p USING(vector_id)
            $inventory$,qualified) INTO source_count,actual_count,missing_count,extra_count USING build.content_id;
            mismatch_count:=0; processed_count:=0;
            FOR part IN SELECT partition_id FROM public.retrieval_content_partitions_v2
                WHERE content_id=build.content_id ORDER BY partition_id LOOP
              PERFORM set_config('application_name','sclib_corpus_validate_'||replace(identifier::text,'-','')||'_'||part::text,true);
              EXECUTE format($bounded$
                WITH authority AS NOT MATERIALIZED ({source})
                SELECT count(a.vector_id),count(*) FILTER(WHERE p.vector_id IS NOT NULL AND (
                    NOT a.intact OR p.paper_id IS DISTINCT FROM a.paper_id
                    OR p.year IS DISTINCT FROM a.year OR p.content_sha256 IS DISTINCT FROM a.content_sha256
                    OR p.vector_sha256 IS DISTINCT FROM a.vector_sha256
                    OR p.chunk_revision_sha256 IS DISTINCT FROM a.chunk_revision_sha256
                    OR substring(vector_send(p.embedding) FROM 5) IS DISTINCT FROM a.vector_bytes))
                FROM authority a LEFT JOIN LATERAL (
                  SELECT vector_id,paper_id,year,content_sha256,vector_sha256,chunk_revision_sha256,embedding
                  FROM %s p WHERE p.vector_id=a.vector_id OFFSET 0
                ) p ON true
              $bounded$,qualified) INTO part_count,part_mismatches USING build.content_id,part;
              processed_count:=processed_count+part_count; mismatch_count:=mismatch_count+part_mismatches;
            END LOOP;
            NEW.source_member_count:=source_count; NEW.projection_member_count:=actual_count;
            NEW.missing_count:=missing_count; NEW.extra_count:=extra_count; NEW.mismatch_count:=mismatch_count;
            NEW.content_manifest_intact:=processed_count=source_count AND NOT EXISTS(
              SELECT 1 FROM public.retrieval_content_partitions_v2 p WHERE p.content_id=build.content_id
                AND p.manifest_sha256 IS DISTINCT FROM public.sclib_retrieval_partition_hash_v2(p.content_id,p.partition_id));
'''
    sql = original[:start] + replacement + original[end:]
    sql = sql.replace('FUNCTION public.sclib_retrieval_backend_insert_v2()', f'FUNCTION public.{FUNCTION}()', 1)
    sql = sql.replace(" SET bytea_output='hex'", " SET bytea_output='hex' SET work_mem='32MB' SET max_parallel_workers_per_gather=0", 1)
    sql = sql.replace('        source_count bigint;',
        '        part integer; part_count bigint; part_mismatches bigint; processed_count bigint; old_application text;\n        source_count bigint;', 1)
    sql = sql.replace('      BEGIN\n        PERFORM public.sclib_retrieval_require_builder_v2();',
        "      BEGIN\n        old_application:=current_setting('application_name');\n        PERFORM public.sclib_retrieval_require_builder_v2();", 1)
    sql = sql.replace('        NEW.created_at:=clock_timestamp();',
        "        PERFORM set_config('application_name',old_application,true);\n        NEW.created_at:=clock_timestamp();", 1)
    return [sql, f'DROP TRIGGER {TRIGGER} ON public.{TABLE}',
        f'CREATE TRIGGER {TRIGGER} BEFORE INSERT ON public.{TABLE} FOR EACH ROW EXECUTE FUNCTION public.{FUNCTION}()']


def register(metadata):
    # Runs after all table-level frozen guards and can also be used without
    # pgvector installed; the closed dynamic SQL executes only for real builds.
    for sql in statements():
        sa.event.listen(metadata, 'after_create', sa.DDL(sql.replace('%', '%%')).execute_if(dialect='postgresql'))
    sa.event.listen(metadata, 'before_drop', sa.DDL(f'''DO $$ BEGIN
      IF to_regclass('public.{TABLE}') IS NOT NULL THEN
        DROP TRIGGER IF EXISTS {TRIGGER} ON public.{TABLE};
      END IF;
      DROP FUNCTION IF EXISTS public.{FUNCTION}();
    END $$''').execute_if(dialect='postgresql'))
