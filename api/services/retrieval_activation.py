"""Private operator attestation/CAS and database-authoritative v2 read pins.

No public route is switched here. A pin does not itself authorize source use;
request hydration, evidence, current rights and final-currentness remain gates.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa

from models.db import Base
from models.retrieval_activation_v2 import GATES, TABLE_ORDER
from models.retrieval_backend_v2 import POLICY, POLICY_SHA256
from services.pgvector_query import ProjectionSpec
from services.retrieval_backend import RetrievalBackendError, _existing, _phase


class RetrievalActivationError(RetrievalBackendError):
    """An exact v2 authority/pointer binding could not be established."""


async def _insert(db, name, keys, values):
    """Use explicit closed tables, preserving caller-owned transaction/replay."""
    if name not in TABLE_ORDER[:2]:
        raise RetrievalActivationError("Unknown activation history relation")
    table = Base.metadata.tables[name]
    predicates = [table.c[key] == value for key, value in keys.items()]
    prior = (await db.execute(sa.select(table).where(*predicates))).mappings().one_or_none()
    if prior is not None:
        intact = await db.scalar(sa.select(table.c.record_sha256 == sa.func.sclib_retrieval_record_hash_v2(
            sa.func.to_jsonb(table.table_valued()))).where(*predicates))
        if intact is not True or any(prior[key] != value for key, value in values.items()):
            raise RetrievalActivationError("Immutable activation identity conflict")
        return dict(prior), False
    await db.execute(table.insert().values(**keys, **values))
    return dict((await db.execute(sa.select(table).where(*predicates))).mappings().one()), True


async def record_operator_acceptance(db, *, acceptance_id, build_id, validation_id, evidence, dry_run=True):
    """Retain explicit reviewed artifact hashes, never generate passing reports.

