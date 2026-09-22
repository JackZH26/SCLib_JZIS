"""Actual owned PostgreSQL/HTTP checks; every event and reviewer is synthetic."""

from __future__ import annotations

import base64
import json
from datetime import timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa

from config import get_settings
from models.db import Base
from routers import ml_pilot_registration as router
from services import ml_pilot_accounting as accounting
from services import ml_pilot_documents as codec
from services import ml_pilot_registration as registration
from services import ml_pilot_review_documents as documents
from services.research_publication import revoke_role
from tests.test_ml_pilot_registration import confirmed, decision_args, fixture, registered
from tests.test_ml_pilot_registration_http import BASE, acceptance_headers
from tests.test_research_distribution_operators import auth
from tests.test_research_freeze import db_session as db_session
from tests.test_research_freeze import state


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setenv("ML_PILOT_REGISTRATION_ENABLED", "true")
    monkeypatch.setenv("ML_PILOT_REVIEW_INTAKE_ENABLED", "true")
    monkeypatch.setenv("ML_PILOT_ATTESTATIONS_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def prepared(db):
    f = await fixture(db)
    first = await registered(db, f["args"])
    heads = {}
    for member in first["participants"]:
        heads[member["id"]] = (await confirmed(db, decision_args(member, f["inputs"])))["decision"]
    await db.commit()
    at = await db.scalar(sa.select(sa.func.clock_timestamp()))
    await db.rollback()
    return f, first, heads, at


def packet(f, member, at, *, conclusion_at=None):
    selection = codec.json_value(f["inputs"]["selection_raw"])
    actors = {r["roles"][0]: r["id"] for r in selection["reviewers"]}
    rows = []
    for index, candidate in enumerate(selection["candidates"]):
        rows.append(
            {
                "schema_version": "ml08-review/1.0.0",
                "review_id": f"SYNTHETIC-review-{index}",
                "candidate_id": candidate["candidate_id"],
                "selection_sha256": selection["selection_sha256"],
                "reviewer_id": actors["primary"],
                "reviewer_kind": "human",
                "role": "primary",
                "revision": 1,
                "supersedes_review_id": None,
                "completed_at": at.isoformat(),
                "active_minutes": None,
                "active_minutes_by_field": {},
                "outcome": "inaccessible",
                "outcome_reason": "PRIVATE_SYNTHETIC_REVIEW",
                "independent_assessment": False,
                "requires_second_review": False,
                "compares_review_ids": [],
                "comparison": "not_compared",
                "disagreement_codes": [],
                "results": [],
            }
        )
    rows.append(
        {
            **rows[0],
            "review_id": "SYNTHETIC-secondary",
            "reviewer_id": actors["secondary"],
            "role": "secondary",
            "independent_assessment": True,
            "compares_review_ids": [rows[0]["review_id"]],
            "comparison": "agreement",
        }
    )
    root = Path(__file__).resolve().parents[2]
    conclusion = json.loads((root / "docs/pilot/conclusion.template.json").read_bytes())
    conclusion.update(
        status="submitted_for_signoff",
        selection_sha256=selection["selection_sha256"],
        review_log_sha256=accounting.review_hash(rows),
        reviewer_id=actors["arbitration"],
        completed_at=(conclusion_at or at).isoformat(),
        recommendation="stop",
        rationale="SYNTHETIC complete failure, not a real study",
        field_actions=[
            {"field": field, "action": "defer", "reason": "SYNTHETIC inaccessible"}
            for field in accounting.FIELDS
        ],
        canary_bundle_reference="SYNTHETIC_UNOPENED_CANARY",
        canary_bundle_sha256="c" * 64,
        limitations=["No actual events, humans or source permissions"],
    )
    raw = {
        "selection": f["inputs"]["selection_raw"],
        "protocol": f["inputs"]["protocol_raw"],
        "reviews": b"\n".join(accounting.canonical(r) for r in rows),
        "conclusion": accounting.canonical(conclusion),
    }
    return {
        "version": "ml08-review-upload/1.0.0",
        "parameters": {
            "participant_id": member["id"],
            "participant_sha256": member["record_sha256"],
            "registration_sha256": member["registration_sha256"],
        },
        "selection_sha256": selection["selection_sha256"],
        "review_log_sha256": conclusion["review_log_sha256"],
        **{name + "_file_sha256": documents.sha(value) for name, value in raw.items()},
        **{name + "_base64": base64.b64encode(value).decode() for name, value in raw.items()},
    }


def replace_document(payload, name, mutate):
    raw = base64.b64decode(payload[name + "_base64"])
    value = codec.review_records(raw) if name == "reviews" else codec.json_value(raw)
    mutate(value)
    raw = (
        b"\n".join(accounting.canonical(r) for r in value)
        if name == "reviews"
        else accounting.canonical(value)
    )
    payload[name + "_base64"] = base64.b64encode(raw).decode()
    payload[name + "_file_sha256"] = documents.sha(raw)
    return value


async def test_real_four_file_preflight_binds_each_account_without_any_database_write(
    client, db_session, tmp_path
):
    root = Path(__file__).resolve().parents[2]
    paths = sorted(
        {
            *(root / "api/models").glob("*.py"),
            *(root / "api/services").glob("*.py"),
            *(root / "api/services").glob("*.schema.json"),
            *(root / "api/routers").glob("*.py"),
            *(root / "api/tests").glob("*.py"),
            *(root / "scripts").glob("*.py"),
            root / "api/main.py",
            root / "api/config.py",
        }
    )

    def pins():
        return [
            {"path": str(path.relative_to(root)), "sha256": documents.sha(path.read_bytes())}
            for path in paths
        ]

    captured = {
        "fixture_notice": "Actual owned SQL, authenticated HTTP and installed review child; synthetic events and accounts only, no attestation or scientific acceptance.",
        "source_pins": pins(),
        "capture_test_path": "api/tests/test_ml_pilot_review_admission.py",
        "replies": [],
    }
    f, first, _, at = await prepared(db_session)
    before = await state(db_session)
    await db_session.rollback()
    outputs = []
    for member in first["participants"]:
        payload = packet(f, member, at)
        response = await client.post(
            BASE + "/review-preflight", json=payload, headers=acceptance_headers(member)
        )
        assert response.status_code == 200, response.text
        result = response.json()
        outputs.append(result)
        captured["replies"].append(
            {
                "raw": response.text,
                "participant_id": member["id"],
                "participant_sha256": member["record_sha256"],
                "actor_user_id": member["user_id"],
                "registration_sha256": member["registration_sha256"],
            }
        )
        assert response.headers["cache-control"] == "private, no-store"
        assert result["actor_user_id"] == member["user_id"] and result["selected_candidates"] == 60
        assert result["review_record_count"] == 61 and result["recorded_recommendation"] == "stop"
        assert (
            result["documentary_binding_checked"]
            and result["declared_review_times_fit_recorded_participation"]
        )
        for key, value in registration.boundary().items():
            if key != "scope":
                assert result[key] == value
        for key in (
            "attestation_recorded",
            "context_bytes_checked",
            "canary_replay_verified",
            "conclusion_endorsed",
        ):
            assert result[key] is False
        for other in first["participants"]:
            if other["id"] != member["id"]:
                assert other["user_id"] not in response.text
        for secret in (
            "PRIVATE_SYNTHETIC",
            "SYNTHETIC_UNOPENED_CANARY",
            "reviewer-",
            "source_reference",
            "results",
        ):
            assert secret not in response.text
    assert sorted(r["own_review_record_count"] for r in outputs) == [0, 1, 60]
    assert len({r["document_projection_sha256"] for r in outputs}) == 1
    assert sum(r["conclusion_author_is_current_account"] for r in outputs) == 1
    assert await state(db_session) == before
    assert captured["source_pins"] == pins()
    (tmp_path / "ml-pilot-review-wire.json").write_text(json.dumps(captured, sort_keys=True) + "\n")


@pytest.mark.parametrize(
    "case",
    [
        "disabled",
        "registration_disabled",
        "anonymous",
        "owner",
        "foreign_pin",
        "missing_header",
        "duplicate_header",
    ],
)
@pytest.mark.parametrize("endpoint", ["/review-preflight", "/review-attestations/coverage"])
async def test_unadmitted_body_and_worker_are_never_entered(
    client, db_session, monkeypatch, case, endpoint
):
    f, first, _, at = await prepared(db_session)
    member = first["participants"][0]
    headers = acceptance_headers(member)

    async def forbidden(*_a, **_k):
        pytest.fail("Unadmitted source bytes were read")

    monkeypatch.setattr(router, "upload", forbidden)
    monkeypatch.setattr(router.review_worker, "check_in_worker", forbidden)
    expected = 400
    if case in {"disabled", "registration_disabled"}:
        monkeypatch.setenv(
            "ML_PILOT_REVIEW_INTAKE_ENABLED"
            if case == "disabled"
            else "ML_PILOT_REGISTRATION_ENABLED",
            "false",
        )
        get_settings.cache_clear()
        expected = 404
    if case == "anonymous":
        headers = {}
        expected = 401
    if case == "owner":
        headers.update(auth(f["people"][0]))
        expected = 404
    if case == "foreign_pin":
        headers["X-SCLib-Participant-Sha256"] = "f" * 64
        expected = 409
    if case == "missing_header":
        del headers["X-SCLib-Participant-Id"]
    if case == "duplicate_header":
        headers = [*headers.items(), ("X-SCLib-Participant-Id", member["id"])]
    response = await client.post(
        BASE + endpoint, content=b"PRIVATE_SYNTHETIC_BYTES", headers=headers
    )
    assert response.status_code == expected, response.text
    assert "PRIVATE_SYNTHETIC_BYTES" not in response.text


@pytest.mark.parametrize(
    "case",
    [
        "before_registration",
        "before_acceptance",
        "future",
        "body_invitation",
        "self_consistent_new_selection",
        "incomplete_log",
        "unregistered_alias",
    ],
)
@pytest.mark.parametrize("endpoint", ["/review-preflight", "/review-attestations/coverage"])
async def test_exact_registration_and_full_denominator_are_not_replaced_by_self_consistent_files(
    client, db_session, case, endpoint
):
    f, first, heads, at = await prepared(db_session)
    member = first["participants"][0]
    if case == "before_registration":
        at = accounting._date(first["registration"]["created_at"]) - timedelta(microseconds=1)
    if case == "before_acceptance":
        at = min(accounting._date(h["created_at"]) for h in heads.values()) - timedelta(
            microseconds=1
        )
    if case == "future":
        at += timedelta(days=1)
    payload = packet(f, member, at)
    expected = 409
    if case == "body_invitation":
        payload["parameters"]["participant_id"] = first["participants"][1]["id"]
    if case in {"self_consistent_new_selection", "unregistered_alias"}:
        selected = codec.json_value(f["inputs"]["selection_raw"])
        if case == "self_consistent_new_selection":
            selected["candidates"][0]["source_reference"] = "SYNTHETIC_REPLACEMENT"
        else:
            selected["reviewers"][0]["id"] = "SYNTHETIC_NEW_ALIAS"
        selected["selection_sha256"] = accounting.selection_hash(selected)
        raw = accounting.canonical(selected)
        f["inputs"].update(
            selection_raw=raw,
            selection_file_sha256=documents.sha(raw),
            selection_sha256=selected["selection_sha256"],
        )
        payload = packet(f, member, at)
    if case == "incomplete_log":
        rows = replace_document(payload, "reviews", lambda rows: rows.pop(3))
        payload["review_log_sha256"] = accounting.review_hash(rows)
        replace_document(
            payload,
            "conclusion",
            lambda c: c.update(review_log_sha256=payload["review_log_sha256"]),
        )
        expected = 400
    response = await client.post(BASE + endpoint, json=payload, headers=acceptance_headers(member))
    assert response.status_code == expected, response.text
    assert "PRIVATE_SYNTHETIC" not in response.text


@pytest.mark.parametrize("case", ["session", "own_role", "other_role", "participation"])
@pytest.mark.parametrize("endpoint", ["/review-preflight", "/review-attestations/coverage"])
async def test_fresh_snapshot_after_actual_worker_rechecks_session_roles_and_participation(
    client, db_session, monkeypatch, case, endpoint
):
    f, first, heads, at = await prepared(db_session)
    member = first["participants"][0]
    original = router.review_worker.check_in_worker

    async def changed(raw):
        result = await original(raw)
        if case == "session":
            users = Base.metadata.tables["users"]
            await db_session.execute(
                users.update()
                .where(users.c.id == member["user_id"])
                .values(session_version=users.c.session_version + 1)
            )
        elif case in {"own_role", "other_role"}:
            target = member if case == "own_role" else first["participants"][1]
            await revoke_role(
                db_session,
                actor_user_id=f["people"][0],
                grant_id=target["reviewer_grant_id"],
                reason_code="synthetic_changed_role",
                dry_run=False,
            )
        else:
            await confirmed(
                db_session,
                decision_args(member, f["inputs"], decision="withdraw", prior=heads[member["id"]]),
            )
        await db_session.commit()
        return result

    monkeypatch.setattr(router.review_worker, "check_in_worker", changed)
    response = await client.post(
        BASE + endpoint, json=packet(f, member, at), headers=acceptance_headers(member)
    )
    assert response.status_code == (409 if case == "participation" else 403), response.text
    assert "x-operation-state" not in response.headers  # This endpoint never starts a commit.


@pytest.mark.parametrize("in_gap", [False, True])
@pytest.mark.parametrize("endpoint", ["/review-preflight", "/review-attestations/coverage"])
async def test_review_times_use_actual_participation_intervals_not_just_the_latest_acceptance(
    client, db_session, in_gap, endpoint
):
    f, first, heads, old_at = await prepared(db_session)
    member = next(m for m in first["participants"] if m["roles"] == ["primary"])
    withdrawal = (
        await confirmed(
            db_session,
            decision_args(member, f["inputs"], decision="withdraw", prior=heads[member["id"]]),
        )
    )["decision"]
    await db_session.commit()
    gap_at = await db_session.scalar(sa.select(sa.func.clock_timestamp()))
    await db_session.rollback()
    await confirmed(db_session, decision_args(member, f["inputs"], prior=withdrawal))
    await db_session.commit()
    end = await db_session.scalar(sa.select(sa.func.clock_timestamp()))
    await db_session.rollback()
    payload = packet(f, member, gap_at if in_gap else old_at, conclusion_at=end)
    response = await client.post(BASE + endpoint, json=payload, headers=acceptance_headers(member))
    assert response.status_code == (409 if in_gap else 200), response.text
