"""Non-serving authority for an unaccepted build on an owned restore.

This cannot mint an activation, enter public DTOs or authorize publication.
The private operator chooses the owned database; every read resolves the actual
validation, physical seal and still-current v1 predecessor again. Production
settings and databases without the independent rehearsal marker are refused.
"""
from dataclasses import dataclass
from contextlib import contextmanager
import json
from uuid import UUID

import sqlalchemy as sa

from config import get_settings
from models.retrieval_policy_v4 import POLICY,POLICY_SHA256
from services.index_generations import _pin as source_pin
from services.pgvector_query import ProjectionSpec
from services.retrieval_activation import RetrievalPinV2,assert_current_backend


class CandidateUnavailable(ValueError):pass


_READ_SNAPSHOT=object()


@contextmanager
def read_pin_snapshot(db):
    """Reuse authority only inside the caller's established read-only RR snapshot."""
    prior=db.info.get(_READ_SNAPSHOT)
    state={'transaction':db.get_transaction(),'pin':None}
    if state['transaction'] is None:raise CandidateUnavailable('An established read snapshot is required')
    db.info[_READ_SNAPSHOT]=state
    try:yield
    finally:
        if prior is None:db.info.pop(_READ_SNAPSHOT,None)
        else:db.info[_READ_SNAPSHOT]=prior


@dataclass(frozen=True,slots=True)
class EngineeringCandidatePin:
    database_name: str
    logical_index: str
    content_id: str
    build_id: str
    validation_id: str
    manifest_sha256: str
    policy_artifact_sha256: str
    profile_json: str
    baseline_json: str
    build_record_sha256: str
    validation_record_sha256: str

    @property
    def projection(self):return ProjectionSpec(self.build_id,self.content_id,self.manifest_sha256)

    def metadata(self):
        return {'version':'sclib-engineering-candidate-pin/1.0.0','scope':'owned_restore_not_activated',
            'logical_index':self.logical_index,'content_id':self.content_id,'build_id':self.build_id,
            'validation_id':self.validation_id,'manifest_sha256':self.manifest_sha256,
            'policy_artifact_sha256':self.policy_artifact_sha256,'profile':json.loads(self.profile_json),
            'source_v1_predecessor':json.loads(self.baseline_json),
            'build_record_sha256':self.build_record_sha256,'validation_record_sha256':self.validation_record_sha256}


