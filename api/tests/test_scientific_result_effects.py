"""Actual exact-property review status, never source or training approval."""

from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa

from models.db import Base
from services import research_publication as publication
from services import scientific_result_effects as effects
from tests.test_research_freeze import add, state
from tests.test_research_freeze import db_session as _serializable_db_session
from tests.test_scientific_adjudication_schema import (
    accepted,
    capture,
    decision_for,
    fixture,
    item_for,
    request_for,
)

db_session = _serializable_db_session


async def next_transaction(db):
    """Observe changes after a completed decision, not a broken outer commit."""
    await db.commit()
    await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
    await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))


async def review(
    db, seeded, subject, *, decision="accept", scientific=False, predecessor=None, extraction=None
):
    await db.execute(sa.text("SET CONSTRAINTS ALL DEFERRED"))
    item = await item_for(
        db,
        subject,
        profile=(
            "sampled-phonon-minimum-review/1.0.0"
            if scientific
            else "native-sampled-frequency-extraction/1.0.0"
        ),
        decision=decision,
        predecessor=predecessor,
    )
    if extraction:
        item["extraction_decision_id"] = str(extraction)
    request = await request_for(db, seeded, [item])
    result = await decision_for(db, request, subject, item)
    await db.execute(sa.text("SET CONSTRAINTS sa67_complete IMMEDIATE"))
    return result


async def test_fidelity_acceptance_is_exact_private_scope_with_no_ml_or_source_rights(db_session):
    seeded, subject, _, decision = await accepted(db_session)
    before = await state(db_session)
    result = await effects.resolve_result_status(db_session, seeded["property_id"])
    assert result["subject_sha256"] == subject["subject_sha256"]
    fidelity, scientific = result["scopes"]
    assert (
        fidelity["decision_id"] == str(decision["id"])
        and fidelity["effective_status"] == "accepted"
    )
    assert fidelity["scientific_scope_accepted"] is False
    assert (
        scientific["effective_status"] == "unreviewed"
        and scientific["scientific_scope_accepted"] is False
    )
    assert result["ml_training_approved"] is result["public_release_authorized"] is False
    assert result == await effects.resolve_result_status(db_session, seeded["property_id"])
    assert await state(db_session) == before
    assert not {"basis", "text", "raw", "source_files", "actor_user_id", "actor_grant_id"} & set(
        result
    )


async def test_scientific_acceptance_depends_on_exact_current_fidelity(db_session):
    seeded, subject, _, fidelity = await accepted(db_session)
    await next_transaction(db_session)
    scientific = await review(
        db_session, seeded, subject, scientific=True, extraction=fidelity["id"]
    )
    first = await effects.resolve_result_status(db_session, seeded["property_id"])
    assert first["scopes"][1]["scientific_scope_accepted"] is True
    assert first["scopes"][1]["decision_id"] == str(scientific["id"])
    await next_transaction(db_session)
    await review(
        db_session, seeded, subject, decision="request_clarification", predecessor=fidelity["id"]
    )
    changed = await effects.resolve_result_status(db_session, seeded["property_id"])
    assert changed["scopes"][0]["effective_status"] == "clarification_required"
    assert changed["scopes"][1]["effective_status"] == "dependency_review_held"
    assert changed["scopes"][1]["scientific_scope_accepted"] is False
    assert changed["revision_sha256"] != first["revision_sha256"]


@pytest.mark.parametrize(
    "decision,expected",
    [
        ("accept", "reviewer_unavailable"),
        ("reject", "rejected"),
        ("request_clarification", "clarification_required"),
    ],
)
async def test_reviewer_revocation_removes_positive_but_does_not_erase_negative(
    db_session, decision, expected
):
    seeded = await fixture(db_session)
    subject = dict(
        await add(
            db_session,
            "scientific_result_subjects",
            **await capture(db_session, seeded["property_id"]),
        )
    )
    await review(db_session, seeded, subject, decision=decision)
    await next_transaction(db_session)
    await publication.revoke_role(
        db_session,
        actor_user_id=seeded["actors"]["admin"],
        grant_id=seeded["grant"]["id"],
        reason_code="synthetic_status_revocation",
        dry_run=False,
    )
    result = await effects.resolve_result_status(db_session, seeded["property_id"])
    assert result["scopes"][0]["effective_status"] == expected
    assert not result["scopes"][0]["scientific_scope_accepted"]


