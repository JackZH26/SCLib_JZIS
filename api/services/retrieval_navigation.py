"""Content-pinned lexical navigation, never permission or scientific approval."""
from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa

from models.db import Base
from models.retrieval_navigation_v2 import TABLE,VERSION,FORMULA_VERSION
from services.index_corpus import formula_terms,is_corpus
from services.retrieval import LexicalHit
from services.retrieval_activation import RetrievalPinV2
from services.retrieval_candidate import is_read_pin,current_read_pin
from services.retrieval_backend import _phase


class RetrievalNavigationError(ValueError):pass


LEXICAL_MATCH_CAP=5000


@dataclass(frozen=True,slots=True)
class LexicalNavigation:
    hits: tuple[LexicalHit,...]
    strategy: str
    eligible_rows_observed: int


async def bounded_lexical_search(db,pin,query,*,limit,year_min=None,year_max=None,exclude_retracted=True):
    """Use semantic navigation for a broad lexical cohort, never a partial rank.

    Stop after cap+1 eligible rows without ranking or fetching their text. A
    lateral primary-key membership lookup prevents a full content hash join.
    The caller must still complete ANN and all current source checks; this is
    a query strategy, not a lexical fallback after a failed semantic request.
    """
    params=_request(pin,limit,year_min,year_max)
    if type(query) is not str or not 2<=len(query)<=2000 or not query.strip() or type(exclude_retracted) is not bool:
        raise RetrievalNavigationError('A bounded original query and explicit source filter are required')
    params.update(query=query,exclude_retracted=exclude_retracted,probe_limit=LEXICAL_MATCH_CAP+1)
    await current_read_pin(db,pin)
    year="AND (CAST(:year_min AS integer) IS NULL OR n.year>=:year_min) AND (CAST(:year_max AS integer) IS NULL OR n.year<=:year_max)"
    observed=await db.scalar(sa.text(f"""
      SELECT count(*) FROM (
        (SELECT n.vector_id FROM index_generation_search n
          JOIN LATERAL (SELECT 1 FROM retrieval_content_members_v2 m
            WHERE m.content_id=:content AND m.vector_id=n.vector_id
              AND m.origin_kind='legacy_v1' AND m.origin_generation_id=n.generation_id
            LIMIT 1) member ON true
          JOIN papers p ON p.id=n.paper_id
          WHERE n.document @@ websearch_to_tsquery('english'::regconfig,:query)
            AND (NOT :exclude_retracted OR p.status<>'retracted') {year}
          LIMIT :probe_limit)
        UNION ALL
        (SELECT n.vector_id FROM {TABLE} n
          JOIN retrieval_content_members_v2 m ON m.content_id=:content
            AND m.origin_kind='native_v2' AND m.native_revision_id=n.native_revision_id
            AND m.vector_id=n.vector_id AND m.origin_record_sha256=n.native_record_sha256
          JOIN papers p ON p.id=m.paper_id
          WHERE n.version=:version AND n.document @@ websearch_to_tsquery('english'::regconfig,:query)
            AND (NOT :exclude_retracted OR p.status<>'retracted') {year}
          LIMIT :probe_limit)
        LIMIT :probe_limit
      ) eligible
    """),params)
    if observed>LEXICAL_MATCH_CAP:
        return LexicalNavigation((),'semantic_broad_cohort',int(observed))
    hits=await lexical_search(db,pin,query,limit=limit,year_min=year_min,year_max=year_max,
        exclude_retracted=exclude_retracted)
    return LexicalNavigation(tuple(hits),'hybrid',int(observed))


async def ensure_native_navigation(db, *, native_revision_id, dry_run=True):
    identifier=UUID(str(native_revision_id));table=Base.metadata.tables[TABLE]
    async with _phase(db,dry_run,{'bytea_output':'hex'}) as operation:
        source=(await db.execute(sa.text("SELECT vector_id,content_sha256,record_sha256,snapshot_json->>'text' AS text,"
            "record_sha256=public.sclib_retrieval_record_hash_v2(to_jsonb(n)) AS intact "
            "FROM retrieval_native_revisions_v2 n WHERE id=:id"),{'id':identifier})).mappings().one_or_none()
        if source is None or source['intact'] is not True:
            raise RetrievalNavigationError('An intact native source is required')
        values={'native_revision_id':identifier,'version':VERSION,'formula_version':FORMULA_VERSION,
            'vector_id':source['vector_id'],'content_sha256':source['content_sha256'],
            'native_record_sha256':source['record_sha256'],'terms':formula_terms(source['text'])}
        row=(await db.execute(sa.select(table).where(table.c.native_revision_id==identifier))).mappings().one_or_none()
        if row is None:
            await db.execute(table.insert().values(**values))
            operation['changed']=True
            row=(await db.execute(sa.select(table).where(table.c.native_revision_id==identifier))).mappings().one()
        intact=await db.scalar(sa.select(table.c.record_sha256==sa.func.sclib_retrieval_record_hash_v2(
            sa.func.to_jsonb(table.table_valued()))).where(table.c.native_revision_id==identifier))
        if intact is not True or any(row[key]!=value for key,value in values.items()):
            raise RetrievalNavigationError('Native navigation replay conflicts with its exact source/normalizer')
        digest=row['record_sha256']
    return {'native_revision_id':str(identifier),'record_sha256':digest,'dry_run':dry_run,'committed':False}


