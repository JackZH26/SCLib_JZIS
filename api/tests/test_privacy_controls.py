"""Personal-data export, minimization, and self-service deletion regressions."""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import func, select

from models.db import (
    ApiKey,
    AskHistory,
    AuthAuditEvent,
    Bookmark,
    User,
    get_session_factory,
)
from models.user import UserCreate


def test_registration_demographics_are_optional() -> None:
    body = UserCreate(
        email="minimal@example.com",
        password="correct horse battery staple",
        name="Minimal User",
    )

    assert body.age is None
    assert body.institution is None
    assert body.country is None
    assert body.research_area is None
    assert body.purpose is None


@pytest.mark.asyncio
async def test_legacy_age_and_purpose_can_be_corrected_or_cleared(
    client, registered_user
) -> None:
    _user, token = registered_user
    headers = {"Authorization": f"Bearer {token}"}

    updated = await client.patch(
        "/v1/auth/me",
        headers=headers,
        json={"age": 35, "purpose": "Materials research"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["age"] == 35
    assert updated.json()["purpose"] == "Materials research"

    cleared = await client.patch(
        "/v1/auth/me",
        headers=headers,
        json={"age": None, "purpose": None},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["age"] is None
    assert cleared.json()["purpose"] is None


@pytest.mark.asyncio
async def test_account_export_is_complete_but_excludes_secret_material(
    client, registered_user
) -> None:
    user, token = registered_user
    factory = get_session_factory()
    async with factory() as session:
        stored = await session.get(User, user.id)
        assert stored is not None
        stored.age = 42
        stored.purpose = "Reproducibility research"
        session.add_all(
            [
                ApiKey(
                    user_id=user.id,
                    key_hash=uuid4().hex,
                    key_prefix="scl_export",
                    name="export test",
                ),
                AskHistory(
                    user_id=user.id,
                    question="What is the Tc of MgB2?",
                    answer="About 39 K.",
                    sources=[{"paper_id": "arxiv:0101446"}],
                    latency_ms=12,
                    language="en",
                ),
                Bookmark(
                    user_id=user.id,
                    target_type="paper",
                    target_id="arxiv:0101446",
                ),
                AuthAuditEvent(
                    event_type="login",
                    outcome="success",
                    user_id=user.id,
                    account_hash=uuid4().hex,
                    client_ip_hash=uuid4().hex,
                    user_agent_hash=uuid4().hex,
                    details={"flow": "browser"},
                ),
            ]
        )
        await session.commit()

    response = await client.get(
        "/v1/auth/me/export",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"].endswith(f'{user.id}.json"')
    body = response.json()
    assert body["schema_version"] == "1"
    assert body["profile"]["age"] == 42
    assert body["profile"]["purpose"] == "Reproducibility research"
    assert body["api_keys"][0]["key_prefix"] == "scl_export"
    assert body["ask_history"][0]["question"].startswith("What is")
    assert body["bookmarks"][0]["target_id"] == "arxiv:0101446"
    assert body["security_events"][0]["event_type"] == "login"
    serialized = response.text
    assert "password_hash" not in serialized
    assert "key_hash" not in serialized
    assert "token_hash" not in serialized
    assert "client_ip_hash" not in serialized
    assert "user_agent_hash" not in serialized


@pytest.mark.asyncio
async def test_account_delete_requires_fresh_confirmation(client, registered_user) -> None:
    user, token = registered_user
    headers = {"Authorization": f"Bearer {token}"}

    wrong = await client.request(
        "DELETE",
        "/v1/auth/me",
        headers=headers,
        json={
            "confirmation": "DELETE",
            "email": user.email,
            "current_password": "wrong-password",
        },
    )

    assert wrong.status_code == 400
    assert (await client.get("/v1/auth/me", headers=headers)).status_code == 200


@pytest.mark.asyncio
async def test_account_delete_cascades_private_rows_and_deidentifies_audit(
    client, registered_user
) -> None:
    user, token = registered_user
    factory = get_session_factory()
    async with factory() as session:
        session.add_all(
            [
                ApiKey(
                    user_id=user.id,
                    key_hash=uuid4().hex,
                    key_prefix="scl_delete",
                    name="delete test",
                ),
                AskHistory(
                    user_id=user.id,
                    question="Delete this question",
                    answer="Delete this answer",
                    sources=[],
                    latency_ms=1,
                ),
                Bookmark(
                    user_id=user.id,
                    target_type="material",
                    target_id="MgB2",
                ),
            ]
        )
        await session.commit()

    response = await client.request(
        "DELETE",
        "/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "confirmation": "DELETE",
            "email": user.email,
            "current_password": "correcthorsebatterystaple",
        },
    )

    assert response.status_code == 200, response.text
    assert "deleted" in response.json()["message"].lower()
    assert (
        await client.get(
            "/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
    ).status_code == 401

    async with factory() as session:
        assert await session.get(User, user.id) is None
        for model in (ApiKey, AskHistory, Bookmark):
            count = await session.scalar(
                select(func.count()).select_from(model).where(model.user_id == user.id)
            )
            assert count == 0
        event = (
            await session.execute(
                select(AuthAuditEvent)
                .where(AuthAuditEvent.event_type == "account_delete")
                .order_by(AuthAuditEvent.created_at.desc())
            )
        ).scalars().first()
        assert event is not None
        assert event.user_id is None


@pytest.mark.asyncio
async def test_admin_must_be_demoted_before_self_deletion(client, registered_user) -> None:
    user, token = registered_user
    factory = get_session_factory()
    async with factory() as session:
        stored = await session.get(User, user.id)
        assert stored is not None
        stored.is_admin = True
        await session.commit()

    response = await client.request(
        "DELETE",
        "/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "confirmation": "DELETE",
            "email": user.email,
            "current_password": "correcthorsebatterystaple",
        },
    )

    assert response.status_code == 409
