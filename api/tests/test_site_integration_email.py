from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit
import re

import pytest
from services import email


@pytest.mark.asyncio
@pytest.mark.parametrize("base", ["https://jzis.org", "https://jzis.org/", "https://jzis.org/sclib/"])
async def test_account_emails_use_working_routes_and_preserve_tokens(monkeypatch, base):
    monkeypatch.setattr(email, "get_settings", lambda: SimpleNamespace(frontend_url=base, password_reset_expiry_minutes=30))
    dispatch = AsyncMock()
    monkeypatch.setattr(email, "_dispatch", dispatch)
    token = "synthetic+token/with?reserved&characters"
    await email.send_verification("synthetic@example.invalid", "<Synthetic>", token)
    await email.send_password_reset("synthetic@example.invalid", "<Synthetic>", token)
    await email.send_welcome("synthetic@example.invalid", "<Synthetic>", "synthetic-key")
    for call, expected_path in zip(dispatch.await_args_list, ["/verify", "/reset-password", "/docs/api"]):
        html = call.args[2]
        url = re.search(r'href="([^"]+)"', html).group(1)
        assert url.startswith(base.rstrip("/") + expected_path)
        assert "<Synthetic>" not in html
        assert "&lt;Synthetic&gt;" in html
        assert "ASRP" not in html
        assert "all JZIS products" not in html
        if expected_path != "/docs/api":
            assert parse_qs(urlsplit(url).query)["token"] == [token]
