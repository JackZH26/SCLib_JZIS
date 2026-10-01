"""Provider failures preserve linkage and still count against the throttle."""
from __future__ import annotations

import asyncio
import gzip
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import sync_mp_ids as sync  # noqa: E402
from services import material_external_references as references  # noqa: E402
from services.materials_project import MaterialsProjectClient  # noqa: E402


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


class ResponseStream(httpx.AsyncByteStream):
    def __init__(self, parts):
        self.parts, self.reads, self.closed = parts, 0, False
    async def __aiter__(self):
        for part in self.parts:
            self.reads += 1
            yield part
    async def aclose(self):
        self.closed = True


def streamed_client(monkeypatch, stream, *, headers=None):
    requests, constructor_options = [], []
    original_client = httpx.AsyncClient
    def respond(request):
        requests.append(request)
        return httpx.Response(200, headers=headers, stream=stream)
    def client(*args, **kwargs):
        constructor_options.append(kwargs)
        return original_client(*args, **kwargs, transport=httpx.MockTransport(respond))
    monkeypatch.setattr(httpx, "AsyncClient", client)
    return requests, constructor_options


class ReferenceCache:
    def __init__(self): self.values = {"unrelated": "retained cache"}
    async def get(self, key): return self.values.get(key)
    async def set(self, key, value, ex): self.values[key] = value
    def pipeline(self, transaction=True): return self
    async def __aenter__(self): return self
    async def __aexit__(self, *_args): pass
    def incr(self, _key): pass
    def expire(self, _key, _ttl): pass
    async def execute(self): return 1, True


@pytest.mark.asyncio
@pytest.mark.parametrize("bounded", [False, True])
async def test_streaming_byte_limit_preserves_normal_summary_and_default_client_compatibility(monkeypatch, bounded):
    rows = [{"material_id": "mp-1", "formula_pretty": "NbN", "structure": {"lattice": {"a": 4.4}, "sites": []}}]
    body = json.dumps({"data": rows}).encode()
    stream = ResponseStream([body[:20], body[20:]])
    requests, _ = streamed_client(monkeypatch, stream)
    async with MaterialsProjectClient("synthetic-key") as client:
        result = await client.search_by_formula("NbN", strict=True, **({"max_response_bytes": len(body)} if bounded else {}))
    assert result == rows and stream.closed
    assert requests[0].url.params["formula"] == "NbN"
    assert requests[0].headers["X-API-KEY"] == "synthetic-key"
    if bounded:
        assert requests[0].headers["Accept-Encoding"] == "identity"