async def test_changed_exact_quantity_is_stale_not_an_old_accept_fallback(db_session):
    seeded, _, _, _ = await accepted(db_session)
    await next_transaction(db_session)
    props = Base.metadata.tables["event_properties"]
    await db_session.execute(
        props.update().where(props.c.id == seeded["property_id"]).values(value=0.5)
    )
    result = await effects.resolve_result_status(db_session, seeded["property_id"])
    assert result["scopes"][0]["effective_status"] == "stale"


@pytest.mark.parametrize(
    "field,value",
    [
        ("validity_status", "retracted"),
        ("validity_status", "excluded"),
        ("review_status", "rejected"),
    ],
)
async def test_explicit_negative_parent_is_live_hold_without_rewriting_basis(
    db_session, field, value
):
    seeded, subject, _, _ = await accepted(db_session)
    await next_transaction(db_session)
    events = Base.metadata.tables["research_events"]
    await db_session.execute(
        events.update().where(events.c.id == subject["event_id"]).values(**{field: value})
    )
    result = await effects.resolve_result_status(db_session, seeded["property_id"])
    assert result["subject_sha256"] == subject["subject_sha256"]
    assert result["scopes"][0]["effective_status"] == "source_held"


async def test_unrelated_sibling_is_unreviewed_and_does_not_change_existing_effect(db_session):
    seeded, subject, _, _ = await accepted(db_session)
    await next_transaction(db_session)
    before = await effects.resolve_result_status(db_session, seeded["property_id"])
    sibling = uuid4()
    await add(
        db_session,
        "event_properties",
        id=sibling,
        event_id=subject["event_id"],
        property_key="phonon_min_frequency",
        registry_version="rv2/1",
        component_key="unrelated-sibling",
        relation="exact",
        value=3.0,
        unit="THz",
        uncertainty={},
        raw={},
        record_sha256="b" * 64,
    )
    assert await effects.resolve_result_status(db_session, seeded["property_id"]) == before
    other = await effects.resolve_result_status(db_session, sibling)
    assert all(scope["effective_status"] == "unreviewed" for scope in other["scopes"])


async def test_exact_gate_preserves_unreviewed_policy_and_restores_caller_settings(db_session):
    seeded = await fixture(db_session)
    await db_session.execute(sa.text("SET LOCAL statement_timeout=0"))
    before = await state(db_session)
    first = await effects.gate_exact_property_reviews(db_session, [seeded["property_id"]])
    assert len(first) == 64 and await db_session.scalar(sa.text("SHOW statement_timeout")) == "0"
    assert await state(db_session) == before
    # It cannot fabricate a subject/source review for an unreviewed property.
    assert (
        before["scientific_result_subjects"]
        == (await state(db_session))["scientific_result_subjects"]
    )


async def test_negative_only_gate_is_exact_and_readonly_including_epochs(db_session):
    seeded, subject, _, decision = await accepted(db_session)
    first = await effects.gate_exact_property_reviews(db_session, [seeded["property_id"]])
    await next_transaction(db_session)
    await review(db_session, seeded, subject, decision="reject", predecessor=decision["id"])
    before = await state(db_session)
    with pytest.raises(effects.ScientificResultReviewHeld):
        await effects.gate_exact_property_reviews(db_session, [seeded["property_id"]])
    assert await state(db_session) == before
    assert len(await effects.gate_exact_property_reviews(db_session, [uuid4()])) == len(first)


