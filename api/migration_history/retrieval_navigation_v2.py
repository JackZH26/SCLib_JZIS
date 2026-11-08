"""Native immutable lexical navigation; original source rows stay unchanged."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID

TABLE = 'retrieval_native_navigation_v2'
VERSION = 'retrieval-navigation/2.0.0'
FORMULA_VERSION = 'formula-query/1.0.0'
PARENTS = ('retrieval_native_revisions_v2', 'retrieval_publication_members_v2',
    'retrieval_publication_seals_v2', 'retrieval_content_members_v2',
    'retrieval_backend_builds_v2', 'retrieval_backend_validations_v2',
    'retrieval_activation_events_v2', 'retrieval_active_pointer_v2',
    'index_generation_members', 'rag_evidence_revisions')
FUNCTION_SIGNATURES = (('sclib_retrieval_navigation_insert_v2',''),
    ('sclib_retrieval_navigation_immutable_v2',''), ('sclib_retrieval_navigation_complete_v2',''))
INDEXES = (
    ('idx_retrieval_content_native_nav_v2', 'retrieval_content_members_v2',
     "(content_id,native_revision_id) WHERE origin_kind='native_v2'"),
    ('idx_retrieval_content_origin_nav_v2', 'retrieval_content_members_v2',
     '(content_id,origin_generation_id,vector_id)'),
    ('idx_index_member_evidence_nav_v2', 'index_generation_members',
     '(evidence_revision_id,generation_id,vector_id)'),
    ('idx_native_evidence_nav_v2', 'retrieval_native_revisions_v2', '(evidence_revision_id,id)'),
    ('idx_derived_evidence_nav_v2', 'rag_evidence_revisions',
     "(id,parent_extraction_revision_id) WHERE chunk_kind='derived_fact'"),
)
_SQL = "LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp SET TimeZone='UTC' SET bytea_output='hex'"


def statements():
    return [f"""
      CREATE FUNCTION public.sclib_retrieval_navigation_insert_v2() RETURNS trigger {_SQL} AS $$
      DECLARE source public.retrieval_native_revisions_v2%ROWTYPE; ordered text[];
      BEGIN
        SELECT * INTO source FROM public.retrieval_native_revisions_v2 WHERE id=NEW.native_revision_id;
        IF source.id IS NULL OR source.record_sha256<>public.sclib_retrieval_record_hash_v2(to_jsonb(source))
          OR NEW.version<>'{VERSION}' OR NEW.formula_version<>'{FORMULA_VERSION}'
          OR NEW.vector_id IS DISTINCT FROM source.vector_id
          OR NEW.content_sha256 IS DISTINCT FROM source.content_sha256
          OR NEW.native_record_sha256 IS DISTINCT FROM source.record_sha256
          OR cardinality(NEW.terms)>2048 OR EXISTS(SELECT 1 FROM unnest(NEW.terms) t
              WHERE t IS NULL OR length(t) NOT BETWEEN 1 AND 200) THEN
          RAISE EXCEPTION 'retrieval_navigation_exact_source_required' USING ERRCODE='23514'; END IF;
        SELECT coalesce(array_agg(t ORDER BY t COLLATE "C"),ARRAY[]::text[]) INTO ordered
          FROM (SELECT DISTINCT t FROM unnest(NEW.terms) t) u;
        IF NEW.terms IS DISTINCT FROM ordered THEN
          RAISE EXCEPTION 'retrieval_navigation_canonical_terms_required' USING ERRCODE='23514'; END IF;
        NEW.document:=to_tsvector('english'::regconfig,coalesce(source.snapshot_json->>'title','')||' '||
          (source.snapshot_json->>'text'));
        NEW.year:=CASE WHEN source.snapshot_json->>'year' ~ '^[0-9]{{1,4}}$'
          THEN (source.snapshot_json->>'year')::integer ELSE NULL END;
        NEW.created_at:=clock_timestamp();
        NEW.record_sha256:=public.sclib_retrieval_record_hash_v2(to_jsonb(NEW)); RETURN NEW;
      END $$
    """, f"""
      CREATE FUNCTION public.sclib_retrieval_navigation_immutable_v2() RETURNS trigger {_SQL} AS $$ BEGIN
        RAISE EXCEPTION 'retrieval_navigation_immutable' USING ERRCODE='55000'; END $$
    """, f"""
      CREATE FUNCTION public.sclib_retrieval_navigation_complete_v2() RETURNS trigger {_SQL} AS $$
      DECLARE missing boolean;
      BEGIN
        IF TG_TABLE_NAME='retrieval_publication_seals_v2' THEN
          SELECT EXISTS(SELECT 1 FROM public.retrieval_publication_members_v2 m
            LEFT JOIN public.{TABLE} n ON n.native_revision_id=m.native_revision_id
            WHERE m.publication_id=NEW.publication_id AND (n.native_revision_id IS NULL
              OR n.native_record_sha256<>m.revision_record_sha256 OR n.vector_id<>m.vector_id
              OR n.record_sha256<>public.sclib_retrieval_record_hash_v2(to_jsonb(n)))) INTO missing;
        ELSE
          SELECT EXISTS(SELECT 1 FROM public.retrieval_backend_builds_v2 b
            JOIN public.retrieval_content_members_v2 m ON m.content_id=b.content_id AND m.origin_kind='native_v2'
            LEFT JOIN public.{TABLE} n ON n.native_revision_id=m.native_revision_id
            WHERE b.id=NEW.build_id AND (n.native_revision_id IS NULL OR n.native_record_sha256<>m.origin_record_sha256
              OR n.vector_id<>m.vector_id OR n.content_sha256<>m.content_sha256
              OR n.record_sha256<>public.sclib_retrieval_record_hash_v2(to_jsonb(n)))) INTO missing;
        END IF;
        IF missing THEN RAISE EXCEPTION 'retrieval_complete_native_navigation_required' USING ERRCODE='23514'; END IF;
        RETURN NEW;
      END $$
    """, f"CREATE TRIGGER nav_v2_insert BEFORE INSERT ON public.{TABLE} FOR EACH ROW EXECUTE FUNCTION public.sclib_retrieval_navigation_insert_v2()",
        f"CREATE TRIGGER nav_v2_immutable BEFORE UPDATE OR DELETE ON public.{TABLE} FOR EACH ROW EXECUTE FUNCTION public.sclib_retrieval_navigation_immutable_v2()",
        f"CREATE TRIGGER nav_v2_truncate BEFORE TRUNCATE ON public.{TABLE} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_retrieval_navigation_immutable_v2()",
        "CREATE TRIGGER aa_navigation_v2_publication BEFORE INSERT ON public.retrieval_publication_seals_v2 FOR EACH ROW EXECUTE FUNCTION public.sclib_retrieval_navigation_complete_v2()",
        "CREATE TRIGGER aa_navigation_v2_validation BEFORE INSERT ON public.retrieval_backend_validations_v2 FOR EACH ROW EXECUTE FUNCTION public.sclib_retrieval_navigation_complete_v2()",
        "CREATE TRIGGER aa_navigation_v2_activation BEFORE INSERT ON public.retrieval_activation_events_v2 FOR EACH ROW EXECUTE FUNCTION public.sclib_retrieval_navigation_complete_v2()",
        *[f'CREATE INDEX {name} ON public.{table} {definition}' for name,table,definition in INDEXES]]


def register(metadata):
    if TABLE in metadata.tables:return metadata.tables[TABLE]
    table=sa.Table(TABLE,metadata,
        sa.Column('native_revision_id',UUID(as_uuid=True),sa.ForeignKey('retrieval_native_revisions_v2.id',ondelete='RESTRICT'),primary_key=True),
        sa.Column('version',sa.String(60),nullable=False),sa.Column('formula_version',sa.String(60),nullable=False),
        sa.Column('vector_id',sa.String(120,collation='C'),nullable=False,unique=True),
        *[sa.Column(key,sa.String(64),nullable=False) for key in ('content_sha256','native_record_sha256')],
        sa.Column('terms',sa.ARRAY(sa.Text()),nullable=False),sa.Column('year',sa.Integer),
        sa.Column('document',TSVECTOR),sa.Column('record_sha256',sa.String(64),nullable=False,server_default='0'*64),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.clock_timestamp()),
        sa.Index('idx_native_navigation_document_v2','document',postgresql_using='gin'),
        sa.Index('idx_native_navigation_formula_v2','terms',postgresql_using='gin'),
        sa.CheckConstraint("record_sha256 ~ '^[0-9a-f]{64}$'",name='ck_native_navigation_hash_v2'))
    for name in PARENTS:table.add_is_dependent_on(metadata.tables[name])
    for sql in statements():
        sa.event.listen(table,'after_create',sa.DDL(sql.replace('%','%%')).execute_if(dialect='postgresql'))
    return table
