"""Full SQL-backed RPS release access, revocation and conditional responses."""
from __future__ import annotations

import asyncio
import re
import threading

import pytest
import pytest_asyncio
import sqlalchemy as sa

from config import get_settings
from routers import discovery_priority as routes
from services import priority_releases
from tests.rps_distribution_fixtures import (
    LocalDistributions,
    distribution_inputs,
    publish_distribution,
    release_document,
    revoke_distribution_permission,
    source_capture_context,
    source_context,
)
from tests.test_research_freeze import db_session as db_session

CATALOG = "/v1/discovery/rps/releases"


async def test_actual_frozen_curation_and_internal_artifact_inventory(db_session):
    from services.research_distribution_inputs import build_inventory

    inputs = await distribution_inputs(db_session, release_document())
    inventory = await build_inventory(db_session, **inputs["arguments"])
    assert inventory["scientific_acceptance"] is False
    assert inventory["ml_training_approved"] is False
    assert {row["table"] for row in inventory["dependencies"]} >= {"papers", "works", "material_claims", "ml_examples"}
    assert all(item["root"]["kind"] == "frozen_result" for item in inventory["artifact_bindings"]
               if item["artifact_kind"] == "evidence")


async def test_actual_capsule_wrong_origin_cannot_be_laundered_as_curation_evidence(db_session):
    from services.research_distribution_contract import ResearchDistributionError
    from services.research_distribution_inputs import build_inventory

    source = await source_context(db_session, event_type="measurement", knowledge_origin="Observed")
    inputs = await distribution_inputs(db_session, release_document(), shared=source)
    with pytest.raises(ResearchDistributionError):
        await build_inventory(db_session, **inputs["arguments"])


@pytest.mark.parametrize("source_kind", ["literature", "calculation"])
async def test_real_capture_or_frozen_computed_producer_publishes_only_with_all_dependency_permissions(
    client, db_session, tmp_path, monkeypatch, source_kind,
):
    shared = (await source_capture_context(db_session) if source_kind == "literature" else
              await source_context(db_session, event_type="calculation", knowledge_origin="Computed"))
    local = LocalDistributions(tmp_path.resolve(), db_session, shared)
    context = await local.publish(release_document(source_kind=source_kind))
    settings = get_settings()
    identifier = context["release"]["id"]
    monkeypatch.setattr(settings, "discovery_rps_public_enabled", True)
    monkeypatch.setattr(settings, "discovery_rps_release_dir", str(local.directory))
    monkeypatch.setattr(settings, "discovery_rps_approved_releases", {identifier: context["release"]["manifest_sha256"]})
    monkeypatch.setattr(settings, "discovery_rps_approved_public_bundles", {identifier: context["bundle"]["bundle_sha256"]})
    inventory = context["registration"]["inventory"]
    tables = {row["table"] for row in inventory["dependencies"]}
    if source_kind == "literature":
        assert tables >= {"source_revisions", "source_captures", "paper_work_map", "papers", "works"}
        assert not context["arguments"]["capsule_artifact_bytes"]
        assert "material_claims" not in tables  # literature binding does not fabricate a result occurrence
    else:
        assert tables >= {"research_runs", "research_events", "material_claims"}
        event = next(row["projection"] for row in inventory["dependencies"] if row["table"] == "research_events")
        assert event["event_type"] == "calculation" and event["knowledge_origin"] == "Computed"
        assert event["producer_run_id"] == str(shared["source"]["run"])
    assert inventory["scientific_acceptance"] is inventory["ml_training_approved"] is False
    try:
        catalog = await client.get(CATALOG)
        assert catalog.status_code == 200 and catalog.json()["status"] == "published"
        for url in urls(context):
            response = await client.get(url)
            assert response.status_code == 200, response.text
        if source_kind == "literature":
            await db_session.execute(sa.text("UPDATE paper_work_map SET review_status='pending' WHERE paper_id=:id"),
                                     {"id": shared["source"]["paper"]})
        else:
            from sqlalchemy.exc import DBAPIError

            with pytest.raises(DBAPIError, match="frozen_research_row"):
                async with db_session.begin_nested():
                    await db_session.execute(sa.text("UPDATE research_runs SET code_version='changed-synthetic-run' WHERE id=:id"),
                                             {"id": shared["source"]["run"]})
            await revoke_distribution_permission(db_session, context, table_name="research_runs")
        await db_session.commit()
        response = await client.get(CATALOG, headers={"If-None-Match": catalog.headers["etag"]})
        assert response.status_code == 200 and response.json()["items"] == []
        for url in urls(context):
            assert (await client.get(url)).status_code == 404
    finally:
        priority_releases.clear_release_cache()


