"""Owned synthetic SQL governance, never a real reviewed scientific pilot.

The empty-scientific fixture deliberately proves that old publication and a new
disclosure decision cannot authorize publishing a purported reviewed pilot.
Actual accepted cells are covered by the dedicated projection integration tests.
"""
from __future__ import annotations

from copy import deepcopy
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Base, Material, get_engine
from models.discovery_projection_v1 import TABLE_ORDER
from services import discovery_projection_governance as service
from services import research_distribution as distribution
from services.research_access import ResearchAccessDenied
from services.research_priority import digest
from tests.rps_distribution_fixtures import publish_distribution, release_document
from tests.test_discovery_scientific_projection import selection_for
from tests.test_research_freeze import state


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    engine = get_engine().execution_options(isolation_level="SERIALIZABLE")
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            try:
                yield session
            finally:
                await session.rollback()
                identifiers = session.info.get("discovery_governance_committed_material_ids", set())
                if identifiers:
                    # Only our retained synthetic catalogue rows; keep immutable
                    # history and prevent unrelated public reads seeing fixtures.
                    await session.execute(sa.update(Material).where(Material.id.in_(identifiers)).values(needs_review=True))
                    await session.commit()
    finally:
        await engine.dispose()


async def fixture(db):
    context = await publish_distribution(db, release_document())
    await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
    await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
    bundle = context["arguments"]["public_bundle"]
    selection = selection_for(bundle)
    arguments = {"actor_user_id": context["shared"]["actors"]["curator"],
        "request_key": "synthetic-discovery:" + uuid4().hex,
        "distribution_package_id": context["package"]["id"],
        "expected_distribution_record_sha256": context["package"]["record_sha256"],
        "expected_inventory_sha256": context["package"]["inventory_sha256"],
        "public_bundle": bundle, "selection": selection, "expected_selection_sha256": digest(selection)}
    return context, arguments


async def register(db):
    context, arguments = await fixture(db)
    preview = await service.register_projection(db, **arguments)
    arguments["expected_payload_sha256"] = preview["payload_sha256"]
    registered = await service.register_projection(db, **arguments, dry_run=False)
    assert registered["payload_sha256"] == preview["payload_sha256"]
    return context, arguments, registered


async def reviewed_publication(db, *, publish=True):
    """Callable native fixture: real synthetic scope decisions, never real science.

    No commit, schema teardown, pytest injection or trigger bypass occurs here.
    The caller owns an isolated guarded SERIALIZABLE transaction.
    """
    from services.research_distribution_rights import prepare_distribution_rights
    from tests.test_discovery_scientific_projection import projected_fixture

    context = await projected_fixture(db, reviewed=True, properties=[{
        "property_key": "phonon_min_frequency", "relation": "exact", "value": -0.125}])
    people, original = context["actors"], context["package"]
    for dependency in context["inventory"]["dependencies"]:
        args = {"actor_user_id": people["reviewer"], "request_key": "synthetic-base-rights:" + uuid4().hex,
            "package_id": original["id"], "dependency_id": dependency["dependency_id"],
            "decision": "allow", "license_code": "permission-on-file", "basis_code": "synthetic_fixture_only",
            "reason_code": "synthetic_fixture_only", "expected_package_sha256": original["record_sha256"],
            "expected_inventory_sha256": original["inventory_sha256"],
            "expected_dependency_row_sha256": dependency["row_sha256"], "expected_head_id": None, "expected_head_sha256": None}
        preview = await prepare_distribution_rights(db, **args)
        await prepare_distribution_rights(db, **args, expected_intent_sha256=preview["intent_sha256"], dry_run=False)
    old_review = await distribution.review_distribution(db, actor_user_id=people["reviewer"], request_key=uuid4().hex,
        package_id=original["id"], expected_inventory_sha256=original["inventory_sha256"],
        disclosure_approved=True, reason_code="synthetic_base_disclosure", dry_run=False)
    await distribution.distribution_action(db, actor_user_id=people["publisher"], request_key=uuid4().hex,
        package_id=original["id"], review_id=old_review["id"], expected_inventory_sha256=original["inventory_sha256"],
        kind="publish", reason_code="synthetic_base_publication", dry_run=False)
    args = {**context["arguments"], "actor_user_id": people["curator"], "request_key": uuid4().hex}
    preview = await service.register_projection(db, **args)
    args["expected_payload_sha256"] = preview["payload_sha256"]
    registered = await service.register_projection(db, **args, dry_run=False)
    # Match the empty-science helper's documented shape for independent callers.
    context["shared"] = {"actors": people, "source": context["source"]}
    context["registration"]["inventory"] = context["inventory"]
    review_arguments = review_args(context, registered)
    reviewed = await service.review_projection(db, **review_arguments, dry_run=False)
    action_arguments = action_args(context, registered, reviewed)
    action = await service.projection_action(db, **action_arguments, dry_run=False) if publish else None
    return {"fixture": context, "arguments": args, "registered": registered, "reviewed": reviewed,
        "review_arguments": review_arguments, "action_arguments": action_arguments, "action": action}


