"""Email service — Resend backend with stdout fallback.

Two backends configured by EMAIL_BACKEND env:
  - resend  (production): calls Resend API (synchronous SDK, wrapped in
            asyncio.to_thread so it does not block the event loop)
  - stdout  (dev/test):   logs the message to the application logger

Spec section 10 for the exact HTML templates.
"""
from __future__ import annotations

import asyncio
import logging

import resend

from config import get_settings

log = logging.getLogger("sclib.email")


async def send_verification(to: str, name: str, token: str) -> None:
    settings = get_settings()
    url = f"{settings.frontend_url}/auth/verify?token={token}"
    subject = "Verify your SCLib_JZIS account"
    html = f"""<p>Hi {name},</p>
<p>Click to verify your email: <a href="{url}">{url}</a></p>
<p>Link expires in 24 hours.</p>
<p>— JZIS Team</p>"""
    await _dispatch(to, subject, html)


async def send_welcome(to: str, name: str, api_key: str) -> None:
    settings = get_settings()
    subject = "Your SCLib_JZIS API Key is ready"
    docs = f"{settings.frontend_url}/api-docs"
    html = f"""<p>Hi {name}, your account is verified!</p>
<p>Your API key: <code>{api_key}</code></p>
<p>Use header: <code>X-API-Key: {api_key}</code></p>
<p>API docs: <a href="{docs}">{docs}</a></p>
<p>— JZIS Team</p>"""
    await _dispatch(to, subject, html)


async def _dispatch(to: str, subject: str, html: str) -> None:
    settings = get_settings()
    if settings.email_backend == "stdout":
        log.info("=== EMAIL (stdout backend) ===\nTo: %s\nSubject: %s\n%s", to, subject, html)
        return
    if not settings.resend_api_key:
        log.error("email_backend=resend but RESEND_API_KEY empty; dropping email to %s", to)
        return
    resend.api_key = settings.resend_api_key
    params = {
        "from": settings.email_from,
        "to": to,
        "subject": subject,
        "html": html,
    }
    # Resend SDK is sync — run in threadpool so we do not block uvicorn
    try:
        await asyncio.to_thread(resend.Emails.send, params)
        log.info("sent email to=%s subject=%s", to, subject)
    except Exception as e:  # noqa: BLE001
        log.exception("email send failed to=%s: %s", to, e)