@pytest.mark.parametrize("tamper", ["capture_bytes", "provider_version"])
async def test_actual_source_capture_bytes_and_provider_revision_are_not_decorative(db_session, tamper):
    from services import research_distribution as service
    from services.research_distribution_contract import ResearchDistributionError

    shared = await source_capture_context(db_session, provider_revision="2" if tamper == "provider_version" else "1")
    release = release_document(source_kind="literature")
    # A genuinely inserted version 2 cannot support a declared version 1;
    # immutable registry rows themselves are never edited to make this case.
    inputs = await distribution_inputs(db_session, release, shared=shared)
    if tamper == "capture_bytes":
        sha = shared["evidence_root"]["bytes_sha256"]
        inputs["arguments"]["artifact_bytes"][sha] = b"Changed synthetic source bytes"
    with pytest.raises(ResearchDistributionError):
        await service.register_distribution(db_session, actor_user_id=shared["actors"]["curator"],
            request_key="synthetic:bad-source", **inputs["arguments"], dry_run=False)


@pytest_asyncio.fixture(loop_scope="function")
async def distribution(db_session, tmp_path, monkeypatch):
    fixture = LocalDistributions(tmp_path.resolve(), db_session, await source_context(db_session))
    context = await fixture.publish(release_document())
    settings = get_settings()
    monkeypatch.setattr(settings, "discovery_rps_public_enabled", True)
    monkeypatch.setattr(settings, "discovery_rps_release_dir", str(fixture.directory))
    monkeypatch.setattr(settings, "discovery_rps_approved_releases",
                        {identifier: value["manifest_sha256"] for identifier, value in fixture.payloads.items()})
    monkeypatch.setattr(settings, "discovery_rps_approved_public_bundles",
                        {identifier: value["bundle_sha256"] for identifier, value in fixture.bundles.items()})
    priority_releases.clear_release_cache()
    yield fixture, context
    priority_releases.clear_release_cache()


def urls(context):
    release, bundle = context["release"], context["bundle"]
    base = CATALOG + "/" + release["id"]
    return [base + "/assessments", base + "/assessments/test-1",
            base + "/bundle?manifest_sha256=" + release["manifest_sha256"] + "&bundle_sha256=" + bundle["bundle_sha256"]]


async def test_real_roles_capsule_permissions_review_publish_admits_all_release_paths(client, distribution):
    fixture, context = distribution
    dependencies = context["registration"]["inventory"]["dependencies"]
    assert {row["table"] for row in dependencies} >= {"material_claims", "papers", "works", "material_states", "ml_examples"}
    assert len(context["permissions"]) == len(dependencies)
    assert len({context["shared"]["actors"][role] for role in ("curator", "reviewer", "publisher")}) == 3
    response = await client.get(CATALOG)
    assert response.status_code == 200 and response.json()["status"] == "published"
    assert [item["id"] for item in response.json()["items"]] == [context["release"]["id"]]
    for url in urls(context):
        response = await client.get(url)
        assert response.status_code == 200, response.text
        assert (await client.get(url, headers={"If-None-Match": response.headers["etag"]})).status_code == 304
    assert (await client.get("/v1/discovery/rps/policy")).status_code == 200


@pytest.mark.parametrize("withdrawal", ["permission", "paper", "work", "publisher",
                                       "curator_grant", "reviewer_grant", "publisher_grant"])
async def test_hot_file_cache_and_etags_never_override_fresh_sql_withdrawal(client, distribution, withdrawal):
    fixture, context = distribution
    catalog = await client.get(CATALOG)
    assert catalog.status_code == 200
    responses = {url: await client.get(url) for url in urls(context)}
    assert all(response.status_code == 200 for response in responses.values())
    verifications = priority_releases.release_cache_stats()["verifications"]
    if withdrawal == "permission":
        await revoke_distribution_permission(fixture.db, context)
    elif withdrawal.endswith("_grant"):
        from services.research_publication import revoke_role

        people = context["shared"]["actors"]
        await revoke_role(fixture.db, actor_user_id=people["admin"],
            grant_id=people["grants"][withdrawal.removesuffix("_grant")],
            reason_code="synthetic_distribution_role_withdrawal", dry_run=False)
    else:
        source = context["shared"]["source"]
        query, identifier = {
            "paper": ("UPDATE papers SET status='retracted' WHERE id=:id", source["paper"]),
            "work": ("UPDATE works SET publication_status='retracted' WHERE id=:id", source["work"]),
            "publisher": ("UPDATE users SET is_active=false WHERE id=:id", context["shared"]["actors"]["publisher"]),
        }[withdrawal]
        await fixture.db.execute(sa.text(query), {"id": identifier})
    await fixture.db.commit()
    withdrawn = await client.get(CATALOG, headers={"If-None-Match": catalog.headers["etag"]})
    assert withdrawn.status_code == 200 and withdrawn.json()["items"] == []
    assert withdrawn.json()["unavailable"] == []
    for url, previous in responses.items():
        response = await client.get(url, headers={"If-None-Match": previous.headers["etag"]})
        assert response.status_code == 404 and response.headers["cache-control"] == "no-store"
        assert context["release"]["id"] not in response.text
    assert priority_releases.release_cache_stats()["verifications"] == verifications


