"""Browser session authentication without a live database."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from models.user import LoginRequest
from routers.auth import (
    browser_session_login,
    current_user_from_jwt,
    google_callback,
    logout,
)
from services import auth_service


class _FakeDb:
    def __init__(self, user: SimpleNamespace) -> None:
        self.user = user

    async def get(self, _model, user_id):
        assert user_id == self.user.id
        return self.user


class _OAuthDb(_FakeDb):
    async def execute(self, _statement):
        return SimpleNamespace(scalar_one_or_none=lambda: self.user)

    async def commit(self):
        return None

    async def refresh(self, _user):
        return None


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


@pytest.mark.asyncio
async def test_google_callback_redirects_without_exposing_jwt():
    user = SimpleNamespace(
        id=uuid4(),
        email="session-user@example.com",
        is_active=True,
        google_sub="google-sub",
        avatar_url=None,
        auth_provider="google",
        email_verified=True,
        last_login=None,
    )
    oauth = MagicMock()
    oauth.google.authorize_access_token = AsyncMock(return_value={
        "userinfo": {
            "sub": user.google_sub,
            "email": user.email,
            "name": "Session User",
        },
    })
    request = _request("oauth-state")

    with patch("routers.auth.get_oauth", return_value=oauth):
        response = await google_callback(request, _OAuthDb(user))

    assert response.status_code == 302
    assert response.headers["location"].endswith("/sclib/auth/callback")
    assert "token=" not in response.headers["location"]
    assert "sclib_session=" in response.headers["set-cookie"]


@pytest.mark.asyncio
async def test_password_browser_login_returns_no_jwt_body():
    password = "browser-session-password"
    user = SimpleNamespace(
        id=uuid4(),
        email="password-user@example.com",
        is_active=True,
        password_hash=auth_service.hash_password(password),
        last_login=None,
    )
    request = _request(
        "pre-login",
        method="POST",
        origin="https://jzis.org",
    )
    response = Response()

    result = await browser_session_login(
        LoginRequest(email=user.email, password=password),
        request,
        response,
        _OAuthDb(user),
    )

    assert result.authenticated is True
    assert not hasattr(result, "access_token")
    assert "sclib_session=" in response.headers["set-cookie"]


@pytest.mark.asyncio
async def test_logout_clears_cookie_even_without_valid_session():
    request = _request(
        "expired-or-invalid",
        method="POST",
        origin="https://jzis.org",
    )
    response = Response()

    result = await logout(request, response)

    assert result.message == "Signed out"
    set_cookie = response.headers["set-cookie"].lower()
    assert set_cookie.startswith("sclib_session=\"")
    assert "max-age=0" in set_cookie
