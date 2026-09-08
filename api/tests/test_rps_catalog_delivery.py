"""Actual HTTP RPS catalog delivery using approved synthetic local files only."""
from __future__ import annotations

import asyncio
import threading

import pytest

from config import get_settings
from routers import discovery_priority as routes
from services import priority_public_bundle, priority_release_cache, priority_releases
from services.research_priority import canonical_json, digest
from tests.test_research_priority import release_payload

CATALOG = "/v1/discovery/rps/releases"
CANARY = "PRIVATE-CANARY-private-reviewer-path-or-source-text"


@pytest.fixture
def local_releases(tmp_path, monkeypatch):
    directory = tmp_path.resolve()
    payloads = {}
    for index in range(4):
        payload = release_payload()
        payload["id"] = f"synthetic-catalog-{index}"
        payload["manifest_sha256"] = digest({key: value for key, value in payload.items() if key != "manifest_sha256"})
        (directory / (payload["id"] + ".json")).write_text(canonical_json(payload), encoding="utf-8")
        payloads[payload["id"]] = payload
    settings = get_settings()
    monkeypatch.setattr(settings, "discovery_rps_public_enabled", True)
    monkeypatch.setattr(settings, "discovery_rps_release_dir", str(directory))
    monkeypatch.setattr(settings, "discovery_rps_approved_releases",
        {key: value["manifest_sha256"] for key, value in payloads.items()})
    monkeypatch.setattr(settings, "discovery_rps_approved_public_bundles", {})
    priority_releases.clear_release_cache()
    yield directory, payloads
    priority_releases.clear_release_cache()


def _page(identifier):
    return CATALOG + "/" + identifier + "/assessments"


def _not_stale_cache(response):
    policy = response.headers.get("cache-control", "")
    assert "no-store" in policy or ("max-age=0" in policy and "must-revalidate" in policy)


def _sanitized(response, directory):
    assert CANARY not in response.text and str(directory) not in response.text
    assert "Traceback" not in response.text
    _not_stale_cache(response)


async def test_four_real_assessed_releases_warm_catalog_without_full_reverification(client, local_releases, monkeypatch):
    _, payloads = local_releases
    computations = []
    original = priority_releases.evaluate

    def counted(*args, **kwargs):
        computations.append(threading.get_ident())
        return original(*args, **kwargs)

    monkeypatch.setattr(priority_releases, "evaluate", counted)
    first = await client.get(CATALOG)
    assert first.status_code == 200, first.text
    catalog = first.json()
    assert catalog["schema_version"] == "rps-catalog/1.3" and catalog["status"] == "published"
    assert {row["id"] for row in catalog["items"]} == set(payloads)
    assert all(row["total"] == 1 for row in catalog["items"])
    assert catalog["unavailable"] == []
    assert catalog["catalog_revision"] == first.headers["x-data-version"]
    cold = priority_releases.release_cache_stats()
    assert cold["verifications"] == 4 and computations
    assert threading.get_ident() not in computations, "Full scientific recomputation ran on the async request loop"
    counts = len(computations)
    for _ in range(3):
        response = await client.get(CATALOG)
        assert response.status_code == 200 and response.json() == catalog
        assert response.headers["etag"] == first.headers["etag"]
        _not_stale_cache(response)
    cached = await client.get(CATALOG, headers={"If-None-Match": first.headers["etag"]})
    assert cached.status_code == 304
    assert cached.headers["x-data-version"] == catalog["catalog_revision"]
    assert priority_releases.release_cache_stats()["verifications"] == 4
    assert len(computations) == counts
    assert priority_releases.release_cache_stats()["entries"] == 4


