"""End-to-end auth flow: register → verify → login → /me → key lifecycle."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from models.db import AuthAuditEvent, EmailVerification, User

ALICE = {
    "email": "alice@example.com",
    "password": "correct horse battery staple",
    "name": "Alice Tester",
    "age": 30,
    "institution": "MIT",
    "country": "US",
    "research_area": "High-Tc",
    "purpose": "Testing the SCLib auth flow",
}


async def _fetch_verification_token(email: str) -> str:
    """Fetch verification token from DB using a short-lived session."""
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
        return ev.token


@pytest.mark.asyncio
async def test_full_auth_flow(client):
    # 1. register
    r = await client.post("/v1/auth/register", json=ALICE)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["user"]["email"] == ALICE["email"]
    assert body["user"]["is_active"] is False

    # 2. fetch token from DB (in prod this arrives by email)
    token = await _fetch_verification_token(ALICE["email"])

    # 3. verify
    r = await client.get(f"/v1/auth/verify?token={token}")
    assert r.status_code == 200, r.text
    verify_body = r.json()
    api_key = verify_body["api_key"]
    assert api_key.startswith("scl_")
    assert verify_body["user"]["is_active"] is True

    # 4. re-verify same token should fail (used)
    r = await client.get(f"/v1/auth/verify?token={token}")
    assert r.status_code == 400

    # 5. login
    r = await client.post("/v1/auth/login", json={
        "email": ALICE["email"], "password": ALICE["password"]
    })
    assert r.status_code == 200, r.text
    jwt_token = r.json()["access_token"]

    # 6. /me with JWT
    r = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {jwt_token}"})
    assert r.status_code == 200
    assert r.json()["email"] == ALICE["email"]

    # 7. wrong password -> 401
    r = await client.post("/v1/auth/login", json={
        "email": ALICE["email"], "password": "nope"
    })
    assert r.status_code == 401

    # 8. create a second API key
    r = await client.post(
        "/v1/auth/keys",
        json={"name": "second key"},
        headers={"Authorization": f"Bearer {jwt_token}"},
    )
    assert r.status_code == 201
    second_key_id = r.json()["id"]
    assert r.json()["key"].startswith("scl_")

    # 9. revoke the second key
    r = await client.delete(
        f"/v1/auth/keys/{second_key_id}",
        headers={"Authorization": f"Bearer {jwt_token}"},
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_duplicate_registration(client):
    data = {**ALICE, "email": "bob@example.com"}
    r1 = await client.post("/v1/auth/register", json=data)
    assert r1.status_code == 201
    r2 = await client.post("/v1/auth/register", json=data)
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_age_validation(client):
    bad = {**ALICE, "email": "tooyoung@example.com", "age": 10}
    r = await client.post("/v1/auth/register", json=bad)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_password_reset_is_one_time_and_revokes_old_jwt(client, monkeypatch):
    email = "password-reset@example.com"
    password = "old-password-correct-horse"
    payload = {**ALICE, "email": email, "password": password}

    assert (await client.post("/v1/auth/register", json=payload)).status_code == 201
    verification = await _fetch_verification_token(email)
    assert (await client.get(f"/v1/auth/verify?token={verification}")).status_code == 200
    login_response = await client.post(
        "/v1/auth/login", json={"email": email, "password": password}
    )
    old_jwt = login_response.json()["access_token"]

    captured: dict[str, str] = {}

    async def capture_reset(_to: str, _name: str, token: str) -> None:
        captured["token"] = token

    monkeypatch.setattr("routers.auth.send_password_reset", capture_reset)
    response = await client.post(
        "/v1/auth/password-reset/request", json={"email": email}
    )
    assert response.status_code == 200
    assert "If the account" in response.json()["message"]
    assert captured["token"]

    # Unknown accounts receive exactly the same public response.
    unknown = await client.post(
        "/v1/auth/password-reset/request",
        json={"email": "unknown-reset@example.com"},
    )
    assert unknown.status_code == 200
    assert unknown.json() == response.json()

    new_password = "new-password-correct-horse"
    complete = await client.post(
        "/v1/auth/password-reset/confirm",
        json={"token": captured["token"], "new_password": new_password},
    )
    assert complete.status_code == 200, complete.text

    old_session = await client.get(
        "/v1/auth/me", headers={"Authorization": f"Bearer {old_jwt}"}
    )
    assert old_session.status_code == 401

    reused = await client.post(
        "/v1/auth/password-reset/confirm",
        json={"token": captured["token"], "new_password": new_password},
    )
    assert reused.status_code == 400

    old_login = await client.post(
        "/v1/auth/login", json={"email": email, "password": password}
    )
    assert old_login.status_code == 401
    new_login = await client.post(
        "/v1/auth/login", json={"email": email, "password": new_password}
    )
    assert new_login.status_code == 200

    from models.db import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(AuthAuditEvent).where(AuthAuditEvent.event_type.like("password_reset%"))
        )
        events = result.scalars().all()
        assert any(event.outcome == "issued" for event in events)
        assert any(event.outcome == "success" for event in events)
        assert all("@" not in (event.account_hash or "") for event in events)


@pytest.mark.asyncio
async def test_revoke_all_sessions_invalidates_issuing_token(client, registered_user):
    _user, token = registered_user
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.post("/v1/auth/sessions/revoke-all", headers=headers)
    assert response.status_code == 200
    assert "revoked" in response.json()["message"]

    response = await client.get("/v1/auth/me", headers=headers)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_failed_login_applies_retry_after_backoff(
    client, registered_user, monkeypatch
):
    user, _token = registered_user
    from config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "auth_backoff_account_threshold", 1)
    monkeypatch.setattr(settings, "auth_backoff_ip_threshold", 100)

    failed = await client.post(
        "/v1/auth/login",
        json={"email": user.email, "password": "definitely-wrong"},
    )
    assert failed.status_code == 401
    assert failed.headers["retry-after"] == "2"

    blocked = await client.post(
        "/v1/auth/login",
        json={
            "email": user.email,
            "password": "correcthorsebatterystaple",
        },
    )
    assert blocked.status_code == 429
    assert blocked.json()["detail"]["error"] == "auth_rate_limited"
    assert int(blocked.headers["retry-after"]) >= 1
