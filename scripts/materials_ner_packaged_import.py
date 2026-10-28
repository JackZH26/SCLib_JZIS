"""Bounded pending-only import from a hash-pinned, relocated review package.

No migrations, identity creation, grants, model calls or scientific decisions.
DATABASE_URL is read only for an explicitly requested database action. Success
is printed after the outer transaction commits or rolls back. On an uncertain
commit, rerun the identical pins: existing rows must match exactly.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'api'), str(ROOT / 'ingestion'), str(ROOT / 'scripts')]

from materials_ner_source_objects import SourceObjects, frozen_file, require, sha256
from materials_ner_canonical_bridge import prepare, _apply_plan, digest

VERSION = 'materials-packaged-pending-import/2'
EXPECTED_REVISION = '0103_materials_ner_amendments'


class CommittedReadbackError(RuntimeError):
    """The write committed; retry exact pins to recover its review receipt."""

    def __init__(self, error):
        super().__init__('committed_review_subject_readback_failed')
        self.orig = getattr(error, 'orig', error)
        self.commit_confirmed = True


def _package_files(root, files_sha256):
    root = Path(root).resolve(strict=True)
    files = json.loads(frozen_file(root, 'FILES.json', files_sha256))['files']
    require(isinstance(files, list) and len(files) <= 256, 'bounded_package_files')
    by_path = {}
    for row in files:
        require(row['path'] not in by_path, 'package_file_duplicate')
        frozen_file(root, row['path'], row['sha256'], row['size_bytes'])
        by_path[row['path']] = row
    require('OBJECT_MANIFEST.json' in by_path, 'source_object_manifest_required')
    return root, files, by_path


@dataclass(frozen=True, init=False)
class PreparedBatch:
    """Process-local validated inputs, with detached views for inspection.

    Construction performs the complete source and semantic verification. Only
    immutable JSON bytes are retained, so a caller cannot mutate a displayed
    request or plan into a write. Before SQL, every pinned file is checked again.
    Serialized plans are never accepted as evidence of validation.
    """

    _records: tuple[bytes, ...]
    _files_sha256: str
    _manifest_sha256: str
    _objects: SourceObjects

    def __init__(self, root, *, files_sha256):
        from ingestion.materials_ner.review_amendments import tc_mapping
        from services.materials_proposal_storage import canonical, projected_rows

        root, files, by_path = _package_files(root, files_sha256)
        objects = SourceObjects(root, manifest_sha256=by_path['OBJECT_MANIFEST.json']['sha256'])
        requests = [x for x in files if x['path'].startswith('requests/') and x['path'].endswith('/request.json')]
        require(0 < len(requests) <= 8, 'bounded_pending_batch_required')
        records = []
        amendment_ids = set()
        for row in sorted(requests, key=lambda x: x['path']):
            request = json.loads(frozen_file(root, row['path'], row['sha256'], row['size_bytes']))
            require(request['bindings']['purpose'] == 'pending_candidates', 'pending_candidate_binding_required')
            # prepare verifies the amendment by replay, including its parent
            # provider receipt, and checks all original source/provenance pins.
            plan = prepare(request, source_objects=objects)
            parent = json.loads(objects.read(request['parent']))
            amendment = json.loads(objects.read(request['amendment']))
            require(plan['amendment_id'] not in amendment_ids, 'duplicate_amendment_request')
            amendment_ids.add(plan['amendment_id'])
            record = {'request_path': row['path'], 'request_sha256': row['sha256'],
                      'request': request, 'plan': plan, 'plan_sha256': digest(plan),
                      'parent': parent, 'amendment': amendment,
                      'proposal_rows': projected_rows(parent), 'mapping': tc_mapping(amendment)}
            records.append(canonical(record).encode())
        object.__setattr__(self, '_records', tuple(records))
        object.__setattr__(self, '_files_sha256', files_sha256)
        object.__setattr__(self, '_manifest_sha256', objects.manifest_sha256)
        object.__setattr__(self, '_objects', objects)

    def __len__(self):
        return len(self._records)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        record = json.loads(self._records[index])
        return {key: record[key] for key in
                ('request_path', 'request_sha256', 'request', 'plan', 'plan_sha256')}

    def _materialize(self, objects):
        require(type(objects) is SourceObjects
                and objects.manifest_sha256 == self._manifest_sha256, 'prepared_source_objects_mismatch')
        # This hash-only closure check happens before creating a database engine.
        # Files may have changed since preparation; cached validation cannot hide it.
        _, _, by_path = _package_files(objects.root, self._files_sha256)
        require(by_path['OBJECT_MANIFEST.json']['sha256'] == self._manifest_sha256,
                'prepared_source_objects_mismatch')
        return [json.loads(raw) for raw in self._records]


def prepare_package(root, *, files_sha256):
    prepared = PreparedBatch(root, files_sha256=files_sha256)
    return prepared._objects, prepared


async def import_prepared(objects, prepared, *, database_url, expected_database, expected_role, execute):
    import sqlalchemy as sa
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from materials_ner_amendment_bridge import _apply_prepared as apply_amendment
    from models import materials_ner_amendments_v1 as schema

    require(type(prepared) is PreparedBatch, 'validated_batch_required')
    require(type(execute) is bool, 'execute_boolean')
    # No original-file I/O or semantic replay after the transaction begins.
    records = prepared._materialize(objects)
    engine = create_async_engine(make_url(database_url).set(drivername='postgresql+asyncpg'),
                                 isolation_level='SERIALIZABLE')
    reports = []
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            await db.begin()
            await db.execute(sa.text("SET LOCAL statement_timeout='45000ms'"))
            await db.execute(sa.text("SET LOCAL lock_timeout='1500ms'"))
            await db.execute(sa.text("SET LOCAL idle_in_transaction_session_timeout='60000ms'"))
            await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
            actual = (await db.execute(sa.text('SELECT current_database(),current_user'))).one()
            require(tuple(actual) == (expected_database, expected_role), 'database_identity_mismatch')
            privileged = (await db.execute(sa.text('SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls '
                                                   'FROM pg_roles WHERE rolname=current_user'))).scalar_one()
            require(not privileged, 'unprivileged_runtime_role_required')
            revision = (await db.execute(sa.text('SELECT version_num FROM alembic_version'))).scalar_one()
            require(revision == EXPECTED_REVISION, 'schema_revision_mismatch')
            fingerprint = (await db.execute(sa.text('SELECT fingerprint FROM materials_ner_v1.schema_version WHERE version=:v'),
                                             {'v': schema.VERSION})).scalar_one_or_none()
            require(fingerprint == schema.FINGERPRINT, 'amendment_schema_fingerprint_mismatch')
            # Existing proposal and canonical importers share these transaction locks.
            await db.execute(sa.text('SELECT pg_advisory_xact_lock(924601)'))
            for item in records:
                retained = await apply_amendment(db, item['parent'], item['amendment'],
                                                 item['proposal_rows'], item['mapping'])
                canonical = await _apply_plan(db, item['plan'], item['amendment'], dry_run=False)
                require(canonical['plan_sha256'] == item['plan_sha256'], 'prepared_plan_changed')
                reports.append({'request_path': item['request_path'], 'request_sha256': item['request_sha256'],
                                'plan_sha256': item['plan_sha256'], 'amendment': retained,
                                'inserted': canonical.get('inserted', 0),
                                'verified_existing': canonical.get('verified_existing', 0),
                                'source_registry_inserted': canonical['registry']['inserted'], 'results': canonical['results']})
            if execute:
                await db.commit()
            else:
                await db.rollback()
        if execute:
            # The existing scientific subject function deliberately requires a
            # read-only snapshot. Never weaken it to inspect transient writes.
            try:
                async with AsyncSession(engine) as reader:
                    await reader.execute(sa.text('SET TRANSACTION READ ONLY'))
                    await reader.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
                    await reader.execute(sa.text("SET LOCAL lock_timeout='1500ms'"))
                    await reader.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
                    for report in reports:
                        for target in report['results']:
                            body = (await reader.execute(sa.text("SELECT public.sclib_scientific_subject_capture_v3('claim',CAST(:id AS uuid))"),
                                                         {'id': target['claim_id']})).scalar_one()
                            target['subject_sha256'] = sha256(body.encode())
            except Exception as error:
                raise CommittedReadbackError(error) from None
        return {'committed': execute, 'review_subjects_persisted': execute,
                'database_role': expected_role, 'schema_revision': revision, 'reports': reports}
    finally:
        await engine.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--files-sha256', required=True)
    parser.add_argument('--action', choices=('prepare', 'dry-run', 'execute'), default='prepare')
    parser.add_argument('--expected-database')
    parser.add_argument('--expected-role', default='sclib_runtime')
    args = parser.parse_args(argv)
    objects, prepared = prepare_package(args.package, files_sha256=args.files_sha256)
    result = {'version': VERSION, 'action': args.action, 'files_sha256': args.files_sha256,
              'object_manifest_sha256': objects.manifest_sha256, 'objects_read': len(objects.read_hashes),
              'works': len(prepared), 'candidates': sum(len(x['plan']['results']) for x in prepared),
              'plans': [{k: x[k] for k in ('request_path', 'request_sha256', 'plan_sha256')} for x in prepared],
              'scientific_acceptance': False, 'ml_training_eligible': False, 'committed': False}
    if args.action != 'prepare':
        require(bool(args.expected_database), 'expected_database_required')
        result.update(asyncio.run(import_prepared(objects, prepared, database_url=os.environ['DATABASE_URL'],
                     expected_database=args.expected_database, expected_role=args.expected_role,
                     execute=args.action == 'execute')))
    print(json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False))
    return result


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Database exception text may include connection credentials or private data.
        original = getattr(error, 'orig', None)
        print(json.dumps({'ok': False, 'error_class': type(error).__name__,
                          'sqlstate': getattr(original, 'sqlstate', None),
                          'commit_confirmed': getattr(error, 'commit_confirmed', False)}))
        sys.exit(1)
