"""Authenticated native transport of bounded, heavily escaped researcher notes.

Owned reconstructed retained facts exercise byte limits, not source-paper
verification, production subject IDs, or human scientific review.
"""
from copy import deepcopy

import pytest

from services import discovery_feedback_contract as contract
from services.research_release_manifest import canonical
from tests.test_discovery_design_http import private
from tests.test_discovery_feedback import feedback_case, return_request
from tests.test_discovery_feedback_http import PREFIX
from tests.test_discovery_feedback_http import feedback_interface as feedback_interface
from tests.test_research_freeze import db_session as db_session

RECEIPT_BYTES = 512 * 1024
RECORD_PROOF_BYTES = 256 * 1024
PAGE_BYTES = 4 * 1024 * 1024


def escaped_request(ctx):
    """Fill the unchanged request budget with quotes requiring JSON escaping."""
    request = return_request(ctx)
    request["payload"].update(findings='"' * 4000, reason='"' * 2000,
                              unknowns=[str(i) + '"' * 999 for i in range(9)])
    # Distinct unknowns are source-independent researcher notes. Add as many
    # escaped characters as fit; at most one byte of this 32 KiB budget is spare.
    notes = request["payload"]["unknowns"]
    while contract.MAX_BYTES - len(canonical(request)) > 5:
        assert len(notes) < 16
        notes.append(str(len(notes)))
        spare = contract.MAX_BYTES - len(canonical(request))
        assert spare >= 0
        notes[-1] += '"' * min(spare // 2, 1000 - len(notes[-1]))
    assert contract.MAX_BYTES - 1 <= len(canonical(request)) <= contract.MAX_BYTES
    assert contract.validate(request) == request
    return request


def bounded_receipt(response):
    assert response.status_code == 200, response.text
    private(response)
    assert 256 * 1024 < len(response.content) <= RECEIPT_BYTES
    receipt = response.json()
    assert len(receipt["receipt_canonical_json"].encode("utf-8")) <= RECORD_PROOF_BYTES
    assert receipt["scientific_acceptance"] is False
    assert receipt["calculation_executed"] is receipt["experiment_executed"] is False
    assert receipt["physical_association_established"] is False
    assert "DO NOT RETURN SOURCE" not in response.text
    return receipt


@pytest.mark.asyncio
async def test_maximum_escaped_notes_preview_commit_original_get_and_eight_return_history(
        client, db_session, feedback_interface):
    actor, material, _, parent, _ = await feedback_case(db_session)
    await db_session.commit()
    context = await client.get(PREFIX + "/context", headers=actor["headers"], params={
        "design_id": parent["design_id"], "revision_id": parent["receipt_id"],
        "record_sha256": parent["receipt_sha256"], "material_id": material, "record_index": 1})
    assert context.status_code == 200, context.text
    private(context)
    requests, retained = [], {}
    for index in range(contract.MAX_PAGE):
        request = escaped_request(context.json())
        requests.append(deepcopy(request))
        preview = bounded_receipt(await client.post(PREFIX + "/operations/preview", headers=actor["headers"],
                                                    json={"request": request}))
        before = await client.get(PREFIX + "/designs/" + parent["design_id"] + "/returns", headers=actor["headers"])
        assert before.status_code == 200 and before.json()["total"] == index
        private(before)
        saved = bounded_receipt(await client.post(PREFIX + "/operations/commit", headers=actor["headers"],
            json={"request": request, "expected_preview_sha256": preview["preview_sha256"]}))
        assert saved["receipt_sha256"] == preview["receipt_sha256"]
        assert saved["pending_ledger_written"] and not saved["dry_run"]
        recovered = bounded_receipt(await client.get(PREFIX + "/operations/outcome", headers=actor["headers"],
            params={"request_key": request["request_key"], "expected_request_sha256": saved["request_sha256"]}))
        assert recovered["replayed"] and recovered["receipt_sha256"] == saved["receipt_sha256"]
        assert recovered["request_canonical_json"] == canonical(request).decode()
        retained[saved["feedback_id"]] = request
    page = await client.get(PREFIX + "/designs/" + parent["design_id"] + "/returns", headers=actor["headers"],
                            params={"limit": contract.MAX_PAGE})
    assert page.status_code == 200, page.text
    private(page)
    # This legal page exceeded the old shared 2 MiB private-reader ceiling.
    assert 2 * 1024 * 1024 < len(page.content) <= PAGE_BYTES
    data = page.json()
    assert data["total"] == len(data["entries"]) == len(requests) == contract.MAX_PAGE
    assert {entry["id"] for entry in data["entries"]} == set(retained)
    for entry in data["entries"]:
        original = retained[entry["id"]]
        for key in ("findings", "decision", "reason", "unknowns", "evidence", "design"):
            assert entry[key] == original["payload"][key]
        assert entry["receipt"]["request_canonical_json"] == canonical(original).decode()
        assert len(canonical(entry["receipt"])) <= RECEIPT_BYTES
        assert len(entry["receipt"]["receipt_canonical_json"].encode("utf-8")) <= RECORD_PROOF_BYTES
        assert entry["eligibility"]["eligible"] and entry["projection"]["record"]["tc_type"] == "zero_resistance"
        assert entry["projection"]["record"]["hc2_conditions"] == "0 K"
        assert entry["follow_ups"] == [] and entry["physical_association_established"] is False
    assert "DO NOT RETURN SOURCE" not in page.text
