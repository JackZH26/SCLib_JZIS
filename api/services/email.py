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
    subject = "Verify your JZIS account"
    html = f"""<p>Hi {name},</p>
<p>Click to verify your email: <a href="{url}">{url}</a></p>
<p>Link expires in 24 hours.</p>
<p>This account gives you access to all JZIS products including SCLib.</p>
<p>— JZIS Team</p>"""
    await _dispatch(to, subject, html)


async def send_welcome(to: str, name: str, api_key: str) -> None:
    settings = get_settings()
    subject = "Your JZIS API Key is ready"
    docs = f"{settings.frontend_url}/api-docs"
    html = f"""<p>Hi {name}, your JZIS account is verified!</p>
<p>Your API key: <code>{api_key}</code></p>
<p>Use header: <code>X-API-Key: {api_key}</code></p>
<p>API docs: <a href="{docs}">{docs}</a></p>
<p>This account works across all JZIS products — SCLib, ASRP, and more.</p>
<p>— JZIS Team</p>"""
    await _dispatch(to, subject, html)


async def send_feedback(
    *,
    category: str,
    message: str,
    submitter_id: str,
    submitter_name: str,
    submitter_email: str,
    contact_email: str | None,
    user_agent: str | None,
    client_ip: str | None,
) -> None:
    """Email a dashboard feedback submission to the JZIS inbox.

    Always addressed to ``settings.feedback_inbox`` (default
    ``info@jzis.org``). The ``Reply-To`` header would be nicer but the
    current ``_dispatch`` helper does not accept extra headers; for now
    we include the contact address in the body so recipients can just
    copy-paste it.
    """
    settings = get_settings()
    safe_msg = _escape_html(message)
    reply_to = contact_email or submitter_email
    subject = f"[SCLib feedback/{category}] {_summary(message)}"
    html = f"""<h3>New feedback from SCLib dashboard</h3>
<p><b>Category:</b> {_escape_html(category)}</p>
<hr>
<p><b>From:</b> {_escape_html(submitter_name)} &lt;{_escape_html(submitter_email)}&gt;</p>
<p><b>User ID:</b> <code>{_escape_html(submitter_id)}</code></p>
<p><b>Reply to:</b> {_escape_html(reply_to)}</p>
<p><b>User agent:</b> <code>{_escape_html(user_agent or 'unknown')}</code></p>
<p><b>Client IP:</b> <code>{_escape_html(client_ip or 'unknown')}</code></p>
<hr>
<p><b>Message:</b></p>
<pre style="white-space: pre-wrap; font-family: inherit;">{safe_msg}</pre>"""
    await _dispatch(settings.feedback_inbox, subject, html)


def _escape_html(s: str) -> str:
    """Minimal HTML escape. Feedback text is untrusted — a user could
    paste <script> and we would happily mail it to info@jzis.org."""
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
    )


def _summary(message: str, max_len: int = 60) -> str:
    """First line or first N chars, whichever is shorter; used in the
    email subject so the inbox is readable without opening each message."""
    first_line = message.strip().splitlines()[0] if message.strip() else ""
    if len(first_line) <= max_len:
        return _escape_html(first_line)
    return _escape_html(first_line[: max_len - 1].rstrip() + "…")


_resend_initialised: bool = False


def _ensure_resend_key() -> bool:
    """Set resend.api_key once. The Resend SDK keeps the key as a
    module-level attribute, so writing it on every send was both
    pointless and a thread race in theory. Now we set it once and
    cache the success/skip decision."""
    global _resend_initialised
    if _resend_initialised:
        return True
    settings = get_settings()
    if not settings.resend_api_key:
        return False
    resend.api_key = settings.resend_api_key
    _resend_initialised = True
    return True


async def _dispatch(to: str, subject: str, html: str) -> None:
    settings = get_settings()
    if settings.email_backend == "stdout":
        log.info("=== EMAIL (stdout backend) ===\nTo: %s\nSubject: %s\n%s", to, subject, html)
        return
    if not _ensure_resend_key():
        log.error("email_backend=resend but RESEND_API_KEY empty; dropping email to %s", to)
        return
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