def review_args(context, registered, *, decision="approve"):
    return {"actor_user_id": context["shared"]["actors"]["reviewer"], "request_key": uuid4().hex,
        "package_id": registered["package_id"], "expected_payload_sha256": registered["payload_sha256"],
        "expected_selection_sha256": registered["selection_sha256"], "decision": decision,
        "representative_selection_approved": decision == "approve", "disclosure_approved": decision == "approve",
        "reason_code": "synthetic_disclosure_only", "rights": [{"dependency_id": row["dependency_id"],
            "row_sha256": row["row_sha256"], "license_code": "permission-on-file", "basis_code": "synthetic_new_scope"}
            for row in context["registration"]["inventory"]["dependencies"]] if decision == "approve" else []}


def action_args(context, registered, review, *, kind="publish"):
    return {"actor_user_id": context["shared"]["actors"]["publisher"], "request_key": uuid4().hex,
        "package_id": registered["package_id"], "review_id": review["id"],
        "expected_payload_sha256": registered["payload_sha256"], "expected_selection_sha256": registered["selection_sha256"],
        "kind": kind, "reason_code": "synthetic_publication_gate"}


def test_native_tables_have_real_restrict_actor_fks_and_closed_new_scope():
    for name in TABLE_ORDER:
        assert name in Base.metadata.tables
        table = Base.metadata.tables[name]
        for column in ("actor_user_id", "actor_grant_id"):
            fk = next(iter(table.c[column].foreign_keys))
            assert fk.ondelete == fk.onupdate == "RESTRICT"
    assert service.SCOPE != distribution.SCOPE


async def test_default_registration_preview_is_full_sql_noop(db_session):
    _, arguments = await fixture(db_session)
    before = await state(db_session)
    first = await service.register_projection(db_session, **arguments)
    second = await service.register_projection(db_session, **arguments)
    assert first["payload_sha256"] == second["payload_sha256"]
    assert first["request_sha256"] == second["request_sha256"]
    assert first["dry_run"] is True and first["committed"] is False
    assert before == await state(db_session)


async def test_actual_register_rebuild_and_exact_replay_are_detached_noop(db_session):
    context, arguments, registered = await register(db_session)
    before = await state(db_session)
    replay = await service.register_projection(db_session, **arguments, dry_run=False)
    assert replay["id"] == registered["id"] and replay["replayed"] is True
    assert before == await state(db_session)
    result = await service.inspect_projection(db_session, actor_user_id=context["shared"]["actors"]["reviewer"],
        package_id=registered["package_id"])
    assert digest(result["payload"]) == registered["payload_sha256"]
    assert len(result["rights_targets"]) == len(context["registration"]["inventory"]["dependencies"])
    assert result["scope"] == "discovery_scientific_projection"
    assert all(type(key) is str for row in result["rights_targets"] for key in row)
    assert distribution.contract._bounded(result)
    result["payload"]["rows"].clear()
    assert (await service.inspect_projection(db_session, actor_user_id=arguments["actor_user_id"],
        package_id=registered["package_id"]))["payload"]["rows"]


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
async def test_native_registered_payload_is_append_only(db_session, operation):
    _, _, registered = await register(db_session)
    before = await state(db_session)
    with pytest.raises(DBAPIError, match="discovery_projection_append_only"):
        async with db_session.begin_nested():
            sql = {"UPDATE": "UPDATE discovery_projection_packages SET payload_json='{}' WHERE id=:id",
                "DELETE": "DELETE FROM discovery_projection_packages WHERE id=:id",
                "TRUNCATE": "TRUNCATE discovery_projection_packages CASCADE"}[operation]
            await db_session.execute(sa.text(sql), {"id": UUID(registered["id"])})
    assert before == await state(db_session)


