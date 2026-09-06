"""DR03 pure filesystem/route tests. No DB or external service is required.

Safe standalone invocation: PYTHONPATH=api api/.venv/bin/python -m pytest
--noconftest api/tests/test_discovery_feed_validation.py api/tests/test_discovery_cache.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from routers.discovery import (
    DiscoveryFeedStore, _store, discovery_candidate_detail, discovery_candidates,
    discovery_metadata,
)
from services import discovery_feed as cache


def payload(ids=("lead-1",)):
    return {
        "page_title": "Synthetic test feed", "intro": [], "status": "active",
        "updated_at_utc": "2026-09-05T00:00:00Z", "source": "test", "filter_rules": [],
        "candidates": [{
            "candidate_id": candidate_id, "formula": "TEST", "branch": "test",
            "evidence_level": "E1", "checker_status": "pending", "public_confidence": "Legacy lead",
            "record_role": "negative_control" if candidate_id == "control" else "exploratory_candidate",
        } for candidate_id in ids],
    }


def metadata(raw):
    return {"status": raw["status"], "candidate_count": len(raw["candidates"]),
            "sha256": cache.producer_digest(raw), "updated_at_utc": raw["updated_at_utc"], "source": "test"}


def write_pair(directory: Path, raw):
    feed, meta = directory / "download.json", directory / "meta.json"
    feed.write_text(json.dumps(raw), encoding="utf-8")
    meta.write_text(json.dumps(metadata(raw)), encoding="utf-8")
    return feed, meta


def request(etag=None):
    return Request({"type": "http", "method": "GET", "path": "/v1/discovery/metadata",
                    "headers": [(b"if-none-match", etag.encode())] if etag else [], "query_string": b""})


@pytest.mark.parametrize("text", [
    '{"a": NaN}', '{"a": Infinity}', '{"a": -Infinity}', '{"a": 1e999}',
    '{"a": 1, "a": 2}', '{"a": [{"x": 1, "x": 2}]}', '[]',
])
def test_strict_json_rejects_nonfinite_duplicates_and_nonobjects(text):
    with pytest.raises(ValueError):
        cache.strict_json(text)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), True, "75"])
def test_strict_scores_do_not_coerce(value):
    raw = payload()
    raw["candidates"][0]["discovery_score"] = value
    with pytest.raises(ValueError):
        cache.validate_feed(raw)


@pytest.mark.parametrize("ids", [("same", "same"), ("",), ("   ",), (" trailing ",), ("bad/id",), ("bad\\id",)])
def test_candidate_identity_rejects_empty_or_duplicate(ids):
    with pytest.raises(ValueError):
        cache.validate_feed(payload(ids))


def test_required_status_is_not_silently_defaulted():
    raw = payload(("control",))
    del raw["status"]
    with pytest.raises(ValueError):
        cache.validate_feed(raw)


def test_empty_active_feed_cannot_replace_good_data_but_planned_is_explicit():
    raw = payload(())
    with pytest.raises(ValueError):
        cache.validate_feed(raw)
    raw["status"] = "planned"
    assert cache.validate_feed(raw).candidates == []


def test_explicit_legacy_extensions_and_control_semantics():
    raw = payload(("control",))
    raw["candidates"][0].update({"base_discovery_score": 66.8, "condition_badges": ["legacy"],
        "display_class": "lead", "family_gate_stage": "comparator", "legacy_candidate_id": "old-1", "taxonomy_bucket": "control"})
    candidate = cache.validate_feed(raw).candidates[0]
    assert candidate.base_discovery_score == 66.8
    assert candidate.record_role == "negative_control"
    assert "negative_outcome" not in candidate.model_dump()
    raw["candidates"][0]["unregistered_extension"] = 1
    with pytest.raises(ValueError):
        cache.validate_feed(raw)


@pytest.mark.parametrize("key,value", [
    ("candidate_count", 99), ("candidate_count", True), ("sha256", "a" * 64),
    ("status", "planned"), ("updated_at_utc", "2026-09-06T00:00:00Z"), ("source", "other"),
])
def test_matching_metadata_contract(key, value):
    raw = payload()
    meta = metadata(raw)
    meta[key] = value
    with pytest.raises(ValueError):
        cache.validate_feed(raw, meta)


def test_publication_is_one_matched_envelope_and_invalid_update_preserves_it(tmp_path):
    destination = tmp_path / "feed.json"
    feed, meta = write_pair(tmp_path, payload())
    cache.publish_feed(feed, meta, destination)
    before = destination.read_bytes()
    assert cache.read_document(destination).metadata == metadata(payload())
    feed.write_text('{"status": "active"}')
    with pytest.raises(ValueError):
        cache.publish_feed(feed, meta, destination)
    assert destination.read_bytes() == before


def test_interrupted_atomic_promotion_keeps_previous_pair(tmp_path, monkeypatch):
    destination = tmp_path / "feed.json"
    feed, meta = write_pair(tmp_path, payload())
    cache.publish_feed(feed, meta, destination)
    before = destination.read_bytes()
    feed, meta = write_pair(tmp_path, payload(("new",)))
    replace = cache.os.replace

    def interrupted(source, target):
        if target == destination:
            raise OSError("Synthetic interruption before promotion")
        replace(source, target)

    monkeypatch.setattr(cache.os, "replace", interrupted)
    with pytest.raises(OSError):
        cache.publish_feed(feed, meta, destination)
    assert destination.read_bytes() == before
    assert cache.read_document(cache.last_good_path(destination)).feed.candidates[0].candidate_id == "lead-1"


def test_standalone_cli_uses_shared_validation_and_records_failed_attempt(tmp_path):
    script = Path(__file__).resolve().parents[2] / "scripts" / "validate_discovery_feed.py"
    feed, meta = write_pair(tmp_path, payload())
    destination = tmp_path / "feed.json"
    command = [sys.executable, str(script), "--feed", str(feed), "--metadata", str(meta), "--publish", str(destination)]
    valid = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=20)
    assert valid.returncode == 0
    before = destination.read_bytes()
    feed.write_text('{"status": "active", "status": "planned"}')
    invalid = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=20)
    assert invalid.returncode == 1
    assert "last-good cache retained" in invalid.stderr
    assert destination.read_bytes() == before
    assert cache.update_failed_after(destination, cache.read_document(destination).validated_at)


async def test_last_good_survives_invalid_update_and_process_restart(tmp_path):
    path = tmp_path / "feed.json"
    path.write_text(json.dumps(payload(("lead-1", "control"))))
    first, _ = await DiscoveryFeedStore().get(path)
    path.write_text('{"candidates": [')
    recovered, _ = await DiscoveryFeedStore().get(path)
    assert recovered.source_status == "stale"
    assert recovered.data_version == first.data_version
    assert recovered.metadata.last_successful_at == first.metadata.last_successful_at
    assert recovered.metadata.source_error == "invalid_update"
    assert set(recovered.candidates_by_id) == {"lead-1", "control"}
    path.unlink()
    missing, _ = await DiscoveryFeedStore().get(path)
    assert missing.source_status == "stale"
    assert missing.metadata.source_error == "source_missing"


async def test_failed_pull_marker_marks_unchanged_good_feed_stale_until_new_publication(tmp_path):
    path = tmp_path / "feed.json"
    feed, meta = write_pair(tmp_path, payload())
    cache.publish_feed(feed, meta, path)
    store = DiscoveryFeedStore()
    first, _ = await store.get(path)
    before = path.read_bytes()
    cache.record_update_failure(path)
    stale, _ = await store.get(path)
    assert path.read_bytes() == before
    assert stale.source_status == "stale" and stale.data_version == first.data_version
    cache.publish_feed(feed, meta, path)
    recovered, _ = await store.get(path)
    assert recovered.source_status == "ready"


async def test_empty_or_invalid_source_does_not_invent_a_valid_feed(tmp_path, monkeypatch):
    path = tmp_path / "missing.json"
    monkeypatch.setenv("SCLIB_DISCOVERY_FEED_PATH", str(path))
    _store.clear()
    result = json.loads((await discovery_metadata(request(), schema_version="1", identity=None)).body)
    assert result["source_status"] == "missing" and result["total_candidates"] == 0
    with pytest.raises(HTTPException) as error:
        await discovery_candidates(request(), offset=0, limit=24, record_role=None, identity=None)
    assert error.value.status_code == 503
    path.write_text('{"status": "active"}')
    result = json.loads((await discovery_metadata(request(), schema_version="1", identity=None)).body)
    assert result["source_status"] == "invalid"
    _store.clear()


async def test_version_pinned_pages_and_details_reject_mix_and_unpinned_continuations(tmp_path, monkeypatch):
    path = tmp_path / "feed.json"
    path.write_text(json.dumps(payload(("lead-1", "lead-2"))))
    monkeypatch.setenv("SCLIB_DISCOVERY_FEED_PATH", str(path))
    _store.clear()
    version = json.loads((await discovery_metadata(request(), identity=None)).body)["data_version"]
    page = await discovery_candidates(request(), offset=0, limit=1, record_role=None, identity=None, data_version=version)
    assert json.loads(page.body)["data_version"] == page.headers["x-data-version"] == version
    detail = await discovery_candidate_detail(request(), candidate_id="lead-1", identity=None, data_version=version)
    assert json.loads(detail.body)["candidate_id"] == "lead-1"
    assert json.loads(detail.body)["data_version"] == version
    for operation in (
        discovery_candidates(request(), offset=1, limit=1, record_role=None, identity=None),
        discovery_candidate_detail(request(), candidate_id="lead-1", identity=None),
    ):
        with pytest.raises(HTTPException) as error:
            await operation
        assert error.value.status_code == 428
    path.write_text(json.dumps(payload(("new", "lead-1", "lead-2"))))
    for operation in (
        discovery_candidates(request(), offset=1, limit=1, record_role=None, identity=None, data_version=version),
        discovery_candidate_detail(request(), candidate_id="lead-1", identity=None, data_version=version),
    ):
        with pytest.raises(HTTPException) as error:
            await operation
        assert error.value.status_code == 409
        assert error.value.headers["Cache-Control"] == "no-store"
    _store.clear()


async def test_stale_metadata_changes_etag_but_not_data_identity(tmp_path, monkeypatch):
    path = tmp_path / "feed.json"
    path.write_text(json.dumps(payload()))
    monkeypatch.setenv("SCLIB_DISCOVERY_FEED_PATH", str(path))
    _store.clear()
    first = await discovery_metadata(request(), identity=None)
    cache.record_update_failure(path)
    stale = await discovery_metadata(request(first.headers["etag"]), identity=None)
    assert stale.status_code == 200
    assert stale.headers["etag"] != first.headers["etag"]
    assert stale.headers["x-data-version"] == first.headers["x-data-version"]
    assert stale.headers["x-discovery-source-status"] == "stale"
    _store.clear()