async def test_consumer_gate_checks_all_21_actual_reviews_with_one_shared_budget(
    db_session, monkeypatch
):
    """Distinct synthetic rows are not a claim of independent scientific evidence."""
    seeded = await fixture(db_session)
    table = Base.metadata.tables["event_properties"]
    original = dict(
        (await db_session.execute(sa.select(table).where(table.c.id == seeded["property_id"])))
        .mappings()
        .one()
    )
    values = {key: value for key, value in original.items() if key not in {"id", "created_at"}}
    properties = sorted(uuid4() for _ in range(21))
    for index, property_id in enumerate(properties):
        await add(
            db_session,
            "event_properties",
            **{
                **values,
                "id": property_id,
                "component_key": f"synthetic-consumer-{index}",
                "record_sha256": "a" * 64,
            },
        )
    subjects = [
        dict(await add(db_session, "scientific_result_subjects", **await capture(db_session, key)))
        for key in properties
    ]
    profile = "recorded-sampled-frequency-fidelity/1.0.0"
    items = [await item_for(db_session, subject, profile=profile) for subject in subjects]
    decisions = []
    for offset in (0, 20):
        await db_session.execute(sa.text("SET CONSTRAINTS ALL DEFERRED"))
        batch = items[offset : offset + 20]
        request = await request_for(db_session, seeded, batch)
        for index, item in enumerate(batch):
            decisions.append(
                await decision_for(db_session, request, subjects[offset + index], item, index=index)
            )
        await db_session.execute(sa.text("SET CONSTRAINTS sa67_complete IMMEDIATE"))
    await next_transaction(db_session)
    before = await state(db_session)
    resolve, observed = effects._resolve, []

    async def observed_resolve(db, property_id, budget):
        result = await resolve(db, property_id, budget)
        observed.append((property_id, id(budget), budget["bytes"]))
        return result

    monkeypatch.setattr(effects, "_resolve", observed_resolve)
    assert effects.MAX_RESULTS == 20 and effects.MAX_GATE_RESULTS == 200
    assert len(await effects.gate_exact_property_reviews(db_session, properties)) == 64
    assert [value[0] for value in observed] == properties
    assert len({value[1] for value in observed}) == 1
    assert all(left[2] < right[2] for left, right in zip(observed, observed[1:]))
    total_bytes = observed[-1][2]
    assert await state(db_session) == before
    with monkeypatch.context() as boundary:
        boundary.setattr(effects, "MAX_GATE_RESULTS", 20)
        with pytest.raises(effects.ScientificResultStatusUnavailable):
            await effects.gate_exact_property_reviews(db_session, properties)
    with monkeypatch.context() as boundary:
        boundary.setattr(effects, "MAX_BYTES", total_bytes - 1)
        with pytest.raises(effects.ScientificResultStatusUnavailable):
            await effects.gate_exact_property_reviews(db_session, properties)
    assert await state(db_session) == before
    item = await item_for(
        db_session,
        subjects[-1],
        profile=profile,
        decision="reject",
        predecessor=decisions[-1]["id"],
    )
    request = await request_for(db_session, seeded, [item])
    await decision_for(db_session, request, subjects[-1], item)
    await db_session.execute(sa.text("SET CONSTRAINTS sa67_complete IMMEDIATE"))
    observed.clear()
    with pytest.raises(effects.ScientificResultReviewHeld):
        await effects.gate_exact_property_reviews(db_session, properties)
    assert [value[0] for value in observed] == properties  # the 21st result is not dropped


@pytest.mark.parametrize("values", [[uuid4()] * 2, [uuid4() for _ in range(21)], "not-a-list"])
async def test_bounded_status_inventory_rejects_duplicates_and_oversized_inputs(values):
    with pytest.raises(effects.ScientificResultStatusUnavailable):
        await effects.resolve_result_statuses(None, values)


async def test_database_failure_is_unavailable_not_unreviewed(db_session, monkeypatch):
    from unittest.mock import AsyncMock

    from services.scientific_result_subject import ScientificSubjectUnavailable

    seeded = await fixture(db_session)
    monkeypatch.setattr(
        effects,
        "capture_result_subject",
        AsyncMock(side_effect=ScientificSubjectUnavailable("PRIVATE_FAILURE")),
    )
    with pytest.raises(effects.ScientificResultStatusUnavailable) as exc:
        await effects.resolve_result_status(db_session, seeded["property_id"])
    assert "PRIVATE_FAILURE" not in str(exc.value)
