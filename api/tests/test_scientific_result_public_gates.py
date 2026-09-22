"""Real SQL exact-result reviews reaching frozen/public consumers, not fake gates."""

from __future__ import annotations

import re
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from config import get_settings
from services import priority_releases
from services import research_distribution as distribution
from services import research_freeze as freeze
from services import research_publication as publication
from services import scientific_result_effects as effects
from services.research_access import active_grant
from tests.rps_distribution_fixtures import LocalDistributions, release_document
from tests.test_research_freeze import add, approved, seed, state
from tests.test_research_freeze import db_session as _serializable_db_session
from tests.test_research_publication import actors
from tests.test_rps_distribution_http import CATALOG, urls
from tests.test_scientific_adjudication_schema import capture, decision_for, item_for, request_for

db_session = _serializable_db_session


async def shared_source(db, *, forward_source=False):
    people = await actors(db)
    source = await seed(db)
    await db.execute(
        sa.text(
            "UPDATE materials SET formula='TEST',formula_normalized='TEST',family='synthetic',"
            "total_papers=1,needs_review=false WHERE id=:id"
        ),
        {"id": source["material"]},
    )
    await db.execute(
        sa.text("UPDATE works SET publication_status='active' WHERE id=:id"), {"id": source["work"]}
    )
    await db.execute(
        sa.text(
            "UPDATE material_states SET pressure_status='explicit_ambient',pressure_gpa=0 WHERE id=:id"
        ),
        {"id": source["state"]},
    )
    await db.execute(
        sa.text(
            "UPDATE research_events SET event_type='curation',knowledge_origin='Inferred' WHERE id=:id"
        ),
        {"id": source["event"]},
    )
    await db.execute(
        sa.text(
            "UPDATE event_properties SET property_key='phonon_min_frequency',unit='THz' WHERE id=:id"
        ),
        {"id": source["children"]["property"]},
    )
    if forward_source:
        parent = await add(
            db,
            "research_events",
            material_id=source["material"],
            state_id=source["state"],
            event_type="curation",
            knowledge_origin="Inferred",
            record_sha256="b" * 64,
        )
        claim = await add(
            db,
            "material_claims",
            material_id=source["material"],
            paper_id=source["paper"],
            work_id=source["work"],
            source_snapshot_id=source["snapshot"],
            event_id=parent["id"],
            result_key="explicit-synthetic-context",
            interpretation_revision=1,
            source_record_hash=uuid4().hex * 2,
            value_relation="exact",
            value_kelvin=39,
            result_status="observed",
            source_kind="table",
            extractor_version="synthetic/1",
            raw_record={"synthetic": True, "role": "context_only_not_claim_validation"},
        )
        await add(
            db,
            "event_evidence",
            event_id=source["event"],
            input_event_id=parent["id"],
            input_claim_id=claim["id"],
            link_type="context",
            locator={"synthetic": True},
        )
    _, args = await approved(db, source)
    capsule = await freeze.freeze_research_release(db, **args, dry_run=False)
    return {
        "actors": people,
        "source": source,
        "capsule": capsule,
        "capsule_bytes": args["artifact_bytes"],
        "internal_artifacts": {},
        "evidence_source_kind": "curation",
    }


async def decide(db, shared, *, decision="reject"):
    await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
    await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
    await db.execute(sa.text("SET CONSTRAINTS ALL DEFERRED"))
    target = shared["source"]["children"]["property"]
    subject = dict(await add(db, "scientific_result_subjects", **await capture(db, target)))
    # Separate scientific reviewer from all disclosure-role actors.
    reviewers = await actors(db)
    person = {
        "reviewer": reviewers["reviewer"],
        "grant": await active_grant(db, reviewers["reviewer"], role="reviewer"),
    }
    item = await item_for(
        db, subject, profile="recorded-sampled-frequency-fidelity/1.0.0", decision=decision
    )
    request = await request_for(db, person, [item])
    result = await decision_for(db, request, subject, item)
    await db.execute(sa.text("SET CONSTRAINTS sa67_complete IMMEDIATE"))
    return result


