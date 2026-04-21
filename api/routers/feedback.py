"""POST /feedback — dashboard feedback form.

Requires JWT auth. Anonymous feedback is intentionally not supported
(product decision — see project memory). The handler collects the
user's identity + request metadata and emails the bundle to the
inbox configured by ``settings.feedback_inbox`` (default
``info@jzis.org``).

No DB table: we trust Resend's delivery log as the audit trail. If a
moderation / triage UI is needed later, persistence can be added in
a future migration without changing this route's contract.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Request

from models.db import User
from models.personal import FeedbackCreate
from models.user import MessageResponse
from routers.auth import current_user_from_jwt
from services.email import send_feedback

log = logging.getLogger(__name__)

router = APIRouter(prefix="/feedback", tags=["feedback"])


async def _send_feedback_bg(**kwargs: object) -> None:
    """Wrapper so a Resend failure logs rather than raising into the
    event loop's default exception handler (which would print a
    scary "Task exception was never retrieved" traceback)."""
    try:
        await send_feedback(**kwargs)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        log.exception("feedback email dispatch failed in background")


@router.post("", response_model=MessageResponse, status_code=202)
async def submit_feedback(
    body: FeedbackCreate,
    request: Request,
    user: User = Depends(current_user_from_jwt),
) -> MessageResponse:
    """Queue a feedback email and return immediately.

    Previously we awaited the Resend call in-band, which turned a slow
    upstream into a 30-second spinner for the user. We now schedule
    the send as a background task and return 202 right away. Delivery
    status is visible in Resend's dashboard; transport failures log
    to the API logger. The tradeoff: a user who hits "Submit" while
    Resend is down gets a success message and a message that never
    arrived — acceptable because the failure mode is operator-visible
    (both Resend and our logs) and the legitimate alternative (a 30 s
    spinner) is worse UX.
    """
    xff = request.headers.get("x-forwarded-for")
    client_ip = (
        xff.split(",", 1)[0].strip()
        if xff
        else (request.client.host if request.client else None)
    )
    user_agent = request.headers.get("user-agent")

    asyncio.create_task(_send_feedback_bg(
        category=body.category,
        message=body.message,
        submitter_id=str(user.id),
        submitter_name=user.name,
        submitter_email=user.email,
        contact_email=body.contact_email,
        user_agent=user_agent,
        client_ip=client_ip,
    ))
    log.info("feedback queued user=%s category=%s", user.id, body.category)

    return MessageResponse(message="Thanks — we read every message.")
