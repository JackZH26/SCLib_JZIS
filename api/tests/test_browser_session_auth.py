"""Browser session authentication without a live database."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from routers.auth import current_user_from_jwt
from services import auth_service


class _FakeDb:
    def __init__(self, user: SimpleNamespace) -> None:
        self.user = user

    async def get(self, _model, user_id):
        assert user_id == self.user.id
        return self.user


def _request(
    token: str,
    *,
    method: str = "GET",
    origin: str | None = None,
) -> Request:
    headers = [(b"cookie", f"sclib_session={token}".encode())]
    if origin:
        headers.append((b"origin", origin.encode()))
    return Request({
        "type": "http",
        "method": method,
        "path": "/v1/auth/me",
        "headers": headers,
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
        "server": ("api.jzis.org", 443),
        "scheme": "https",
    })


@pytest.mark.asyncio
async def test_http_only_cookie_authenticates_browser_session():
    user = SimpleNamespace(id=uuid4(), is_active=True)
    token, _ = auth_service.create_access_token(user.id)

    resolved = await current_user_from_jwt(_request(token), None, _FakeDb(user))

    assert resolved is user


@pytest.mark.asyncio
async def test_cookie_authenticated_write_requires_trusted_origin():
    user = SimpleNamespace(id=uuid4(), is_active=True)
    token, _ = auth_service.create_access_token(user.id)

    with pytest.raises(HTTPException) as exc_info:
        await current_user_from_jwt(
            _request(token, method="PATCH"),
            None,
            _FakeDb(user),
        )
    assert exc_info.value.status_code == 403

    resolved = await current_user_from_jwt(
        _request(token, method="PATCH", origin="https://jzis.org"),
        None,
        _FakeDb(user),
    )
    assert resolved is user


@pytest.mark.asyncio
async def test_bearer_client_remains_compatible_without_browser_origin():
    user = SimpleNamespace(id=uuid4(), is_active=True)
    token, _ = auth_service.create_access_token(user.id)
    request = _request("ignored", method="PATCH")

    resolved = await current_user_from_jwt(
        request,
        f"Bearer {token}",
        _FakeDb(user),
    )

    assert resolved is user
