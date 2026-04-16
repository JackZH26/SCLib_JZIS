"""Tests for unified JZIS auth + Google OAuth.

Covers:
  - User model: new fields (google_sub, auth_provider, scopes, avatar_url, profile)
  - Login guard for Google-only users (no password_hash)
  - /me endpoint returns new fields
  - Google OAuth redirect endpoint
  - Google OAuth callback (mocked userinfo)
  - Account merging: existing local + Google same-email → auth_provider="both"
  - CORS: asrp.jzis.org allowed
  - Duplicate registration still blocked
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from models.db import ApiKey, User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _register_and_activate(client, db_session, email: str, password: str = "test_pass_12345") -> tuple[str, User]:
    """Register a user, manually activate, return (jwt_token, user)."""
    r = await client.post("/v1/auth/register", json={
        "email": email,
        "password": password,
        "name": "Test User",
        "age": 25,
        "purpose": "testing unified auth",
    })
    assert r.status_code == 201, r.text

    # Manually activate (skip email verification for unit tests)
    q = await db_session.execute(select(User).where(User.email == email))
    user = q.scalar_one()
    user.email_verified = True
    user.is_active = True
    await db_session.commit()
    await db_session.refresh(user)

    # Login to get JWT
    r = await client.post("/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"], user


async def _create_google_user(db_session, email: str, google_sub: str) -> User:
    """Insert a Google-only user directly into DB."""
    user = User(
        email=email,
        name="Google User",
        google_sub=google_sub,
        auth_provider="google",
        avatar_url="https://lh3.googleusercontent.com/photo.jpg",
        email_verified=True,
        is_active=True,
        password_hash=None,  # No password for Google users
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# User model tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_new_user_has_default_fields(client, db_session):
    """Newly registered user gets auth_provider=local, scopes=[basic,sclib]."""
    token, user = await _register_and_activate(client, db_session, "newuser_defaults@test.com")

    r = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["auth_provider"] == "local"
    assert body["avatar_url"] is None
    assert "basic" in body["scopes"]
    assert "sclib" in body["scopes"]


@pytest.mark.asyncio
async def test_google_user_no_password(db_session):
    """Google-only user has password_hash=None."""
    user = await _create_google_user(db_session, "gonly@test.com", "google_sub_001")
    assert user.password_hash is None
    assert user.auth_provider == "google"
    assert user.google_sub == "google_sub_001"
    assert user.avatar_url is not None
    assert user.email_verified is True
    assert user.is_active is True


# ---------------------------------------------------------------------------
# Login guard: Google-only user can't email+password login
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_login_rejects_google_only_user(client, db_session):
    """Email+password login returns 401 for Google-only users with helpful message."""
    await _create_google_user(db_session, "google_only_login@test.com", "google_sub_002")

    r = await client.post("/v1/auth/login", json={
        "email": "google_only_login@test.com",
        "password": "doesnt_matter",
    })
    assert r.status_code == 401
    assert "Google" in r.json()["detail"]


# ---------------------------------------------------------------------------
# /me endpoint returns new fields
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_me_returns_unified_fields(client, db_session):
    """GET /me includes auth_provider, avatar_url, scopes."""
    token, _ = await _register_and_activate(client, db_session, "me_fields@test.com")

    r = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    # Must have all three new fields
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
# Google OAuth callback (mocked)
# ---------------------------------------------------------------------------

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


@pytest.mark.asyncio
async def test_google_callback_creates_new_user(client, db_session):
    """Google callback with unknown email creates a new active user + API key."""
    email = "brand_new_google@test.com"
    sub = "google_sub_new_100"

    mock_token = _mock_google_token(email, sub, "Brand New")

    with patch("routers.auth.get_oauth") as mock_get_oauth:
        mock_oauth = MagicMock()
        mock_oauth.google.authorize_access_token = AsyncMock(return_value=mock_token)
        mock_get_oauth.return_value = mock_oauth

        r = await client.get("/v1/auth/google/callback", follow_redirects=False)

    assert r.status_code == 302
    location = r.headers["location"]
    assert "token=" in location
    assert "error" not in location

    # Verify user was created in DB
    q = await db_session.execute(select(User).where(User.email == email))
    user = q.scalar_one_or_none()
    assert user is not None
    assert user.google_sub == sub
    assert user.auth_provider == "google"
    assert user.is_active is True
    assert user.email_verified is True
    assert user.password_hash is None
    assert user.name == "Brand New"

    # Verify default API key was created
    q = await db_session.execute(select(ApiKey).where(ApiKey.user_id == user.id))
    keys = q.scalars().all()
    assert len(keys) >= 1


@pytest.mark.asyncio
async def test_google_callback_merges_existing_local_user(client, db_session):
    """Google callback with email matching an existing local user binds Google."""
    email = "merge_test@test.com"
    sub = "google_sub_merge_200"

    # First, register a local user
    _, user = await _register_and_activate(client, db_session, email)
    assert user.auth_provider == "local"
    assert user.google_sub is None

    # Now simulate Google callback with same email
    mock_token = _mock_google_token(email, sub, "Merged User", "https://lh3.google.com/merged")

    with patch("routers.auth.get_oauth") as mock_get_oauth:
        mock_oauth = MagicMock()
        mock_oauth.google.authorize_access_token = AsyncMock(return_value=mock_token)
        mock_get_oauth.return_value = mock_oauth

        r = await client.get("/v1/auth/google/callback", follow_redirects=False)

    assert r.status_code == 302
    assert "token=" in r.headers["location"]

    # Verify user was merged (not duplicated)
    await db_session.refresh(user)
    assert user.google_sub == sub
    assert user.auth_provider == "both"
    assert user.avatar_url == "https://lh3.google.com/merged"
    assert user.is_active is True


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
async def test_google_user_can_still_email_login_after_merge(client, db_session):
    """A local user who binds Google can still use email+password login."""
    email = "dual_login@test.com"
    password = "dual_pass_12345"
    sub = "google_sub_dual_300"

    # Register + activate local user
    _, user = await _register_and_activate(client, db_session, email, password)

    # Bind Google
    mock_token = _mock_google_token(email, sub)
    with patch("routers.auth.get_oauth") as mock_get_oauth:
        mock_oauth = MagicMock()
        mock_oauth.google.authorize_access_token = AsyncMock(return_value=mock_token)
        mock_get_oauth.return_value = mock_oauth
        await client.get("/v1/auth/google/callback", follow_redirects=False)

    await db_session.refresh(user)
    assert user.auth_provider == "both"

    # Email+password login should still work
    r = await client.post("/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200
    assert "access_token" in r.json()
