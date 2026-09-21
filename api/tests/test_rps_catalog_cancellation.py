"""HTTP catalogue cancellation stops future traversal, not live thread cleanup."""
from __future__ import annotations

import asyncio
import threading
from copy import deepcopy

import pytest

from config import get_settings
from routers import discovery_priority as routes
from services.research_priority import digest
from tests.test_research_freeze import db_session as db_session
from tests.test_rps_catalog_delivery import CATALOG, _use_pool, _wait, worker_pool
from tests.test_rps_catalog_delivery import local_releases as local_releases


async def _eight_releases(local_releases):
    directory, payloads = local_releases
    original = next(iter(payloads.values()))
    for index in range(4):
        value = deepcopy(original)
        value["id"] = original["id"] + f"-extra-{index}"
        value["manifest_sha256"] = digest({key: item for key, item in value.items() if key != "manifest_sha256"})
        await local_releases.publish(value)
    get_settings().discovery_rps_approved_releases.update(
        {identifier: value["manifest_sha256"] for identifier, value in payloads.items()})
    get_settings().discovery_rps_approved_public_bundles.update(
        {identifier: value["bundle_sha256"] for identifier, value in local_releases.bundles.items()})
    return directory, payloads


def _track_workers(monkeypatch):
    workers = set()
    original = routes._offload
    async def tracked(function, *args):
        if function is routes._catalog_entry:
            workers.add(asyncio.current_task())
        return await original(function, *args)
    monkeypatch.setattr(routes, "_offload", tracked)
    return workers


async def test_catalog_capacity_503_cancels_siblings_before_traversing_later_releases(client, local_releases, monkeypatch, worker_pool):
    _use_pool(worker_pool, monkeypatch)
    _, payloads = await _eight_releases(local_releases)
    pages_entered, pages_release = threading.Event(), threading.Event()
    catalog_entered, catalog_release, catalog_finished = threading.Event(), threading.Event(), threading.Event()
    lock = threading.Lock()
    page_count = 0
    started, finished = [], []
    original_read, original_entry = routes.read_release, routes._catalog_entry

    def hold_page(*args):
        nonlocal page_count
        result = original_read(*args)
        with lock:
            page_count += 1
            if page_count == 6:
                pages_entered.set()
        assert pages_release.wait(8)
        return result

    def hold_catalog(approval, identifier, expected):
        with lock:
            started.append(identifier)
            if len(started) == 2:
                catalog_entered.set()
        try:
            assert catalog_release.wait(8)
            return original_entry(approval, identifier, expected)
        finally:
            with lock:
                finished.append(identifier)
                if len(finished) == 2:
                    catalog_finished.set()

    monkeypatch.setattr(routes, "read_release", hold_page)
    monkeypatch.setattr(routes, "_catalog_entry", hold_catalog)
    workers = _track_workers(monkeypatch)
    identifier = sorted(payloads)[0]
    pages = [asyncio.create_task(client.get(f"{CATALOG}/{identifier}/assessments")) for _ in range(6)]
    request = None
    try:
        await _wait(pages_entered)
        request = asyncio.create_task(client.get(CATALOG))
        response = await asyncio.wait_for(request, timeout=4)
        assert response.status_code == 503 and response.headers["retry-after"] == "1"
        assert response.headers["cache-control"] == "no-store"
        assert len(workers) == 4 and all(worker.done() for worker in workers)
        if worker_pool[0] == 6:
            # Six held pages occupy every worker. The two admitted catalogue
            # jobs are shielded in the queue after their HTTP readers cancel.
            assert started == []
        else:
            await _wait(catalog_entered)
            assert len(started) == 2
        pages_release.set()
        await _wait(catalog_entered)
        assert len(started) == 2 and not catalog_finished.is_set()
        catalog_release.set()
        await _wait(catalog_finished)
        assert set(started) == set(finished) and len(started) == 2
    finally:
        catalog_release.set()
        pages_release.set()
        if request is not None:
            await asyncio.gather(request, return_exceptions=True)
        await asyncio.gather(*pages, *workers, return_exceptions=True)
    # Thread-owned permits are returned by the actual job, even after its
    # awaiting coroutine has been cancelled. A new complete request can run.
    monkeypatch.setattr(routes, "read_release", original_read)
    monkeypatch.setattr(routes, "_catalog_entry", original_entry)
    assert (await client.get(CATALOG)).status_code == 200


async def test_cancelled_catalog_http_request_ends_all_worker_traversal_but_finishes_submitted_jobs(client, local_releases, monkeypatch, worker_pool):
    _use_pool(worker_pool, monkeypatch)
    await _eight_releases(local_releases)
    entered, release, completed = threading.Event(), threading.Event(), threading.Event()
    lock = threading.Lock()
    started, finished = [], []
    original_entry = routes._catalog_entry

    def hold_catalog(approval, identifier, expected):
        with lock:
            started.append(identifier)
            if len(started) == 4:
                entered.set()
        try:
            assert release.wait(8)
            return original_entry(approval, identifier, expected)
        finally:
            with lock:
                finished.append(identifier)
                if len(finished) == 4:
                    completed.set()

    monkeypatch.setattr(routes, "_catalog_entry", hold_catalog)
    workers = _track_workers(monkeypatch)
    request = asyncio.create_task(client.get(CATALOG))
    try:
        await _wait(entered)
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        assert len(workers) == 4 and all(worker.done() for worker in workers)
        assert len(started) == 4 and not completed.is_set()
        release.set()
        await _wait(completed)
        assert set(started) == set(finished) and len(started) == 4
    finally:
        release.set()
        await asyncio.gather(request, *workers, return_exceptions=True)
    monkeypatch.setattr(routes, "_catalog_entry", original_entry)
    assert (await client.get(CATALOG)).status_code == 200