@pytest.mark.parametrize("bad_kind", ["missing", "corrupt", "wrong_pin"])
async def test_catalog_isolates_one_bad_release_and_direct_read_stays_closed(client, local_releases, bad_kind):
    directory, payloads = local_releases
    approved = get_settings().discovery_rps_approved_releases
    bad = sorted(payloads)[-1]
    del approved[sorted(payloads)[-2]]  # exactly two valid and one invalid approved release
    path = directory / (bad + ".json")
    if bad_kind == "missing":
        path.unlink()
    elif bad_kind == "corrupt":
        path.write_text('{"private":"' + CANARY + '"}', encoding="utf-8")
    else:
        approved[bad] = "0" * 64
    response = await client.get(CATALOG)
    assert response.status_code == 200, response.text
    catalog = response.json()
    assert catalog["status"] == "degraded" and len(catalog["items"]) == 2
    assert catalog["unavailable"] == [{"id": bad, "status": "unavailable", "reason_code": "verification_failed"}]
    assert bad not in {row["id"] for row in catalog["items"]}
    _sanitized(response, directory)
    direct = await client.get(_page(bad), headers={"If-None-Match": "*"})
    assert direct.status_code == 503
    _sanitized(direct, directory)


async def test_all_bad_is_unavailable_not_an_empty_published_catalog(client, local_releases):
    directory, payloads = local_releases
    for identifier in payloads:
        (directory / (identifier + ".json")).write_text("{}", encoding="utf-8")
    response = await client.get(CATALOG)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "unavailable" and response.json()["items"] == []
    assert len(response.json()["unavailable"]) == 4
    _sanitized(response, directory)


@pytest.mark.parametrize("change", ["revocation", "changed_file", "changed_pin", "disabled"])
async def test_old_catalog_etag_cannot_mask_approval_or_file_changes(client, local_releases, change):
    directory, payloads = local_releases
    initial = await client.get(CATALOG)
    assert initial.status_code == 200
    identifier = sorted(payloads)[0]
    settings = get_settings()
    if change == "revocation":
        settings.discovery_rps_approved_releases.pop(identifier)
    elif change == "changed_file":
        (directory / (identifier + ".json")).write_text("{}", encoding="utf-8")
    elif change == "changed_pin":
        settings.discovery_rps_approved_releases[identifier] = "0" * 64
    else:
        settings.discovery_rps_public_enabled = False
    response = await client.get(CATALOG, headers={"If-None-Match": initial.headers["etag"],
        "If-Modified-Since": "Wed, 01 Jan 2099 00:00:00 GMT"})
    assert response.status_code == 200, response.text
    assert response.headers["etag"] != initial.headers["etag"]
    assert response.headers["x-data-version"] != initial.headers["x-data-version"]
    assert response.json()["catalog_revision"] == response.headers["x-data-version"]
    assert identifier not in {row["id"] for row in response.json()["items"]}
    _sanitized(response, directory)


@pytest.mark.parametrize("change", ["revocation", "changed_file", "changed_pin", "disabled"])
async def test_direct_warm_etag_cannot_bypass_current_publication(client, local_releases, change):
    directory, payloads = local_releases
    identifier = sorted(payloads)[0]
    initial = await client.get(_page(identifier))
    assert initial.status_code == 200
    settings = get_settings()
    if change == "revocation":
        settings.discovery_rps_approved_releases.pop(identifier)
    elif change == "changed_file":
        (directory / (identifier + ".json")).write_text("{}", encoding="utf-8")
    elif change == "changed_pin":
        settings.discovery_rps_approved_releases[identifier] = "0" * 64
    else:
        settings.discovery_rps_public_enabled = False
    response = await client.get(_page(identifier), headers={"If-None-Match": initial.headers["etag"]})
    assert response.status_code == (404 if change in {"revocation", "disabled"} else 503)
    _sanitized(response, directory)


async def test_concurrent_same_key_http_reads_share_one_actual_verification(client, local_releases, monkeypatch):
    _, payloads = local_releases
    identifier = sorted(payloads)[0]
    entered, proceed = threading.Event(), threading.Event()
    calls = []
    original = priority_releases.PriorityRelease.model_validate

    def blocked(*args, **kwargs):
        calls.append(threading.get_ident())
        entered.set()
        assert proceed.wait(5), "Test verification gate was not released"
        return original(*args, **kwargs)

    monkeypatch.setattr(priority_releases.PriorityRelease, "model_validate", staticmethod(blocked))
    tasks = [asyncio.create_task(client.get(_page(identifier))) for _ in range(8)]
    try:
        assert await asyncio.wait_for(asyncio.to_thread(entered.wait, 2), timeout=3)
        # An independent coroutine runs while real verification is blocked;
        # this is a scheduling invariant, not a production timing benchmark.
        await asyncio.sleep(0)
        assert not any(task.done() for task in tasks)
        assert priority_releases.release_cache_stats()["inflight"] == 1
    finally:
        proceed.set()
        responses = await asyncio.gather(*tasks)
    assert len(calls) == 1
    assert all(response.status_code == 200 for response in responses)
    assert len({response.headers["etag"] for response in responses}) == 1
    assert priority_releases.release_cache_stats()["verifications"] == 1


