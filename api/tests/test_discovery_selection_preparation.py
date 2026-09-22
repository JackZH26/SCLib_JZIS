"""Curator preparation over real, disposable, synthetic registered rows.

This tests transport and scientific data integrity, not real scientific review,
disclosure rights, a production pilot or authorization to train a model.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from uuid import uuid4

import pytest
import sqlalchemy as sa

from models.db import Base
from routers import discovery_projections as router
from services import discovery_scientific_projection as projection
from services import discovery_selection_preparation as service
from services import research_distribution as distribution
from services import research_publication as publication
from services.research_distribution_contract import _bounded
from tests.rps_distribution_fixtures import distribution_inputs, release_document, source_context
from tests.test_discovery_projection_http import (
    BASE,
    protected,
    track_material,
)
from tests.test_discovery_projection_http import (
    isolate_owned_materials as isolate_owned_materials,
)
from tests.test_discovery_projection_http import (
    people as people,
)
from tests.test_discovery_scientific_cells import CANARY, read_settings, review_cell
from tests.test_discovery_scientific_projection import (
    add_assessment,
    projected_fixture,
    selection_for,
    verified_bundle,
)
from tests.test_priority_public_bundle import reseal_public_release
from tests.test_research_distribution_operators import auth
from tests.test_research_freeze import add, state
from tests.test_research_freeze import db_session as db_session


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def source_for(fixture):
    text = _bounded(fixture["bundle"]).decode()
    return {
        "distribution_package_id": fixture["arguments"]["distribution_package_id"],
        "public_bundle_json": text,
        "expected_public_bundle_text_sha256": sha(text),
    }


def choices_for(selection):
    return [
        {
            "material_id": c["material"]["id"],
            "assessment_id": c["assessment"]["id"],
            "structure_id": c["structure"]["row_id"] if c["structure"] else None,
            "rationale": c["rationale"],
            "cells": [
                {k: deepcopy(v) for k, v in cell.items() if k != "result_refs"}
                for cell in c["cells"]
            ],
        }
        for c in selection["representatives"]
    ]


async def context_for(client, db, **options):
    fixture = await projected_fixture(db, **options)
    track_material(db, fixture)
    await db.commit()
    source, headers = source_for(fixture), auth(fixture["actors"]["curator"])
    response = await client.post(
        BASE + "/selection/context", json={"source": source}, headers=headers
    )
    assert response.status_code == 200, response.text
    protected(response)
    result = response.json()
    assert sha(result["context_json"]) == result["context_sha256"]
    return fixture, source, result, json.loads(result["context_json"]), headers


def preparation_request(fixture, source, context):
    return {
        "source": source,
        "expected_context_sha256": context["context_sha256"],
        "request_key": "synthetic-selection:" + uuid4().hex,
        "choices": choices_for(fixture["selection"]),
    }


async def test_actual_selection_context_prepare_preview_commit_and_original_recovery(
    client, db_session
):
    fixture, source, envelope, context, headers = await context_for(
        client, db_session, structure=True, sample=True
    )
    before = await state(db_session)
    await db_session.rollback()
    access = await client.get(BASE + "/selection/access", headers=headers)
    assert access.status_code == 200, access.text
    assert access.json() == {
        "version": service.VERSION,
        "actor_user_id": str(fixture["actors"]["curator"]),
        "actor_grant_id": str(fixture["actors"]["grants"]["curator"]),
        "can_prepare_selection": True,
        **service.AUTHORITY,
    }
    assert set(envelope) == {"version", "context_json", "context_sha256", *service.AUTHORITY}
    assert context["quantity_basis"] == "frozen_inventory_not_current_scientific_acceptance"
    assert context["distribution_record_sha256"] == fixture["package"]["record_sha256"]
    assert context["inventory_sha256"] == fixture["package"]["inventory_sha256"]
    assert context["public_bundle_text_sha256"] == source["expected_public_bundle_text_sha256"]
    material = context["materials"][0]
    assert len(context["materials"]) == 1 and len(material["assessments"]) == 1
    assert material["material"]["row_id"] == fixture["source"]["material"]
    assert material["structures"][0] == {"reference": None, "structure_kind": "not_selected"}
    assert material["structures"][1]["reference"]["row_id"] == str(fixture["source"]["structure"])
    assert {r["property_key"] for r in material["results"]} == set(projection.REGISTRY)
    assert {e["reference"]["table"] for e in material["declaration_evidence"]} == {
        "event_evidence",
        "evidence_artifacts",
        "research_runs",
    }
    assert all(
        e["structure_id"] == str(fixture["source"]["structure"])
        for e in material["declaration_evidence"]
    )
    assert "selected_assessment" not in material  # No first/highest-score default.

    request = preparation_request(fixture, source, envelope)
    prepared_response = await client.post(
        BASE + "/selection/prepare", json=request, headers=headers
    )
    assert prepared_response.status_code == 200, prepared_response.text
    prepared = prepared_response.json()
    assert set(prepared) == {
        "version",
        "actor_user_id",
        "actor_grant_id",
        "context_sha256",
        "request_key",
        "request_sha256",
        "payload_json",
        "payload_sha256",
        "selection_sha256",
        "preview_json",
        "preview_sha256",
        "commit_json",
        "commit_sha256",
        *service.AUTHORITY,
    }
    assert all(prepared[k] is False for k in service.AUTHORITY)
    for stem in ("payload", "preview", "commit"):
        assert sha(prepared[stem + "_json"]) == prepared[stem + "_sha256"]
    payload = json.loads(prepared["payload_json"])
    assert payload["selection"] == fixture["selection"]
    assert len(payload["rows"][0]["cells"]) == 8
    observations = [o for c in payload["rows"][0]["cells"] for o in c["observations"]]
    assert len(observations) == 8 and not any(o["scientific_scope_accepted"] for o in observations)
    assert CANARY not in prepared_response.text
    # String transport preserves canonical Python float lexemes end-to-end.
    assert '"value":0' in prepared["payload_json"]
    assert '"value":-0.125' in prepared["payload_json"]
    preview_command, commit_command = (
        json.loads(prepared[name + "_json"]) for name in ("preview", "commit")
    )
    assert preview_command == {**commit_command, "dry_run": True}
    assert commit_command["dry_run"] is False
    assert prepared["context_sha256"] == envelope["context_sha256"]
    preview = await client.post(
        BASE + "/register",
        content=prepared["preview_json"],
        headers={**headers, "Content-Type": "application/json"},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["committed"] is False
    for key in ("request_sha256", "payload_sha256", "selection_sha256"):
        assert preview.json()["result"][key] == prepared[key]
    assert before == await state(db_session)  # Context, preparation and rehearsal never write.
    await db_session.rollback()
    outcome_query = {
        "operation": "register",
        "request_key": prepared["request_key"],
        "expected_request_sha256": prepared["request_sha256"],
    }
    absent = await client.get(BASE + "/outcome", params=outcome_query, headers=headers)
    assert absent.status_code == 404
    committed = await client.post(
        BASE + "/register",
        content=prepared["commit_json"],
        headers={**headers, "Content-Type": "application/json"},
    )
    assert committed.status_code == 200, committed.text
    assert (
        committed.json()["committed"] is True and committed.json()["result"]["committed"] is False
    )
    assert committed.json()["result"]["id"] != preview.json()["result"]["id"]
    after = await state(db_session)
    assert (
        len(after["discovery_projection_packages"])
        == len(before["discovery_projection_packages"]) + 1
    )
    for table in (
        "discovery_projection_reviews",
        "discovery_projection_actions",
        "scientific_result_decisions",
        "research_distribution_permissions",
        "research_distribution_reviews",
        "research_distribution_actions",
    ):
        assert before[table] == after[table]
    await db_session.rollback()
    recovered = await client.get(BASE + "/outcome", params=outcome_query, headers=headers)
    assert (
        recovered.status_code == 200
        and recovered.json()["result"]["id"] == committed.json()["result"]["id"]
    )
    assert recovered.json()["result"]["replayed"] is True
    assert after == await state(db_session)
    for response in (access, prepared_response, preview, absent, committed, recovered):
        protected(response)


@pytest.mark.parametrize("role", [None, "admin", "member", "curator", "reviewer", "publisher"])
async def test_actual_selection_access_is_curator_only(client, people, role):
    response = await client.get(
        BASE + "/selection/access", headers={} if role is None else auth(people[role])
    )
    assert response.status_code == (200 if role == "curator" else 401 if role is None else 403), (
        response.text
    )
    protected(response)


@pytest.mark.parametrize("endpoint", ["context", "prepare"])
async def test_role_precedes_embedded_bundle_upload(client, people, monkeypatch, endpoint):
    async def forbidden(*_args, **_kwargs):
        pytest.fail("unadmitted source body was read")

    monkeypatch.setattr(router, "_body", forbidden)
    for role in (None, "admin", "member", "reviewer", "publisher"):
        response = await client.post(
            BASE + "/selection/" + endpoint,
            content=CANARY,
            headers={
                **({} if role is None else auth(people[role])),
                "Content-Type": "application/json",
                "Content-Length": "999999999",
            },
        )
        assert response.status_code == (401 if role is None else 403), response.text
        protected(response)


@pytest.mark.parametrize(
    "text",
    [
        "{}\n",
        '{"a":0,"a":0}',
        '{"a":1e-999}',
        '{"a":NaN}',
        '{"a":Infinity}',
        '{"a":1e999}',
        '{"a":"\\ud800"}',
        "[]",
        "null",
        '{"a":1e-7}',
    ],
)
def test_inner_bundle_must_be_bounded_closed_canonical_json(text):
    with pytest.raises(ValueError):
        service.capture_source(
            {
                "distribution_package_id": str(uuid4()),
                "public_bundle_json": text,
                "expected_public_bundle_text_sha256": sha(text),
            }
        )


@pytest.mark.parametrize("kind", ["depth", "nodes", "bytes", "hash"])
def test_inner_limits_precede_json_hydration(monkeypatch, kind):
    text = "[" * 60 + "0" + "]" * 60 if kind == "depth" else "[0,0,0,0,0,0]"
    if kind == "nodes":
        monkeypatch.setattr(service.contract, "MAX_NODES", 4)
    if kind == "bytes":
        monkeypatch.setattr(service, "MAX_BUNDLE_BYTES", 4)

    def forbidden(*_args, **_kwargs):
        pytest.fail("over-budget or wrong-hash inner text reached decoder")

    monkeypatch.setattr(service.public, "strict_json", forbidden)
    with pytest.raises(ValueError):
        service.capture_source(
            {
                "distribution_package_id": str(uuid4()),
                "public_bundle_json": text,
                "expected_public_bundle_text_sha256": "0" * 64 if kind == "hash" else sha(text),
            }
        )


@pytest.mark.parametrize(
    "change",
    [
        "extra",
        "no_cell",
        "cell_extra",
        "availability_type",
        "evidence_type",
        "evidence_extra",
        "missing_rationale",
        "duplicate_material",
        "unknown_structure",
        "unsorted_cells",
        "fabricated_result",
        "score",
    ],
)
def test_choice_capture_is_closed_and_never_accepts_values_or_scores(change):
    choices = choices_for(selection_for(verified_bundle()))
    choice, cell = choices[0], choices[0]["cells"][0]
    if change == "extra":
        choice["scientific_acceptance"] = True
    elif change == "no_cell":
        choice["cells"].pop()
    elif change == "cell_extra":
        cell["value"] = 1
    elif change == "availability_type":
        cell["availability"] = []
    elif change == "evidence_type":
        cell["evidence_refs"] = "paper"
    elif change == "evidence_extra":
        cell["evidence_refs"] = [
            {
                "table": "evidence_artifacts",
                "row_id": str(uuid4()),
                "row_sha256": "a" * 64,
                "license": "CC0",
            }
        ]
    elif change == "missing_rationale":
        choice["rationale"] = "  "
    elif change == "duplicate_material":
        choices.append(deepcopy(choice))
    elif change == "unknown_structure":
        choice["structure_id"] = "unknown"
    elif change == "unsorted_cells":
        choice["cells"].reverse()
    elif change == "fabricated_result":
        cell["result_refs"] = []
    elif change == "score":
        choice["rps_score"] = 10000
    with pytest.raises(ValueError):
        service.capture_choices(choices)


@pytest.mark.parametrize(
    "change",
    [
        "pin",
        "bundle",
        "foreign_assessment",
        "foreign_structure",
        "foreign_evidence",
        "no_evidence",
        "hide_results",
    ],
)
async def test_preparation_rejects_drift_and_fabricated_selection_without_write(
    client, db_session, change
):
    fixture, source, envelope, context, headers = await context_for(
        client, db_session, structure=True
    )
    request = preparation_request(fixture, source, envelope)
    cell = next(c for c in request["choices"][0]["cells"] if c["property_key"] == "band_gap")
    if change == "pin":
        request["expected_context_sha256"] = "0" * 64
    elif change == "bundle":
        request["source"]["public_bundle_json"] = "{}"
        request["source"]["expected_public_bundle_text_sha256"] = sha("{}")
    elif change == "foreign_assessment":
        request["choices"][0]["assessment_id"] = "absent"
    elif change == "foreign_structure":
        request["choices"][0]["structure_id"] = str(uuid4())
    elif change == "foreign_evidence":
        cell["evidence_refs"] = [
            {"table": "research_runs", "row_id": str(uuid4()), "row_sha256": "a" * 64}
        ]
    elif change == "no_evidence":
        cell.update(availability="conflicted", reason_code="declared_conflict")
    elif change == "hide_results":
        cell.update(availability="unknown", reason_code="no_matching_registered_result")
    before = await state(db_session)
    await db_session.rollback()
    response = await client.post(BASE + "/selection/prepare", json=request, headers=headers)
    assert response.status_code == (409 if change == "pin" else 400), response.text
    assert before == await state(db_session)
    protected(response)


async def test_null_structure_is_exact_and_cannot_borrow_evidence(client, db_session):
    fixture, source, envelope, context, headers = await context_for(
        client, db_session, structure=True
    )
    request = preparation_request(fixture, source, envelope)
    request["choices"][0]["structure_id"] = None
    for cell in request["choices"][0]["cells"]:
        cell.update(
            availability="unknown", reason_code="no_matching_registered_result", evidence_refs=[]
        )
    good = await client.post(BASE + "/selection/prepare", json=request, headers=headers)
    assert good.status_code == 200, good.text
    row = json.loads(good.json()["payload_json"])["rows"][0]
    assert row["structure"] is None and all(c["observations"] == [] for c in row["cells"])
    request["choices"][0]["cells"][0].update(
        availability="not_computed",
        reason_code="declared_not_computed",
        evidence_refs=[context["materials"][0]["declaration_evidence"][0]["reference"]],
    )
    bad = await client.post(BASE + "/selection/prepare", json=request, headers=headers)
    assert bad.status_code == 400, bad.text
    protected(good)
    protected(bad)


@pytest.mark.parametrize("change", ["session", "grant"])
async def test_current_identity_is_rechecked_after_preparation_upload(client, db_session, change):
    fixture, source, envelope, context, headers = await context_for(client, db_session)
    request = preparation_request(fixture, source, envelope)
    expected = []

    async def stream():
        raw = json.dumps(request).encode()
        yield raw[:20]
        if change == "session":
            users = Base.metadata.tables["users"]
            await db_session.execute(
                sa.update(users)
                .where(users.c.id == fixture["actors"]["curator"])
                .values(session_version=1)
            )
        else:
            await publication.revoke_role(
                db_session,
                actor_user_id=fixture["actors"]["admin"],
                grant_id=fixture["actors"]["grants"]["curator"],
                reason_code="synthetic_selection_upload",
                dry_run=False,
            )
        await db_session.commit()
        expected.append(await state(db_session))
        await db_session.rollback()
        yield raw[20:]

    response = await client.post(
        BASE + "/selection/prepare",
        content=stream(),
        headers={**headers, "Content-Type": "application/json"},
    )
    assert response.status_code == 403, response.text
    assert expected == [await state(db_session)]
    protected(response)


async def test_context_pin_binds_original_actor_and_grant(client, db_session):
    fixture, source, envelope, context, headers = await context_for(client, db_session)
    people = fixture["actors"]
    await publication.grant_role(
        db_session,
        actor_user_id=people["admin"],
        user_id=people["member"],
        role="curator",
        reason_code="synthetic_other_curator",
        dry_run=False,
    )
    await db_session.commit()
    request = preparation_request(fixture, source, envelope)
    other = await client.post(
        BASE + "/selection/prepare", json=request, headers=auth(people["member"])
    )
    assert other.status_code == 409, other.text
    await publication.revoke_role(
        db_session,
        actor_user_id=people["admin"],
        grant_id=people["grants"]["curator"],
        reason_code="synthetic_replacement",
        dry_run=False,
    )
    await publication.grant_role(
        db_session,
        actor_user_id=people["admin"],
        user_id=people["curator"],
        role="curator",
        reason_code="synthetic_replacement",
        dry_run=False,
    )
    await db_session.commit()
    replacement = await client.post(BASE + "/selection/prepare", json=request, headers=headers)
    assert replacement.status_code == 409, replacement.text
    fresh = await client.post(BASE + "/selection/context", json={"source": source}, headers=headers)
    assert fresh.status_code == 200 and fresh.json()["context_sha256"] != envelope["context_sha256"]
    for response in (other, replacement, fresh):
        protected(response)


async def test_later_scientific_acceptance_requires_new_payload_pin_not_in_place_approval(
    client, db_session
):
    fixture, source, envelope, context, headers = await context_for(
        client,
        db_session,
        properties=[{"property_key": "phonon_min_frequency", "relation": "exact", "value": -0.125}],
    )
    request = preparation_request(fixture, source, envelope)
    first = await client.post(BASE + "/selection/prepare", json=request, headers=headers)
    assert first.status_code == 200, first.text
    before_packages = (await state(db_session))["discovery_projection_packages"]
    await read_settings(db_session)
    await review_cell(db_session, fixture, scientific=True)
    await db_session.commit()
    stale = await client.post(
        BASE + "/register",
        content=first.json()["commit_json"],
        headers={**headers, "Content-Type": "application/json"},
    )
    assert stale.status_code == 409, stale.text
    assert (await state(db_session))["discovery_projection_packages"] == before_packages
    await db_session.rollback()
    second = await client.post(BASE + "/selection/prepare", json=request, headers=headers)
    assert second.status_code == 200, second.text
    assert second.json()["payload_sha256"] != first.json()["payload_sha256"]
    # Context states frozen quantities only; actual science is compiled anew.
    assert second.json()["context_sha256"] == first.json()["context_sha256"]
    for response in (first, stale, second):
        protected(response)


@pytest.mark.parametrize("alias", [False, True])
async def test_actual_alternatives_retain_explicit_lower_score_and_reject_native_alias(
    client, db_session, alias
):
    shared = await source_context(db_session)
    fixture = {"source": shared["source"], "actors": shared["actors"]}
    track_material(db_session, fixture)
    release = release_document(source_kind=shared["evidence_source_kind"])
    release["id"] = "synthetic-selection-alternatives:" + uuid4().hex
    add_assessment(release, "lower-action", new_material=alias)
    add_assessment(release, "another-action")
    release = reseal_public_release(release)
    inputs = await distribution_inputs(db_session, release, shared=shared)
    registered = await distribution.register_distribution(
        db_session,
        actor_user_id=fixture["actors"]["curator"],
        request_key=uuid4().hex,
        **inputs["arguments"],
        dry_run=False,
    )
    fixture.update(
        bundle=inputs["bundle"],
        selection=selection_for(inputs["bundle"], choose="lower-action"),
        arguments={"distribution_package_id": str(registered["package_id"])},
    )
    await db_session.commit()
    headers, source = auth(fixture["actors"]["curator"]), source_for(fixture)
    response = await client.post(
        BASE + "/selection/context", json={"source": source}, headers=headers
    )
    protected(response)
    if alias:
        assert response.status_code == 400, response.text
        return
    assert response.status_code == 200, response.text
    envelope = response.json()
    context = json.loads(envelope["context_json"])
    assert [a["reference"]["id"] for a in context["materials"][0]["assessments"]] == [
        "another-action",
        "lower-action",
        "test-1",
    ]
    prepared = await client.post(
        BASE + "/selection/prepare",
        json=preparation_request(fixture, source, envelope),
        headers=headers,
    )
    assert prepared.status_code == 200, prepared.text
    row = json.loads(prepared.json()["payload_json"])["rows"][0]
    assert row["representative"]["id"] == "lower-action"
    assert [a["reference"]["id"] for a in row["alternatives"]] == ["another-action", "test-1"]
    assert (
        row["assessment"]["result"]["score_display"]
        < row["alternatives"][1]["assessment"]["result"]["score_display"]
    )
    assert row["selection_rationale"] == fixture["selection"]["representatives"][0]["rationale"]
    protected(prepared)


async def test_exact_tiny_float_survives_context_preparation_and_native_rehearsal(
    client, db_session
):
    fixture, source, envelope, context, headers = await context_for(
        client,
        db_session,
        properties=[{"property_key": "band_gap", "relation": "exact", "value": 1e-7}],
    )
    assert '"value":1e-07' in envelope["context_json"]
    assert context["materials"][0]["results"][0]["quantity"]["value"] == 1e-7
    prepared = await client.post(
        BASE + "/selection/prepare",
        json=preparation_request(fixture, source, envelope),
        headers=headers,
    )
    assert prepared.status_code == 200, prepared.text
    raw = prepared.json()
    assert '"value":1e-07' in raw["payload_json"]
    rehearsal = await client.post(
        BASE + "/register",
        content=raw["preview_json"],
        headers={**headers, "Content-Type": "application/json"},
    )
    assert rehearsal.status_code == 200, rehearsal.text
    assert rehearsal.json()["result"]["payload_sha256"] == raw["payload_sha256"]
    protected(prepared)
    protected(rehearsal)


@pytest.mark.parametrize("change", ["material", "paper", "work", "scientific"])
async def test_current_source_holds_reject_context_and_preparation(client, db_session, change):
    fixture, source, envelope, context, headers = await context_for(
        client,
        db_session,
        properties=[{"property_key": "phonon_min_frequency", "relation": "exact", "value": -0.125}],
    )
    if change == "scientific":
        await read_settings(db_session)
        await review_cell(db_session, fixture, decision="reject")
    else:
        table_name, field, value, identifier = {
            "material": ("materials", "needs_review", True, fixture["source"]["material"]),
            "paper": ("papers", "status", "retracted", fixture["source"]["paper"]),
            "work": ("works", "publication_status", "withdrawn", fixture["source"]["work"]),
        }[change]
        table = Base.metadata.tables[table_name]
        await db_session.execute(
            table.update().where(table.c.id == identifier).values(**{field: value})
        )
    await db_session.commit()
    before = await state(db_session)
    await db_session.rollback()
    for endpoint, request in (
        ("context", {"source": source}),
        ("prepare", preparation_request(fixture, source, envelope)),
    ):
        response = await client.post(BASE + "/selection/" + endpoint, json=request, headers=headers)
        assert response.status_code == 400, response.text
        assert before == await state(db_session)
        await db_session.rollback()
        protected(response)


@pytest.mark.parametrize(
    "kind", ["context_bytes", "candidate_results", "candidate_evidence", "prepared_bytes"]
)
async def test_budgets_refuse_whole_result_without_clipping_or_writing(
    client, db_session, monkeypatch, kind
):
    fixture, source, envelope, context, headers = await context_for(client, db_session)
    before = await state(db_session)
    await db_session.rollback()
    variable = {
        "context_bytes": "MAX_CONTEXT_BYTES",
        "candidate_results": "MAX_CANDIDATE_PROPERTIES",
        "candidate_evidence": "MAX_CANDIDATE_EVIDENCE",
        "prepared_bytes": "MAX_PREPARED_BYTES",
    }[kind]
    monkeypatch.setattr(service, variable, 1)
    endpoint = "prepare" if kind == "prepared_bytes" else "context"
    request = (
        preparation_request(fixture, source, envelope)
        if endpoint == "prepare"
        else {"source": source}
    )
    response = await client.post(BASE + "/selection/" + endpoint, json=request, headers=headers)
    assert response.status_code == 400, response.text
    assert before == await state(db_session)
    assert "context_json" not in response.json() and "payload_json" not in response.json()
    protected(response)


async def test_candidate_budget_is_independent_of_final_selected_property_cap(
    client, db_session, monkeypatch
):
    fixture, source, envelope, context, headers = await context_for(client, db_session)
    monkeypatch.setattr(projection, "MAX_PROPERTIES", 1)
    read = await client.post(BASE + "/selection/context", json={"source": source}, headers=headers)
    assert read.status_code == 200, read.text
    assert len(json.loads(read.json()["context_json"])["materials"][0]["results"]) == 8
    assert read.json()["context_sha256"] == envelope["context_sha256"]
    rejected = await client.post(
        BASE + "/selection/prepare",
        json=preparation_request(fixture, source, envelope),
        headers=headers,
    )
    assert rejected.status_code == 400, rejected.text
    protected(read)
    protected(rejected)


@pytest.mark.parametrize("endpoint", ["context", "prepare"])
async def test_preparation_transactions_are_repeatable_read_and_read_only(
    client, db_session, monkeypatch, endpoint
):
    fixture, source, envelope, context, headers = await context_for(client, db_session)
    name = "selection_context" if endpoint == "context" else "prepare_selection"
    original = getattr(service, name)
    checked = []

    async def verify(db, **arguments):
        assert await db.scalar(sa.text("SHOW transaction_read_only")) == "on"
        assert await db.scalar(sa.text("SHOW transaction_isolation")) == "repeatable read"
        assert await db.scalar(sa.text("SHOW statement_timeout")) == "10s"
        checked.append(True)
        return await original(db, **arguments)

    monkeypatch.setattr(service, name, verify)
    request = (
        {"source": source}
        if endpoint == "context"
        else preparation_request(fixture, source, envelope)
    )
    result = await client.post(BASE + "/selection/" + endpoint, json=request, headers=headers)
    assert result.status_code == 200, result.text
    assert checked == [True]
    protected(result)


@pytest.mark.parametrize("endpoint", ["context", "prepare"])
@pytest.mark.parametrize("change", ["query", "actor", "source_path", "source_extra", "wrong_type"])
async def test_closed_preparation_transport_never_reaches_service(
    client, people, monkeypatch, endpoint, change
):
    source = {
        "distribution_package_id": str(uuid4()),
        "public_bundle_json": "{}",
        "expected_public_bundle_text_sha256": sha("{}"),
    }
    request = {"source": source}
    if endpoint == "prepare":
        request.update(
            expected_context_sha256="a" * 64,
            request_key="synthetic-closed",
            choices=choices_for(selection_for(verified_bundle())),
        )
    if change == "actor":
        request["actor_user_id"] = str(people["curator"])
    elif change == "source_path":
        source["public_bundle_json"] = {"path": CANARY}
    elif change == "source_extra":
        source["public_release_authorized"] = True
    elif change == "wrong_type":
        request["source"] = []

    async def forbidden(*_args, **_kwargs):
        pytest.fail("unclosed request reached preparation")

    monkeypatch.setattr(
        service, "selection_context" if endpoint == "context" else "prepare_selection", forbidden
    )
    response = await client.post(
        BASE + "/selection/" + endpoint + ("?secret=value" if change == "query" else ""),
        json=request,
        headers=auth(people["curator"]),
    )
    assert response.status_code == 400, response.text
    protected(response)


async def test_multiple_components_are_complete_and_not_an_automatic_conflict(client, db_session):
    fixture, source, envelope, context, headers = await context_for(
        client,
        db_session,
        properties=[
            {
                "property_key": "band_gap",
                "relation": "exact",
                "value": value,
                "component_key": component,
            }
            for value, component in ((0, "spin-up"), (1, "spin-down"))
        ],
    )
    request = preparation_request(fixture, source, envelope)
    prepared = await client.post(BASE + "/selection/prepare", json=request, headers=headers)
    assert prepared.status_code == 200, prepared.text
    cell = next(
        c
        for c in json.loads(prepared.json()["payload_json"])["rows"][0]["cells"]
        if c["property_key"] == "band_gap"
    )
    assert {o["property"]["component_key"] for o in cell["observations"]} == {
        "spin-up",
        "spin-down",
    }
    assert len(cell["result_refs"]) == 2 and cell["availability"] == "reported"
    declaration = next(c for c in request["choices"][0]["cells"] if c["property_key"] == "band_gap")
    declaration.update(
        availability="conflicted",
        reason_code="synthetic_declared_conflict",
        evidence_refs=[context["materials"][0]["declaration_evidence"][0]["reference"]],
    )
    rejected = await client.post(BASE + "/selection/prepare", json=request, headers=headers)
    assert rejected.status_code == 400, rejected.text
    protected(prepared)
    protected(rejected)


@pytest.mark.parametrize("availability", ["not_computed", "not_applicable"])
async def test_positive_missingness_declarations_remain_unreviewed_not_zero(
    client, db_session, availability
):
    fixture, source, envelope, context, headers = await context_for(
        client, db_session, properties=[]
    )
    request = preparation_request(fixture, source, envelope)
    evidence = context["materials"][0]["declaration_evidence"][0]["reference"]
    declaration = next(c for c in request["choices"][0]["cells"] if c["property_key"] == "band_gap")
    declaration.update(
        availability=availability,
        reason_code="synthetic_missingness_declaration",
        evidence_refs=[evidence],
    )
    result = await client.post(BASE + "/selection/prepare", json=request, headers=headers)
    assert result.status_code == 200, result.text
    assert all(result.json()[key] is False for key in service.AUTHORITY)
    cell = next(
        c
        for c in json.loads(result.json()["payload_json"])["rows"][0]["cells"]
        if c["property_key"] == "band_gap"
    )
    assert (
        cell["availability"] == availability
        and cell["observations"] == []
        and cell["result_refs"] == []
    )
    assert (
        cell["evidence_refs"] == [evidence]
        and cell["availability_basis"] == "explicit_review_required_declaration"
    )
    protected(result)


async def test_real_same_capsule_other_state_evidence_is_not_a_declaration_option(
    client, db_session
):
    from services.research_release_manifest import canonical, digest

    async def another_state(db, source):
        document = {
            "synthetic_declaration": "No calculation for another state; not a real scientific finding."
        }
        payload, pin = canonical(document), digest(document)
        artifact = await add(
            db,
            "evidence_artifacts",
            kind="literature_locator",
            schema_version="synthetic/1",
            source="synthetic-selection-other-state",
            bytes_sha256=pin,
            record_sha256=pin,
            hash_status="verified",
            access="restricted",
        )
        source["args"]["artifact_bytes"][pin] = payload
        source["unrelated_artifact"] = artifact["id"]
        state_row = await add(
            db,
            "material_states",
            material_id=source["material"],
            resolution="source_scoped",
            condition_schema_version="synthetic/1",
            pressure_status="not_reported",
            temperature_role="unknown",
            context_sha256=digest({"other_state": True}),
            source_artifact_id=artifact["id"],
        )
        event = await add(
            db,
            "research_events",
            material_id=source["material"],
            state_id=state_row["id"],
            event_type="curation",
            knowledge_origin="Inferred",
            record_sha256=pin,
        )
        await add(
            db,
            "event_evidence",
            event_id=event["id"],
            link_type="source",
            artifact_id=artifact["id"],
            locator={"line": 8},
        )
        await add(
            db,
            "snapshot_event_memberships",
            snapshot_id=source["snapshot"],
            event_id=event["id"],
            event_revision=1,
            source_occurrence_key="synthetic-other-state",
            locator={"line": 8},
            source_record_sha256=pin,
            result_manifest_sha256=pin,
        )

    fixture, source, envelope, context, headers = await context_for(
        client, db_session, properties=[], before_freeze=another_state
    )
    dependency = next(
        r
        for r in fixture["inventory"]["dependencies"]
        if r["table"] == "evidence_artifacts"
        and r["row_id"] == str(fixture["source"]["unrelated_artifact"])
    )
    ref = {key: dependency[key] for key in ("table", "row_id", "row_sha256")}
    assert ref not in [e["reference"] for e in context["materials"][0]["declaration_evidence"]]
    request = preparation_request(fixture, source, envelope)
    cell = request["choices"][0]["cells"][0]
    for availability in ("not_computed", "not_applicable"):
        cell.update(
            availability=availability, reason_code="synthetic_wrong_state", evidence_refs=[ref]
        )
        rejected = await client.post(BASE + "/selection/prepare", json=request, headers=headers)
        assert rejected.status_code == 400, rejected.text
        protected(rejected)