async def test_old_rights_do_not_authorize_new_payload_and_no_scientific_cells_cannot_publish(db_session):
    context, _, registered = await register(db_session)
    assert context["permissions"] and context["action"]
    with pytest.raises(service.DiscoveryGovernanceError):
        await service.admitted_projection(db_session, registered["package_id"])
    before = await state(db_session)
    args = review_args(context, registered)
    reviewed = await service.review_projection(db_session, **args)
    assert reviewed["committed"] is False and before == await state(db_session)
    reviewed = await service.review_projection(db_session, **args, dry_run=False)
    before = await state(db_session)
    with pytest.raises(service.DiscoveryGovernanceError, match="discovery_reviewed_scientific_cell_required"):
        await service.projection_action(db_session, **action_args(context, registered, reviewed), dry_run=False)
    assert before == await state(db_session)


@pytest.mark.parametrize("mutation", ["missing", "row_hash", "duplicate", "scope", "license_null", "basis_null"])
async def test_new_scope_complete_exact_rights_cannot_be_inherited_or_forged(db_session, mutation):
    context, _, registered = await register(db_session)
    args = review_args(context, registered)
    if mutation == "missing": args["rights"].pop()
    elif mutation == "duplicate": args["rights"].append(deepcopy(args["rights"][0]))
    elif mutation == "row_hash": args["rights"][0]["row_sha256"] = "0" * 64
    elif mutation == "scope": args["rights"][0]["scope"] = distribution.SCOPE
    elif mutation == "license_null": args["rights"][0]["license_code"] = None
    else: args["rights"][0]["basis_code"] = None
    before = await state(db_session)
    with pytest.raises((ValueError, DBAPIError)):
        await service.review_projection(db_session, **args, dry_run=False)
    assert before == await state(db_session)


@pytest.mark.parametrize("field", ["representative_selection_approved", "disclosure_approved"])
@pytest.mark.parametrize("value", [False, 1, "true"])
async def test_approval_requires_both_explicit_boolean_decisions(db_session, field, value):
    context, _, registered = await register(db_session)
    args = review_args(context, registered)
    args[field] = value
    before = await state(db_session)
    with pytest.raises(ValueError):
        await service.review_projection(db_session, **args, dry_run=False)
    assert before == await state(db_session)


async def test_protective_negative_and_withdrawal_do_not_require_fresh_source_eligibility(db_session):
    context, _, registered = await register(db_session)
    reviewed = await service.review_projection(db_session, **review_args(context, registered), dry_run=False)
    await db_session.execute(sa.text("UPDATE materials SET needs_review=true WHERE id=:id"),
        {"id": context["shared"]["source"]["material"]})
    negative = await service.review_projection(db_session, **review_args(context, registered, decision="reject"), dry_run=False)
    assert negative["operation"] == "review"
    args = action_args(context, registered, reviewed, kind="withdraw")
    withdrawn = await service.projection_action(db_session, **args, dry_run=False)
    assert withdrawn["operation"] == "withdraw"
    before = await state(db_session)
    assert (await service.projection_action(db_session, **args, dry_run=False))["replayed"] is True
    assert before == await state(db_session)


async def test_review_replay_and_actor_scoped_recovery_preserve_old_receipt(db_session):
    context, _, registered = await register(db_session)
    args = review_args(context, registered)
    receipt = await service.review_projection(db_session, **args, dry_run=False)
    await db_session.execute(sa.text("UPDATE materials SET needs_review=true WHERE id=:id"),
        {"id": context["shared"]["source"]["material"]})
    before = await state(db_session)
    replay = await service.review_projection(db_session, **args, dry_run=False)
    assert replay["id"] == receipt["id"] and replay["replayed"] is True
    historical = await service.inspect_operation(db_session, actor_user_id=args["actor_user_id"], operation="review",
        request_key=args["request_key"], expected_request_sha256=receipt["request_sha256"])
    assert historical == replay and before == await state(db_session)
    with pytest.raises(service.DiscoveryGovernanceConflict):
        await service.inspect_operation(db_session, actor_user_id=args["actor_user_id"], operation="review",
            request_key=args["request_key"], expected_request_sha256="0" * 64)
    with pytest.raises(service.DiscoveryGovernanceNotFound):
        await service.inspect_operation(db_session, actor_user_id=args["actor_user_id"], operation="review",
            request_key="missing", expected_request_sha256=receipt["request_sha256"])