async def test_different_http_keys_verify_at_most_two_at_a_time(client, local_releases, monkeypatch):
    _, payloads = local_releases
    proceed, two_entered = threading.Event(), threading.Event()
    lock = threading.Lock()
    active, maximum = 0, 0
    original = priority_releases.PriorityRelease.model_validate

    def blocked(*args, **kwargs):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(active, maximum)
            if active == 2:
                two_entered.set()
        try:
            assert proceed.wait(5)
            return original(*args, **kwargs)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(priority_releases.PriorityRelease, "model_validate", staticmethod(blocked))
    tasks = [asyncio.create_task(client.get(_page(identifier))) for identifier in payloads]
    try:
        assert await asyncio.wait_for(asyncio.to_thread(two_entered.wait, 2), timeout=3)
        assert priority_releases.release_cache_stats()["inflight"] == 2
    finally:
        proceed.set()
        responses = await asyncio.gather(*tasks)
    assert maximum == 2 and all(response.status_code == 200 for response in responses)
    assert priority_releases.release_cache_stats()["verifications"] == 4


@pytest.mark.parametrize("change", ["revocation", "changed_pin", "disabled"])
async def test_direct_approval_changed_during_worker_read_withholds_completed_object(client, local_releases, monkeypatch, change):
    directory, payloads = local_releases
    identifier = sorted(payloads)[0]
    entered, proceed = threading.Event(), threading.Event()
    original = routes.read_release

    def blocked(*args, **kwargs):
        value = original(*args, **kwargs)
        entered.set()
        assert proceed.wait(5)
        return value

    monkeypatch.setattr(routes, "read_release", blocked)
    task = asyncio.create_task(client.get(_page(identifier), headers={"If-None-Match": "*"}))
    try:
        assert await asyncio.wait_for(asyncio.to_thread(entered.wait, 2), timeout=3)
        settings = get_settings()
        if change == "revocation":
            settings.discovery_rps_approved_releases.pop(identifier)
        elif change == "changed_pin":
            settings.discovery_rps_approved_releases[identifier] = "0" * 64
        else:
            settings.discovery_rps_public_enabled = False
    finally:
        proceed.set()
        response = await task
    assert response.status_code in {404, 503} and response.status_code != 304
    _sanitized(response, directory)


async def test_changed_bytes_during_real_model_validation_cannot_publish_old_verified_rows(client, local_releases, monkeypatch):
    directory, payloads = local_releases
    identifier = sorted(payloads)[0]
    original = priority_releases.PriorityRelease.model_validate

    def changed(*args, **kwargs):
        release = original(*args, **kwargs)
        (directory / (identifier + ".json")).write_text("{}", encoding="utf-8")
        return release

    monkeypatch.setattr(priority_releases.PriorityRelease, "model_validate", staticmethod(changed))
    response = await client.get(_page(identifier), headers={"If-None-Match": "*"})
    assert response.status_code == 503
    _sanitized(response, directory)


async def test_negative_cache_is_bounded_and_changed_valid_file_retries_immediately(client, local_releases, monkeypatch):
    directory, payloads = local_releases
    identifier = sorted(payloads)[0]
    path = directory / (identifier + ".json")
    path.write_text("{}", encoding="utf-8")
    clock = [100.0]
    monkeypatch.setattr(priority_release_cache, "time", type("Clock", (), {"monotonic": staticmethod(lambda: clock[0])}))
    first = await client.get(_page(identifier))
    assert first.status_code == 503
    before = priority_releases.release_cache_stats()
    second = await client.get(_page(identifier))
    assert second.status_code == 503
    assert priority_releases.release_cache_stats()["verifications"] == before["verifications"]
    assert priority_releases.release_cache_stats()["negative_hits"] == 1
    clock[0] += 2
    assert (await client.get(_page(identifier))).status_code == 503
    assert priority_releases.release_cache_stats()["verifications"] == before["verifications"] + 1
    path.write_text(canonical_json(payloads[identifier]), encoding="utf-8")
    repaired = await client.get(_page(identifier))
    assert repaired.status_code == 200, repaired.text


