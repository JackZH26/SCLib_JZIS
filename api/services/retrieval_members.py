"""Bounded v2 content/origin hydration, still unwired from public routes.

Retained v1/native origin identities stay distinct. This module invents no
generation, provider resource, extraction parent or source permission.
"""
from __future__ import annotations

import hashlib
import math
from uuid import UUID

import sqlalchemy as sa

from models.db import Paper
from services import index_retrieval
from services.index_generations import vector_id_for
from services.pgvector_query import CandidateBatch
from services.retrieval_activation import RetrievalPinV2, assert_current_backend
from services.retrieval_backend import _phase

MAX_MEMBERS = 1000
MAX_BYTES = 8 * 1024 * 1024


class RetrievalMemberError(ValueError):
    """An exact bounded content/origin/evidence binding is unavailable."""


def _ids(values):
    if (type(values) not in {list, tuple} or len(values) > MAX_MEMBERS
            or any(type(value) is not str or not 1 <= len(value) <= 120 for value in values)
            or len(set(values)) != len(values)):
        raise RetrievalMemberError('An exact unique bounded member inventory is required')
    return list(values)


def _source_sql():
    # Every identifier is closed source code. Values remain bound parameters.
    origin = "CASE m.origin_kind WHEN 'legacy_v1' THEN to_jsonb(old) ELSE to_jsonb(native) END"
    raw = "CASE m.origin_kind WHEN 'legacy_v1' THEN old.vector_bytes ELSE native.vector_bytes END"
    intact = """CASE m.origin_kind WHEN 'legacy_v1' THEN
        old.record_sha256=public.sclib_index_record_hash_v1(to_jsonb(old))
        AND old.chunk_revision_sha256=public.sclib_index_revision_hash_v1(to_jsonb(old))
      ELSE native.record_sha256=public.sclib_retrieval_record_hash_v2(to_jsonb(native))
        AND native.chunk_revision_sha256=public.sclib_retrieval_native_hash_v2(to_jsonb(native))
        AND input.id IS NOT NULL AND input.record_sha256=native.input_receipt_record_sha256
        AND input.record_sha256=public.sclib_retrieval_record_hash_v2(to_jsonb(input))
        AND input.paper_id=native.paper_id AND input.source_snapshot_sha256=native.source_snapshot_sha256
        AND input.parser_version=native.parser_version AND input.chunker_version=native.chunker_version END"""
    return f"""SELECT to_jsonb(m) AS reference,({origin})-'vector_bytes' AS origin,
      encode({raw},'hex') AS vector_hex,
      coalesce(m.record_sha256=public.sclib_retrieval_record_hash_v2(to_jsonb(m)) AND {intact},false) AS intact
      FROM public.retrieval_content_members_v2 m
      LEFT JOIN public.index_generation_members old ON m.origin_kind='legacy_v1'
        AND old.generation_id=m.origin_generation_id AND old.vector_id=m.vector_id
      LEFT JOIN public.retrieval_native_revisions_v2 native ON m.origin_kind='native_v2'
        AND native.id=m.native_revision_id AND native.vector_id=m.vector_id
      LEFT JOIN public.retrieval_input_receipts_v2 input ON input.id=native.input_receipt_id
      WHERE m.content_id=:content AND m.vector_id IN :ids"""


async def load_members(db, pin, identifiers):
    """Load only current authoritative content refs and their exact origins.

    Private archive paths/locators are never selected. Unknown members are an
    integrity error here, rather than a successful empty vector result.
    """
    if type(pin) is not RetrievalPinV2:
        raise RetrievalMemberError('An authoritative versioned v2 pin is required')
    ids = _ids(identifiers)
    await assert_current_backend(db, pin)
    if not ids:
        return []
    source = _source_sql()
    params = {'content': UUID(pin.content_id), 'ids': ids}
    # V1 record hashes predate bytea normalization. Use a temporary savepoint
    # setting and restore it even when the caller has chosen escape output.
    async with _phase(db, True, {'bytea_output': 'hex'}):
        size_sql = sa.text('SELECT count(*),coalesce(sum(octet_length(reference::text) + '
            'octet_length(origin::text) + length(vector_hex)/2),0) FROM (' + source + ') bounded').bindparams(
                sa.bindparam('ids', expanding=True))
        count, size = (await db.execute(size_sql, params)).one()
        if count != len(ids) or size > MAX_BYTES:
            raise RetrievalMemberError('Retained member inventory unavailable or exceeds byte budget')
        statement = sa.text(source).bindparams(sa.bindparam('ids', expanding=True))
        rows = (await db.execute(statement, params)).mappings().all()
    result = {}
    for row in rows:
        ref, origin = row['reference'], row['origin']
        if row['intact'] is not True or type(origin) is not dict:
            raise RetrievalMemberError('Retained content or origin record integrity mismatch')
        if (ref['content_id'] != pin.content_id or ref['vector_id'] not in ids
                or any(ref[key] != origin[key] for key in ('vector_id', 'paper_id', 'chunk_key',
                    'content_sha256', 'vector_sha256', 'chunk_revision_sha256'))
                or ref['origin_record_sha256'] != origin['record_sha256']):
            raise RetrievalMemberError('Retained reference does not match its original binding')
        if ref['origin_kind'] == 'legacy_v1':
            expected = vector_id_for(ref['origin_generation_id'], origin['chunk_revision_sha256'])
            if origin.get('generation_id') != ref['origin_generation_id']:
                raise RetrievalMemberError('Legacy origin generation mismatch')
        else:
            expected = 'rv2_' + origin['chunk_revision_sha256']
            if origin.get('id') != ref['native_revision_id'] or 'generation_id' in origin:
                raise RetrievalMemberError('Native origin identity mismatch')
        try:
            raw = bytes.fromhex(row['vector_hex'])
            text = origin['snapshot_json']['text']
            if (expected != ref['vector_id'] or len(raw) != 3072
                    or hashlib.sha256(raw).hexdigest() != origin['vector_sha256']
                    or hashlib.sha256(text.encode()).hexdigest() != origin['content_sha256']):
                raise ValueError
        except (ValueError, TypeError, KeyError):
            raise RetrievalMemberError('Retained text/vector bytes are incompatible') from None
        # Preserve the original identity inside the origin. Add explicit v2
        # reference fields without relabelling a native row as a v1 generation.
        result[ref['vector_id']] = {**origin, 'vector_bytes': raw,
            'content_id': pin.content_id, 'content_member_record_sha256': ref['record_sha256'],
            'origin_kind': ref['origin_kind'], 'origin_record_sha256': ref['origin_record_sha256'],
            'origin_generation_id': ref['origin_generation_id'], 'native_revision_id': ref['native_revision_id']}
    if set(result) != set(ids):
        raise RetrievalMemberError('Complete retained member inventory required')
    return [result[identifier] for identifier in ids]


