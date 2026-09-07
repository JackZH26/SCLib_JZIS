"""Publication-only anonymous HTTP reads on real guarded research capsules.

Synthetic source rows remain pending. A disclosed metadata inventory is not a
public training dataset, scientific acceptance or permission to fetch sources.
"""
from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from config import get_settings
from routers import research_publications as router
from services import research_freeze as freeze
from services import research_publication as service
from services.research_release_manifest import canonical, digest
from tests.test_research_freeze import add
from tests.test_research_publication import db_session as _serializable_db_session
from tests.test_research_publication import proposed, published, revoke_permission

db_session = _serializable_db_session
pytestmark = pytest.mark.asyncio


def paths(identifier):
    base = f"/v1/ml/releases/{identifier}"
    return (base, base + "/manifest", base + "/download")


def assert_private(response):
    assert response.headers["cache-control"] == "private, no-store"
    assert "etag" not in response.headers
    assert "location" not in response.headers


async def withdraw_capsule(db, context):
    release = context["release"]
    document = freeze.notice_review_payload(
        release_id=release["release_id"], manifest_sha256=release["manifest_sha256"],
        kind="withdrawn", reason_code="synthetic_disclosure_hold",
    )
    encoded = canonical(document)
    review = await add(
        db, "evidence_artifacts", kind="review", schema_version=freeze.NOTICE_REVIEW_VERSION,
        source="synthetic-http-notice", record_sha256=digest(document),
        bytes_sha256=hashlib.sha256(encoded).hexdigest(), hash_status="verified", access="restricted",
        metadata={"release_notice_review": document},
    )
    return await freeze.append_release_notice(
        db, release_id=release["release_id"], kind="withdrawn", reason_code="synthetic_disclosure_hold",
        review_artifact_id=review["id"], review_bytes=encoded, dry_run=False,
    )


async def test_publication_routes_remain_hidden_when_global_switch_is_off(client, monkeypatch):
    monkeypatch.setenv("ML_FOUNDATION_PUBLIC_ENABLED", "false")
    get_settings.cache_clear()
    try:
        for path in ("/v1/ml/releases", *paths(uuid4())):
            response = await client.get(path)
            assert response.status_code == 404
            assert response.json()["detail"] == "Not found"
            assert_private(response)
    finally:
        monkeypatch.setenv("ML_FOUNDATION_PUBLIC_ENABLED", "true")
        get_settings.cache_clear()


async def test_anonymous_detail_manifest_download_share_exact_reviewed_bytes(client, db_session):
    context = await published(db_session)
    await db_session.commit()
    proposal = context["proposal"]
    expected = canonical(proposal["public_payload"])
    for path in paths(proposal["id"]):
        response = await client.get(path, headers={"If-None-Match": "*"})
        assert response.status_code == 200, response.text
        assert response.content == expected
        assert response.headers["x-public-manifest-sha256"] == hashlib.sha256(expected).hexdigest()
        assert response.headers["x-content-type-options"] == "nosniff"
        assert_private(response)
    document = proposal["public_payload"]
    assert document["scope"] == "metadata_only"
    assert document["scientific_acceptance"] is document["ml_training_approved"] is False
    assert sum(row["object_count"] for row in document["counts"]) == len(document["objects"])
    for forbidden in (b"MgB2", b"39 K", b"Synthetic", b"abstract", b"password", b"freeze-paper:",
                      str(context["actors"]["reviewer"]).encode(), str(context["fixture"]["claim"]).encode()):
        assert forbidden not in expected


async def test_draft_and_internal_ids_cannot_bypass_publication_admission(client, db_session):
    context = await proposed(db_session)
    await db_session.commit()
    identifiers = (context["proposal"]["id"], context["release"]["release_id"],
                   context["fixture"]["args"]["dataset_id"], context["permission_ids"][0], uuid4())
    for identifier in identifiers:
        for path in paths(identifier):
            response = await client.get(path)
            assert response.status_code == 404
            assert response.json()["detail"] == "Publication unavailable"
            assert "payload_sha256" not in response.text
            assert_private(response)
    raw_manifest = await client.get(f"/v1/ml/snapshots/{context['fixture']['args']['dataset_id']}/manifest")
    assert raw_manifest.status_code == 401


async def test_public_list_uses_the_same_admission_and_count_as_detail(client, db_session):
    context = await published(db_session)
    draft = await proposed(db_session)
    await db_session.commit()
    before = await client.get("/v1/ml/releases")
    assert before.status_code == 200, before.text
    body = before.json()
    assert body["count"] == len(body["items"])
    entries = {row["id"]: row for row in body["items"]}
    assert context["proposal"]["id"] in entries
    assert draft["proposal"]["id"] not in entries
    assert entries[context["proposal"]["id"]]["object_count"] == len(context["proposal"]["public_payload"]["objects"])
    assert_private(before)
    await revoke_permission(db_session, context)
    await db_session.commit()
    after = await client.get("/v1/ml/releases", headers={"If-None-Match": "*"})
    assert after.status_code == 200
    assert after.json()["count"] == body["count"] - 1
    assert context["proposal"]["id"] not in {row["id"] for row in after.json()["items"]}
    assert after.json()["count"] == len(after.json()["items"])
    assert_private(after)