@pytest.mark.asyncio
async def test_bounded_client_accepts_a_transport_with_an_already_buffered_normal_response(monkeypatch):
    original_client = httpx.AsyncClient
    rows = [{"material_id": "mp-1", "formula_pretty": "NbN"}]
    def client(*args, **kwargs):
        return original_client(*args, **kwargs, transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={"data": rows})))
    monkeypatch.setattr(httpx, "AsyncClient", client)
    async with MaterialsProjectClient("synthetic-key") as mp:
        assert await mp.search_by_formula("NbN", strict=True, max_response_bytes=512) == rows


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", [False, True])
async def test_response_byte_limit_rejects_declared_and_streamed_oversize_before_json_parse(monkeypatch, declared):
    body = json.dumps({"data": [{"structure": {"sites": ["x" * 256]}}]}).encode()
    stream = ResponseStream([body[:65], body[65:130], body[130:]])
    requests, _ = streamed_client(monkeypatch, stream, headers={"Content-Length": str(len(body))} if declared else None)
    async with MaterialsProjectClient("synthetic-key") as client:
        with pytest.raises(ValueError, match="MP response exceeds byte limit"):
            await client.search_by_formula("NbN", strict=True, max_response_bytes=64)
    assert len(requests) == 1 and stream.closed
    assert stream.reads == (0 if declared else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("bounded", [False, True])
async def test_legacy_compression_compatibility_and_bounded_encoding_fail_closed(monkeypatch, bounded):
    rows = [{"material_id": "mp-1", "formula_pretty": "NbN"}]
    compressed = gzip.compress(json.dumps({"data": rows}).encode())
    stream = ResponseStream([compressed])
    streamed_client(monkeypatch, stream, headers={"Content-Encoding": "gzip"})
    async with MaterialsProjectClient("synthetic-key") as client:
        if bounded:
            with pytest.raises(ValueError, match="requires identity encoding"):
                await client.search_by_formula("NbN", strict=True, max_response_bytes=512)
            assert stream.reads == 0
        else:
            assert await client.search_by_formula("NbN", strict=True) == rows
    assert stream.closed


@pytest.mark.asyncio
async def test_oversized_raw_structure_returns_unavailable_and_preserves_reference_cache(monkeypatch):
    cache = ReferenceCache()
    monkeypatch.setattr(references, "get_redis", lambda: cache)
    row = {"material_id": "mp-1", "formula_pretty": "NbN", "structure": {"sites": ["x" * references.MAX_BYTES]}}
    body = json.dumps({"data": [row]}).encode()
    stream = ResponseStream([body[i:i + 65536] for i in range(0, len(body), 65536)])
    requests, options = streamed_client(monkeypatch, stream)
    result = await references.fetch_external_references("NbN", api_key="synthetic-key")
    assert result["status"] == "unavailable" and result["candidates"] == []
    assert result["reason"] == "provider_or_cache_unavailable"
    assert cache.values == {"unrelated": "retained cache"}
    assert len(requests) == 1 and stream.closed
    assert options[0]["timeout"].read == 12.0 and options[0]["timeout"].connect == 4.0
    assert "synthetic-key" not in json.dumps(result)


@pytest.mark.asyncio
async def test_overall_stream_deadline_returns_unavailable_closes_response_and_preserves_cache(monkeypatch):
    class StalledStream(ResponseStream):
        async def __aiter__(self):
            yield b'{"data":['
            await asyncio.Event().wait()
    cache, stream = ReferenceCache(), StalledStream([])
    monkeypatch.setattr(references, "get_redis", lambda: cache)
    streamed_client(monkeypatch, stream)
    original_timeout = asyncio.timeout
    def fast_deadline(seconds):
        assert seconds == 12.0
        return original_timeout(.001)
    monkeypatch.setattr(references.asyncio, "timeout", fast_deadline)
    result = await asyncio.wait_for(references.fetch_external_references("NbN", api_key="synthetic-key"), timeout=1)
    assert result["status"] == "unavailable" and result["candidates"] == []
    assert result["reason"] == "provider_or_cache_unavailable"
    assert stream.closed and cache.values == {"unrelated": "retained cache"}


def test_unrepresentable_numeric_metadata_is_omitted_without_discarding_a_valid_reference():
    result = references.project_external_references("NbN", [{
        "material_id": "mp-1", "formula_pretty": "NbN", "density": 10 ** 400,
        "symmetry": {"number": 10 ** 400},
        "structure": {"lattice": {"a": 4.4, "b": 10 ** 400}},
    }], retrieved_at="2026-10-02T00:00:00+00:00")
    assert result["status"] == "available"
    candidate = result["candidates"][0]
    assert candidate["density_g_cm3"] is None and candidate["space_group_number"] is None
    assert candidate["lattice"] == {"a": 4.4}
    json.dumps(result, allow_nan=False)


@pytest.mark.asyncio
async def test_cancelled_waiter_and_released_owner_keep_one_formula_lock_until_all_users_finish(monkeypatch):
    class Uncached(ReferenceCache):
        async def get(self, _key): return None
    cache = Uncached()
    monkeypatch.setattr(references, "get_redis", lambda: cache)
    entered = [asyncio.Event(), asyncio.Event()]
    releases = [asyncio.Event(), asyncio.Event()]
    calls = active = peak = 0
    class Provider:
        def __init__(self, *_args, **_kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): pass
        async def search_by_formula(self, *_args, **_kwargs):
            nonlocal calls, active, peak
            index = calls
            calls += 1
            active += 1
            peak = max(peak, active)
            try:
                if index < 2:
                    entered[index].set()
                    await releases[index].wait()
                return []
            finally:
                active -= 1
    monkeypatch.setattr(references, "MaterialsProjectClient", Provider)
    tasks = []
    try:
        tasks.append(asyncio.create_task(references.fetch_external_references("NbN", api_key="synthetic")))
        await asyncio.wait_for(entered[0].wait(), 1)
        slot = next(iter(references._locks.values()))
        tasks.extend(asyncio.create_task(references.fetch_external_references("NbN", api_key="synthetic")) for _ in range(2))
        await asyncio.sleep(0)
        assert slot.users == 3
        tasks[1].cancel()
        with pytest.raises(asyncio.CancelledError):
            await tasks[1]
        assert slot.users == 2
        releases[0].set()
        assert (await tasks[0])["status"] == "no_match"
        await asyncio.wait_for(entered[1].wait(), 1)
        assert list(references._locks.values()) == [slot]
        tasks.append(asyncio.create_task(references.fetch_external_references("NbN", api_key="synthetic")))
        await asyncio.sleep(0)
        assert slot.users == 2 and calls == 2 and peak == 1
        releases[1].set()
        assert all(result["status"] == "no_match" for result in await asyncio.gather(tasks[2], tasks[3]))
        assert calls == 3 and peak == 1 and references._locks == {}
    finally:
        for release in releases:
            release.set()
        for task in tasks:
            if not task.done(): task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["stalled_cache", "recursive_cache", "overflowing_provider"])
async def test_cache_deadline_recursive_json_and_provider_overflow_fail_closed_without_cache_write(monkeypatch, failure):
    class Cache(ReferenceCache):
        async def get(self, _key):
            if failure == "stalled_cache":
                await asyncio.Event().wait()
            if failure == "recursive_cache":
                return "[" * 1200 + "]" * 1200
            return None
    class Provider:
        def __init__(self, *_args, **_kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): pass
        async def search_by_formula(self, *_args, **_kwargs): raise OverflowError("Synthetic provider failure")
    cache = Cache()
    monkeypatch.setattr(references, "get_redis", lambda: cache)
    monkeypatch.setattr(references, "MaterialsProjectClient", Provider)
    original_timeout = asyncio.timeout
    monkeypatch.setattr(references.asyncio, "timeout", lambda seconds: original_timeout(.001) if seconds == 12.0 else original_timeout(seconds))
    result = await asyncio.wait_for(references.fetch_external_references("NbN", api_key="synthetic"), 1)
    assert result["status"] == "unavailable" and result["reason"] == "provider_or_cache_unavailable"
    assert result["candidates"] == [] and cache.values == {"unrelated": "retained cache"}
    assert references._locks == {}
