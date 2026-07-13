"""Helpers for adding privacy-preserving auth audit rows to a DB transaction."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from models.db import AuthAuditEvent
from services.auth_security import normalize_account, privacy_hash
from services.request_context import client_ip


def add_auth_audit(
    db: AsyncSession,
    request: Request,
    *,
    event_type: str,
    outcome: str,
    account: str | None = None,
    user_id: UUID | None = None,
    details: Mapping[str, str | int | bool] | None = None,
) -> None:
    user_agent = request.headers.get("user-agent")
    db.add(
        AuthAuditEvent(
            event_type=event_type,
            outcome=outcome,
            user_id=user_id,
            account_hash=(privacy_hash("account", normalize_account(account)) if account else None),
            client_ip_hash=privacy_hash("ip", client_ip(request)),
            user_agent_hash=(privacy_hash("user_agent", user_agent) if user_agent else None),
            details=dict(details or {}),
        )
    )