async def load_candidate(db,*,build_id,validation_id,expected_database='sclib_restore_drill'):
    if get_settings().environment=='production' or type(expected_database) is not str or not expected_database:
        raise CandidateUnavailable('An explicit non-production owned database is required')
    if await db.scalar(sa.text('SELECT current_database()'))!=expected_database:
        raise CandidateUnavailable('Owned candidate database mismatch')
    try:
        rows=(await db.execute(sa.text("""
          SELECT to_jsonb(b) AS build,to_jsonb(v) AS validation,to_jsonb(c) AS content,
            to_jsonb(s) AS seal,to_jsonb(p) AS physical,to_jsonb(old) AS generation,
            source.activation_event_id AS source_event_id,marker.generation_id AS marker_generation,
            marker.manifest AS marker_manifest,
            NOT EXISTS(SELECT 1 FROM retrieval_active_pointer_v2 active WHERE active.logical_index=c.logical_index) AS not_activated,
            b.record_sha256=public.sclib_retrieval_record_hash_v2(to_jsonb(b))
            AND v.record_sha256=public.sclib_retrieval_record_hash_v2(to_jsonb(v))
            AND c.record_sha256=public.sclib_retrieval_record_hash_v2(to_jsonb(c))
            AND s.record_sha256=public.sclib_retrieval_record_hash_v2(to_jsonb(s))
            AND p.record_sha256=public.sclib_retrieval_record_hash_v2(to_jsonb(p)) AS intact,
            old.record_sha256=public.sclib_index_record_hash_v1(to_jsonb(old))
            AND predecessor.record_sha256=public.sclib_index_record_hash_v1(to_jsonb(predecessor))
            AND predecessor.generation_id=old.id AND old.logical_index=c.logical_index AS source_intact,
            to_regclass('retrieval_projection.b_'||replace(b.id::text,'-',''))::oid=p.table_oid
            AND EXISTS(SELECT 1 FROM pg_index WHERE indexrelid=p.index_oid AND indrelid=p.table_oid AND indisvalid AND indisready)
            AND (SELECT count(*) FROM pg_trigger WHERE tgrelid=p.table_oid AND NOT tgisinternal AND tgenabled='O'
              AND tgfoid='public.sclib_retrieval_projection_write_v2()'::regprocedure::oid
              AND tgnargs=1 AND tgargs=convert_to(b.id::text,'UTF8')||decode('00','hex')
              AND ((tgname='retrieval_projection_write_v2' AND tgtype=30)
                OR(tgname='retrieval_projection_truncate_v2' AND tgtype=34)))=2 AS physical_intact
          FROM retrieval_backend_builds_v2 b
          JOIN retrieval_backend_validations_v2 v ON v.id=:validation AND v.build_id=b.id
          JOIN retrieval_contents_v2 c ON c.id=b.content_id
          JOIN retrieval_content_seals_v2 s ON s.content_id=c.id
          JOIN retrieval_projection_seals_v2 p ON p.build_id=b.id
          LEFT JOIN index_active_pointer source ON source.logical_index=c.logical_index
          LEFT JOIN index_activation_events predecessor ON predecessor.id=source.activation_event_id
          LEFT JOIN index_generations old ON old.id=source.generation_id
          LEFT JOIN sclib_pgvector_rehearsal.source marker ON marker.singleton
          WHERE b.id=:build
        """),{'build':UUID(str(build_id)),'validation':UUID(str(validation_id))})).mappings().one_or_none()
    except sa.exc.ProgrammingError as error:
        if getattr(error.orig,'sqlstate',None) not in {'42P01','3F000'}:raise
        raise CandidateUnavailable('Independent owned marker and complete candidate relations required') from None
    if rows is None or rows['intact'] is not True:
        raise CandidateUnavailable('Actual intact build, validation and complete seals required')
    build,validation,content,seal,physical=(rows[key] for key in ('build','validation','content','seal','physical'))
    if (build['policy']!=POLICY or build['policy_artifact_sha256']!=POLICY_SHA256
            or build['content_record_sha256']!=content['record_sha256']
            or build['content_manifest_sha256']!=seal['manifest_sha256'] or build['profile']!=content['profile']
            or build['expected_member_count']!=seal['member_count']
            or validation['build_id']!=build['id'] or validation['outcome']!='validated'
            or validation['source_member_count']!=seal['member_count']
            or validation['projection_member_count']!=seal['member_count']
            or any(validation[key]!=0 for key in ('missing_count','extra_count','mismatch_count'))
            or validation['content_manifest_intact'] is not True
            or any(validation[key]!=physical[key] for key in ('table_oid','index_oid'))):
        raise CandidateUnavailable('Exact validated V4 candidate required')
    logical=content['logical_index']
    # This initial-migration rehearsal is subordinate to its actual v1 source.
    # It is never a second active pointer beside an activated v2 backend.
    if rows['not_activated'] is not True:
        raise CandidateUnavailable('Candidate scope ended after v2 activation')
    if rows['source_intact'] is not True or rows['generation'] is None:
        raise CandidateUnavailable('Actual intact current v1 predecessor required')
    baseline=source_pin(rows['generation'],rows['source_event_id'])
    if str(rows['marker_generation'])!=baseline['generation_id'] or rows['marker_manifest']!=baseline['manifest_sha256']:
        raise CandidateUnavailable('Owned marker and current actual v1 predecessor must agree')
    canonical=lambda value:json.dumps(value,sort_keys=True,separators=(',',':'))
    pin=EngineeringCandidatePin(expected_database,logical,str(content['id']),str(build['id']),str(validation['id']),
        seal['manifest_sha256'],POLICY_SHA256,canonical(build['profile']),canonical(baseline),
        build['record_sha256'],validation['record_sha256'])
    if rows['physical_intact'] is not True:raise CandidateUnavailable('Actual sealed physical candidate unavailable')
    return pin


def is_read_pin(pin):return type(pin) in {RetrievalPinV2,EngineeringCandidatePin}


async def current_read_pin(db,pin):
    if not is_read_pin(pin):raise CandidateUnavailable('A closed internal read authority is required')
    state=db.info.get(_READ_SNAPSHOT)
    same_snapshot=state is not None and state['transaction'] is db.get_transaction() and state['transaction'].is_active
    if same_snapshot and state['pin']==pin:return pin
    if type(pin) is RetrievalPinV2:
        await assert_current_backend(db,pin)
    elif type(pin) is EngineeringCandidatePin:
        current=await load_candidate(db,build_id=pin.build_id,validation_id=pin.validation_id,expected_database=pin.database_name)
        if current!=pin:raise CandidateUnavailable('Engineering candidate or predecessor changed')
    else:raise CandidateUnavailable('A closed internal read authority is required')
    if same_snapshot:state['pin']=pin
    return pin