async def test_cache_returned_release_copy_cannot_poison_later_http_projection(client, local_releases):
    directory, payloads = local_releases
    identifier = sorted(payloads)[0]
    release = await asyncio.to_thread(priority_releases.read_release, directory, identifier,
        payloads[identifier]["manifest_sha256"])
    rows = release.rows()
    rows[0]["result"]["score_display"] = -123
    release.assessments.clear()
    response = await client.get(_page(identifier))
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1 and response.json()["items"][0]["result"]["score_display"] == 7100


async def test_cache_entry_and_byte_limits_are_reported_and_enforced(client, local_releases, monkeypatch):
    directory, payloads = local_releases
    monkeypatch.setattr(priority_release_cache, "MAX_ENTRIES", 2)
    for identifier in payloads:
        assert (await client.get(_page(identifier))).status_code == 200
    assert priority_releases.release_cache_stats()["entries"] <= 2
    priority_releases.clear_release_cache()
    monkeypatch.setattr(priority_release_cache, "MAX_CACHED_BYTES", 64)
    identifier = sorted(payloads)[0]
    assert (await client.get(_page(identifier))).status_code == 200
    assert priority_releases.release_cache_stats()["entries"] == 0
    assert priority_releases.release_cache_stats()["cached_bytes"] <= 64
    assert (await client.get(_page(identifier))).status_code == 200
    assert priority_releases.release_cache_stats()["verifications"] == 2


async def test_catalog_approval_change_restarts_complete_snapshot_instead_of_publishing_mixed_membership(client, local_releases, monkeypatch):
    _, payloads = local_releases
    identifier = sorted(payloads)[0]
    original = routes._catalog_entry
    rounds = []
    lock = threading.Lock()

    def revoke_after_read(approval, key, expected):
        result = original(approval, key, expected)
        with lock:
            rounds.append(approval.sha256)
            if key == identifier:
                get_settings().discovery_rps_approved_releases.pop(identifier, None)
        return result

    monkeypatch.setattr(routes, "_catalog_entry", revoke_after_read)
    response = await client.get(CATALOG)
    assert response.status_code == 200, response.text
    catalog = response.json()
    assert catalog["status"] == "published" and len(catalog["items"]) == 3
    assert identifier not in {row["id"] for row in catalog["items"]}
    assert len(set(rounds)) == 2
    assert catalog["approval_sha256"] == routes._approval().sha256


async def test_repeated_catalog_approval_drift_has_one_retry_then_sanitized_503_not_stale_304(client, local_releases, monkeypatch):
    directory, payloads = local_releases
    baseline = await client.get(CATALOG)
    assert baseline.status_code == 200
    identifier = sorted(payloads)[0]
    good = payloads[identifier]["manifest_sha256"]
    original = routes._catalog_entry
    changed = []

    def change_each_snapshot(approval, key, expected):
        result = original(approval, key, expected)
        if key == identifier:
            settings = get_settings()
            settings.discovery_rps_approved_releases[key] = "0" * 64 if expected == good else good
            changed.append(approval.sha256)
        return result

    monkeypatch.setattr(routes, "_catalog_entry", change_each_snapshot)
    response = await client.get(CATALOG, headers={"If-None-Match": baseline.headers["etag"]})
    assert response.status_code == 503 and len(changed) == 2
    _sanitized(response, directory)