async def verified_hits(db, pin, batch):
    if type(pin) is not RetrievalPinV2 or type(batch) is not CandidateBatch or batch.projection != pin.projection:
        raise RetrievalMemberError('Candidate batch does not match the request backend pin')
    ids = _ids([item.vector_id for item in batch.neighbors])
    members = {row['vector_id']: row for row in await load_members(db, pin, ids)}
    result, previous = [], -1.0
    for item in batch.neighbors:
        member = members[item.vector_id]
        if (any(getattr(item, key) != member[key] for key in ('paper_id', 'content_sha256',
                'vector_sha256', 'chunk_revision_sha256')) or type(item.distance) not in {int, float}
                or not math.isfinite(item.distance) or not 0 <= item.distance <= 2 or item.distance < previous):
            raise RetrievalMemberError('Candidate payload does not match its authoritative member')
        previous = item.distance
        result.append((item.vector_id, 1.0 - item.distance))
    return result


async def hydrate(db, pin, identifiers):
    members = await load_members(db, pin, identifiers)
    paper_ids = {row['paper_id'] for row in members}
    if not paper_ids:
        return {}
    sizes = (await db.execute(sa.select(Paper.id, sa.func.octet_length(sa.cast(
        sa.func.to_jsonb(Paper.__table__.table_valued()), sa.Text))).where(Paper.id.in_(paper_ids)))).all()
    if {identifier for identifier, _ in sizes} != paper_ids or sum(size for _, size in sizes) > MAX_BYTES:
        raise RetrievalMemberError('Current source overlay unavailable or oversized')
    papers = {row.id: row for row in (await db.execute(sa.select(Paper).where(Paper.id.in_(paper_ids))
        .execution_options(populate_existing=True))).scalars()}
    result = {}
    for member in members:
        snapshot = member['snapshot_json']
        if (snapshot.get('paper_id') != member['paper_id'] or member['paper_snapshot_json'].get('id') != member['paper_id']
                or type(snapshot.get('text')) is not str or type(snapshot.get('materials_mentioned')) is not list):
            raise RetrievalMemberError('Malformed retained snapshot')
        # GenerationChunk is the existing internal retained-snapshot policy
        # view, not a public v1 generation declaration. Its pin here is v2.
        result[member['vector_id']] = index_retrieval.GenerationChunk(
            id=member['vector_id'], paper_id=member['paper_id'], title=snapshot.get('title'),
            section=snapshot.get('section'), chunk_index=snapshot.get('chunk_index'), text=snapshot['text'],
            materials_mentioned=snapshot['materials_mentioned'], has_equation=bool(snapshot.get('has_equation')),
            has_table=bool(snapshot.get('has_table')), paper=papers[member['paper_id']], member=member,
            generation_pin=pin.metadata())
    return result


async def resolve_evidence(db, pin, chunks):
    if type(pin) is not RetrievalPinV2 or any(type(row) is not index_retrieval.GenerationChunk
            or row.generation_pin != pin.metadata() or row.member.get('content_id') != pin.content_id for row in chunks):
        raise RetrievalMemberError('Mixed content/backend evidence is inadmissible')
    await assert_current_backend(db, pin)
    # Existing retained policy preserves missing parents, historical warnings,
    # source lifecycle and past restrictions. Native input observation grants
    # no new root, independent evidence or scientific support.
    return await index_retrieval.resolve_evidence(db, chunks)


async def paper_member_ids(db, pin, paper_id, *, limit=20):
    if type(pin) is not RetrievalPinV2 or type(paper_id) is not str or not 1 <= len(paper_id) <= 100:
        raise RetrievalMemberError('An exact current content and source paper are required')
    if type(limit) is not int or not 1 <= limit <= 20:
        raise RetrievalMemberError('Bounded source vector selection required')
    await assert_current_backend(db, pin)
    return list((await db.execute(sa.text('SELECT vector_id FROM retrieval_content_members_v2 '
        'WHERE content_id=:content AND paper_id=:paper ORDER BY vector_id COLLATE "C" LIMIT :limit'),
        {'content': UUID(pin.content_id), 'paper': paper_id, 'limit': limit})).scalars())