@pytest.mark.parametrize("decision", ["reject", "request_clarification"])
async def test_actual_review_blocks_hot_rps_and_304_without_changing_frozen_files(
    client, db_session, tmp_path, monkeypatch, decision
):
    shared = await shared_source(db_session)
    local = LocalDistributions(tmp_path.resolve(), db_session, shared)
    context = await local.publish(release_document())
    settings = get_settings()
    release_id = context["release"]["id"]
    monkeypatch.setattr(settings, "discovery_rps_public_enabled", True)
    monkeypatch.setattr(settings, "discovery_rps_release_dir", str(local.directory))
    monkeypatch.setattr(
        settings,
        "discovery_rps_approved_releases",
        {release_id: context["release"]["manifest_sha256"]},
    )
    monkeypatch.setattr(
        settings,
        "discovery_rps_approved_public_bundles",
        {release_id: context["bundle"]["bundle_sha256"]},
    )
    bodies = {path.name: path.read_bytes() for path in local.directory.iterdir()}
    frozen = deepcopy(shared["capsule"]["manifest"])
    priority_releases.clear_release_cache()
    try:
        paths = [CATALOG, *urls(context)]
        cached = {path: await client.get(path) for path in paths}
        assert all(response.status_code == 200 for response in cached.values())
        assert any(
            row["table"] == "event_properties"
            for row in context["registration"]["inventory"]["dependencies"]
        )
        await decide(db_session, shared, decision=decision)
        await db_session.commit()
        for path, previous in cached.items():
            response = await client.get(path, headers={"If-None-Match": previous.headers["etag"]})
            if path == CATALOG:
                assert response.status_code == 200 and response.json()["items"] == []
            else:
                assert response.status_code == 404
                assert response.headers["cache-control"] == "no-store"
        assert {path.name: path.read_bytes() for path in local.directory.iterdir()} == bodies
        stored = await freeze._stored(
            db_session, "research_releases", shared["capsule"]["release_id"]
        )
        assert stored["manifest"] == frozen
    finally:
        priority_releases.clear_release_cache()


async def test_unrelated_package_remains_available_after_exact_property_rejection(db_session):
    from tests.rps_distribution_fixtures import publish_distribution

    first, second = await shared_source(db_session), await shared_source(db_session)
    a = await publish_distribution(db_session, release_document(), shared=first)
    b = await publish_distribution(db_session, release_document(), shared=second)
    await decide(db_session, first)
    before = await state(db_session)
    with pytest.raises(
        distribution.ResearchDistributionError, match="distribution_exact_scientific_review_hold"
    ):
        await distribution.admitted_distribution(db_session, a["registration"]["package_id"])
    admitted = await distribution.admitted_distribution(db_session, b["registration"]["package_id"])
    assert admitted["package_id"] == b["registration"]["package_id"]
    assert await state(db_session) == before


async def test_changed_positive_effect_receipt_is_rechecked_after_async_work(db_session, tmp_path):
    shared = await shared_source(db_session)
    local = LocalDistributions(tmp_path.resolve(), db_session, shared)
    context = await local.publish(release_document())
    pins = [
        {
            "release_id": context["release"]["id"],
            "release_sha256": context["release"]["manifest_sha256"],
            "bundle_sha256": context["bundle"]["bundle_sha256"],
        }
    ]
    before = await distribution.prepare_rps_distribution_access(pins=pins, purpose="page")
    assert before.admitted_release_ids == (context["release"]["id"],)
    await decide(db_session, shared, decision="accept")
    await db_session.commit()
    current = await distribution.prepare_rps_distribution_access(pins=pins, purpose="page")
    assert current.admitted_release_ids == before.admitted_release_ids
    assert current.revision_sha256 != before.revision_sha256
    with pytest.raises(distribution.DistributionAdmissionChanged):
        await distribution.recheck_rps_distribution_access(before)


@pytest.mark.parametrize("change", ["reviewer_revocation", "work_retraction"])
async def test_positive_fidelity_does_not_bypass_live_role_or_source_holds(
    client, db_session, tmp_path, monkeypatch, change
):
    shared = await shared_source(db_session, forward_source=change == "work_retraction")
    local = LocalDistributions(tmp_path.resolve(), db_session, shared)
    context = await local.publish(release_document())
    decision = await decide(db_session, shared, decision="accept")
    accepted = await effects.resolve_result_status(
        db_session, shared["source"]["children"]["property"]
    )
    assert accepted["scopes"][0]["effective_status"] == "accepted"
    await db_session.commit()
    settings = get_settings()
    release_id = context["release"]["id"]
    monkeypatch.setattr(settings, "discovery_rps_public_enabled", True)
    monkeypatch.setattr(settings, "discovery_rps_release_dir", str(local.directory))
    monkeypatch.setattr(
        settings,
        "discovery_rps_approved_releases",
        {release_id: context["release"]["manifest_sha256"]},
    )
    monkeypatch.setattr(
        settings,
        "discovery_rps_approved_public_bundles",
        {release_id: context["bundle"]["bundle_sha256"]},
    )
    priority_releases.clear_release_cache()
    try:
        url = urls(context)[0]
        warm = await client.get(url)
        assert warm.status_code == 200
        if change == "reviewer_revocation":
            await publication.revoke_role(
                db_session,
                actor_user_id=shared["actors"]["admin"],
                grant_id=decision["actor_grant_id"],
                reason_code="synthetic_review_revoked",
                dry_run=False,
            )
            expected = "reviewer_unavailable"
        else:
            await db_session.execute(
                sa.text("UPDATE works SET publication_status='retracted' WHERE id=:id"),
                {"id": shared["source"]["work"]},
            )
            expected = "source_held"
        await db_session.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
        await db_session.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
        current = await effects.resolve_result_status(
            db_session, shared["source"]["children"]["property"]
        )
        assert current["subject_sha256"] == accepted["subject_sha256"]
        assert current["scopes"][0]["effective_status"] == expected
        await db_session.commit()
        withheld = await client.get(url, headers={"If-None-Match": warm.headers["etag"]})
        assert withheld.status_code == 404 and withheld.headers["cache-control"] == "no-store"
    finally:
        priority_releases.clear_release_cache()


