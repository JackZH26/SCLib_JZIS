"""Real existing account authentication, synthetic download bytes, owned DB only."""
from unittest.mock import AsyncMock

import pytest

from routers import materials_vnext as route
from routers.auth import _browser_session_config

pytestmark = pytest.mark.asyncio(loop_scope='session')


async def test_manifest_and_files_require_a_real_active_session(client, registered_user, monkeypatch):
    version = 'a' * 64
    snapshot = dict(version=version, created_at='2026-10-31T00:00:00Z', paper_count=1,
        files={key: dict(rows=1, columns=1, sha256='b' * 64) for key in ('results', 'evidence', 'training')},
        source_scope='Synthetic source fixture', training_policy='Preserve quantities', grouping_policy='Group by work')
    current = AsyncMock(return_value=(None, snapshot))
    monkeypatch.setattr(route, 'current_download', current)
    monkeypatch.setattr(route, 'read_csv', lambda *args: b'record_id\nowned-fixture\n')
    urls = ['/v1/materials/dataset', *(f'/v1/materials/dataset/{version}/{kind}' for kind in snapshot['files'])]
    for url in urls:
        assert (await client.get(url)).status_code == 401
        assert (await client.get(url, headers={'Authorization': 'Bearer invalid'})).status_code == 401
    current.assert_not_awaited()
    _, token = registered_user
    for url in urls:
        response = await client.get(url, headers={'Authorization': 'Bearer ' + token})
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'private, no-store'
        assert response.headers['vary'] == 'Cookie, Authorization'
        cookie_response = await client.get(url, headers={'Cookie': _browser_session_config().cookie_name + '=' + token})
        assert cookie_response.status_code == 200
    assert current.await_count == 2 * len(urls)
