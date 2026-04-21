"""Smoke tests for POST/DELETE/GET /bookmarks.

Phase B added the feature; these pin the three behaviours the
review flagged:

* happy-path create → list includes joined paper fields
* duplicate create → 409 from the unique index
* create against a non-existent target → 404 (atomic INSERT SELECT
  pattern means zero rows returned, no dangling bookmark persisted)
"""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_create_and_list_paper_bookmark(client, registered_user, sample_paper):
    _, jwt = registered_user
    headers = {"Authorization": f"Bearer {jwt}"}

    # Create
    r = await client.post(
        "/v1/bookmarks",
        json={"target_type": "paper", "target_id": sample_paper},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["target_type"] == "paper"
    assert created["target_id"] == sample_paper

    # List — response hydrates paper fields
    r = await client.get("/v1/bookmarks/papers", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    row = body["results"][0]
    assert row["target_id"] == sample_paper
    assert row["title"] == "A Test Paper"
    assert "Alice Test" in row["authors"]


@pytest.mark.asyncio
async def test_duplicate_bookmark_returns_409(client, registered_user, sample_paper):
    _, jwt = registered_user
    headers = {"Authorization": f"Bearer {jwt}"}
    body = {"target_type": "paper", "target_id": sample_paper}

    r1 = await client.post("/v1/bookmarks", json=body, headers=headers)
    assert r1.status_code == 201

    r2 = await client.post("/v1/bookmarks", json=body, headers=headers)
    assert r2.status_code == 409, r2.text


@pytest.mark.asyncio
async def test_bookmark_nonexistent_target_is_404(client, registered_user):
    _, jwt = registered_user
    headers = {"Authorization": f"Bearer {jwt}"}

    r = await client.post(
        "/v1/bookmarks",
        json={"target_type": "paper", "target_id": "arxiv:does-not-exist"},
        headers=headers,
    )
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_bookmark_rejects_unknown_target_type(client, registered_user):
    _, jwt = registered_user
    r = await client.post(
        "/v1/bookmarks",
        json={"target_type": "author", "target_id": "someone"},
        headers={"Authorization": f"Bearer {jwt}"},
    )
    # Pydantic Literal["paper","material"] rejects "author" at 422.
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_delete_bookmark_owner_only(client, registered_user, sample_paper):
    _, jwt = registered_user
    headers = {"Authorization": f"Bearer {jwt}"}

    r = await client.post(
        "/v1/bookmarks",
        json={"target_type": "paper", "target_id": sample_paper},
        headers=headers,
    )
    bm_id = r.json()["id"]

    # Delete with owner's token
    r = await client.delete(f"/v1/bookmarks/{bm_id}", headers=headers)
    assert r.status_code == 200, r.text

    # Second delete should 404 (no such row anymore)
    r = await client.delete(f"/v1/bookmarks/{bm_id}", headers=headers)
    assert r.status_code == 404
