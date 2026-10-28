"""Transaction-boundary regressions, without a provider or database connection."""
from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import materials_ner_packaged_import as importer


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def source_package(tmp_path, monkeypatch):
    root = tmp_path / 'package'
    (root / 'objects').mkdir(parents=True)
    refs, objects, paths = {}, [], {}
    for name, value in [('parent', {'run_id': 'parent'}), ('amendment', {'amendment_id': 'amendment'})]:
        raw = json.dumps(value).encode()
        h = sha(raw)
        (root / 'objects' / h).write_bytes(raw)
        refs[name] = {'path': '/historical/' + name, 'sha256': h}
        objects.append({'path': 'objects/' + h, 'sha256': h, 'size_bytes': len(raw)})
        paths[refs[name]['path']] = h
    manifest = {'schema': 'materials-review-source-objects/1', 'objects': objects,
                'logical_path_to_sha256': paths}
    (root / 'OBJECT_MANIFEST.json').write_text(json.dumps(manifest))
    request = {**refs, 'bindings': {'purpose': 'pending_candidates'}}
    request_path = root / 'requests/work/request.json'
    request_path.parent.mkdir(parents=True)
    request_path.write_text(json.dumps(request))
    files = [{'path': str(path.relative_to(root)), 'sha256': sha(path.read_bytes()),
              'size_bytes': path.stat().st_size} for path in sorted(root.rglob('*')) if path.is_file()]
    (root / 'FILES.json').write_text(json.dumps({'files': files}))
    calls = []

    def prepare(request, *, source_objects):
        calls.append('semantic_validation')
        for key in ('parent', 'amendment'):
            source_objects.read(request[key])
        return {'amendment_id': 'amendment', 'results': [{'claim_id': 'claim'}]}

    monkeypatch.setattr(importer, 'prepare', prepare)
    monkeypatch.setattr('ingestion.materials_ner.review_amendments.tc_mapping', lambda _: {'records': []})
    monkeypatch.setattr('services.materials_proposal_storage.projected_rows', lambda _: {'runs': []})
    return root, sha((root / 'FILES.json').read_bytes()), calls


def test_preparation_is_immutable_and_views_are_detached(source_package):
    root, pin, calls = source_package
    objects, batch = importer.prepare_package(root, files_sha256=pin)
    assert calls == ['semantic_validation']
    view = batch[0]
    view['request']['bindings']['purpose'] = 'changed'
    view['plan']['results'][0]['claim_id'] = 'changed'
    assert batch[0]['request']['bindings']['purpose'] == 'pending_candidates'
    assert batch[0]['plan']['results'][0]['claim_id'] == 'claim'
    with pytest.raises(FrozenInstanceError):
        batch._records = ()
    first = batch._materialize(objects)
    first[0]['amendment']['amendment_id'] = 'changed'
    assert batch._materialize(objects)[0]['amendment']['amendment_id'] == 'amendment'
    # Repeated imports recheck bytes, without repeating expensive semantic replay.
    assert calls == ['semantic_validation']


def test_semantic_failure_cannot_create_a_prepared_batch(source_package, monkeypatch):
    root, pin, _ = source_package
    def reject(*args, **kwargs):
        raise ValueError('invalid_amendment')
    monkeypatch.setattr(importer, 'prepare', reject)
    with pytest.raises(ValueError, match='invalid_amendment'):
        importer.prepare_package(root, files_sha256=pin)


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['source', 'request', 'manifest', 'files', 'missing', 'symlink'])
async def test_changed_closure_fails_before_database_engine(source_package, monkeypatch, change):
    root, pin, _ = source_package
    objects, batch = importer.prepare_package(root, files_sha256=pin)
    target = next((root / 'objects').iterdir())
    if change in {'request', 'manifest', 'files'}:
        target = root / {'request': 'requests/work/request.json', 'manifest': 'OBJECT_MANIFEST.json',
                         'files': 'FILES.json'}[change]
    if change == 'missing':
        target.unlink()
    elif change == 'symlink':
        outside = root.parent / 'outside'
        outside.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(outside)
    else:
        target.write_bytes(target.read_bytes() + b' ')
    def unexpected_engine(*args, **kwargs):
        pytest.fail('database engine created before input rejection')
    monkeypatch.setattr('sqlalchemy.ext.asyncio.create_async_engine', unexpected_engine)
    with pytest.raises(ValueError, match='package_'):
        await importer.import_prepared(objects, batch, database_url='unused', expected_database='owned',
                                       expected_role='runtime', execute=True)


@pytest.mark.asyncio
async def test_serialized_plan_is_not_a_validation_capability(source_package, monkeypatch):
    root, pin, _ = source_package
    objects, batch = importer.prepare_package(root, files_sha256=pin)
    def unexpected_engine(*args, **kwargs):
        pytest.fail('unvalidated input reached database')
    monkeypatch.setattr('sqlalchemy.ext.asyncio.create_async_engine', unexpected_engine)
    with pytest.raises(ValueError, match='validated_batch_required'):
        await importer.import_prepared(objects, list(batch), database_url='unused', expected_database='owned',
                                       expected_role='runtime', execute=True)
    with pytest.raises(ValueError, match='execute_boolean'):
        await importer.import_prepared(objects, batch, database_url='unused', expected_database='owned',
                                       expected_role='runtime', execute='false')
