"""Explicit v2 interpretations on owned synthetic data, never real scientific approval."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from config import get_settings
from models.db import Base
from services import discovery_projection_governance as governance
from services import discovery_scientific_projection as projection
from services.research_priority import digest
from tests.test_discovery_projection_governance import reviewed_publication
from tests.test_discovery_projection_http import BASE, protected, track_material
from tests.test_discovery_projection_http import isolate_owned_materials as isolate_owned_materials
from tests.test_discovery_projection_http import people as people
from tests.test_discovery_scientific_cells import read_settings
from tests.test_discovery_scientific_projection import (
    projected_fixture,
    selection_for,
    verified_bundle,
)
from tests.test_discovery_selection_preparation import (
    choices_for,
    context_for,
    preparation_request,
    source_for,
)
from tests.test_research_distribution_operators import auth
from tests.test_research_freeze import db_session as db_session
from tests.test_research_freeze import state

V2 = "discovery-scientific-selection/2.0.0"
PAYLOAD_V2 = "discovery-scientific-projection/2.0.0"


def barrier(category="evidence_gap", key="superfluid_stiffness"):
    return {
        "status": "declared",
        "category": category,
        "statement": "Synthetic follow-up question, not an established causal obstacle.",
        "rationale": "The exact selected context needs further investigation; this does not establish superconductivity.",
        "basis_refs": [{"kind": "scientific_cell", "property_key": key}],
    }


def upgraded(selection, declaration=None):
    value = deepcopy(selection)
    value["version"] = V2
    for choice in value["representatives"]:
        choice["main_barrier"] = deepcopy(
            declaration if declaration is not None else {"status": "not_declared"}
        )
    return value


def arguments(fixture, declaration=None):
    selected = upgraded(fixture["selection"], declaration)
    return {
        **fixture["arguments"],
        "selection": selected,
        "expected_selection_sha256": digest(selected),
    }


def capture(selection):
    return projection.capture_selection(selection, digest(selection))


def test_v1_remains_exact_and_v2_nondeclaration_is_explicit_detached():
    old = selection_for(verified_bundle())
    assert capture(old) == old and "main_barrier" not in old["representatives"][0]
    new = upgraded(old)
    result = capture(new)
    new["representatives"][0]["main_barrier"]["status"] = "declared"
    assert result["representatives"][0]["main_barrier"] == {"status": "not_declared"}
    assert digest(result) != digest(old)
    old["representatives"][0]["main_barrier"] = {"status": "not_declared"}
    with pytest.raises(ValueError):
        capture(old)


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "null",
        "string",
        "extra",
        "status_bool",
        "status_future",
        "missing_category",
        "category_future",
        "empty_statement",
        "long_statement",
        "blank_rationale",
        "long_rationale",
        "control",
        "del",
        "empty_refs",
        "many_refs",
        "duplicate",
        "unsorted",
        "ref_extra",
        "ref_kind",
        "ref_key",
        "code_invalid",
        "code_bool",
        "unknown_key",
        "future_selection",
    ],
)
def test_closed_v2_barrier_capture_rejects_malformed_or_implicit_choices(change):
    selected = upgraded(selection_for(verified_bundle()), barrier())
    choice = selected["representatives"][0]
    b = choice["main_barrier"]
    if change == "missing":
        del choice["main_barrier"]
    elif change == "null":
        choice["main_barrier"] = None
    elif change == "string":
        choice["main_barrier"] = "not_declared"
    elif change == "extra":
        b["scientific_acceptance"] = True
    elif change == "status_bool":
        b["status"] = True
    elif change == "status_future":
        b["status"] = "automatically_inferred"
    elif change == "missing_category":
        del b["category"]
    elif change == "category_future":
        b["category"] = "physical_proof"
    elif change == "empty_statement":
        b["statement"] = "  "
    elif change == "long_statement":
        b["statement"] = "x" * 501
    elif change == "blank_rationale":
        b["rationale"] = "\n\t"
    elif change == "long_rationale":
        b["rationale"] = "x" * 2001
    elif change == "control":
        b["statement"] = "hidden\x01text"
    elif change == "del":
        b["rationale"] = "hidden\x7ftext"
    elif change == "empty_refs":
        b["basis_refs"] = []
    elif change == "many_refs":
        b["basis_refs"] *= 9
    elif change == "duplicate":
        b["basis_refs"] *= 2
    elif change == "unsorted":
        b["basis_refs"] += [{"kind": "scientific_cell", "property_key": "band_gap"}]
    elif change == "ref_extra":
        b["basis_refs"][0]["url"] = "https://invalid.example/source"
    elif change == "ref_kind":
        b["basis_refs"][0]["kind"] = "remote_source"
    elif change == "ref_key":
        b["basis_refs"][0]["row_sha256"] = "0" * 64
    elif change == "code_invalid":
        b["basis_refs"] = [{"kind": "assessment_reason", "code": "hidden\x01code"}]
    elif change == "code_bool":
        b["basis_refs"] = [{"kind": "assessment_reason", "code": False}]
    elif change == "unknown_key":
        b["basis_refs"][0]["property_key"] = "rps_score"
    else:
        selected["version"] = "discovery-scientific-selection/3.0.0"
    with pytest.raises(ValueError):
        capture(selected)


@pytest.mark.parametrize("extra", ["statement", "category", "rationale", "basis_refs"])
def test_nondeclaration_does_not_conceal_an_unreviewed_interpretation(extra):
    selected = upgraded(selection_for(verified_bundle()))
    selected["representatives"][0]["main_barrier"][extra] = barrier()[extra]
    with pytest.raises(ValueError):
        capture(selected)


def test_policy_reason_is_selected_not_inferred_from_scores_or_other_action():
    from services.discovery_main_barrier import validate_context, validate_shape

    chosen = {
        "reason_codes": ["missing:DFPT.Input"],
        "execution_constraint_reasons": ["budget:DFPT"],
    }
    b = barrier("recorded_policy_reason")
    b["basis_refs"] = [{"kind": "assessment_reason", "code": "missing:DFPT.Input"}]
    validate_shape(b, property_keys=projection.REGISTRY)
    validate_context(b, result=chosen, cells=[])
    with pytest.raises(ValueError):
        validate_context(
            b, result={"reason_codes": [], "execution_constraint_reasons": []}, cells=[]
        )
    b["category"] = "execution_constraint"
    b["basis_refs"] = [{"kind": "execution_constraint", "code": "budget:DFPT"}]
    validate_context(b, result=chosen, cells=[])
    before = deepcopy(b)
    for scores in ([0, 100, None], [100, 0, None], [None, None, None]):
        validate_context(b, result={**chosen, "irrelevant_dimension_scores": scores}, cells=[])
        assert b == before


def test_statement_bounds_count_codepoints_without_reformatting_declaration():
    selected = upgraded(selection_for(verified_bundle()), barrier())
    b = selected["representatives"][0]["main_barrier"]
    b["statement"] = "λ" * 500
    b["rationale"] = "Explicit\nline\twith\rreturn."
    assert capture(selected) == selected
    b["statement"] += "λ"
    with pytest.raises(ValueError):
        capture(selected)


@pytest.mark.parametrize(
    "value,valid",
    [
        ("\u0085", False),
        ("\u00a0", False),
        ("\u2003", False),
        ("\u2028\u202f\u3000", False),
        ("\ufeff", True),
        ("λ\n\t", True),
        ("x\x7f", False),
    ],
)
async def test_native_and_python_barrier_unicode_text_agree(db_session, value, valid):
    from services.discovery_main_barrier import validate_shape

    b = barrier("recorded_policy_reason")
    b["statement"] = value
    b["basis_refs"] = [{"kind": "assessment_reason", "code": "test:Case"}]
    if valid:
        validate_shape(b, property_keys=projection.REGISTRY)
    else:
        with pytest.raises(ValueError):
            validate_shape(b, property_keys=projection.REGISTRY)
    assert (
        await db_session.scalar(
            sa.text(
                "SELECT public.sclib_discovery_main_barrier_v2(CAST(:barrier AS jsonb),CAST(:result AS jsonb),'[]'::jsonb)"
            ),
            {"barrier": json.dumps(b), "result": json.dumps({"reason_codes": ["test:Case"]})},
        )
        is valid
    )


async def test_native_basis_order_matches_unicode_codepoints_not_utf16(db_session):
    from services.discovery_main_barrier import validate_shape

    b = barrier("recorded_policy_reason")
    codes = ["test:\ue000", "test:\U00010000"]
    b["basis_refs"] = [{"kind": "assessment_reason", "code": code} for code in codes]
    validate_shape(b, property_keys=projection.REGISTRY)
    sql = sa.text(
        "SELECT public.sclib_discovery_main_barrier_v2(CAST(:barrier AS jsonb),CAST(:result AS jsonb),'[]'::jsonb)"
    )
    result = json.dumps({"reason_codes": codes})
    assert await db_session.scalar(sql, {"barrier": json.dumps(b), "result": result}) is True
    b["basis_refs"].reverse()
    with pytest.raises(ValueError):
        validate_shape(b, property_keys=projection.REGISTRY)
    assert await db_session.scalar(sql, {"barrier": json.dumps(b), "result": result}) is False


async def test_v2_same_context_gap_and_hypothesis_never_change_rps_or_v1(db_session):
    fixture = await projected_fixture(db_session, structure=True, sample=True)
    before = await state(db_session)
    old = (await projection.build_projection(db_session, **fixture["arguments"]))["payload"]
    for b in (
        {"status": "not_declared"},
        barrier(),
        barrier("scientific_hypothesis", "phonon_min_frequency"),
    ):
        value = (await projection.build_projection(db_session, **arguments(fixture, b)))["payload"]
        assert value["version"] == PAYLOAD_V2 and value["capabilities"] == old["capabilities"]
        assert (
            value["rows"][0]["main_barrier"]
            == value["selection"]["representatives"][0]["main_barrier"]
            == b
        )
        assert {k: v for k, v in value["rows"][0].items() if k != "main_barrier"} == old["rows"][0]
        assert all(value[k] is False for k in projection.AUTHORITY)
    assert before == await state(db_session)
    assert (await projection.build_projection(db_session, **fixture["arguments"]))["payload"] == old


@pytest.mark.parametrize(
    "category,key",
    [
        ("evidence_gap", "band_gap"),
        ("scientific_hypothesis", "superfluid_stiffness"),
        ("execution_constraint", "band_gap"),
        ("recorded_policy_reason", "band_gap"),
    ],
)
async def test_category_cannot_turn_unknown_into_physical_negative_or_data_into_execution_constraint(
    db_session, category, key
):
    fixture = await projected_fixture(db_session)
    with pytest.raises(ValueError):
        await projection.build_projection(db_session, **arguments(fixture, barrier(category, key)))


@pytest.mark.parametrize(
    "kind,category",
    [
        ("assessment_reason", "recorded_policy_reason"),
        ("execution_constraint", "execution_constraint"),
    ],
)
async def test_only_exact_selected_assessment_reason_codes_are_admitted(db_session, kind, category):
    fixture = await projected_fixture(db_session)
    row = fixture["bundle"]["rows"][0]
    key = "reason_codes" if kind == "assessment_reason" else "execution_constraint_reasons"
    b = barrier(category)
    b["basis_refs"] = [{"kind": kind, "code": "invented_unretained_reason"}]
    with pytest.raises(ValueError):
        await projection.build_projection(db_session, **arguments(fixture, b))
    for code in row["result"][key]:
        b["basis_refs"] = [{"kind": kind, "code": code}]
        result = await projection.build_projection(db_session, **arguments(fixture, b))
        assert result["payload"]["rows"][0]["main_barrier"] == b


async def test_foreign_structure_results_and_stale_result_hash_cannot_back_a_barrier(db_session):
    fixture = await projected_fixture(db_session, structure=True)
    original = arguments(fixture, barrier("scientific_hypothesis", "phonon_min_frequency"))
    for change in ("structure", "result_hash"):
        args = deepcopy(original)
        c = args["selection"]["representatives"][0]
        if change == "structure":
            c["structure"] = None
        else:
            cell = next(
                cell for cell in c["cells"] if cell["property_key"] == "phonon_min_frequency"
            )
            cell["result_refs"][0]["row_sha256"] = "0" * 64
        args["expected_selection_sha256"] = digest(args["selection"])
        with pytest.raises(ValueError):
            await projection.build_projection(db_session, **args)


async def test_v2_preparation_requires_opt_in_and_does_not_silently_upgrade_v1(client, db_session):
    fixture, source, envelope, context, headers = await context_for(client, db_session)
    request = preparation_request(fixture, source, envelope)
    for endpoint, choices in (
        ("prepare-v2", request["choices"]),
        (
            "prepare",
            [{**c, "main_barrier": {"status": "not_declared"}} for c in request["choices"]],
        ),
    ):
        result = await client.post(
            BASE + "/selection/" + endpoint, json={**request, "choices": choices}, headers=headers
        )
        assert result.status_code == 400, result.text
        protected(result)
    request["choices"] = [
        {**c, "main_barrier": {"status": "not_declared"}} for c in request["choices"]
    ]
    result = await client.post(BASE + "/selection/prepare-v2", json=request, headers=headers)
    assert result.status_code == 200, result.text
    payload = json.loads(result.json()["payload_json"])
    assert payload["version"] == PAYLOAD_V2
    assert payload["rows"][0]["main_barrier"] == {"status": "not_declared"}
    # Context never chooses a default barrier, primary reason or low-score cell.
    assert "main_barrier" not in context["materials"][0]


async def test_v2_unadmitted_body_is_not_read(client, people, monkeypatch):
    from routers import discovery_projections as router

    async def forbidden(*_args, **_kwargs):
        pytest.fail("unadmitted body read")

    monkeypatch.setattr(router, "_body", forbidden)
    for role in (None, "admin", "member", "reviewer", "publisher"):
        result = await client.post(
            BASE + "/selection/prepare-v2",
            content="not json",
            headers={} if role is None else auth(people[role]),
        )
        assert result.status_code == (401 if role is None else 403), result.text


async def test_barrier_edit_needs_new_preview_package_and_independent_review_then_source_hold(
    client, db_session, monkeypatch, tmp_path
):
    repo = Path(__file__).resolve().parents[2]
    pinned = sorted(
        {
            *repo.glob("api/models/*.py"),
            *repo.glob("api/services/*.py"),
            *repo.glob("api/services/*.schema.json"),
            *repo.glob("api/routers/*.py"),
            *repo.glob("api/tests/test_discovery*.py"),
            *repo.glob("api/tests/test_research*.py"),
            *repo.glob("api/tests/rps*.py"),
            repo / "api/config.py",
            repo / "api/main.py",
            repo / "api/tests/conftest.py",
            repo / "api/tests/test_priority_public_bundle.py",
            repo / "api/tests/test_scientific_adjudication_schema.py",
        }
    )
    source_pins = [
        {"path": str(p.relative_to(repo)), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in pinned
    ]
    seeded = await reviewed_publication(db_session, publish=False)
    fixture = seeded["fixture"]
    track_material(db_session, fixture)
    people = fixture["actors"]
    await db_session.commit()
    headers = auth(people["curator"])
    selection_access = await client.get(BASE + "/selection/access", headers=headers)
    operator_access = await client.get(BASE + "/operator/access", headers=auth(people["reviewer"]))
    assert selection_access.status_code == operator_access.status_code == 200
    source = source_for(fixture)
    response = await client.post(
        BASE + "/selection/context", json={"source": source}, headers=headers
    )
    assert response.status_code == 200, response.text
    context_wire = response.text
    request = {
        "source": source,
        "expected_context_sha256": response.json()["context_sha256"],
        "request_key": uuid4().hex,
        "choices": choices_for(fixture["selection"]),
    }
    request["choices"][0]["main_barrier"] = barrier("scientific_hypothesis", "phonon_min_frequency")
    result = await client.post(BASE + "/selection/prepare-v2", json=request, headers=headers)
    assert result.status_code == 200, result.text
    prepared_wire = result.text
    first = result.json()
    original_request = deepcopy(request)
    request["choices"][0]["main_barrier"]["rationale"] += (
        " Additional explicitly declared limitation."
    )
    result = await client.post(BASE + "/selection/prepare-v2", json=request, headers=headers)
    assert result.status_code == 200, result.text
    second = result.json()
    for key in ("payload_sha256", "selection_sha256", "request_sha256"):
        assert first[key] != second[key]
    command = json.loads(second["commit_json"])
    command["expected_payload_sha256"] = first["payload_sha256"]
    rejected = await client.post(BASE + "/register", json=command, headers=headers)
    assert rejected.status_code == 409, rejected.text
    response = await client.post(
        BASE + "/register",
        content=first["commit_json"],
        headers={**headers, "Content-Type": "application/json"},
    )
    assert response.status_code == 200, response.text
    registered = response.json()["result"]
    response = await client.post(
        BASE + "/register",
        content=second["commit_json"],
        headers={**headers, "Content-Type": "application/json"},
    )
    assert response.status_code == 409, response.text  # Same key cannot replace interpretation.
    package = registered["package_id"]
    review = {
        k: v
        for k, v in seeded["review_arguments"].items()
        if k not in {"actor_user_id", "package_id"}
    }
    review.update(
        expected_payload_sha256=registered["payload_sha256"],
        expected_selection_sha256=registered["selection_sha256"],
        request_key=uuid4().hex,
        dry_run=False,
    )
    reviewed = await client.post(
        BASE + "/" + package + "/reviews", json=review, headers=auth(people["reviewer"])
    )
    assert reviewed.status_code == 200, reviewed.text
    action = {
        k: v
        for k, v in seeded["action_arguments"].items()
        if k not in {"actor_user_id", "package_id"}
    }
    action.update(
        expected_payload_sha256=registered["payload_sha256"],
        expected_selection_sha256=registered["selection_sha256"],
        request_key=uuid4().hex,
        dry_run=False,
    )
    rejected = await client.post(
        BASE + "/" + package + "/actions", json=action, headers=auth(people["publisher"])
    )
    assert rejected.status_code in {400, 409}, rejected.text  # v1 approval cannot be reused.
    action["review_id"] = reviewed.json()["result"]["id"]
    published = await client.post(
        BASE + "/" + package + "/actions", json=action, headers=auth(people["publisher"])
    )
    assert published.status_code == 200, published.text
    settings, bundle = get_settings(), fixture["bundle"]
    monkeypatch.setattr(settings, "discovery_scientific_public_enabled", True)
    monkeypatch.setattr(
        settings,
        "discovery_scientific_approved_projections",
        {package: registered["payload_sha256"]},
    )
    monkeypatch.setattr(settings, "discovery_rps_public_enabled", True)
    monkeypatch.setattr(
        settings,
        "discovery_rps_approved_releases",
        {bundle["release"]["id"]: bundle["release"]["manifest_sha256"]},
    )
    monkeypatch.setattr(
        settings,
        "discovery_rps_approved_public_bundles",
        {bundle["release"]["id"]: bundle["bundle_sha256"]},
    )
    path = "/v1/discovery/scientific/" + package
    public = await client.get(path)
    assert public.status_code == 200, public.text
    inspection = await client.get(BASE + "/" + package, headers=auth(people["reviewer"]))
    assert inspection.status_code == 200, inspection.text
    governance_header = await client.get(
        BASE + "/" + package + "/governance", headers=auth(people["reviewer"])
    )
    assert governance_header.status_code == 200, governance_header.text
    assert source_pins == [
        {"path": str(p.relative_to(repo)), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in pinned
    ]
    (tmp_path / "main-barrier-wire.json").write_text(
        json.dumps(
            {
                "fixture_notice": "Actual guarded SQL-to-HTTP synthetic v2 capture; no real scientific or rights approval.",
                "capture_test_path": "api/tests/test_discovery_main_barrier.py",
                "capture_test_name": "test_barrier_edit_needs_new_preview_package_and_independent_review_then_source_hold",
                "source_pins": source_pins,
                "selection_access_response": selection_access.text,
                "operator_access_response": operator_access.text,
                "governance_header_response": governance_header.text,
                "request": original_request,
                "context_response": context_wire,
                "prepared_response": prepared_wire,
                "inspection_response": inspection.text,
                "public_response": public.text,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    assert (
        public.json()["payload"]["rows"][0]["main_barrier"]
        == original_request["choices"][0]["main_barrier"]
    )
    assert public.json()["scientific_acceptance"] is public.json()["ml_training_approved"] is False
    await read_settings(db_session)
    await db_session.execute(
        sa.text("UPDATE materials SET needs_review=true WHERE id=:id"),
        {"id": fixture["source"]["material"]},
    )
    await db_session.commit()
    assert (await client.get(path)).status_code in {409, 503}
    history = await client.get(BASE + "/" + package + "/governance", headers=headers)
    assert history.status_code == 200, history.text
    negative = {
        **review,
        "request_key": uuid4().hex,
        "decision": "reject",
        "rights": [],
        "representative_selection_approved": False,
        "disclosure_approved": False,
    }
    rejected = await client.post(
        BASE + "/" + package + "/reviews", json=negative, headers=auth(people["reviewer"])
    )
    assert rejected.status_code == 200, rejected.text
    withdrawn = await client.post(
        BASE + "/" + package + "/actions",
        json={**action, "kind": "withdraw", "request_key": uuid4().hex},
        headers=auth(people["publisher"]),
    )
    assert withdrawn.status_code == 200, withdrawn.text


async def test_native_cannot_mix_versions_or_substitute_unhashed_row_barrier(db_session):
    fixture = await projected_fixture(db_session)
    args = {
        **arguments(fixture, barrier()),
        "actor_user_id": fixture["actors"]["curator"],
        "request_key": uuid4().hex,
    }
    preview = await governance.register_projection(db_session, **args)
    registered = await governance.register_projection(
        db_session, **args, expected_payload_sha256=preview["payload_sha256"], dry_run=False
    )
    original = await governance._get(db_session, "discovery_projection_packages", registered["id"])
    before = await state(db_session)
    for change in (
        "payload_v1",
        "future_version",
        "row_barrier",
        "extra_barrier",
        "missing_barrier",
    ):
        payload = json.loads(original["payload_json"])
        if change == "payload_v1":
            payload["version"] = projection.VERSION
        elif change == "future_version":
            payload["version"] = "discovery-scientific-projection/3.0.0"
        elif change == "row_barrier":
            payload["rows"][0]["main_barrier"] = {"status": "not_declared"}
        else:
            for c in (payload["rows"][0], payload["selection"]["representatives"][0]):
                if change == "extra_barrier":
                    c["main_barrier"]["score"] = 10000
                else:
                    del c["main_barrier"]
        selected = payload["selection"]
        payload["selection_sha256"] = digest(selected)
        values = {
            k: v for k, v in original.items() if k not in {"id", "record_sha256", "created_at"}
        }
        values.update(
            payload_json=governance._json(payload),
            payload_sha256=digest(payload),
            selection_json=governance._json(selected),
            selection_sha256=digest(selected),
            request_key=uuid4().hex,
            request_sha256="0" * 64,
        )
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                await db_session.execute(
                    Base.metadata.tables["discovery_projection_packages"].insert().values(**values)
                )
    assert before == await state(db_session)
