"""Tests for unified JZIS auth + Google OAuth.

Covers:
  - User model: new fields (google_sub, auth_provider, scopes, avatar_url, profile)
  - Login guard for Google-only users (no password_hash)
  - /me endpoint returns new fields
  - Google OAuth redirect endpoint
  - Google OAuth callback (mocked userinfo)
  - Account merging: existing local + Google same-email → auth_provider="both"
  - CORS: asrp.jzis.org allowed

All tests use only the ``client`` fixture (no direct ``db_session``) to
avoid the asyncpg "Event loop is closed" teardown issue that occurs when
session-scoped and function-scoped async fixtures share an engine.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from models.db import EmailVerification, User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_COUNTER = 0


def _unique_email(prefix: str = "test") -> str:
    global _COUNTER
    _COUNTER += 1
    return f"{prefix}_{_COUNTER}_{uuid.uuid4().hex[:6]}@test.com"


async def _register_verify_login(client, email: str, password: str = "test_pass_12345") -> str:
    """Register → verify (via DB) → login, return JWT.

    Uses the full API flow. Verification token is fetched by making
    a raw DB query through the engine (not the db_session fixture).
    """
    # Register
    r = await client.post("/v1/auth/register", json={
        "email": email,
        "password": password,
        "name": "Test User",
        "age": 25,
        "purpose": "testing unified auth flow",
    })
    assert r.status_code == 201, r.text

    # Fetch verification token via engine (in a self-contained session)
    from models.db import get_session_factory
    factory = get_session_factory()
    async with factory() as sess:
        q = await sess.execute(
            select(EmailVerification)
            .join(User, EmailVerification.user_id == User.id)
            .where(User.email == email)
            .order_by(EmailVerification.created_at.desc())
        )
        ev = q.scalars().first()
        assert ev is not None, f"no verification row for {email}"
        token = ev.token

    # Verify
    r = await client.get(f"/v1/auth/verify?token={token}")
    assert r.status_code == 200, r.text

    # Login
    r = await client.post("/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _mock_google_token(email: str, sub: str, name: str = "Test Google", picture: str | None = None):
    """Build a fake token dict that mimics Google's authorize_access_token response."""
    return {
        "access_token": "mock_access_token",
        "token_type": "Bearer",
        "userinfo": {
            "sub": sub,
            "email": email,
            "name": name,
            "picture": picture or f"https://lh3.google.com/{sub}",
            "email_verified": True,
        },
    }


async def _google_callback(client, email: str, sub: str, name: str = "Test Google"):
    """Simulate a Google OAuth callback and return the redirect response."""
    mock_token = _mock_google_token(email, sub, name)
    with patch("routers.auth.get_oauth") as mock_get_oauth:
        mock_oauth = MagicMock()
        mock_oauth.google.authorize_access_token = AsyncMock(return_value=mock_token)
        mock_get_oauth.return_value = mock_oauth
        return await client.get("/v1/auth/google/callback", follow_redirects=False)


# ---------------------------------------------------------------------------
# User model: new default fields
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_new_user_has_default_fields(client):
    """Newly registered user gets auth_provider=local, scopes=[basic,sclib]."""
    email = _unique_email("defaults")
    jwt = await _register_verify_login(client, email)

    r = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {jwt}"})
    assert r.status_code == 200
    body = r.json()
    assert body["auth_provider"] == "local"
    assert body["avatar_url"] is None
    assert "basic" in body["scopes"]
    assert "sclib" in body["scopes"]


# ---------------------------------------------------------------------------
# Login guard: Google-only user can't email+password login
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_login_rejects_google_only_user(client):
    """Email+password login returns 401 for Google-only users with helpful message."""
    email = _unique_email("gonly")
    sub = f"gsub_{uuid.uuid4().hex[:8]}"

    # Create user via Google callback
    r = await _google_callback(client, email, sub)
    assert r.status_code == 302

    # Try email+password login — should fail
    r = await client.post("/v1/auth/login", json={
        "email": email,
        "password": "doesnt_matter",
    })
    assert r.status_code == 401
    assert "Google" in r.json()["detail"]


# ---------------------------------------------------------------------------
# /me endpoint returns new fields
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_me_returns_unified_fields(client):
    """GET /me includes auth_provider, avatar_url, scopes."""
    email = _unique_email("me_fields")
    jwt = await _register_verify_login(client, email)

    r = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {jwt}"})
    assert r.status_code == 200
    body = r.json()
    assert "auth_provider" in body
    assert "avatar_url" in body
    assert "scopes" in body


