"""Email delivery must not disclose credentials or personal data in logs."""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from services import email


@pytest.mark.asyncio
async def test_stdout_backend_logs_no_message_or_recipient_data(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        email,
        "get_settings",
        lambda: SimpleNamespace(email_backend="stdout"),
    )
    recipient = "private-recipient@example.test"
    subject = "Reset your password"
    body = '<a href="https://example.test/reset?token=secret-reset-token">reset</a>'

    with caplog.at_level(logging.INFO, logger="sclib.email"):
        await email._dispatch(recipient, subject, body)

    assert "email delivery suppressed by stdout backend" in caplog.text
    for sensitive_value in (recipient, subject, body, "secret-reset-token"):
        assert sensitive_value not in caplog.text