def _request(pin,limit,year_min,year_max):
    if not is_read_pin(pin) or type(limit) is not int or not 1<=limit<=300:
        raise RetrievalNavigationError('An exact content pin and bounded candidate limit are required')
    if any(year is not None and (type(year) is not int or not 1<=year<=9999) for year in (year_min,year_max)):
        raise RetrievalNavigationError('Exact year bounds are required')
    if year_min is not None and year_max is not None and year_min>year_max:
        raise RetrievalNavigationError('Ordered year bounds are required')
    return {'content':UUID(pin.content_id),'limit':limit,'year_min':year_min,'year_max':year_max,'version':VERSION}


async def lexical_search(db,pin,query,*,limit,year_min=None,year_max=None,exclude_retracted=True):
    params=_request(pin,limit,year_min,year_max)
    if type(query) is not str or not 2<=len(query)<=2000 or not query.strip() or type(exclude_retracted) is not bool:
        raise RetrievalNavigationError('A bounded original query and explicit source filter are required')
    params.update(query=query,exclude_retracted=exclude_retracted)
    await current_read_pin(db,pin)
    year="AND (CAST(:year_min AS integer) IS NULL OR n.year>=:year_min) AND (CAST(:year_max AS integer) IS NULL OR n.year<=:year_max)"
    rows=(await db.execute(sa.text(f"""
      WITH candidates AS (
        SELECT n.vector_id,ts_rank_cd(n.document,websearch_to_tsquery('english'::regconfig,:query)) AS score,
          false AS native
        FROM index_generation_search n JOIN retrieval_content_members_v2 m
          ON m.content_id=:content AND m.origin_kind='legacy_v1'
          AND m.origin_generation_id=n.generation_id AND m.vector_id=n.vector_id
        JOIN papers p ON p.id=n.paper_id
        WHERE n.document @@ websearch_to_tsquery('english'::regconfig,:query)
          AND (NOT :exclude_retracted OR p.status<>'retracted') {year}
        UNION ALL
        SELECT n.vector_id,ts_rank_cd(n.document,websearch_to_tsquery('english'::regconfig,:query)),true
        FROM {TABLE} n JOIN retrieval_content_members_v2 m
          ON m.content_id=:content AND m.origin_kind='native_v2' AND m.native_revision_id=n.native_revision_id
          AND m.vector_id=n.vector_id AND m.origin_record_sha256=n.native_record_sha256
        JOIN papers p ON p.id=m.paper_id
        WHERE n.version=:version AND n.document @@ websearch_to_tsquery('english'::regconfig,:query)
          AND (NOT :exclude_retracted OR p.status<>'retracted') {year}
      ), selected AS MATERIALIZED (
        SELECT * FROM candidates ORDER BY score DESC,vector_id COLLATE "C" LIMIT :limit
      )
      SELECT s.vector_id,s.score,s.native FROM selected s
      ORDER BY s.score DESC,s.vector_id COLLATE "C"
    """),params)).mappings().all()
    # Keep the corpus-wide ranking parallel-safe. The PL/pgSQL hash function
    # otherwise disables parallelism for the entire lexical query, even when
    # its CASE arm would only inspect a few selected native rows.
    native_ids=[row['vector_id'] for row in rows if row['native']]
    if native_ids:
        checked=(await db.execute(sa.text(f"SELECT vector_id,"
            "record_sha256=public.sclib_retrieval_record_hash_v2(to_jsonb(n)) AS intact "
            f"FROM {TABLE} n WHERE vector_id=ANY(CAST(:ids AS text[]))"),
            {'ids':native_ids})).mappings().all()
        if ({row['vector_id'] for row in checked}!=set(native_ids)
                or any(row['intact'] is not True for row in checked)):
            raise RetrievalNavigationError('Selected lexical navigation integrity mismatch')
    return [LexicalHit(row['vector_id'],float(row['score'])) for row in rows]