async def test_catalog_file_replacement_after_entry_read_cannot_publish_stale_validity(client, local_releases, monkeypatch):
    directory, payloads = local_releases
    baseline = await client.get(CATALOG)
    identifier = sorted(payloads)[0]
    original = routes._catalog_entry
    replaced = []

    def changed_after_read(approval, key, expected):
        result = original(approval, key, expected)
        if key == identifier and not replaced:
            (directory / (identifier + ".json")).write_text("{}", encoding="utf-8")
            replaced.append(key)
        return result

    monkeypatch.setattr(routes, "_catalog_entry", changed_after_read)
    response = await client.get(CATALOG, headers={"If-None-Match": baseline.headers["etag"]})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "degraded"
    assert response.json()["unavailable"] == [{"id": identifier, "status": "unavailable", "reason_code": "verification_failed"}]
    assert response.headers["etag"] != baseline.headers["etag"]


def _public_files(local_releases):
    from tests.test_priority_public_bundle import disclosure_for, public_release_payload

    directory, payloads = local_releases
    bundles = {}
    for identifier in payloads:
        release = public_release_payload()
        release["id"] = identifier
        release["manifest_sha256"] = digest({key: value for key, value in release.items() if key != "manifest_sha256"})
        bundle = priority_public_bundle.build_public_bundle(release, disclosure=disclosure_for(release))
        (directory / (identifier + ".json")).write_text(canonical_json(release), encoding="utf-8")
        (directory / (identifier + ".public.json")).write_text(canonical_json(bundle), encoding="utf-8")
        payloads[identifier] = release
        bundles[identifier] = bundle
    settings = get_settings()
    settings.discovery_rps_approved_releases = {key: value["manifest_sha256"] for key, value in payloads.items()}
    settings.discovery_rps_approved_public_bundles = {key: value["bundle_sha256"] for key, value in bundles.items()}
    priority_releases.clear_release_cache()
    return bundles


def _download(identifier, release, bundle):
    return (CATALOG + "/" + identifier + "/bundle?manifest_sha256=" + release["manifest_sha256"]
            + "&bundle_sha256=" + bundle["bundle_sha256"])


async def test_four_complete_public_bundles_share_warmed_cache_and_pinned_http_identities(client, local_releases):
    directory, payloads = local_releases
    bundles = _public_files(local_releases)
    first = await client.get(CATALOG)
    assert first.status_code == 200 and first.json()["status"] == "published"
    assert all(row["public_bundle"]["status"] == "available" for row in first.json()["items"])
    stats = priority_releases.release_cache_stats()
    assert stats["verifications"] == stats["entries"] == 8
    assert stats["cached_bytes"] >= sum((directory / (key + ".public.json")).stat().st_size for key in payloads)
    for _ in range(2):
        assert (await client.get(CATALOG)).json() == first.json()
        for identifier, release in payloads.items():
            response = await client.get(_download(identifier, release, bundles[identifier]))
            assert response.status_code == 200, response.text
            assert response.content == canonical_json(bundles[identifier]).encode("utf-8")
            assert response.headers["x-data-version"] == release["manifest_sha256"]
            assert response.headers["x-rps-bundle-sha256"] == bundles[identifier]["bundle_sha256"]
            assert response.headers["x-content-type-options"] == "nosniff"
            _not_stale_cache(response)
            cached = await client.get(_download(identifier, release, bundles[identifier]),
                headers={"If-None-Match": response.headers["etag"]})
            assert cached.status_code == 304
    assert priority_releases.release_cache_stats()["verifications"] == 8


async def test_nested_restricted_canary_cannot_appear_in_public_bundle_or_catalog(client, local_releases):
    directory, payloads = local_releases
    bundles = _public_files(local_releases)
    identifier = sorted(payloads)[0]
    bundle = bundles[identifier]
    bundle["disclosure"]["private_notes"] = {"raw_source": CANARY}
    bundle["bundle_sha256"] = priority_public_bundle.bundle_sha256(bundle)
    get_settings().discovery_rps_approved_public_bundles[identifier] = bundle["bundle_sha256"]
    (directory / (identifier + ".public.json")).write_text(canonical_json(bundle), encoding="utf-8")
    response = await client.get(CATALOG)
    assert response.status_code == 200 and response.json()["status"] == "degraded"
    row = next(item for item in response.json()["items"] if item["id"] == identifier)
    assert row["public_bundle"] == {"status": "unavailable", "sha256": None, "verifier_version": None}
    assert response.json()["unavailable"] == []  # original release remains verified
    _sanitized(response, directory)
    direct = await client.get(_download(identifier, payloads[identifier], bundle))
    assert direct.status_code == 503
    _sanitized(direct, directory)


