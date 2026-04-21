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

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from models.db import User
from models.personal import FeedbackCreate
from models.user import MessageResponse
from routers.auth import current_user_from_jwt
from services.email import send_feedback

log = logging.getLogger(__name__)

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("", response_model=MessageResponse, status_code=202)
async def submit_feedback(
    body: FeedbackCreate,
    request: Request,
    user: User = Depends(current_user_from_jwt),
) -> MessageResponse:
    """Send feedback to the JZIS inbox.

    Returns 202 (Accepted) — we've enqueued the email for delivery. The
    send is awaited in-band so a Resend failure surfaces as a 500 the
    frontend can retry, rather than silently vanishing into a
    background task.
    """
    # Prefer X-Forwarded-For (we sit behind Nginx on VPS2) but fall back
    # to the direct peer so local / curl tests still see a non-empty IP.
    xff = request.headers.get("x-forwarded-for")
    client_ip = (
        xff.split(",", 1)[0].strip()
        if xff
        else (request.client.host if request.client else None)
    )
    user_agent = request.headers.get("user-agent")

    try:
        await send_feedback(
            category=body.category,
            message=body.message,
            submitter_id=str(user.id),
            submitter_name=user.name,
            submitter_email=user.email,
            contact_email=body.contact_email,
            user_agent=user_agent,
            client_ip=client_ip,
        )
    except Exception as e:  # noqa: BLE001
        log.exception("feedback email dispatch failed for user=%s", user.id)
        raise HTTPException(
            status_code=502,
            detail="Failed to deliver feedback. Please try again in a moment.",
        ) from e

    return MessageResponse(message="Thanks — we read every message.")