The separate publisher is responsible for verifying those artifacts and their
scientific/deployment scope. This method does not perform that external review.
"""
    if (type(evidence) is not dict or set(evidence) != set(GATES)
            or any(type(value) is not str or not re.fullmatch('[a-f0-9]{64}', value) for value in evidence.values())):
        raise RetrievalActivationError("Complete exact operator evidence references are required")
    async with _phase(db, dry_run) as operation:
        row, operation['changed'] = await _insert(db, TABLE_ORDER[0], {'id': UUID(str(acceptance_id))}, {
            'build_id': UUID(str(build_id)), 'validation_id': UUID(str(validation_id)),
            'evidence': evidence, 'attestation': 'operator-reviewed-artifact-references/1.0.0'})
    return {'acceptance_id': str(row['id']), 'record_sha256': row['record_sha256'],
            'attestation': row['attestation'], 'dry_run': dry_run, 'committed': False,
            'active_pointer_changed': False, 'external_artifacts_verified_by_this_method': False}


async def activate_backend(db, *, event_id, build_id, validation_id, acceptance_id,
        expected_event_id, idempotency_key, expected_v1=None, action='promote', dry_run=True):
    if (action not in {'promote', 'rollback'} or type(idempotency_key) is not str
            or not re.fullmatch('[A-Za-z0-9._:-]{1,160}', idempotency_key)):
        raise RetrievalActivationError('An explicit action and bounded idempotency key are required')
    old = expected_v1 or {}
    if (expected_v1 is not None and (type(expected_v1) is not dict
            or set(expected_v1) != {'generation_id', 'activation_event_id', 'manifest_sha256'}
            or type(old['manifest_sha256']) is not str or not re.fullmatch('[a-f0-9]{64}', old['manifest_sha256']))):
        raise RetrievalActivationError('An exact retained v1 predecessor is required')
    identifier = UUID(str(build_id))
    async with _phase(db, dry_run, {'lock_timeout': '250ms', 'statement_timeout': '2s'}) as operation:
        build = await _existing(db, 'retrieval_backend_builds_v2', {'id': identifier})
        if build is None:
            raise RetrievalActivationError('Explicit backend unavailable')
        content = (await db.execute(sa.select(Base.metadata.tables['retrieval_contents_v2']).where(
            Base.metadata.tables['retrieval_contents_v2'].c.id == build['content_id']))).mappings().one()
        row, operation['changed'] = await _insert(db, TABLE_ORDER[1], {'id': UUID(str(event_id))}, {
            'logical_index': content['logical_index'], 'build_id': identifier,
            'validation_id': UUID(str(validation_id)), 'acceptance_id': UUID(str(acceptance_id)),
            'predecessor_id': UUID(str(expected_event_id)) if expected_event_id else None,
            'idempotency_key': idempotency_key, 'action': action,
            'expected_v1_generation_id': UUID(str(old['generation_id'])) if old else None,
            'expected_v1_event_id': UUID(str(old['activation_event_id'])) if old else None,
            'expected_v1_manifest_sha256': old.get('manifest_sha256')})
    return {'activation_event_id': str(row['id']), 'build_id': str(identifier),
            'content_id': str(row['content_id']), 'manifest_sha256': row['manifest_sha256'],
            'event_number': row['event_number'], 'dry_run': dry_run, 'committed': False}


@dataclass(frozen=True)
class RetrievalPinV2:
    logical_index: str
    content_id: str
    build_id: str
    activation_event_id: str
    manifest_sha256: str
    policy_artifact_sha256: str
    # A canonical immutable string prevents nested dict mutation in a frozen pin.
    profile_json: str

    @property
    def projection(self):
        return ProjectionSpec(self.build_id, self.content_id, self.manifest_sha256)

    def metadata(self):
        return {'version': 'sclib-retrieval-pin/2.0.0', 'logical_index': self.logical_index,
            'content_id': self.content_id, 'build_id': self.build_id,
            'activation_event_id': self.activation_event_id, 'manifest_sha256': self.manifest_sha256,
            'policy_artifact_sha256': self.policy_artifact_sha256, 'profile': json.loads(self.profile_json)}


async def load_active_backend(db, *, logical_index='sclib-main'):
    """Resolve authoritative exact records, not caller/config projection names.

    Uses only SELECT. It performs no full corpus scan and grants no privileges.
    Reader provisioning must include the relevant private catalog visibility.
    """
    if type(logical_index) is not str or not re.fullmatch('[A-Za-z0-9._-]{1,160}', logical_index):
        raise RetrievalActivationError('Bounded logical index required')
    tables = {name: Base.metadata.tables[name] for name in (
        *TABLE_ORDER, 'retrieval_backend_builds_v2', 'retrieval_backend_validations_v2',
        'retrieval_contents_v2', 'retrieval_content_seals_v2', 'retrieval_projection_seals_v2')}
    p, e, a = (tables[name] for name in (TABLE_ORDER[2], TABLE_ORDER[1], TABLE_ORDER[0]))
    b, v, c, s, physical = (tables[name] for name in ('retrieval_backend_builds_v2',
        'retrieval_backend_validations_v2', 'retrieval_contents_v2', 'retrieval_content_seals_v2', 'retrieval_projection_seals_v2'))
    # LEFT joins distinguish a genuinely absent pointer from corrupt authority.
    joined = p.outerjoin(e, e.c.id == p.c.activation_event_id).outerjoin(b, b.c.id == p.c.build_id).outerjoin(
        c, c.c.id == p.c.content_id).outerjoin(a, a.c.id == e.c.acceptance_id).outerjoin(
        v, v.c.id == e.c.validation_id).outerjoin(s, s.c.content_id == c.c.id).outerjoin(physical, physical.c.build_id == b.c.id)
    names = (e, b, c, a, v, s, physical)
    checks = [table.c.record_sha256 == sa.func.sclib_retrieval_record_hash_v2(
        sa.func.to_jsonb(table.table_valued())) for table in names]
    checks += [e.c.logical_index == p.c.logical_index, c.c.logical_index == p.c.logical_index,
        e.c.build_id == b.c.id, e.c.content_id == c.c.id, b.c.content_id == c.c.id,
        a.c.build_id == b.c.id, a.c.content_id == c.c.id, v.c.build_id == b.c.id,
        v.c.outcome == 'validated', e.c.manifest_sha256 == s.c.manifest_sha256,
        b.c.content_manifest_sha256 == s.c.manifest_sha256, a.c.manifest_sha256 == s.c.manifest_sha256,
        b.c.expected_member_count == s.c.member_count, b.c.policy_artifact_sha256 == POLICY_SHA256,
        b.c.policy == POLICY, a.c.policy_artifact_sha256 == b.c.policy_artifact_sha256,
        a.c.image_digest == b.c.image_digest, b.c.profile == c.c.profile,
        e.c.build_record_sha256 == b.c.record_sha256, e.c.validation_record_sha256 == v.c.record_sha256,
        e.c.acceptance_record_sha256 == a.c.record_sha256,
        v.c.table_oid == physical.c.table_oid, v.c.index_oid == physical.c.index_oid]
    row = (await db.execute(sa.select(p.c.build_id, p.c.content_id, p.c.activation_event_id,
        s.c.manifest_sha256, b.c.policy_artifact_sha256, b.c.profile, physical.c.table_oid, physical.c.index_oid,
        sa.and_(*checks).label('intact')).select_from(joined).where(p.c.logical_index == logical_index))).mappings().one_or_none()
    if row is None:
        return None
    if row['intact'] is not True:
        raise RetrievalActivationError('Active backend authority integrity mismatch')
    pin = RetrievalPinV2(logical_index, str(row['content_id']), str(row['build_id']), str(row['activation_event_id']),
        row['manifest_sha256'], row['policy_artifact_sha256'], json.dumps(row['profile'], sort_keys=True, separators=(',', ':')))
    intact = await db.scalar(sa.text("SELECT to_regclass(:qualified)::oid=:physical "
        "AND EXISTS(SELECT 1 FROM pg_index WHERE indexrelid=:graph AND indrelid=:physical AND indisvalid AND indisready) "
        "AND (SELECT count(*) FROM pg_trigger WHERE tgrelid=:physical AND NOT tgisinternal AND tgenabled='O' "
        "AND tgfoid='public.sclib_retrieval_projection_write_v2()'::regprocedure::oid "
        "AND tgnargs=1 AND tgargs=convert_to(:identifier,'UTF8')||decode('00','hex') "
        "AND ((tgname='retrieval_projection_write_v2' AND tgtype=30) "
        "OR(tgname='retrieval_projection_truncate_v2' AND tgtype=34)))=2"),
        {'qualified': pin.projection.table, 'physical': row['table_oid'], 'graph': row['index_oid'], 'identifier': pin.build_id})
    if intact is not True:
        raise RetrievalActivationError('Active sealed physical projection unavailable')
    return pin


async def assert_current_backend(db, pin):
    if type(pin) is not RetrievalPinV2 or await load_active_backend(db, logical_index=pin.logical_index) != pin:
        raise RetrievalActivationError('Pinned backend is no longer current')
