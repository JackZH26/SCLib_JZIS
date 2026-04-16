"""End-to-end auth flow: register → verify → login → /me → key lifecycle."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from models.db import ApiKey, EmailVerification, User


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