async def test_unverifiable_retained_capsule_never_breaks_public_collection(client, db_session, monkeypatch):
    context = await published(db_session)
    await db_session.commit()

    async def corrupt(*_args, **_kwargs):
        raise freeze.ResearchFreezeError("Synthetic internal pin mismatch; do not disclose")

    monkeypatch.setattr(service, "_verify_pins", corrupt)
    for path in paths(context["proposal"]["id"]):
        response = await client.get(path)
        assert response.status_code == 404
        assert "Synthetic" not in response.text
        assert_private(response)
    listing = await client.get("/v1/ml/releases")
    assert listing.status_code == 200 and listing.json()["count"] == 0
    assert_private(listing)


@pytest.mark.parametrize("change", ["permission", "reviewer_role", "publisher_role", "actor_inactive", "capsule_notice", "withdrawal"])
async def test_current_holds_block_every_public_alias_without_304_or_cached_body(client, db_session, change):
    context = await published(db_session)
    await db_session.commit()
    proposal = context["proposal"]
    first = await client.get(paths(proposal["id"])[0])
    assert first.status_code == 200
    digest_header = first.headers["x-public-manifest-sha256"]
    if change == "permission":
        await revoke_permission(db_session, context)
    elif change.endswith("_role"):
        await service.revoke_role(
            db_session, actor_user_id=context["actors"]["admin"],
            grant_id=context["actors"]["grants"][change.removesuffix("_role")],
            reason_code="synthetic_http_revocation", dry_run=False,
        )
    elif change == "actor_inactive":
        await db_session.execute(sa.text("UPDATE users SET is_active=false WHERE id=:id"),
                                 {"id": context["actors"]["publisher"]})
    elif change == "capsule_notice":
        await withdraw_capsule(db_session, context)
    else:
        await service.publication_action(
            db_session, actor_user_id=context["actors"]["publisher"], proposal_id=proposal["id"],
            review_id=context["review"]["id"], expected_payload_sha256=proposal["payload_sha256"],
            kind="withdraw", reason_code="synthetic_http_withdrawal", dry_run=False,
        )
    await db_session.commit()
    for path in paths(proposal["id"]):
        response = await client.get(path, headers={"If-None-Match": f'"{digest_header}"'})
        assert response.status_code == 404, response.text
        assert response.json()["detail"] == "Publication unavailable"
        assert "objects" not in response.json()
        assert "x-public-manifest-sha256" not in response.headers
        assert_private(response)
    listing = await client.get("/v1/ml/releases")
    assert listing.status_code == 200
    assert proposal["id"] not in {row["id"] for row in listing.json()["items"]}


async def test_missing_publication_registry_never_discloses_driver_details(client, monkeypatch):
    async def unavailable(*_args):
        raise SQLAlchemyError("PRIVATE-ML07-REGISTRY-DSN")

    monkeypatch.setattr(router, "admitted_publication", unavailable)
    monkeypatch.setattr(router, "public_inventory", unavailable)
    for path in ("/v1/ml/releases", *paths(uuid4())):
        response = await client.get(path)
        assert response.status_code == 503
        assert response.json()["detail"] == "Publication registry unavailable"
        assert "PRIVATE-ML07" not in response.text
        assert_private(response)


async def test_read_session_setup_failure_is_a_private_sanitized_503(client, monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise SQLAlchemyError("PRIVATE-ML07-CONNECTION-DSN")

    monkeypatch.setattr(router, "AsyncSession", unavailable)
    for path in ("/v1/ml/releases", *paths(uuid4())):
        response = await client.get(path)
        assert response.status_code == 503
        assert response.json()["detail"] == "Publication registry unavailable"
        assert "PRIVATE-ML07" not in response.text
        assert_private(response)


@pytest.mark.parametrize("status", ["retracted", "withdrawn", "corrected", "disputed"])
async def test_source_lifecycle_hold_removes_public_access_without_rewriting_frozen_bytes(client, db_session, status):
    context = await published(db_session)
    await db_session.commit()
    proposal = context["proposal"]
    before = await client.get(paths(proposal["id"])[0])
    assert before.status_code == 200
    await db_session.execute(sa.text("UPDATE papers SET status=:status WHERE id=:id"),
                             {"status": status, "id": context["fixture"]["paper"]})
    await db_session.commit()
    for path in paths(proposal["id"]):
        held = await client.get(path, headers={"If-None-Match": before.headers["x-public-manifest-sha256"]})
        assert held.status_code == 404 and "objects" not in held.json()
        assert_private(held)
    inventory = await client.get("/v1/ml/releases")
    assert proposal["id"] not in {item["id"] for item in inventory.json()["items"]}
    release = context["release"]
    historical = await freeze.inspect_research_release(
        db_session, release_id=release["release_id"], expected_manifest_sha256=release["manifest_sha256"],
        artifact_bytes=context["arguments"]["artifact_bytes"],
    )
    assert canonical(historical["manifest"]) == canonical(release["manifest"])
    assert historical["current_eligibility_reassessed"] is False
    # Live hold checks are not a human-authenticated withdrawal notice. No
    # automatic review artifact or scientific judgment is manufactured here.
    notices = await db_session.scalar(sa.text("SELECT count(*) FROM research_release_notices WHERE release_id=:id"),
                                      {"id": release["release_id"]})
    assert notices == 0