async def formula_search(db,pin,wanted,*,limit,year_min=None,year_max=None):
    from services.retrieval_members import load_text_bindings
    from services.scientific_query import match_source_formulas
    params=_request(pin,limit,year_min,year_max)
    if type(wanted) is not set or not 1<=len(wanted)<=32 or any(type(term) is not str or not 1<=len(term)<=200 for term in wanted):
        raise RetrievalNavigationError('Bounded normalized formula terms are required')
    await current_read_pin(db,pin);params['wanted']=sorted(wanted)
    rows=(await db.execute(sa.text(f"""
      WITH selected AS MATERIALIZED (
        SELECT n.*, (SELECT count(*) FROM unnest(n.terms) t WHERE t=ANY(CAST(:wanted AS text[]))) AS matches
        FROM {TABLE} n JOIN retrieval_content_members_v2 m ON m.content_id=:content
          AND m.origin_kind='native_v2' AND m.native_revision_id=n.native_revision_id
          AND m.vector_id=n.vector_id AND m.origin_record_sha256=n.native_record_sha256
        WHERE n.version=:version AND n.terms && CAST(:wanted AS text[])
          AND (CAST(:year_min AS integer) IS NULL OR n.year>=:year_min)
          AND (CAST(:year_max AS integer) IS NULL OR n.year<=:year_max)
        ORDER BY matches DESC,n.vector_id COLLATE "C" LIMIT :limit
      ) SELECT vector_id,matches,record_sha256=public.sclib_retrieval_record_hash_v2(
        to_jsonb(selected)-'matches') AS intact FROM selected ORDER BY matches DESC,vector_id COLLATE "C"
    """),params)).mappings().all()
    if any(row['intact'] is not True for row in rows):raise RetrievalNavigationError('Selected formula navigation integrity mismatch')
    expected={row['vector_id']:row['matches'] for row in rows}
    generations=list((await db.execute(sa.text("SELECT DISTINCT origin_generation_id FROM retrieval_content_members_v2 "
        "WHERE content_id=:content AND origin_kind='legacy_v1'"),params)).scalars())
    if len(generations)>1:raise RetrievalNavigationError('Unexpected legacy source universe')
    for generation in generations:
        if await is_corpus(db,generation):
            found=(await db.execute(sa.text("""
              WITH selected AS MATERIALIZED (
                SELECT n,(SELECT count(*) FROM unnest(n.terms) t WHERE t=ANY(CAST(:wanted AS text[]))) AS matches
                FROM index_corpus_formula_terms n JOIN retrieval_content_members_v2 m
                  ON m.content_id=:content AND m.origin_kind='legacy_v1'
                  AND m.origin_generation_id=n.generation_id AND m.vector_id=n.vector_id
                JOIN index_generation_search year ON year.generation_id=n.generation_id AND year.vector_id=n.vector_id
                WHERE n.generation_id=:generation AND n.terms && CAST(:wanted AS text[])
                  AND (CAST(:year_min AS integer) IS NULL OR year.year>=:year_min)
                  AND (CAST(:year_max AS integer) IS NULL OR year.year<=:year_max)
                ORDER BY matches DESC,n.vector_id COLLATE "C" LIMIT :limit
              ) SELECT (n).vector_id,matches,(n).record_sha256=public.sclib_index_record_hash_v1(to_jsonb(n)) AS intact
              FROM selected ORDER BY matches DESC,(n).vector_id COLLATE "C"
            """),{**params,'generation':generation})).mappings().all()
            if any(row['intact'] is not True for row in found):raise RetrievalNavigationError('Retained formula navigation integrity mismatch')
            expected.update({row['vector_id']:row['matches'] for row in found})
        else:
            ids=list((await db.execute(sa.text("SELECT m.vector_id FROM retrieval_content_members_v2 m "
                "JOIN index_generation_search n ON n.generation_id=m.origin_generation_id AND n.vector_id=m.vector_id "
                "WHERE m.content_id=:content AND m.origin_generation_id=:generation "
                "AND (CAST(:year_min AS integer) IS NULL OR n.year>=:year_min) "
                'AND (CAST(:year_max AS integer) IS NULL OR n.year<=:year_max) ORDER BY m.vector_id COLLATE "C" LIMIT 1001'),
                {**params,'generation':generation})).scalars())
            if len(ids)>1000:raise RetrievalNavigationError('Bounded non-corpus legacy inventory exceeded')
            for identifier,text in (await load_text_bindings(db,pin,ids)).items():
                matches=len(match_source_formulas(text,wanted))
                if matches:expected[identifier]=matches
    # Verify selected indexed terms against the actual immutable text before
    # returning them. An inconsistent index is an error, never silent backfill.
    ordered=sorted(expected,key=lambda identifier:(-expected[identifier],identifier))[:limit]
    texts=await load_text_bindings(db,pin,ordered)
    if any(len(match_source_formulas(texts[identifier],wanted))!=expected[identifier] for identifier in ordered):
        raise RetrievalNavigationError('Formula navigation disagrees with retained text')
    return [LexicalHit(identifier,expected[identifier]/len(wanted)) for identifier in ordered]