@pytest.mark.parametrize("change", ["revoke_bundle", "revoke_release", "bundle_pin", "release_pin", "file"])
async def test_bundle_download_old_etag_cannot_bypass_either_pin_or_file_state(client, local_releases, change):
    directory, payloads = local_releases
    bundles = _public_files(local_releases)
    identifier = sorted(payloads)[0]
    url = _download(identifier, payloads[identifier], bundles[identifier])
    initial = await client.get(url)
    assert initial.status_code == 200
    settings = get_settings()
    if change == "revoke_bundle":
        settings.discovery_rps_approved_public_bundles.pop(identifier)
    elif change == "revoke_release":
        settings.discovery_rps_approved_releases.pop(identifier)
    elif change == "bundle_pin":
        settings.discovery_rps_approved_public_bundles[identifier] = "0" * 64
    elif change == "release_pin":
        settings.discovery_rps_approved_releases[identifier] = "0" * 64
    else:
        (directory / (identifier + ".public.json")).write_text("{}", encoding="utf-8")
    response = await client.get(url, headers={"If-None-Match": initial.headers["etag"]})
    expected = 404 if change.startswith("revoke") else 503 if change == "file" else 409
    assert response.status_code == expected
    _sanitized(response, directory)


@pytest.mark.parametrize("change", ["revoke_bundle", "bundle_pin", "file"])
async def test_bundle_approval_or_bytes_changed_during_read_withholds_download_and_304(client, local_releases, monkeypatch, change):
    directory, payloads = local_releases
    bundles = _public_files(local_releases)
    identifier = sorted(payloads)[0]
    entered, proceed = threading.Event(), threading.Event()
    original = priority_public_bundle.read_public_bundle

    def blocked(*args, **kwargs):
        receipt = original(*args, **kwargs)
        entered.set()
        assert proceed.wait(5)
        return receipt

    monkeypatch.setattr(priority_public_bundle, "read_public_bundle", blocked)
    task = asyncio.create_task(client.get(_download(identifier, payloads[identifier], bundles[identifier]),
        headers={"If-None-Match": "*"}))
    try:
        assert await asyncio.wait_for(asyncio.to_thread(entered.wait, 2), timeout=3)
        if change == "revoke_bundle":
            get_settings().discovery_rps_approved_public_bundles.pop(identifier)
        elif change == "bundle_pin":
            get_settings().discovery_rps_approved_public_bundles[identifier] = "0" * 64
        else:
            (directory / (identifier + ".public.json")).write_text("{}", encoding="utf-8")
    finally:
        proceed.set()
        response = await task
    assert response.status_code == {"revoke_bundle": 404, "bundle_pin": 409, "file": 503}[change]
    _sanitized(response, directory)


async def test_public_bundle_detached_document_does_not_poison_cached_download(client, local_releases):
    directory, payloads = local_releases
    bundles = _public_files(local_releases)
    identifier = sorted(payloads)[0]
    receipt = await asyncio.to_thread(priority_public_bundle.read_public_bundle, directory, identifier,
        bundles[identifier]["bundle_sha256"], expected_release_sha256=payloads[identifier]["manifest_sha256"])
    document = receipt.document
    document["rows"][0]["result"]["score_display"] = -123
    document["release"]["artifacts"].clear()
    response = await client.get(_download(identifier, payloads[identifier], bundles[identifier]))
    assert response.status_code == 200
    assert response.json()["rows"][0]["result"]["score_display"] == 7100
    assert response.json()["release"]["artifacts"]


async def test_bundle_pin_change_alone_changes_catalog_revision(client, local_releases):
    directory, payloads = local_releases
    _public_files(local_releases)
    initial = await client.get(CATALOG)
    identifier = sorted(payloads)[0]
    get_settings().discovery_rps_approved_public_bundles.pop(identifier)
    response = await client.get(CATALOG, headers={"If-None-Match": initial.headers["etag"]})
    assert response.status_code == 200
    assert response.headers["x-data-version"] != initial.headers["x-data-version"]
    assert response.json()["approval_sha256"] != initial.json()["approval_sha256"]
    assert next(row for row in response.json()["items"] if row["id"] == identifier)["public_bundle"]["status"] == "not_published"
    _sanitized(response, directory)