@pytest.mark.parametrize("role", ["admin", "member", "reviewer", "publisher"])
async def test_registered_curator_is_explicit_not_legacy_role(db_session, role):
    context, arguments = await fixture(db_session)
    arguments["actor_user_id"] = context["shared"]["actors"][role]
    arguments["expected_payload_sha256"] = "0" * 64
    before = await state(db_session)
    with pytest.raises(ResearchAccessDenied):
        await service.register_projection(db_session, **arguments, dry_run=False)
    assert before == await state(db_session)


async def test_same_actor_request_key_collision_never_substitutes_new_selection(db_session):
    _, arguments, _ = await register(db_session)
    arguments["selection"]["representatives"][0]["rationale"] += " Different asserted choice."
    arguments["expected_selection_sha256"] = digest(arguments["selection"])
    before = await state(db_session)
    with pytest.raises(service.DiscoveryGovernanceConflict):
        await service.register_projection(db_session, **arguments, dry_run=False)
    assert before == await state(db_session)


@pytest.mark.parametrize("setting", ["SET LOCAL TIME ZONE 'Asia/Singapore'", "SET LOCAL statement_timeout=0"])
async def test_session_admission_rejects_unbounded_or_non_utc_reads(db_session, setting):
    await db_session.execute(sa.text(setting))
    with pytest.raises(service.DiscoveryGovernanceError, match="discovery_bounded_snapshot_required"):
        await service.public_projection_inventory(db_session)


async def test_actual_scoped_review_new_rights_and_third_publisher_admit_exact_payload(db_session):
    import json

    seeded = await reviewed_publication(db_session)
    registered = seeded["registered"]
    before = await state(db_session)
    current = await service.admitted_projection(db_session, registered["id"])
    assert current["payload_sha256"] == digest(current["payload"]) == registered["payload_sha256"]
    observations = [item for row in current["payload"]["rows"] for cell in row["cells"] for item in cell["observations"]]
    assert len(observations) == 1 and observations[0]["scientific_scope_accepted"] is True
    assert observations[0]["quantity"]["value"] == -0.125
    assert set(current[key] for key in service.AUTHORITY) == {False}
    catalog = await service.public_projection_inventory(db_session)
    assert any(row["package_id"] == registered["id"] for row in catalog["items"])
    assert (await service.projection_action(db_session, **seeded["action_arguments"], dry_run=False))["replayed"] is True
    package = await service._package(db_session, registered["id"])
    wrong = json.loads(package["scientific_pins_json"])
    next(iter(wrong.values()))["scopes"][0]["scientific_scope_accepted"] = True
    with pytest.raises(DBAPIError, match="discovery_closed_review_status_required"):
        async with db_session.begin_nested():
            await db_session.execute(sa.text("SELECT public.sclib_discovery_projection_science_v1(:id,CAST(:pins AS jsonb),true)"),
                {"id": package["distribution_package_id"], "pins": service._json(wrong)})
    assert await state(db_session) == before


@pytest.mark.parametrize("change", ["material", "scientific_reviewer", "negative_disclosure", "withdraw"])
async def test_fresh_public_reads_fail_closed_after_current_governance_changes(db_session, change):
    from services.research_publication import revoke_role

    seeded = await reviewed_publication(db_session)
    context, registered = seeded["fixture"], seeded["registered"]
    if change == "material":
        await db_session.execute(sa.text("UPDATE materials SET needs_review=true WHERE id=:id"), {"id": context["source"]["material"]})
    elif change == "scientific_reviewer":
        db_session.info.setdefault("discovery_governance_committed_material_ids", set()).add(context["source"]["material"])
        # A revoked reviewer cannot finish a decision in the same transaction.
        # Exercise the actual later-revocation workflow, not an invalid assembly.
        await db_session.commit()
        await db_session.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
        await db_session.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
        await revoke_role(db_session, actor_user_id=context["actors"]["admin"],
            grant_id=context["actors"]["grants"]["reviewer"], reason_code="synthetic_review_withdrawal", dry_run=False)
    elif change == "negative_disclosure":
        await service.review_projection(db_session, **review_args(context, registered, decision="reject"), dry_run=False)
    else:
        await service.projection_action(db_session, **{**seeded["action_arguments"], "kind": "withdraw", "request_key": uuid4().hex}, dry_run=False)
    before = await state(db_session)
    with pytest.raises(ValueError):
        await service.admitted_projection(db_session, registered["id"])
    assert registered["id"] not in {row["package_id"] for row in (await service.public_projection_inventory(db_session))["items"]}
    assert before == await state(db_session)