async def test_config_pins_do_not_publish_pending_package_or_leak_its_catalog_fingerprint(client, distribution):
    fixture, published = distribution
    previous = await client.get(CATALOG)
    value = release_document()
    pending = await publish_distribution(fixture.db, value, shared=fixture.shared, publish=False, permissions=False)
    await fixture.db.commit()
    settings = get_settings()
    settings.discovery_rps_approved_releases[value["id"]] = value["manifest_sha256"]
    settings.discovery_rps_approved_public_bundles[value["id"]] = pending["bundle"]["bundle_sha256"]
    response = await client.get(CATALOG, headers={"If-None-Match": previous.headers["etag"]})
    assert response.status_code == 304
    for url in urls(pending):
        refused = await client.get(url)
        assert refused.status_code == 404 and refused.headers["cache-control"] == "no-store"


async def test_one_unlicensed_transitive_capsule_dependency_blocks_disclosure_review(db_session):
    from services import research_distribution as service
    from services.research_distribution_contract import ResearchDistributionError

    context = await publish_distribution(db_session, release_document(), publish=False, omit_permission_table="ml_examples")
    package = context["registration"]
    dependencies = package["inventory"]["dependencies"]
    assert sum(row["table"] == "ml_examples" for row in dependencies) == 1
    assert len(context["permissions"]) == len(dependencies) - 1
    with pytest.raises(ResearchDistributionError):
        await service.review_distribution(db_session, actor_user_id=context["shared"]["actors"]["reviewer"],
            request_key=context["request_prefix"] + ":missing-transitive-review", package_id=package["package_id"],
            expected_inventory_sha256=package["inventory_sha256"], disclosure_approved=True,
            reason_code="synthetic_missing_transitive_permission", dry_run=False)


@pytest.mark.parametrize("path", ["page", "detail", "download", "catalog"])
async def test_permission_revoked_after_file_read_rechecked_before_any_body_or_304(client, distribution, monkeypatch, path):
    fixture, context = distribution
    target = CATALOG if path == "catalog" else urls(context)[["page", "detail", "download"].index(path)]
    first = await client.get(target)
    assert first.status_code == 200
    entered, proceed = threading.Event(), threading.Event()
    original = routes._unchanged

    def blocked(*args):
        result = original(*args)
        entered.set()
        assert proceed.wait(10)
        return result

    monkeypatch.setattr(routes, "_unchanged", blocked)
    task = asyncio.create_task(client.get(target, headers={"If-None-Match": first.headers["etag"]}))
    try:
        assert await asyncio.wait_for(asyncio.to_thread(entered.wait, 5), timeout=6)
        await revoke_distribution_permission(fixture.db, context)
        await fixture.db.commit()
    finally:
        proceed.set()
        response = await task
    if path == "catalog":
        assert response.status_code == 200 and response.json()["items"] == []
    else:
        assert response.status_code == 409 and response.headers["cache-control"] == "no-store"
    assert response.status_code != 304


@pytest.mark.parametrize("path", ["page", "detail", "download", "catalog"])
async def test_file_replacement_during_final_database_recheck_cannot_return_stale_304(client, distribution, monkeypatch, path):
    fixture, context = distribution
    target = CATALOG if path == "catalog" else urls(context)[["page", "detail", "download"].index(path)]
    first = await client.get(target)
    assert first.status_code == 200
    original = routes._recheck_admission
    changed = []

    async def changed_after_actual_fresh_check(receipt):
        result = await original(receipt)
        if not changed:
            (fixture.directory / (context["release"]["id"] + ".json")).write_text("{}", encoding="utf-8")
            changed.append(True)
        return result

    monkeypatch.setattr(routes, "_recheck_admission", changed_after_actual_fresh_check)
    response = await client.get(target, headers={"If-None-Match": first.headers["etag"]})
    if path == "catalog":
        assert response.status_code == 200 and response.json()["items"] == []
        assert response.json()["status"] == "unavailable"
    else:
        assert response.status_code == 409 and response.headers["cache-control"] == "no-store"
    assert response.status_code != 304


@pytest.mark.parametrize("boundary", ["prepare", "recheck"])
@pytest.mark.parametrize("path", ["catalog", "page", "detail", "download"])
async def test_actual_published_hot_cache_cannot_fallback_when_registry_is_unavailable(client, distribution, monkeypatch, boundary, path):
    from services import research_distribution as service

    _, context = distribution
    target = CATALOG if path == "catalog" else urls(context)[["page", "detail", "download"].index(path)]
    first = await client.get(target)
    assert first.status_code == 200

    async def outage(*args, **kwargs):
        raise service.DistributionRegistryUnavailable("private-driver-credentials-canary")

    function = "prepare_rps_distribution_access" if boundary == "prepare" else "recheck_rps_distribution_access"
    monkeypatch.setattr(service, function, outage)
    response = await client.get(target, headers={"If-None-Match": first.headers["etag"]})
    assert response.status_code == 503 and response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"detail", "error_code", "request_id"}
    assert body["detail"] == "RPS publication registry unavailable"
    assert body["error_code"] == "service_unavailable"
    assert re.fullmatch(r"[0-9a-f]{32}", body["request_id"])
    assert "canary" not in response.text and "credentials" not in response.text
    assert (await client.get("/v1/discovery/rps/policy")).status_code == 200
