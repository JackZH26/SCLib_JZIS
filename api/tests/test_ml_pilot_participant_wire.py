"""Actual private HTTP, SQL and upload child; every study/account is synthetic."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from config import get_settings
from services.research_publication import revoke_role
from tests.test_ml_pilot_registration import decision_args, fixture, no_authority
from tests.test_ml_pilot_registration_http import (
    BASE,
    acceptance_headers,
    http_registration,
    upload,
)
from tests.test_ml_pilot_registration_http import enabled as enabled
from tests.test_research_distribution_operators import auth
from tests.test_research_freeze import db_session as db_session
from tests.test_research_freeze import state


@pytest.mark.parametrize("case", ["anonymous", "disabled", "active_without_curator"])
async def test_participant_access_is_private_read_only_and_not_a_role_grant(
    client, db_session, monkeypatch, case
):
    f = await fixture(db_session)
    await db_session.commit()
    before = await state(db_session)
    await db_session.rollback()
    if case == "disabled":
        monkeypatch.setenv("ML_PILOT_REGISTRATION_ENABLED", "false")
        get_settings.cache_clear()
    response = await client.get(
        BASE + "/participant-access", headers={} if case == "anonymous" else auth(f["people"][1])
    )
    assert (
        response.status_code
        == {"anonymous": 401, "disabled": 404, "active_without_curator": 200}[case]
    )
    assert response.headers["cache-control"] == "private, no-store"
    if response.status_code == 200:
        no_authority(response.json())
        assert response.json()["actor_user_id"] == str(f["people"][1])
        assert set(response.json()) == {"version", "actor_user_id", *no_authority_keys()}
    assert await state(db_session) == before


def no_authority_keys():
    from services.ml_pilot_registration import boundary

    return boundary()


async def test_participant_workbench_real_native_wire(client, db_session, tmp_path):
    repo = Path(__file__).resolve().parents[2]
    paths = sorted(
        {
            *(repo / "api/models").glob("*.py"),
            *(repo / "api/services").glob("*.py"),
            *(repo / "api/services").glob("*.schema.json"),
            *(repo / "api/routers").glob("*.py"),
            *(repo / "api/tests").glob("*.py"),
            *(repo / "scripts").glob("*.py"),
            repo / "api/main.py",
            repo / "api/config.py",
        }
    )

    def pins():
        return [
            {"path": str(p.relative_to(repo)), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in paths
        ]

    source = pins()
    f = await fixture(db_session)
    await db_session.commit()
    _, first = await http_registration(client, f)
    reg, member = first["registration"], first["participants"][0]
    capture = {
        "fixture_notice": "Actual owned SQL, authenticated HTTP and installed upload worker; synthetic accounts and declared events only, no real scientific approval or source permission.",
        "capture_test_path": "api/tests/test_ml_pilot_participant_wire.py",
        "source_pins": source,
        "query": {"registration_id": reg["id"], "registration_sha256": reg["record_sha256"]},
        "owner_id": str(f["people"][0]),
        "participant_id": member["user_id"],
        "selection_base64": upload(f)["selection_base64"],
        "protocol_base64": upload(f)["protocol_base64"],
    }

    async def read(name, endpoint, body=None, *, actor=None, headers=None):
        headers = headers or auth(actor or member["user_id"])
        response = await (
            client.get(BASE + endpoint, headers=headers)
            if body is None
            else client.post(BASE + endpoint, json=body, headers=headers)
        )
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
        capture[name] = response.text
        result = response.json()
        no_authority(result.get("result", result))
        return result

    await read("access", "/participant-access")
    await read("owner_access", "/participant-access", actor=f["people"][0])
    await read("owner_initial", "/inspect", capture["query"], actor=f["people"][0])
    await read("initial", "/inspect", capture["query"])
    for other in first["participants"][1:]:
        payload = upload(f, other)
        preview = await client.post(
            BASE + "/participation/accept", json=payload, headers=acceptance_headers(other)
        )
        assert preview.status_code == 200, preview.text
        payload["parameters"].update(
            dry_run=False, expected_intent_sha256=preview.json()["result"]["intent_sha256"]
        )
        saved = await client.post(
            BASE + "/participation/accept", json=payload, headers=acceptance_headers(other)
        )
        assert saved.status_code == 200 and saved.json()["committed"], saved.text
    await read("pending", "/inspect", capture["query"])
    head = None
    for action in ("decline", "accept", "withdraw"):
        args = decision_args(member, f["inputs"], decision=action, prior=head)
        plain = {k: v for k, v in args.items() if k not in {"actor_user_id", "document_check"}}
        capture[action + "_input"] = plain
        if action == "accept":
            payload = {
                **upload(f, member),
                "parameters": {k: v for k, v in plain.items() if k != "decision"},
            }
            endpoint, headers = "/participation/accept", acceptance_headers(member)
        else:
            payload, endpoint, headers = (
                dict(plain),
                "/participation/decisions",
                auth(member["user_id"]),
            )
        preview = await read(action + "_preview", endpoint, payload, headers=headers)
        target = payload["parameters"] if action == "accept" else payload
        target.update(dry_run=False, expected_intent_sha256=preview["result"]["intent_sha256"])
        saved = await read(action + "_committed", endpoint, payload, headers=headers)
        head = saved["result"]["decision"]
        lookup = {
            "request_key": plain["request_key"],
            "expected_intent_sha256": preview["result"]["intent_sha256"],
        }
        capture[action + "_lookup"] = lookup
        await read(action + "_outcome", "/participation/outcome", lookup)
        view = await read(action + "_inspection", "/inspect", capture["query"])
        assert view["ready_for_prospective_review"] is (action == "accept")
        if action == "accept":
            await read("owner_ready", "/inspect", capture["query"], actor=f["people"][0])
            await revoke_role(
                db_session,
                actor_user_id=f["people"][0],
                grant_id=member["reviewer_grant_id"],
                reason_code="synthetic_revocation",
                dry_run=False,
            )
            await db_session.commit()
            await read("revoked_access", "/participant-access")
            changed = await read("revoked_inspection", "/inspect", capture["query"])
            assert (
                not changed["ready_for_prospective_review"]
                and not changed["current_bound_roles_available"]
            )
    historical = await read("accept_historical", "/participation/outcome", capture["accept_lookup"])
    assert (
        historical["result"]["decision"]
        == json.loads(capture["accept_committed"])["result"]["decision"]
    )
    assert pins() == source
    (tmp_path / "ml-pilot-participant-wire.json").write_text(
        json.dumps(capture, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
