"""Private rights preparation HTTP on synthetic capability-owned PostgreSQL.

No test seeds a rights artifact directly. The new route must render and retain
the fixed intent before the existing independent disclosure/publication chain.
"""

from __future__ import annotations

import json
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from models.db import Base
from services import research_distribution as distribution
from services import research_publication as publication
from services.research_distribution_contract import ResearchDistributionError
from tests.test_research_distribution_operators import auth, private
from tests.test_research_distribution_rights import registered_fixture, rights_arguments
from tests.test_research_freeze import db_session as db_session
from tests.test_research_freeze import state
from tests.test_research_publication import actors

BASE = "/v1/ml/distributions"


def path(arguments):
    return f"{BASE}/{arguments['package_id']}/rights/{arguments['dependency_id']}"


def body(arguments, *, preview=None, dry_run=None):
    value = {key: deepcopy(item) for key, item in arguments.items()
             if key not in {"actor_user_id", "package_id", "dependency_id"}}
    if preview is not None:
        value["expected_intent_sha256"] = preview["intent_sha256"]
    if dry_run is not None:
        value["dry_run"] = dry_run
    return value


async def http_commit(client, arguments):
    headers = auth(arguments["actor_user_id"])
    preview = await client.post(path(arguments), json=body(arguments), headers=headers)
    assert preview.status_code == 200, preview.text
    assert preview.json()["committed"] is False and preview.json()["result"]["artifact"] is None
    response = await client.post(path(arguments), json=body(arguments, preview=preview.json()["result"], dry_run=False), headers=headers)
    assert response.status_code == 200 and response.json()["committed"] is True, response.text
    private(response)
    return preview.json()["result"], response.json()["result"]


