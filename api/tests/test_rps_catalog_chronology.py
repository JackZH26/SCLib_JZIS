"""Catalogue newest-first means chronological instants, not ISO text order."""
from __future__ import annotations

from config import get_settings
from services.priority_releases import PriorityRelease
from services.research_priority import canonical_json, digest
from tests.test_rps_catalog_delivery import CATALOG
from tests.test_rps_catalog_delivery import local_releases as local_releases


async def test_actual_catalog_orders_aware_publication_times_without_changing_wire_or_manifest(client, local_releases):
    directory, payloads = local_releases
    older, newer = sorted(payloads)[:2]
    dates = {older: "2026-09-06T00:30:00+02:00", newer: "2026-09-05T23:00:00+00:00"}
    approvals = {}
    for identifier, published in dates.items():
        payload = payloads[identifier]
        # The immutable JSON contract serializes UTC as Z, while catalogue
        # isoformat() preserves an explicit +00:00. Hash canonical input bytes.
        payload["published_at"] = published.replace("+00:00", "Z")
        payload["manifest_sha256"] = digest({key: value for key, value in payload.items() if key != "manifest_sha256"})
        PriorityRelease.model_validate(payload)
        approvals[identifier] = payload["manifest_sha256"]
        (directory / f"{identifier}.json").write_text(canonical_json(payload), encoding="utf-8")
    get_settings().discovery_rps_approved_releases = approvals
    response = await client.get(CATALOG)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "published" and response.json()["unavailable"] == []
    assert [item["id"] for item in response.json()["items"]] == [newer, older]
    for item in response.json()["items"]:
        assert item["published_at"] == dates[item["id"]]
        assert item["manifest_sha256"] == approvals[item["id"]]