async def test_resealed_raw_sql_payload_cannot_pass_scientific_reconstruction(db_session):
    import json

    seeded = await reviewed_publication(db_session, publish=False)
    original = await service._get(db_session, TABLE_ORDER[0], seeded["registered"]["id"])
    payload = json.loads(original["payload_json"])
    observation = next(item for row in payload["rows"] for cell in row["cells"] for item in cell["observations"])
    observation["quantity"]["value"] = 123
    values = {key: value for key, value in original.items() if key not in {"id", "record_sha256", "created_at"}}
    values.update(payload_json=service._json(payload), payload_sha256=digest(payload), request_key=uuid4().hex,
                  request_sha256="0" * 64)
    table = Base.metadata.tables[TABLE_ORDER[0]]
    forged = (await db_session.execute(table.insert().values(**values).returning(table.c.id))).scalar_one()
    with pytest.raises(service.DiscoveryGovernanceConflict):
        await service.inspect_projection(db_session, actor_user_id=seeded["arguments"]["actor_user_id"], package_id=forged)
    args = {**seeded["review_arguments"], "package_id": forged, "expected_payload_sha256": digest(payload), "request_key": uuid4().hex}
    before = await state(db_session)
    with pytest.raises(service.DiscoveryGovernanceConflict):
        await service.review_projection(db_session, **args, dry_run=False)
    assert before == await state(db_session)


async def test_native_payload_never_grants_whole_package_scientific_or_ml_authority(db_session):
    import json

    _, _, registered = await register(db_session)
    original = await service._get(db_session, TABLE_ORDER[0], registered["id"])
    before = await state(db_session)
    for field in ("scientific_acceptance", "ml_training_approved", "public_release_authorized"):
        payload = json.loads(original["payload_json"])
        payload[field] = True
        values = {key: value for key, value in original.items() if key not in {"id", "record_sha256", "created_at"}}
        values.update(payload_json=service._json(payload), payload_sha256=digest(payload),
            request_key=uuid4().hex, request_sha256="0" * 64)
        with pytest.raises(DBAPIError, match="discovery_exact_package_required"):
            async with db_session.begin_nested():
                await db_session.execute(Base.metadata.tables[TABLE_ORDER[0]].insert().values(**values))
    assert before == await state(db_session)


async def test_new_scientific_review_between_preview_and_commit_changes_exact_payload(db_session):
    from tests.test_discovery_scientific_cells import review_cell
    from tests.test_discovery_scientific_projection import projected_fixture

    fixture = await projected_fixture(db_session, properties=[{
        "property_key": "phonon_min_frequency", "relation": "exact", "value": -0.125}])
    args = {**fixture["arguments"], "actor_user_id": fixture["actors"]["curator"], "request_key": uuid4().hex}
    preview = await service.register_projection(db_session, **args)
    await review_cell(db_session, fixture, scientific=True)
    before = await state(db_session)
    with pytest.raises(service.DiscoveryGovernanceConflict):
        await service.register_projection(db_session, **args, expected_payload_sha256=preview["payload_sha256"], dry_run=False)
    assert before == await state(db_session)


async def test_native_scientific_pins_are_closed_and_unreviewed_cannot_name_a_fake_decision(db_session):
    from tests.test_discovery_scientific_projection import projected_fixture

    fixture = await projected_fixture(db_session, properties=[{"property_key": "band_gap", "relation": "exact", "value": 0}])
    built = await service.projection.build_projection(db_session, **fixture["arguments"])
    for change in ("version", "extra", "hash", "decision", "profile", "reason", "scope_extra"):
        pins = deepcopy(built["scientific_pins"])
        status = next(iter(pins.values()))
        if change == "version": status["version"] = "unknown/1"
        elif change == "extra": status["private"] = "rejected"
        elif change == "hash": status["scopes"][0]["decision_sha256"] = "0" * 64
        elif change == "decision": status["scopes"][0]["decision"] = "accept"
        elif change == "profile": status["scopes"][0]["profile_version"] = "invented/1"
        elif change == "reason": status["scopes"][0]["reason_codes"] = ["claimed_approval"]
        else: status["scopes"][0]["unknown"] = 1
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                await db_session.execute(sa.text("SELECT public.sclib_discovery_projection_science_v1(:id,CAST(:pins AS jsonb),false)"),
                    {"id": fixture["package"]["id"], "pins": service._json(pins)})
