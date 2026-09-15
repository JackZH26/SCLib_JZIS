"""Owned SQL + real child + authenticated HTTP, synthetic science only."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from config import get_settings
from services import ml_pilot_canary as canary
from services import ml_pilot_documents as codec
from services import ml_pilot_evidence_worker as worker
from services.research_publication import revoke_role
from tests.test_ml_pilot_attestations import URL, payload, signed
from tests.test_ml_pilot_registration import confirmed, decision_args
from tests.test_ml_pilot_registration_http import acceptance_headers
from tests.test_ml_pilot_review_admission import packet, prepared
from tests.test_ml_pilot_review_coverage import for_member
from tests.test_research_freeze import db_session as db_session
from tests.test_research_freeze import state

ENDPOINT = URL + "/evidence"


def assemble(args, params, contexts):
    originals = {key: args[key + "_raw"] for key in worker.ORIGINALS[:4]}
    bundle = canary.compile_canary(
        codec.json_value(originals["selection"]),
        codec.review_records(originals["reviews"]),
        selection_sha256=args["selection_sha256"],
        review_log_sha256=args["review_log_sha256"],
        input_pins={
            k + "_file_sha256": args[k + "_file_sha256"]
            for k in ("selection", "protocol", "reviews")
        },
        source=canary.implementation(),
        evidence=[{"sha256": pin, "size_bytes": len(raw)} for pin, raw in sorted(contexts.items())],
    )
    originals["canary"] = canary.canonical(bundle)
    conclusion = codec.json_value(originals["conclusion"])
    conclusion["canary_bundle_sha256"] = canary.sha(originals["canary"])
    originals["conclusion"] = codec.canonical(conclusion)
    meta = {
        "version": worker.VERSION,
        "parameters": params,
        "selection_sha256": args["selection_sha256"],
        "review_log_sha256": args["review_log_sha256"],
        "files": [
            {"key": k, "sha256": canary.sha(raw), "size_bytes": len(raw)}
            for k, raw in originals.items()
        ]
        + [
            {"key": pin + ".bin", "sha256": pin, "size_bytes": len(raw)}
            for pin, raw in sorted(contexts.items())
        ],
    }
    return meta, originals, contexts


def frame(meta, originals, contexts):
    raw = codec.canonical(meta)
    return (
        worker.MAGIC
        + f"{len(raw):08x}\n".encode()
        + raw
        + b"".join(
            originals[row["key"]] if i < 5 else contexts[row["sha256"]]
            for i, row in enumerate(meta["files"])
        )
    )


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    for key in ("REGISTRATION", "REVIEW_INTAKE", "ATTESTATIONS", "EVIDENCE_INTAKE"):
        monkeypatch.setenv("ML_PILOT_" + key + "_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def upload(f, member, at):
    value = packet(f, member, at)
    args = {key: item for key, item in value.items() if key.endswith("sha256")}
    args.update(
        {key + "_raw": base64.b64decode(value[key + "_base64"]) for key in worker.ORIGINALS[:4]}
    )
    meta, originals, contexts = assemble(args, value["parameters"], {})
    # Fresh synthetic originals are what accounts subsequently declare against.
    value.update(
        {key + "_base64": base64.b64encode(originals[key]).decode() for key in worker.ORIGINALS[:4]}
    )
    value.update({row["key"] + "_file_sha256": row["sha256"] for row in meta["files"][:4]})
    return frame(meta, originals, contexts), value


def headers(member):
    return {**acceptance_headers(member), "content-type": worker.MEDIA_TYPE}


async def test_byte_replay_is_read_only_and_never_turns_missing_declarations_into_acceptance(
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
            {"path": str(path.relative_to(root)), "sha256": canary.sha(path.read_bytes())}
            for path in paths
        ]

    captured = {
        "fixture_notice": "Actual owned SQL, authenticated HTTP and streaming child; synthetic accounts and events only, not scientific acceptance.",
        "capture_test_path": "api/tests/test_ml_pilot_evidence.py",
        "source_pins": pins(),
    }
    f, first, _, at = await prepared(db_session)
    members = first["participants"]
    own = members[0]
    raw, documents = upload(f, own, at)
    for name, endpoint, body in [
        ("wording", URL + "/declaration", None),
        ("history", URL + "/inspect", documents["parameters"]),
        ("preflight", "/v1/ml/pilots/review-preflight", documents),
    ]:
        r = (
            await client.get(endpoint, headers=headers(own))
            if body is None
            else await client.post(endpoint, json=body, headers=acceptance_headers(own))
        )
        assert r.status_code == 200, r.text
        captured[name] = r.text
    captured.update(
        actor_user_id=own["user_id"],
        reference=documents["parameters"],
        upload=documents,
        frame_base64=base64.b64encode(raw).decode(),
    )
    before = await state(db_session)
    await db_session.rollback()
    reply = await client.post(ENDPOINT, content=raw, headers=headers(own))
    assert reply.status_code == 200, reply.text
    value = reply.json()
    captured["initial"] = reply.text
    assert value["context_bytes_checked"] and value["canary_replay_verified"]
    assert value["canary"]["context_file_count"] == 0  # No scientific evidence is inferred.
    assert value["account_snapshot"]["missing_declaration_count"] == 3
    assert not value["account_snapshot"]["account_declarations_complete"]
    assert not value["scientific_acceptance"] and not value["source_permissions_verified"]
    assert not value["current_collective_signoff_verified"] and not value["attestation_recorded"]
    assert value["training_execution"] == "disabled"
    assert await state(db_session) == before
    await db_session.rollback()
    for member in members:
        declaration = payload(f, member, at)
        declaration.update(
            {
                key: item
                for key, item in for_member(documents, member).items()
                if key not in {"version", "parameters"}
            }
        )
        await signed(client, declaration, member)
    before = await state(db_session)
    await db_session.rollback()
    checked = await client.post(ENDPOINT, content=raw, headers=headers(own))
    assert checked.status_code == 200, checked.text
    assert checked.json()["account_snapshot"]["account_declarations_complete"]
    assert not checked.json()["scientific_acceptance"]
    assert await state(db_session) == before
    for private in ("SYNTHETIC", "PRIVATE_SYNTHETIC_REVIEW", "canary_bundle_reference"):
        assert private not in checked.text
    assert checked.headers["cache-control"] == "private, no-store"
    captured["complete"] = checked.text
    assert captured["source_pins"] == pins()
    (tmp_path / "ml-pilot-evidence-wire.json").write_text(
        json.dumps(captured, ensure_ascii=False, indent=2) + "\n"
    )


@pytest.mark.parametrize(
    "flag", ["REGISTRATION", "REVIEW_INTAKE", "ATTESTATIONS", "EVIDENCE_INTAKE"]
)
async def test_every_switch_fails_before_body_or_worker(client, db_session, monkeypatch, flag):
    _, first, _, _ = await prepared(db_session)
    own = first["participants"][0]
    monkeypatch.setenv("ML_PILOT_" + flag + "_ENABLED", "false")
    get_settings.cache_clear()

    async def forbidden(*args, **kwargs):
        pytest.fail("Disabled evidence must not run a byte worker")

    monkeypatch.setattr(worker, "check_in_worker", forbidden)
    reply = await client.post(ENDPOINT, content=b"invalid", headers=headers(own))
    assert reply.status_code == 404


@pytest.mark.parametrize(
    "case,expected",
    [
        ("mime", 415),
        ("encoding", 415),
        ("size", 413),
        ("frame", 400),
        ("cross_account", 409),
        ("missing_header", 400),
    ],
)
async def test_transport_and_account_binding_fail_closed(client, db_session, case, expected):
    f, first, _, at = await prepared(db_session)
    own = first["participants"][0]
    raw, _ = upload(f, own, at)
    h = headers(own)
    if case == "mime":
        h["content-type"] = "application/json"
    if case == "encoding":
        h["content-encoding"] = "gzip"
    if case == "size":
        h["content-length"] = str(worker.MAX_ENVELOPE_BYTES + 1)
    if case == "frame":
        raw = raw[:-1]
    if case == "cross_account":
        raw, _ = upload(f, first["participants"][1], at)
    if case == "missing_header":
        h.pop("X-SCLib-Participant-Sha256")
    before = await state(db_session)
    await db_session.rollback()
    reply = await client.post(ENDPOINT, content=raw, headers=h)
    assert reply.status_code == expected, reply.text
    assert "SYNTHETIC" not in reply.text and "JSON" not in reply.text
    assert "x-operation-state" not in reply.headers
    assert await state(db_session) == before


@pytest.mark.parametrize("action", ["withdraw", "revoke"])
async def test_new_snapshot_rejects_participation_or_grant_changed_during_worker(
    client, db_session, monkeypatch, action
):
    f, first, heads, at = await prepared(db_session)
    own, other = first["participants"][:2]
    raw, _ = upload(f, own, at)
    original = worker.check_in_worker

    async def changed(stream):
        value = await original(stream)
        if action == "withdraw":
            await confirmed(
                db_session,
                decision_args(other, f["inputs"], decision="withdraw", prior=heads[other["id"]]),
            )
        else:
            await revoke_role(
                db_session,
                actor_user_id=f["people"][0],
                grant_id=other["reviewer_grant_id"],
                reason_code="synthetic_evidence_midflight",
                dry_run=False,
            )
        await db_session.commit()
        return value

    monkeypatch.setattr(worker, "check_in_worker", changed)
    reply = await client.post(ENDPOINT, content=raw, headers=headers(own))
    assert reply.status_code in {403, 409}, reply.text
    assert "canary_replay_verified" not in reply.text


async def test_worker_limits_are_413_and_timeouts_are_503_not_unknown_commits(
    client, db_session, monkeypatch
):
    f, first, _, at = await prepared(db_session)
    own = first["participants"][0]
    raw, _ = upload(f, own, at)
    for error, expected in [(worker.EvidenceLimitError(), 413), (TimeoutError(), 503)]:

        async def failed(*args, error=error):
            raise error

        monkeypatch.setattr(worker, "check_in_worker", failed)
        reply = await client.post(ENDPOINT, content=raw, headers=headers(own))
        assert reply.status_code == expected, reply.text
        assert "x-operation-state" not in reply.headers
