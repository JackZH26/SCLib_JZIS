"""Production OAuth settings must fail closed."""
from __future__ import annotations

import pytest
from pydantic import ValidationError
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import PlainTextResponse

from config import Settings
from services.session_config import build_oauth_session_config


def _production_settings(**overrides: str) -> Settings:
    values = {
        "environment": "production",
        "database_url": "postgresql://sclib:test@postgres:5432/sclib",
        "jwt_secret": "test_secret_that_is_long_enough_for_validation_123456",
        "frontend_url": "https://jzis.org/sclib",
        "api_base_url": "https://api.jzis.org/sclib/v1",
        "google_redirect_uri": "https://api.jzis.org/v1/auth/google/callback",
        "frontend_callback_url": "https://jzis.org/sclib/auth/callback",
    }
    values.update(overrides)
    return Settings(**values)


def test_production_oauth_cookie_is_host_locked_and_secure():
    cookie = build_oauth_session_config("production")

    assert cookie.session_cookie == "__Host-sclib_oauth_state"
    assert cookie.https_only is True
    assert cookie.path == "/"
    assert cookie.same_site == "lax"
    assert cookie.max_age == 300


def test_non_production_cookie_does_not_claim_host_prefix():
    cookie = build_oauth_session_config("test")

    assert cookie.session_cookie == "sclib_oauth_state"
    assert cookie.https_only is False


@pytest.mark.asyncio
async def test_production_session_middleware_emits_secure_cookie_attributes():
    cookie_config = build_oauth_session_config("production")

    async def endpoint(scope, receive, send):
        scope["session"]["oauth_state"] = "test"
        await PlainTextResponse("ok")(scope, receive, send)

    app = SessionMiddleware(
        endpoint,
        secret_key="test_secret_that_is_long_enough_for_middleware_123456",
        session_cookie=cookie_config.session_cookie,
        max_age=cookie_config.max_age,
        path=cookie_config.path,
        same_site=cookie_config.same_site,
        https_only=cookie_config.https_only,
    )
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": "/v1/auth/google/login",
            "raw_path": b"/v1/auth/google/login",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("api.jzis.org", 443),
        },
        receive,
        send,
    )

    response_headers = dict(sent[0]["headers"])
    set_cookie = response_headers[b"set-cookie"].decode().lower()
    assert set_cookie.startswith("__host-sclib_oauth_state=")
    for attribute in ("path=/", "max-age=300", "httponly", "samesite=lax", "secure"):
        assert attribute in set_cookie
    assert "domain=" not in set_cookie


@pytest.mark.parametrize(
    ("field", "url"),
    [
        ("frontend_url", "http://jzis.org/sclib"),
        ("api_base_url", "http://api.jzis.org/sclib/v1"),
        ("google_redirect_uri", "http://api.jzis.org/v1/auth/google/callback"),
        ("frontend_callback_url", "http://jzis.org/sclib/auth/callback"),
    ],
)
def test_production_rejects_insecure_auth_urls(field: str, url: str):
    with pytest.raises(ValidationError, match="must use HTTPS"):
        _production_settings(**{field: url})


def test_production_accepts_https_auth_urls():
    settings = _production_settings()
    assert settings.environment == "production"