async def test_actual_preview_commit_get_outcome_and_post_replay_are_private_zero_write_reads(client, db_session, tmp_path):
    context = await registered_fixture(db_session)
    arguments = rights_arguments(context)
    await db_session.commit()
    before = await state(db_session)
    await db_session.rollback()
    capabilities = await client.get(BASE + "/operator/capabilities", headers=auth(arguments["actor_user_id"]))
    assert capabilities.status_code == 200, capabilities.text
    assert capabilities.json()["can_read"] is capabilities.json()["can_prepare"] is True
    inventory_path = BASE + "/" + arguments["package_id"] + "/rights"
    listing = await client.get(inventory_path, headers=auth(arguments["actor_user_id"]))
    assert listing.status_code == 200, listing.text
    first_page, all_dependencies = listing.json(), []
    page = first_page
    while True:
        assert len(page["dependencies"]) <= 25
        assert all(set(row) == {"dependency_id", "table", "row_id", "row_sha256"} for row in page["dependencies"])
        all_dependencies.extend(page["dependencies"])
        if page["next_after"] is None:
            break
        next_page = await client.get(inventory_path, headers=auth(arguments["actor_user_id"]), params={
            "after": page["next_after"], "expected_inventory_sha256": first_page["inventory_sha256"]})
        assert next_page.status_code == 200, next_page.text
        page = next_page.json()
    assert len(all_dependencies) == first_page["dependency_count"]
    assert [row["dependency_id"] for row in all_dependencies] == sorted({row["dependency_id"] for row in all_dependencies})
    assert {row["dependency_id"] for row in all_dependencies} == {
        row["dependency_id"] for row in context["registration"]["inventory"]["dependencies"]}
    for query, expected in (({"after": all_dependencies[0]["dependency_id"]}, 400),
                            ({"expected_inventory_sha256": "0" * 64}, 409)):
        response = await client.get(inventory_path, headers=auth(arguments["actor_user_id"]), params=query)
        assert response.status_code == expected, response.text
        private(response)
    inspected = await client.get(path(arguments), headers=auth(arguments["actor_user_id"]))
    assert inspected.status_code == 200, inspected.text
    info = inspected.json()
    assert info["package_record_sha256"] == arguments["expected_package_sha256"]
    assert info["dependency"]["row_sha256"] == arguments["expected_dependency_row_sha256"]
    assert info["head"] is None and "projection" not in info["dependency"]
    assert info["scientific_acceptance"] is info["ml_training_approved"] is info["current_authorization_checked"] is False
    preview = await client.post(path(arguments), json=body(arguments), headers=auth(arguments["actor_user_id"]))
    assert preview.status_code == 200, preview.text
    assert preview.json()["dry_run"] is True and preview.json()["committed"] is False
    assert before == await state(db_session)
    await db_session.rollback()
    committed = await client.post(path(arguments), headers=auth(arguments["actor_user_id"]),
        json=body(arguments, preview=preview.json()["result"], dry_run=False))
    assert committed.status_code == 200 and committed.json()["committed"] is True, committed.text
    result = committed.json()["result"]
    stable = await state(db_session)
    await db_session.rollback()
    outcome = await client.get(path(arguments) + "/outcome", headers=auth(arguments["actor_user_id"]),
        params={"request_key": arguments["request_key"], "expected_intent_sha256": result["intent_sha256"]})
    assert outcome.status_code == 200, outcome.text
    assert outcome.json()["committed"] is True and outcome.json()["result"]["replayed"] is True
    assert outcome.json()["result"]["permission"] == result["permission"]
    replay = await client.post(path(arguments), headers=auth(arguments["actor_user_id"]),
        json=body(arguments, preview=result, dry_run=False))
    assert replay.status_code == 200 and replay.json()["result"]["replayed"] is True, replay.text
    assert stable == await state(db_session)
    for response in (capabilities, listing, inspected, preview, committed, outcome, replay):
        private(response)
    fixture = {"capabilities": capabilities.json(), "listing": first_page, "selected": info,
               "request": body(arguments), "preview": preview.json(), "committed": committed.json(), "outcome": outcome.json()}
    (tmp_path / "distribution-rights-http.json").write_text(json.dumps(fixture, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")


@pytest.mark.parametrize("role", [None, "admin", "curator", "publisher", "member"])
async def test_role_admission_precedes_body_capture_for_every_private_path(client, db_session, monkeypatch, role):
    from routers import research_distribution_rights as router

    people = await actors(db_session)
    await db_session.commit()
    target = f"{BASE}/{uuid4()}/rights/" + "a" * 64

    async def no_body(*args):
        pytest.fail("unadmitted account reached rights body")

    monkeypatch.setattr(router, "_small_body", no_body)
    headers = {} if role is None else auth(people[role])
    for endpoint in (BASE + "/operator/capabilities", target.rsplit("/", 1)[0], target,
                     target + "/outcome?request_key=absent&expected_intent_sha256=" + "b" * 64):
        response = await client.get(endpoint, headers=headers)
        assert response.status_code == (401 if role is None else 403), response.text
        private(response)
    response = await client.post(target, content=b"PRIVATE-NOT-JSON", headers={**headers,
        "Content-Type": "application/json", "Content-Length": "999999"})
    assert response.status_code == (401 if role is None else 403), response.text
    private(response)


@pytest.mark.parametrize("addition", [
    {"actor_user_id": "private-actor"}, {"rights_document": {"private": "raw text"}},
    {"uri": "https://private.invalid/source"}, {"path": "/private/rights"},
    {"synthetic": True}, {"approved": True}, {"role": "reviewer"},
    {"license_code": "all-rights-assumed"}, {"dry_run": "false"},
])
async def test_closed_wire_never_accepts_arbitrary_rights_or_identity(client, db_session, addition):
    context = await registered_fixture(db_session)
    arguments = rights_arguments(context)
    await db_session.commit()
    before = await state(db_session)
    await db_session.rollback()
    response = await client.post(path(arguments), headers=auth(arguments["actor_user_id"]), json={**body(arguments), **addition})
    assert response.status_code == 400 and "private" not in response.text.lower(), response.text
    assert before == await state(db_session)
    private(response)


@pytest.mark.parametrize("change", ["role_revoked", "session_revoked", "inactive", "unverified"])
async def test_streamed_body_identity_drift_is_rechecked_in_fresh_transaction(client, db_session, change):
    context = await registered_fixture(db_session)
    arguments = rights_arguments(context)
    people = context["shared"]["actors"]
    await db_session.commit()
    expected = []

    async def stream():
        payload = json.dumps(body(arguments)).encode()
        yield payload[:12]
        if change == "role_revoked":
            await publication.revoke_role(db_session, actor_user_id=people["admin"],
                grant_id=people["grants"]["reviewer"], reason_code="synthetic_during_upload", dry_run=False)
        else:
            column, value = {"session_revoked": ("session_version", 1), "inactive": ("is_active", False),
                             "unverified": ("email_verified", False)}[change]
            await db_session.execute(sa.update(Base.metadata.tables["users"]).where(
                Base.metadata.tables["users"].c.id == people["reviewer"]).values(**{column: value}))
        await db_session.commit()
        expected.append(await state(db_session))
        await db_session.rollback()
        yield payload[12:]

    response = await client.post(path(arguments), headers={**auth(people["reviewer"]), "Content-Type": "application/json"}, content=stream())
    assert response.status_code == 403, response.text
    assert len(expected) == 1 and expected[0] == await state(db_session)
    private(response)


@pytest.mark.parametrize("failure", ["serialization", "outer_commit", "response_lost_after_commit"])
async def test_http_failure_never_invents_durability_and_exact_get_recovers_only_committed_work(client, db_session, monkeypatch, failure):
    from routers import research_distribution_rights as router

    context = await registered_fixture(db_session)
    arguments = rights_arguments(context)
    await db_session.commit()
    preview = await client.post(path(arguments), json=body(arguments), headers=auth(arguments["actor_user_id"]))
    assert preview.status_code == 200, preview.text
    intent = preview.json()["result"]
    before = await state(db_session)
    await db_session.rollback()
    completed = []

    with monkeypatch.context() as patch:
        if failure == "response_lost_after_commit":
            operate = router._operate

            async def lost(*args, **kwargs):
                await operate(*args, **kwargs)
                completed.append(True)
                raise SQLAlchemyError("PRIVATE_POST_COMMIT_ACK_LOSS")

            patch.setattr(router, "_operate", lost)
        else:
            prepare = router.prepare_distribution_rights

            async def fail(db, **kwargs):
                result = await prepare(db, **kwargs)
                completed.append(True)
                if failure == "serialization":
                    return {**result, "not_serializable": object()}
                await db.execute(sa.text("CREATE TEMP TABLE rights_commit_probe (id int PRIMARY KEY, "
                    "parent int REFERENCES rights_commit_probe(id) DEFERRABLE INITIALLY DEFERRED) ON COMMIT DROP"))
                await db.execute(sa.text("INSERT INTO rights_commit_probe VALUES (1,2)"))
                return result

            patch.setattr(router, "prepare_distribution_rights", fail)
        response = await client.post(path(arguments), json=body(arguments, preview=intent, dry_run=False), headers=auth(arguments["actor_user_id"]))
    assert completed == [True]
    assert response.status_code == (400 if failure == "serialization" else 503), response.text
    assert "PRIVATE" not in response.text and "committed" not in response.json()
    after = await state(db_session)
    if failure != "response_lost_after_commit":
        assert after == before
    else:
        assert len(after["evidence_artifacts"]) == len(before["evidence_artifacts"]) + 1
        assert len(after["research_distribution_permissions"]) == len(before["research_distribution_permissions"]) + 1
    await db_session.rollback()
    recovered = await client.get(path(arguments) + "/outcome", headers=auth(arguments["actor_user_id"]),
        params={"request_key": arguments["request_key"], "expected_intent_sha256": intent["intent_sha256"]})
    assert recovered.status_code == (200 if failure == "response_lost_after_commit" else 404), recovered.text
    assert after == await state(db_session)
    private(response)
    private(recovered)


async def test_historical_outcome_survives_two_heads_and_source_drift_without_becoming_current_permission(client, db_session):
    context = await registered_fixture(db_session)
    people = context["shared"]["actors"]
    dependency = next(row for row in context["registration"]["inventory"]["dependencies"] if row["table"] == "papers")
    arguments = rights_arguments(context, dependency=dependency)
    await db_session.commit()
    _, original = await http_commit(client, arguments)
    _, second = await http_commit(client, rights_arguments(context, dependency=dependency, head=original["permission"]))
    await http_commit(client, rights_arguments(context, dependency=dependency, head=second["permission"], decision="revoke"))
    await db_session.execute(sa.update(Base.metadata.tables["papers"]).where(
        Base.metadata.tables["papers"].c.id == dependency["row_id"]).values(status="retracted"))
    await db_session.execute(sa.update(Base.metadata.tables["evidence_artifacts"]).where(
        Base.metadata.tables["evidence_artifacts"].c.id == UUID(original["artifact"]["id"])).values(metadata={}))
    await db_session.commit()
    stable_history = await state(db_session)
    await db_session.rollback()
    historical_replay = await client.post(path(arguments), headers=auth(people["reviewer"]),
        json=body(arguments, preview=original, dry_run=False))
    assert historical_replay.status_code == 200, historical_replay.text
    assert historical_replay.json()["result"]["permission"] == original["permission"]
    assert historical_replay.json()["result"]["replayed"] is True
    assert stable_history == await state(db_session)
    await db_session.rollback()
    await publication.revoke_role(db_session, actor_user_id=people["admin"], grant_id=people["grants"]["reviewer"],
        reason_code="synthetic_regrant", dry_run=False)
    await publication.grant_role(db_session, actor_user_id=people["admin"], user_id=people["reviewer"], role="reviewer",
        reason_code="synthetic_regrant", dry_run=False)
    await publication.grant_role(db_session, actor_user_id=people["admin"], user_id=people["member"], role="reviewer",
        reason_code="synthetic_other_actor", dry_run=False)
    await db_session.commit()
    before = await state(db_session)
    await db_session.rollback()
    query = {"request_key": arguments["request_key"], "expected_intent_sha256": original["intent_sha256"]}
    outcome = await client.get(path(arguments) + "/outcome", headers=auth(people["reviewer"]), params=query)
    assert outcome.status_code == 200, outcome.text
    restored = outcome.json()["result"]
    assert restored["permission"] == original["permission"] and restored["artifact"] == original["artifact"]
    assert restored["intent"] == original["intent"] and restored["current_authorization_checked"] is False
    for actor, params, expected in ((people["member"], query, 404),
        (people["reviewer"], {**query, "expected_intent_sha256": "0" * 64}, 409),
        (people["reviewer"], {**query, "request_key": "absent-exact-key"}, 404)):
        response = await client.get(path(arguments) + "/outcome", headers=auth(actor), params=params)
        assert response.status_code == expected, response.text
        private(response)
    replay = await client.post(path(arguments), headers=auth(people["reviewer"]), json=body(arguments, preview=original, dry_run=False))
    assert replay.status_code == 409, replay.text  # Changed grant cannot bind an old preview for new work.
    assert before == await state(db_session)


async def test_complete_http_rights_preparation_feeds_existing_review_publish_and_protective_revoke(client, db_session):
    context = await registered_fixture(db_session)
    people = context["shared"]["actors"]
    await db_session.commit()
    receipts = []
    for dependency in context["registration"]["inventory"]["dependencies"]:
        arguments = rights_arguments(context, dependency=dependency)
        preview, receipt = await http_commit(client, arguments)
        receipts.append((arguments, preview, receipt))
    review_request = {"request_key": "synthetic-rights-review:" + uuid4().hex,
        "expected_inventory_sha256": context["registration"]["inventory_sha256"], "disclosure_approved": True,
        "reason_code": "synthetic_independent_disclosure", "dry_run": False}
    package_path = BASE + "/" + context["registration"]["package_id"]
    review = await client.post(package_path + "/reviews", headers=auth(people["reviewer"]), json=review_request)
    assert review.status_code == 200, review.text
    action_request = {"request_key": "synthetic-rights-publish:" + uuid4().hex,
        "expected_inventory_sha256": context["registration"]["inventory_sha256"],
        "review_id": review.json()["result"]["id"], "kind": "publish", "reason_code": "synthetic_publication", "dry_run": False}
    action = await client.post(package_path + "/actions", headers=auth(people["publisher"]), json=action_request)
    assert action.status_code == 200, action.text
    admitted = await distribution.admitted_distribution(db_session, context["registration"]["package_id"])
    assert admitted["bundle_sha256"] == context["bundle"]["bundle_sha256"]
    await db_session.rollback()
    selected = next(item for item in receipts if next(dep for dep in context["registration"]["inventory"]["dependencies"]
                    if dep["dependency_id"] == item[0]["dependency_id"])["table"] == "papers")
    await db_session.execute(sa.update(Base.metadata.tables["papers"]).where(
        Base.metadata.tables["papers"].c.id == context["shared"]["source"]["paper"]).values(status="retracted"))
    await db_session.commit()
    with pytest.raises(ResearchDistributionError):
        await distribution.admitted_distribution(db_session, context["registration"]["package_id"])
    await db_session.rollback()
    revoked_arguments = {**selected[0], "request_key": "synthetic-protective-revoke:" + uuid4().hex,
        "decision": "revoke", "expected_head_id": selected[2]["permission"]["id"],
        "expected_head_sha256": selected[2]["permission"]["record_sha256"]}
    await http_commit(client, revoked_arguments)
    with pytest.raises(ResearchDistributionError):
        await distribution.admitted_distribution(db_session, context["registration"]["package_id"])
    private(review)
    private(action)