async def metadata_publication(db_session, shared):
    release, people = shared["capsule"], shared["actors"]
    for row in release["manifest"]["rows"]:
        await publication.decide_permission(
            db_session,
            actor_user_id=people["reviewer"],
            release_id=release["release_id"],
            table_name=row["table"],
            row_id=row["row_id"],
            row_sha256=row["row_sha256"],
            decision="allow",
            license_code="permission-on-file",
            basis_code="synthetic_metadata",
            reason_code="synthetic_disclosure",
            dry_run=False,
        )
    proposal = await publication.propose_publication(
        db_session,
        actor_user_id=people["curator"],
        release_id=release["release_id"],
        expected_capsule_sha256=release["manifest_sha256"],
        artifact_bytes=shared["capsule_bytes"],
        dry_run=False,
    )
    review = await publication.review_publication(
        db_session,
        actor_user_id=people["reviewer"],
        proposal_id=proposal["id"],
        expected_payload_sha256=proposal["payload_sha256"],
        disclosure_approved=True,
        reason_code="synthetic_review",
        dry_run=False,
    )
    await publication.publication_action(
        db_session,
        actor_user_id=people["publisher"],
        proposal_id=proposal["id"],
        review_id=review["id"],
        expected_payload_sha256=proposal["payload_sha256"],
        kind="publish",
        reason_code="synthetic_publish",
        dry_run=False,
    )
    return proposal


async def test_metadata_publication_exact_property_hold_preserves_original_payload(db_session):
    shared = await shared_source(db_session)
    proposal = await metadata_publication(db_session, shared)
    assert (await publication.admitted_publication(db_session, proposal["id"]))[
        "public_payload"
    ] == proposal["public_payload"]
    await decide(db_session, shared)
    with pytest.raises(publication.PublicationUnavailable, match="scientific result"):
        await publication.admitted_publication(db_session, proposal["id"])
    stored = await publication._get(
        db_session, "research_publication_proposals", UUID(proposal["id"])
    )
    assert stored["public_payload"] == proposal["public_payload"]


async def test_metadata_http_status_failure_is_sanitized_503_not_unreviewed_or_hidden(
    client, db_session, monkeypatch
):
    from unittest.mock import AsyncMock

    from services.scientific_result_subject import ScientificSubjectUnavailable

    shared = await shared_source(db_session)
    proposal = await metadata_publication(db_session, shared)
    await decide(db_session, shared, decision="accept")
    await db_session.commit()
    monkeypatch.setattr(get_settings(), "ml_foundation_public_enabled", True)
    paths = [
        "/v1/ml/releases",
        f"/v1/ml/releases/{proposal['id']}",
        f"/v1/ml/releases/{proposal['id']}/manifest",
        f"/v1/ml/releases/{proposal['id']}/download",
    ]
    for path in paths:
        assert (await client.get(path)).status_code == 200
    before = await state(db_session)
    monkeypatch.setattr(
        effects,
        "capture_result_subject",
        AsyncMock(side_effect=ScientificSubjectUnavailable("PRIVATE_SOURCE_SQL_FAILURE")),
    )
    for path in paths:
        response = await client.get(path)
        assert response.status_code == 503
        error = response.json()
        assert set(error) == {"detail", "error_code", "request_id"}
        assert error["detail"] == "Publication registry unavailable"
        assert error["error_code"] == "service_unavailable"
        assert re.fullmatch(r"[0-9a-f]{32}", error["request_id"])
        assert response.headers["cache-control"] == "private, no-store"
        assert "PRIVATE_SOURCE_SQL_FAILURE" not in response.text
    assert await state(db_session) == before
