"""Provider failures preserve linkage and still count against the throttle."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import sync_mp_ids as sync  # noqa: E402


def provider_error(kind):
    request = httpx.Request("GET", "https://api.materialsproject.org/materials/summary/")
    if kind == "429":
        response = httpx.Response(429, request=request)
        return httpx.HTTPStatusError("Rate limited", request=request, response=response)
    if kind == "transport":
        return httpx.ConnectError("Synthetic transport failure", request=request)
    return ValueError("MP summary response data is unavailable")


class FailedProvider:
    def __init__(self, kind): self.kind, self.calls = kind, 0
    async def search_by_formula(self, formula, *, strict):
        assert formula == "NbN" and strict is True
        self.calls += 1
        raise provider_error(self.kind)


def unexpected_session():
    raise AssertionError("An unsuccessful provider request must not write or stamp linkage")


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["429", "transport", "malformed"])
async def test_attempted_provider_failures_preserve_linkage_and_remain_queried(kind):
    provider = FailedProvider(kind)
    assert await sync._process_one(
        provider, unexpected_session, "mat:nbn", "NbN", dry_run=False, verbose=False,
    ) == (False, None, True)
    assert provider.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["429", "malformed"])
async def test_main_loop_keeps_throttle_after_provider_failure(monkeypatch, kind):
    provider, sleeps = FailedProvider(kind), []
    class Client:
        def __init__(self, _key): pass
        async def __aenter__(self): return provider
        async def __aexit__(self, *_args): pass
    async def targets(*_args, **_kwargs):
        return [("mat:first", "NbN"), ("mat:second", "NbN")]
    async def sleep(seconds): sleeps.append(seconds)
    monkeypatch.setenv("MP_API_KEY", "test-only")
    monkeypatch.setattr(sync, "parse_args", lambda: SimpleNamespace(
        limit=2, max_age_days=30, force=False, verbose=False, dry_run=False, throttle_sec=.25,
    ))
    monkeypatch.setattr(sync, "get_session_factory", lambda: unexpected_session)
    monkeypatch.setattr(sync, "_candidate_materials", targets)
    monkeypatch.setattr(sync, "MaterialsProjectClient", Client)
    monkeypatch.setattr(sync.asyncio, "sleep", sleep)
    assert await sync._main() == 0
    assert provider.calls == 2
    assert sleeps == [.25]
