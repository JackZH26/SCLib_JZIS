"""Smoke tests for the dashboard-phase backend surface.

Covers three scenarios that the phase-A/B/C review flagged as worth
pinning in regression:

1. PATCH /auth/me whitelist — editable fields update, identity fields
   refuse, explicit null on NOT-NULL fields is rejected at 400 not
   500, ORCID normalization strips URL/trailing slash/case.
2. 429 quota enforcement — driven at the service layer so we don't
   need to mock Vertex AI; the HTTP wrapper is a thin translation.
3. GET /auth/usage returns the shape the frontend expects.

Each test is independent — a fresh registered_user fixture seeds the
DB and tears it back down in the conftest truncate.
"""
from __future__ import annotations

from uuid import uuid4

import pytest


# ---------------------------------------------------------------------------
# 1. PATCH /auth/me whitelist
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_patch_me_updates_whitelisted_fields(client, registered_user):
    _, jwt = registered_user
    headers = {"Authorization": f"Bearer {jwt}"}

    r = await client.patch(
        "/v1/auth/me",
        json={
            "institution": "MIT",
            "bio": "Condensed matter physicist.",
            "orcid": "0000-0002-1825-0097",
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["institution"] == "MIT"
    assert body["bio"] == "Condensed matter physicist."
    assert body["orcid"] == "0000-0002-1825-0097"


@pytest.mark.asyncio
async def test_patch_me_ignores_identity_fields(client, registered_user):
    """email / id / auth_provider / is_active are not in UserUpdate — any
    attempt to set them should be silently ignored (Pydantic drops
    them) and the stored value should stay put."""
    user, jwt = registered_user
    headers = {"Authorization": f"Bearer {jwt}"}

    r = await client.patch(
        "/v1/auth/me",
        json={
            "email": "hacker@example.com",
            "id": str(uuid4()),
            "is_active": False,
            "name": "Legitimate Update",
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Legitimate Update"
    assert body["email"] == user.email            # unchanged
    assert body["id"] == str(user.id)             # unchanged
    assert body["is_active"] is True              # unchanged


@pytest.mark.asyncio
async def test_patch_me_null_name_is_400_not_500(client, registered_user):
    """Name is NOT NULL in the DB; passing explicit null must be
    rejected at the Pydantic layer, not fall through to a 500."""
    _, jwt = registered_user
    r = await client.patch(
        "/v1/auth/me",
        json={"name": None},
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert r.status_code == 422, r.text
    # Pydantic puts validation errors in `detail`; we just confirm the
    # shape rather than the exact phrasing so copy changes don't break
    # the test.
    assert "name" in r.text.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("0000-0002-1825-0097", "0000-0002-1825-0097"),
        ("0000-0002-1825-009X", "0000-0002-1825-009X"),
        ("0000-0002-1825-009x", "0000-0002-1825-009X"),  # lowercase x
        ("https://orcid.org/0000-0002-1825-0097", "0000-0002-1825-0097"),
        ("orcid.org/0000-0002-1825-0097/", "0000-0002-1825-0097"),  # trailing /
    ],
)
async def test_patch_me_orcid_normalization(client, registered_user, raw, expected):
    _, jwt = registered_user
    r = await client.patch(
        "/v1/auth/me",
        json={"orcid": raw},
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert r.status_code == 200, f"raw={raw}  body={r.text}"
    assert r.json()["orcid"] == expected


@pytest.mark.asyncio
async def test_patch_me_bad_orcid_rejected(client, registered_user):
    _, jwt = registered_user
    r = await client.patch(
        "/v1/auth/me",
        json={"orcid": "not-an-orcid"},
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# 2. 429 quota enforcement (service-level — HTTP wrapper is trivial)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_consume_user_enforces_daily_limit(monkeypatch):
    """Validate the exact contract deps.require_identity relies on:
    consume_user returns a decreasing remaining, and goes negative once
    the cap is exceeded."""
    from config import get_settings
    from services.rate_limit import consume_user, get_user_remaining

    settings = get_settings()
    monkeypatch.setattr(settings, "registered_daily_limit", 3)

    uid = uuid4()
    r1 = await consume_user(uid)
    r2 = await consume_user(uid)
    r3 = await consume_user(uid)
    r4 = await consume_user(uid)

    assert r1 == 2
    assert r2 == 1
    assert r3 == 0
    assert r4 == -1  # over limit — deps.py surfaces this as 429

    # get_user_remaining clamps at 0 for display purposes
    assert await get_user_remaining(uid) == 0


# ---------------------------------------------------------------------------
# 3. GET /auth/usage response shape
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_usage_returns_expected_shape(client, registered_user):
    _, jwt = registered_user
    r = await client.get(
        "/v1/auth/usage",
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Exact value of today_used depends on test ordering + Redis flush;
    # what we care about is that all five fields are present with the
    # right types.
    assert set(body) == {
        "today_used", "today_remaining", "daily_limit",
        "week_used", "all_time_used",
    }
    assert body["today_remaining"] + body["today_used"] <= body["daily_limit"] + 1
    assert body["all_time_used"] >= 0