# ---------------------------------------------------------------------------
# Google OAuth redirect
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_google_login_redirects_to_google(client):
    """GET /auth/google/login returns 302 to accounts.google.com."""
    r = await client.get("/v1/auth/google/login", follow_redirects=False)
    assert r.status_code in (302, 307)
    location = r.headers.get("location", "")
    assert "accounts.google.com" in location
    assert "client_id=" in location
    assert "redirect_uri=" in location
    # Should set a session cookie
    cookies = r.headers.get_list("set-cookie")
    assert any("session=" in c for c in cookies)


# ---------------------------------------------------------------------------
# Google OAuth callback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_google_callback_creates_new_user(client):
    """Google callback with unknown email creates a new active user + API key."""
    email = _unique_email("gcreate")
    sub = f"gsub_{uuid.uuid4().hex[:8]}"

    r = await _google_callback(client, email, sub, "Brand New User")
    assert r.status_code == 302
    location = r.headers["location"]
    assert "token=" in location
    assert "error" not in location

    # Extract JWT and check user via /me
    token = location.split("token=")[1].split("&")[0]
    r = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == email
    assert body["auth_provider"] == "google"
    assert body["name"] == "Brand New User"
    assert body["is_active"] is True


@pytest.mark.asyncio
async def test_google_callback_merges_existing_local_user(client):
    """Google callback with email matching existing local user → auth_provider='both'."""
    email = _unique_email("merge")
    sub = f"gsub_{uuid.uuid4().hex[:8]}"
    password = "merge_test_pw_123"

    # Register + verify + login a local user
    jwt_local = await _register_verify_login(client, email, password)
    r = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {jwt_local}"})
    assert r.json()["auth_provider"] == "local"

    # Now simulate Google callback with same email
    r = await _google_callback(client, email, sub, "Merged Google")
    assert r.status_code == 302
    token = r.headers["location"].split("token=")[1].split("&")[0]

    # Check merged user via /me
    r = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["auth_provider"] == "both"
    assert body["email"] == email


@pytest.mark.asyncio
async def test_google_callback_handles_oauth_error(client):
    """Google callback gracefully handles token exchange failure."""
    with patch("routers.auth.get_oauth") as mock_get_oauth:
        mock_oauth = MagicMock()
        mock_oauth.google.authorize_access_token = AsyncMock(
            side_effect=Exception("state mismatch")
        )
        mock_get_oauth.return_value = mock_oauth

        r = await client.get("/v1/auth/google/callback", follow_redirects=False)

    assert r.status_code == 302
    location = r.headers["location"]
    assert "error=oauth_failed" in location


@pytest.mark.asyncio
async def test_google_callback_missing_userinfo(client):
    """Google callback with empty userinfo redirects with error."""
    with patch("routers.auth.get_oauth") as mock_get_oauth:
        mock_oauth = MagicMock()
        mock_oauth.google.authorize_access_token = AsyncMock(
            return_value={"access_token": "x", "userinfo": {}}
        )
        mock_get_oauth.return_value = mock_oauth

        r = await client.get("/v1/auth/google/callback", follow_redirects=False)

    assert r.status_code == 302
    assert "error=missing_userinfo" in r.headers["location"]


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cors_asrp_allowed(client):
    """OPTIONS preflight from asrp.jzis.org returns 200 with correct ACAO."""
    r = await client.options(
        "/v1/auth/login",
        headers={
            "origin": "https://asrp.jzis.org",
            "access-control-request-method": "POST",
            "access-control-request-headers": "content-type",
        },
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "https://asrp.jzis.org"


@pytest.mark.asyncio
async def test_cors_jzis_allowed(client):
    """Both jzis.org and www.jzis.org are allowed CORS origins."""
    for origin in ["https://jzis.org", "https://www.jzis.org"]:
        r = await client.options(
            "/v1/auth/login",
            headers={
                "origin": origin,
                "access-control-request-method": "POST",
                "access-control-request-headers": "content-type",
            },
        )
        assert r.status_code == 200, f"CORS failed for {origin}"
        assert r.headers.get("access-control-allow-origin") == origin


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_merged_user_can_still_email_login(client):
    """A local user who binds Google can still use email+password login."""
    email = _unique_email("dual")
    sub = f"gsub_{uuid.uuid4().hex[:8]}"
    password = "dual_auth_test_123"

    # Register local user
    await _register_verify_login(client, email, password)

    # Bind Google via callback
    r = await _google_callback(client, email, sub)
    assert r.status_code == 302

    # Email+password login should still work
    r = await client.post("/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200
    jwt = r.json()["access_token"]

    # And /me should show merged state
    r = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {jwt}"})
    assert r.status_code == 200
    assert r.json()["auth_provider"] == "both"