async def test_cancelled_http_reader_keeps_worker_capacity_until_its_real_job_finishes(client, local_releases, monkeypatch):
    directory, payloads = local_releases
    identifier = sorted(payloads)[0]
    entered, proceed, finished = threading.Event(), threading.Event(), threading.Event()
    lock = threading.Lock()
    running, done = 0, 0
    original = routes.read_release

    def blocked(*args, **kwargs):
        nonlocal running, done
        value = original(*args, **kwargs)
        with lock:
            running += 1
            if running == 8:
                entered.set()
        try:
            assert proceed.wait(5)
            return value
        finally:
            with lock:
                done += 1
                if done == 8:
                    finished.set()

    monkeypatch.setattr(routes, "read_release", blocked)
    tasks = [asyncio.create_task(client.get(_page(identifier))) for _ in range(8)]
    try:
        assert await asyncio.wait_for(asyncio.to_thread(entered.wait, 2), timeout=3)
        tasks[0].cancel()
        cancelled = await asyncio.gather(tasks[0], return_exceptions=True)
        assert isinstance(cancelled[0], asyncio.CancelledError)
        overflow = await client.get(_page(identifier))
        assert overflow.status_code == 503 and overflow.headers["retry-after"] == "1"
        _sanitized(overflow, directory)
        assert not finished.is_set()
    finally:
        proceed.set()
        responses = await asyncio.gather(*tasks[1:], return_exceptions=True)
        assert await asyncio.wait_for(asyncio.to_thread(finished.wait, 2), timeout=3)
    assert all(getattr(response, "status_code", None) == 200 for response in responses)
    assert (await client.get(_page(identifier))).status_code == 200


async def test_catalog_submits_at_most_four_parallel_entry_reads(client, local_releases, monkeypatch):
    entered, proceed = threading.Event(), threading.Event()
    lock = threading.Lock()
    active, maximum = 0, 0
    original = routes._catalog_entry

    def blocked(*args, **kwargs):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
            if active == 4:
                entered.set()
        try:
            assert proceed.wait(5)
            return original(*args, **kwargs)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(routes, "_catalog_entry", blocked)
    task = asyncio.create_task(client.get(CATALOG))
    try:
        assert await asyncio.wait_for(asyncio.to_thread(entered.wait, 2), timeout=3)
        assert not task.done()
    finally:
        proceed.set()
        response = await task
    assert maximum == 4 and response.status_code == 200
    assert len(response.json()["items"]) == 4


@pytest.mark.parametrize("kind", ["symlink", "directory", "fifo", "oversize"])
async def test_nonregular_or_oversized_approved_file_fails_closed_without_hanging(client, local_releases, kind):
    import os

    directory, payloads = local_releases
    identifier = sorted(payloads)[0]
    path = directory / (identifier + ".json")
    if kind == "oversize":
        with path.open("wb") as stream:
            stream.truncate(priority_release_cache.MAX_FILE_BYTES + 1)
    else:
        retained = directory / "synthetic-original.json"
        path.rename(retained)
        if kind == "symlink":
            path.symlink_to(retained)
        elif kind == "directory":
            path.mkdir()
        else:
            os.mkfifo(path)
    response = await asyncio.wait_for(client.get(_page(identifier)), timeout=3)
    assert response.status_code == 503
    _sanitized(response, directory)


async def test_capture_synthetic_catalog_and_page_wire_for_cross_stack_rehearsal(client, local_releases, tmp_path):
    _, payloads = local_releases
    _public_files(local_releases)
    catalog = await client.get(CATALOG)
    page = await client.get(_page(sorted(payloads)[0]))
    assert catalog.status_code == page.status_code == 200
    assert all(row["public_bundle"]["status"] == "available" for row in catalog.json()["items"])
    for name, response in (("catalog", catalog), ("page", page)):
        target = tmp_path / ("synthetic-rps-" + name + "-http.json")
        target.write_bytes(response.content)
        print("SYNTHETIC_RPS_WIRE_PATH=" + str(target))
