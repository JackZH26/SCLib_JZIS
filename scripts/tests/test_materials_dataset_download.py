"""Download lifecycle tests use synthetic records, not a scientific gold set."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from routers import materials_vnext as route
from services.materials_dataset_download import FILES, DownloadUnavailable, read_snapshot
from materials_ner_tc_publish_downloads import checked_csv_files


@pytest.fixture
def download(tmp_path, monkeypatch):
    version = 'a' * 64
    folder = tmp_path / version
    folder.mkdir()
    files = {}
    for kind, name in FILES.items():
        content = b'record_id,quantity\nfixture-1,23\n'
        (folder / name).write_bytes(content)
        files[kind] = dict(rows=1, columns=2, sha256=hashlib.sha256(content).hexdigest(), path='/Users/private/file.csv')
    state = dict(schema='materials-download-state/1', rows=1, sha256='b' * 64)
    snapshot = dict(schema='materials-downloads/1', version=version, created_at='2026-10-28T00:00:00Z',
        canonical_state=state, files=files, paper_count=1, source_scope='Selected source assertions',
        training_policy='Scalar experimental Tc', grouping_policy='Group by work',
        private_capture_path='/Users/private/capture.json')
    (folder / 'SNAPSHOT.json').write_text(json.dumps(snapshot))
    (tmp_path / 'CURRENT.json').write_text(json.dumps(dict(version=version)))
    settings = SimpleNamespace(materials_vnext_enabled=True, materials_dataset_download_root=str(tmp_path))
    monkeypatch.setattr(route, 'get_settings', lambda: settings)
    current = AsyncMock(return_value=deepcopy(state))
    monkeypatch.setattr(route, 'canonical_download_state', current)
    async def database():
        yield object()
    app = FastAPI()
    app.include_router(route.router, prefix='/v1')
    app.dependency_overrides[route.get_db] = database
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, root=tmp_path, folder=folder, snapshot=snapshot,
            settings=settings, current=current, url=f'/v1/materials/dataset/{version}')


def test_current_metadata_and_csv_are_downloadable_without_private_paths(download):
    meta = download.client.get('/v1/materials/dataset')
    assert meta.status_code == 200
    assert meta.headers['cache-control'] == 'no-store'
    assert '/Users/' not in meta.text
    assert 'canonical_state' not in meta.json()
    for kind in FILES:
        response = download.client.get(f'{download.url}/{kind}')
        assert response.status_code == 200
        assert response.content == (download.folder / FILES[kind]).read_bytes()
        assert response.headers['content-disposition'] == f'attachment; filename="{FILES[kind]}"'
        assert response.headers['x-dataset-version'] == 'a' * 64


@pytest.mark.parametrize('rows', [0, 1, 2])
def test_withdrawal_same_count_correction_and_new_admission_invalidate_downloads(download, rows):
    download.current.return_value = dict(schema='materials-download-state/1', rows=rows, sha256='c' * 64)
    for url in ['/v1/materials/dataset', f'{download.url}/training']:
        response = download.client.get(url)
        assert response.status_code == 409
        assert response.headers['cache-control'] == 'no-store'
        assert 'dataset changed' in response.json()['detail']


def test_changed_bytes_and_linked_files_are_never_served(download, tmp_path):
    path = download.folder / FILES['results']
    path.write_text('unverified replacement')
    assert download.client.get(f'{download.url}/results').status_code == 503
    path.unlink()
    source = tmp_path / 'outside.csv'
    source.write_bytes(b'record_id,quantity\nfixture-1,23\n')
    path.symlink_to(source)
    assert download.client.get(f'{download.url}/results').status_code == 503


def test_disabled_downloads_unknown_kind_and_previous_snapshot(download):
    assert download.client.get(f'/v1/materials/dataset/{"c" * 64}/training').status_code == 409
    assert download.client.get(f'{download.url}/private.json').status_code == 422
    download.settings.materials_dataset_download_root = None
    assert download.client.get('/v1/materials/dataset').status_code == 404
    download.settings.materials_vnext_enabled = False
    assert download.client.get(f'{download.url}/training').status_code == 404


def test_pointer_cannot_escape_configured_directory(download):
    (download.root / 'CURRENT.json').write_text(json.dumps(dict(version='../outside')))
    with pytest.raises(DownloadUnavailable):
        read_snapshot(download.root)


@pytest.mark.parametrize('verification_version', [3, 4])
def test_publisher_rejects_csv_modified_after_verification(tmp_path, verification_version):
    artifacts = []
    verified = dict(schema=f'materials-csv-verification/{verification_version}', source_dataset_sha256='d' * 64,
        result_rows=1, evidence_rows=1, training_rows=1)
    for key in ('csv_roundtrip_verified', 'original_quotes_unchanged', 'quantity_relations_preserved',
        'no_unknown_pressure_imputation', 'no_known_group_split_leakage', 'no_cjk_or_private_paths',
        'training_quality_and_lifecycle_metadata_verified', 'training_metadata_is_not_model_input'):
        verified[key] = True
    if verification_version == 4:
        verified.pop('no_cjk_or_private_paths')
        verified.update(no_cjk_in_structured_fields=True, private_paths_absent=True)
    for name in FILES.values():
        path = tmp_path / name
        path.write_text('id\nfixture\n')
        artifacts.append(dict(path=str(path), rows=1, columns=1, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    (tmp_path / 'MANIFEST.json').write_text(json.dumps(dict(schema='materials-tabular-export/3',
        source=dict(sha256='d' * 64), artifacts=artifacts)))
    (tmp_path / 'CSV_VERIFICATION.json').write_text(json.dumps(verified))
    assert checked_csv_files(tmp_path)[1]['training']['rows'] == 1
    if verification_version == 4:
        for key in ('no_cjk_in_structured_fields', 'private_paths_absent'):
            incomplete = dict(verified, **{key: False})
            (tmp_path / 'CSV_VERIFICATION.json').write_text(json.dumps(incomplete))
            with pytest.raises(ValueError, match=f'csv_verification_missing:{key}'):
                checked_csv_files(tmp_path)
        (tmp_path / 'CSV_VERIFICATION.json').write_text(json.dumps(verified))
    (tmp_path / FILES['training']).write_text('id\nwrong\n')
    with pytest.raises(ValueError, match='csv_changed:training'):
        checked_csv_files(tmp_path)
