"""Partitioned immutable content references, independent of ANN resources.

Construction locks one content row rather than the global source write fence.
Unique admitted references plus a separately counted immutable source universe
prove completeness; a caller cannot bless an arbitrary subset with its count.
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from models.index_generations_v1 import PROFILE

MAX_MEMBERS = 5_000_000
TABLE_ORDER = ("retrieval_publications_v2", "retrieval_publication_members_v2", "retrieval_publication_seals_v2",
    "retrieval_contents_v2", "retrieval_content_changes_v2", "retrieval_content_members_v2",
    "retrieval_content_partitions_v2", "retrieval_content_seals_v2")
FUNCTION_SIGNATURES = (("sclib_retrieval_reference_v2", "text, uuid, uuid, text"),
    ("sclib_retrieval_partition_hash_v2", "uuid, integer"), ("sclib_retrieval_content_root_v2", "uuid"),
    ("sclib_retrieval_content_insert_v2", ""))
_SQL = "LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp SET TimeZone='UTC'"


def guard_statements():
    statements = ["""
      CREATE FUNCTION public.sclib_retrieval_reference_v2(kind text, generation uuid, native uuid, member text)
      RETURNS jsonb LANGUAGE sql STABLE SET search_path=pg_catalog,public,pg_temp AS $$
        SELECT jsonb_build_object('paper_id',m.paper_id,'chunk_key',m.chunk_key,
          'content_sha256',m.content_sha256,'vector_sha256',m.vector_sha256,
          'chunk_revision_sha256',m.chunk_revision_sha256,'origin_record_sha256',m.record_sha256)
        FROM public.index_generation_members m WHERE kind='legacy_v1' AND native IS NULL
          AND m.generation_id=generation AND m.vector_id=member
        UNION ALL
        SELECT jsonb_build_object('paper_id',n.paper_id,'chunk_key',n.chunk_key,
          'content_sha256',n.content_sha256,'vector_sha256',n.vector_sha256,
          'chunk_revision_sha256',n.chunk_revision_sha256,'origin_record_sha256',n.record_sha256)
        FROM public.retrieval_native_revisions_v2 n WHERE kind='native_v2' AND generation IS NULL
          AND n.id=native AND n.vector_id=member
      $$
    """, """
      CREATE FUNCTION public.sclib_retrieval_partition_hash_v2(content uuid, part integer)
      RETURNS text LANGUAGE sql STABLE SET search_path=pg_catalog,public,pg_temp AS $$
        SELECT public.sclib_index_hash_v1(coalesce(jsonb_agg(
          to_jsonb(m)-ARRAY['content_id','partition_id','created_at','record_sha256']
          ORDER BY m.vector_id COLLATE "C"),'[]'::jsonb))
        FROM public.retrieval_content_members_v2 m WHERE m.content_id=content AND m.partition_id=part
      $$
    """, """
      CREATE FUNCTION public.sclib_retrieval_content_root_v2(content uuid)
      RETURNS text LANGUAGE sql STABLE SET search_path=pg_catalog,public,pg_temp AS $$
        SELECT public.sclib_index_hash_v1(jsonb_build_object('version','retrieval-content-root/2.0.0',
          'partitions',coalesce(jsonb_agg(jsonb_build_object('partition_id',p.partition_id,
            'member_count',p.member_count,'manifest_sha256',p.manifest_sha256)
            ORDER BY p.partition_id),'[]'::jsonb)))
        FROM public.retrieval_content_partitions_v2 p WHERE p.content_id=content
      $$
    """, f"""
      CREATE FUNCTION public.sclib_retrieval_content_insert_v2() RETURNS trigger {_SQL} AS $$
      DECLARE publication public.retrieval_publications_v2%ROWTYPE;
        content public.retrieval_contents_v2%ROWTYPE; parent public.retrieval_contents_v2%ROWTYPE;
        generation public.index_generations%ROWTYPE; native public.retrieval_native_revisions_v2%ROWTYPE;
        origin jsonb; total bigint; expected bigint; parts integer; actual_hash text;
      BEGIN
        IF TG_TABLE_NAME='retrieval_publications_v2' THEN
          IF NEW.profile IS DISTINCT FROM '{json.dumps(PROFILE)}'::jsonb
            OR NOT EXISTS(SELECT 1 FROM public.papers WHERE id=NEW.paper_id) THEN
            RAISE EXCEPTION 'native_publication_profile_source' USING ERRCODE='23514'; END IF;
        ELSIF TG_TABLE_NAME IN ('retrieval_publication_members_v2','retrieval_publication_seals_v2') THEN
          IF TG_TABLE_NAME='retrieval_publication_seals_v2' THEN PERFORM public.sclib_index_lock_v1(); END IF;
          SELECT * INTO publication FROM public.retrieval_publications_v2 WHERE id=NEW.publication_id FOR UPDATE;
          IF publication.id IS NULL OR EXISTS(SELECT 1 FROM public.retrieval_publication_seals_v2
              WHERE publication_id=publication.id) THEN
            RAISE EXCEPTION 'native_publication_missing_or_sealed' USING ERRCODE='23514'; END IF;
          IF TG_TABLE_NAME='retrieval_publication_members_v2' THEN
            SELECT * INTO native FROM public.retrieval_native_revisions_v2 WHERE id=NEW.native_revision_id;
            IF native.id IS NULL OR native.paper_id<>publication.paper_id OR
              (SELECT count(*) FROM public.retrieval_publication_members_v2 WHERE publication_id=publication.id)>=1000 THEN
              RAISE EXCEPTION 'native_publication_exact_bounded_revision' USING ERRCODE='23514'; END IF;
            NEW.vector_id:=native.vector_id; NEW.chunk_key:=native.chunk_key;
            NEW.revision_record_sha256:=native.record_sha256;
          ELSE
            SELECT count(*),public.sclib_index_hash_v1(coalesce(jsonb_agg(jsonb_build_object(
                'vector_id',m.vector_id,'native_revision_id',m.native_revision_id,
                'revision_record_sha256',m.revision_record_sha256) ORDER BY m.vector_id COLLATE "C"),'[]'))
              INTO total,actual_hash FROM public.retrieval_publication_members_v2 m WHERE m.publication_id=publication.id;
            SELECT count(*) INTO expected FROM public.chunks WHERE paper_id=publication.paper_id;
            IF total<>publication.expected_member_count OR total<>expected OR EXISTS(
              SELECT 1 FROM public.retrieval_publication_members_v2 m
              JOIN public.retrieval_native_revisions_v2 n ON n.id=m.native_revision_id
              LEFT JOIN public.chunks c ON c.id=n.chunk_key AND c.paper_id=publication.paper_id
              LEFT JOIN public.papers p ON p.id=c.paper_id
              LEFT JOIN public.chunk_evidence_current e ON e.chunk_id=c.id
              WHERE m.publication_id=publication.id AND (c.id IS NULL OR e.evidence_revision_id IS DISTINCT FROM n.evidence_revision_id
                OR n.source_snapshot_sha256 IS DISTINCT FROM public.sclib_source_lifecycle_snapshot_hash_v1('paper',to_jsonb(p))
                OR n.snapshot_sha256 IS DISTINCT FROM public.sclib_index_hash_v1(jsonb_build_object(
                  'chunk',to_jsonb(c),'paper',public.sclib_index_paper_snapshot_v1(to_jsonb(p)))))) THEN
              RAISE EXCEPTION 'native_publication_full_current_inventory_required' USING ERRCODE='23514'; END IF;
            NEW.member_count:=total; NEW.manifest_sha256:=actual_hash;
          END IF;
        ELSIF TG_TABLE_NAME='retrieval_contents_v2' THEN
          IF NEW.source_generation_id IS NOT NULL THEN
            SELECT * INTO generation FROM public.index_generations WHERE id=NEW.source_generation_id;
            SELECT count(*) INTO total FROM public.index_generation_members WHERE generation_id=generation.id;
            IF generation.id IS NULL OR NEW.logical_index IS DISTINCT FROM generation.logical_index
              OR total<>generation.expected_member_count
              OR (CASE WHEN EXISTS(SELECT 1 FROM public.index_corpora WHERE generation_id=generation.id)
                  THEN public.sclib_corpus_root_v1(generation.id)
                  ELSE public.sclib_index_manifest_hash_v1(public.sclib_index_manifest_v1(generation.id)) END)
                  IS DISTINCT FROM generation.manifest_sha256 THEN
              RAISE EXCEPTION 'retrieval_complete_legacy_generation_required' USING ERRCODE='23514'; END IF;
            NEW.profile:=generation.profile;
          ELSE
            SELECT * INTO parent FROM public.retrieval_contents_v2 WHERE id=NEW.base_content_id;
            IF parent.id IS NULL OR parent.logical_index<>NEW.logical_index OR NOT EXISTS(
                SELECT 1 FROM public.retrieval_content_seals_v2 WHERE content_id=parent.id) THEN
              RAISE EXCEPTION 'retrieval_sealed_base_required' USING ERRCODE='23514'; END IF;
            NEW.profile:=parent.profile;
          END IF;
          IF NEW.profile IS DISTINCT FROM '{json.dumps(PROFILE)}'::jsonb THEN
            RAISE EXCEPTION 'retrieval_content_profile_mismatch' USING ERRCODE='23514'; END IF;
        ELSE
          SELECT * INTO content FROM public.retrieval_contents_v2 WHERE id=NEW.content_id FOR UPDATE;
          IF content.id IS NULL OR EXISTS(SELECT 1 FROM public.retrieval_content_seals_v2 WHERE content_id=content.id) THEN
            RAISE EXCEPTION 'retrieval_content_missing_or_sealed' USING ERRCODE='23514'; END IF;
          IF TG_TABLE_NAME='retrieval_content_changes_v2' THEN
            SELECT * INTO publication FROM public.retrieval_publications_v2 WHERE id=NEW.publication_id;
            IF content.base_content_id IS NULL OR publication.id IS NULL OR publication.paper_id<>NEW.paper_id
              OR publication.profile IS DISTINCT FROM content.profile OR NOT EXISTS(
                SELECT 1 FROM public.retrieval_publication_seals_v2 WHERE publication_id=publication.id)
              OR EXISTS(SELECT 1 FROM public.retrieval_content_members_v2 WHERE content_id=content.id) THEN
              RAISE EXCEPTION 'retrieval_frozen_native_change_plan_required' USING ERRCODE='23514'; END IF;
          ELSIF TG_TABLE_NAME='retrieval_content_members_v2' THEN
            origin:=public.sclib_retrieval_reference_v2(NEW.origin_kind,NEW.origin_generation_id,NEW.native_revision_id,NEW.vector_id);
            IF origin IS NULL OR EXISTS(SELECT 1 FROM public.retrieval_content_partitions_v2
                WHERE content_id=content.id AND partition_id=NEW.partition_id)
              OR (SELECT count(*) FROM public.retrieval_content_members_v2
                  WHERE content_id=content.id AND partition_id=NEW.partition_id)>=1000 THEN
              RAISE EXCEPTION 'retrieval_exact_bounded_reference_required' USING ERRCODE='23514'; END IF;
            NEW.paper_id:=origin->>'paper_id'; NEW.chunk_key:=origin->>'chunk_key';
            NEW.content_sha256:=origin->>'content_sha256'; NEW.vector_sha256:=origin->>'vector_sha256';
            NEW.chunk_revision_sha256:=origin->>'chunk_revision_sha256'; NEW.origin_record_sha256:=origin->>'origin_record_sha256';
            IF NOT (content.source_generation_id IS NOT NULL AND NEW.origin_kind='legacy_v1'
                AND NEW.origin_generation_id=content.source_generation_id) AND NOT (
              content.base_content_id IS NOT NULL AND (
                EXISTS(SELECT 1 FROM public.retrieval_content_members_v2 base WHERE base.content_id=content.base_content_id
                  AND base.vector_id=NEW.vector_id AND base.origin_kind=NEW.origin_kind
                  AND base.origin_generation_id IS NOT DISTINCT FROM NEW.origin_generation_id
                  AND base.native_revision_id IS NOT DISTINCT FROM NEW.native_revision_id
                  AND NOT EXISTS(SELECT 1 FROM public.retrieval_content_changes_v2 change
                    WHERE change.content_id=content.id AND change.paper_id=base.paper_id))
                OR NEW.origin_kind='native_v2' AND EXISTS(SELECT 1 FROM public.retrieval_content_changes_v2 change
                  JOIN public.retrieval_publication_members_v2 m ON m.publication_id=change.publication_id
                  WHERE change.content_id=content.id AND change.paper_id=NEW.paper_id AND m.native_revision_id=NEW.native_revision_id))) THEN
              RAISE EXCEPTION 'retrieval_reference_outside_source_universe' USING ERRCODE='23514'; END IF;
            IF NEW.partition_id>=(content.expected_member_count+999)/1000 THEN
              RAISE EXCEPTION 'retrieval_partition_outside_plan' USING ERRCODE='23514'; END IF;
          ELSIF TG_TABLE_NAME='retrieval_content_partitions_v2' THEN
            SELECT count(*) INTO total FROM public.retrieval_content_members_v2
              WHERE content_id=content.id AND partition_id=NEW.partition_id;
            IF total NOT BETWEEN 1 AND 1000 OR NEW.partition_id>=(content.expected_member_count+999)/1000 THEN
              RAISE EXCEPTION 'retrieval_partition_inventory_required' USING ERRCODE='23514'; END IF;
            NEW.member_count:=total;
            NEW.manifest_sha256:=public.sclib_retrieval_partition_hash_v2(content.id,NEW.partition_id);
          ELSIF TG_TABLE_NAME='retrieval_content_seals_v2' THEN
            SELECT count(*) INTO total FROM public.retrieval_content_members_v2 WHERE content_id=content.id;
            SELECT count(*),coalesce(sum(member_count),0) INTO parts,expected
              FROM public.retrieval_content_partitions_v2 WHERE content_id=content.id;
            IF total<>content.expected_member_count OR total<>expected OR parts<>(total+999)/1000 THEN
              RAISE EXCEPTION 'retrieval_all_partitions_required' USING ERRCODE='23514'; END IF;
            IF content.source_generation_id IS NOT NULL THEN
              SELECT count(*) INTO expected FROM public.index_generation_members WHERE generation_id=content.source_generation_id;
            ELSE
              IF NOT EXISTS(SELECT 1 FROM public.retrieval_content_changes_v2 WHERE content_id=content.id) THEN
                RAISE EXCEPTION 'retrieval_native_batch_requires_changes' USING ERRCODE='23514'; END IF;
              SELECT (SELECT count(*) FROM public.retrieval_content_members_v2 base WHERE base.content_id=content.base_content_id
                AND NOT EXISTS(SELECT 1 FROM public.retrieval_content_changes_v2 change
                  WHERE change.content_id=content.id AND change.paper_id=base.paper_id)) +
                (SELECT coalesce(sum(seal.member_count),0) FROM public.retrieval_content_changes_v2 change
                  JOIN public.retrieval_publication_seals_v2 seal USING(publication_id) WHERE change.content_id=content.id)
                INTO expected;
            END IF;
            IF total<>expected THEN
              RAISE EXCEPTION 'retrieval_complete_source_universe_required' USING ERRCODE='23514'; END IF;
            NEW.member_count:=total; NEW.partition_count:=parts;
            NEW.manifest_sha256:=public.sclib_retrieval_content_root_v2(content.id);
          END IF;
        END IF;
        NEW.created_at:=clock_timestamp();
        NEW.record_sha256:=public.sclib_retrieval_record_hash_v2(to_jsonb(NEW));
        RETURN NEW;
      END $$
    """]
    for name in TABLE_ORDER:
        statements.extend([
            f"CREATE TRIGGER retrieval_content_v2_insert BEFORE INSERT ON public.{name} "
            "FOR EACH ROW EXECUTE FUNCTION public.sclib_retrieval_content_insert_v2()",
            f"CREATE TRIGGER retrieval_content_v2_immutable BEFORE UPDATE OR DELETE ON public.{name} "
            "FOR EACH ROW EXECUTE FUNCTION public.sclib_retrieval_native_immutable_v2()",
            f"CREATE TRIGGER retrieval_content_v2_no_truncate BEFORE TRUNCATE ON public.{name} "
            "FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_retrieval_native_immutable_v2()"])
    return statements


def register(metadata):
    def col(name, kind, nullable=False, default=None):
        return sa.Column(name, kind, nullable=nullable, server_default=default)

    def uid(name, target=None, nullable=False):
        if target is None:
            return col(name, UUID(as_uuid=True), nullable=nullable)
        return sa.Column(name, UUID(as_uuid=True), sa.ForeignKey(target, ondelete="RESTRICT", onupdate="RESTRICT"), nullable=nullable)

    def history(name, *fields):
        return sa.Table(name, metadata, *fields, col("record_sha256", sa.String(64), default="0" * 64),
            col("created_at", sa.DateTime(timezone=True), default=sa.func.clock_timestamp()),
            sa.CheckConstraint("record_sha256 ~ '^[0-9a-f]{64}$'", name="ck_" + name + "_hash"))

    publications = history(TABLE_ORDER[0], uid("id"), col("paper_id", sa.String(100)),
        col("expected_member_count", sa.Integer), col("profile", JSONB), sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("expected_member_count BETWEEN 1 AND 1000", name="ck_retrieval_pub_v2_count"))
    publication_members = history(TABLE_ORDER[1], uid("publication_id", TABLE_ORDER[0] + ".id"),
        uid("native_revision_id", "retrieval_native_revisions_v2.id"),
        col("vector_id", sa.String(120)), col("chunk_key", sa.String(200)), col("revision_record_sha256", sa.String(64)),
        sa.PrimaryKeyConstraint("publication_id", "native_revision_id"),
        sa.UniqueConstraint("publication_id", "vector_id"), sa.UniqueConstraint("publication_id", "chunk_key"))
    publication_seals = history(TABLE_ORDER[2], uid("publication_id", TABLE_ORDER[0] + ".id"),
        col("member_count", sa.Integer), col("manifest_sha256", sa.String(64)), sa.PrimaryKeyConstraint("publication_id"))
    contents = history(TABLE_ORDER[3], uid("id"), col("logical_index", sa.String(160)),
        uid("source_generation_id", "index_generations.id", nullable=True), uid("base_content_id", TABLE_ORDER[3] + ".id", nullable=True),
        col("expected_member_count", sa.Integer), col("profile", JSONB), sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("(source_generation_id IS NULL) <> (base_content_id IS NULL) "
            f"AND expected_member_count BETWEEN 1 AND {MAX_MEMBERS} AND logical_index ~ '^[A-Za-z0-9._-]{{1,160}}$'",
            name="ck_retrieval_content_v2_plan"))
    changes = history(TABLE_ORDER[4], uid("content_id", TABLE_ORDER[3] + ".id"), col("paper_id", sa.String(100)),
        uid("publication_id", TABLE_ORDER[0] + ".id"), sa.PrimaryKeyConstraint("content_id", "paper_id"))
    members = history(TABLE_ORDER[5], uid("content_id", TABLE_ORDER[3] + ".id"), col("partition_id", sa.Integer),
        col("vector_id", sa.String(120)), col("origin_kind", sa.String(20)),
        uid("origin_generation_id", "index_generations.id", nullable=True), uid("native_revision_id", "retrieval_native_revisions_v2.id", nullable=True),
        col("paper_id", sa.String(100)), col("chunk_key", sa.String(200)),
        *[col(name, sa.String(64)) for name in ("content_sha256", "vector_sha256", "chunk_revision_sha256", "origin_record_sha256")],
        sa.PrimaryKeyConstraint("content_id", "vector_id"),
        sa.CheckConstraint("partition_id>=0 AND ((origin_kind='legacy_v1' AND origin_generation_id IS NOT NULL "
            "AND native_revision_id IS NULL) OR (origin_kind='native_v2' AND origin_generation_id IS NULL "
            "AND native_revision_id IS NOT NULL))", name="ck_retrieval_content_v2_origin"),
        sa.Index("idx_retrieval_content_v2_partition", "content_id", "partition_id", "vector_id"),
        sa.Index("idx_retrieval_content_v2_paper", "content_id", "paper_id"))
    partitions = history(TABLE_ORDER[6], uid("content_id", TABLE_ORDER[3] + ".id"), col("partition_id", sa.Integer),
        col("member_count", sa.Integer), col("manifest_sha256", sa.String(64)), sa.PrimaryKeyConstraint("content_id", "partition_id"),
        sa.CheckConstraint("partition_id>=0 AND member_count BETWEEN 1 AND 1000", name="ck_retrieval_content_v2_partition"))
    seals = history(TABLE_ORDER[7], uid("content_id", TABLE_ORDER[3] + ".id"), col("member_count", sa.Integer),
        col("partition_count", sa.Integer), col("manifest_sha256", sa.String(64)), sa.PrimaryKeyConstraint("content_id"))
    seals.add_is_dependent_on(metadata.tables["retrieval_native_revisions_v2"])
    for dependency in (publications, publication_members, publication_seals, contents, changes, members, partitions):
        seals.add_is_dependent_on(dependency)
    for statement in guard_statements():
        sa.event.listen(seals, "after_create", sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"))
    return {table.name: table for table in (publications, publication_members, publication_seals, contents, changes, members, partitions, seals)}
