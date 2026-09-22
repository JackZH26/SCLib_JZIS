"""External-only exact private Discovery selection HTTP asset capture.

Use only the unchanged owned disposable runner with -p tests.conftest and
-c pyproject.toml. No repository/site edits, providers, arbitrary DB targets or
credentials are accepted. Raw response bytes and nested canonical JSON strings
are retained without rewriting; output is an exclusive private pytest tmp_path.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa

from tests.conftest import _test_capability

# The unmodified test plugin has already validated the parent's private
# capability before importing app code. Subsequent sockets are owned only.
_allowed_ports = {_test_capability.manifest[name]["port"] for name in ("postgres", "redis")}
_denied_attempts = []


def socket_guard(event, args):
    if event == "socket.connect":
        address = args[1]
        allowed = isinstance(address, tuple) and len(address) >= 2 and address[0] == "127.0.0.1" and address[1] in _allowed_ports
    elif event == "socket.getaddrinfo":
        allowed = args[0] == "127.0.0.1" and args[1] in _allowed_ports
    else:
        return
    if not allowed:
        _denied_attempts.append(event)
        raise RuntimeError("asset_external_network_forbidden")


sys.addaudithook(socket_guard)

from services import discovery_scientific_projection as projection
from services import discovery_selection_preparation as preparation
from services.research_distribution_contract import _bounded
from tests.test_discovery_projection_http import BASE, protected
from tests.test_discovery_scientific_cells import read_settings
from tests.test_discovery_scientific_projection import projected_fixture
from tests.test_discovery_selection_preparation import preparation_request, sha, source_for
from tests.test_research_distribution_operators import auth
from tests.test_research_freeze import db_session as db_session
from tests.test_research_freeze import state

ROOT = Path.cwd().resolve().parent
assert Path.cwd().resolve() == ROOT / "api", "asset_guarded_api_cwd_required"
assert all((ROOT / name).is_file() for name in (
    "api/pyproject.toml", "api/tests/conftest.py", "scripts/run_disposable_tests.py",
    "scripts/test_safety.py", "api/routers/discovery_projections.py", "api/services/discovery_selection_preparation.py",
)), "asset_repository_layout_required"
OUTPUT = None
OUTPUT_FD = None
OUTPUT_IDENTITY = None


def admit_output(path):
    """Only a fresh pytest-owned 0700 directory, held by a no-follow descriptor."""
    global OUTPUT, OUTPUT_FD, OUTPUT_IDENTITY
    assert path.is_absolute(), "asset_output_absolute_required"
    info = path.lstat()
    assert stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode), "asset_output_directory_required"
    assert info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700, "asset_output_private_owner_required"
    assert not any(path.iterdir()), "asset_output_empty_required"
    OUTPUT = path.resolve(strict=True)
    OUTPUT_FD = os.open(OUTPUT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    held = os.fstat(OUTPUT_FD)
    OUTPUT_IDENTITY = (held.st_dev, held.st_ino)
    assert OUTPUT_IDENTITY == (info.st_dev, info.st_ino), "asset_output_changed"


def stable_output():
    assert OUTPUT is not None and OUTPUT_FD is not None
    info = OUTPUT.lstat()
    assert (info.st_dev, info.st_ino) == OUTPUT_IDENTITY, "asset_output_changed"
    assert stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700


def checkout_head():
    value = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
        capture_output=True, text=True, timeout=5).stdout.strip()
    assert re.fullmatch(r"[0-9a-f]{40}", value), "asset_repository_revision_required"
    return value
SOURCE_PATHS = [
    "scripts/run_disposable_tests.py", "scripts/test_safety.py", "api/tests/conftest.py", "api/pyproject.toml",
    "api/main.py", "api/config.py", "api/models/db.py", "api/models/discovery_projection_v1.py",
    "api/routers/discovery_projections.py", "api/routers/research_distributions.py",
    "api/services/discovery_selection_preparation.py", "api/tests/test_discovery_selection_preparation.py",
    "api/tests/test_discovery_projection_http.py", "api/tests/test_research_distribution_operators.py",
    "api/routers/discovery_scientific.py", "api/routers/discovery_priority.py",
    "api/services/discovery_projection_governance.py", "api/services/discovery_scientific_cells.py",
    "api/services/discovery_scientific_projection.py", "api/services/research_distribution.py",
    "api/services/research_distribution_rights.py", "api/services/research_distribution_contract.py",
    "api/services/research_distribution_inputs.py", "api/services/research_access.py",
    "api/services/scientific_result_subject.py", "api/services/scientific_result_effects.py",
    "api/services/research_freeze.py", "api/services/priority_public_bundle.py",
    "api/tests/rps_distribution_fixtures.py", "api/tests/test_research_freeze.py",
    "api/tests/test_discovery_projection_governance.py", "api/tests/test_discovery_scientific_cells.py",
    "api/tests/test_discovery_scientific_projection.py", "api/tests/test_discovery_scientific_http.py",
    "api/tests/test_scientific_adjudication_schema.py", "api/tests/test_priority_public_bundle.py",
]


def source_pins():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCE_PATHS}


def write_new(name, payload):
    assert name in {
        "source.public-bundle.wire.json", "selection-access.response.wire.json",
        "selection-context.request.wire.json", "selection-context.response.wire.json",
        "selection-prepare.request.wire.json", "selection-prepare.response.wire.json",
        "register-preview.request.wire.json", "register-preview.response.wire.json",
        "register-commit.request.wire.json", "register-commit.response.wire.json",
        "original-outcome.query.json", "original-outcome-absent.response.wire.json",
        "original-outcome.response.wire.json", "register-replay.response.wire.json", "provenance.json",
    }
    stable_output()
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=OUTPUT_FD)
    with os.fdopen(fd, "wb") as handle:
        handle.write(payload)
    stable_output()
    return {"file": name, "sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload)}



@pytest.mark.asyncio
async def test_capture_actual_selection_workflow(client, db_session, tmp_path):
    admit_output(tmp_path)
    pins, head = source_pins(), checkout_head()
    fixture = await projected_fixture(db_session, structure=True, sample=True, reviewed=False)
    material_id = fixture["source"]["material"]
    files, calls = [], []

    def retain(name, payload):
        files.append(write_new(name, payload))

    def response(name, actual, *, status=200):
        assert actual.status_code == status, actual.text
        protected(actual)
        retain(name + ".response.wire.json", actual.content)
        calls.append({"response_file": name + ".response.wire.json", "method": actual.request.method,
            "path": actual.request.url.path, "query": actual.request.url.query.decode("ascii"),
            "status_code": actual.status_code,
            "headers": {key: actual.headers[key] for key in ("content-type", "cache-control", "x-content-type-options")}})
        return actual.json()

    try:
        await db_session.commit()
        before = await state(db_session)
        await db_session.rollback()
        headers = auth(fixture["actors"]["curator"])
        access = response("selection-access", await client.get(BASE + "/selection/access", headers=headers))
        assert access["actor_user_id"] == str(fixture["actors"]["curator"])
        assert access["actor_grant_id"] == str(fixture["actors"]["grants"]["curator"])
        assert access["can_prepare_selection"] is True
        assert all(access[key] is False for key in preparation.AUTHORITY)

        source = source_for(fixture)
        assert sha(source["public_bundle_json"]) == source["expected_public_bundle_text_sha256"]
        retain("source.public-bundle.wire.json", source["public_bundle_json"].encode("utf-8"))
        source_body = _bounded({"source": source})
        retain("selection-context.request.wire.json", source_body)
        context_response = await client.post(BASE + "/selection/context", content=source_body,
            headers={**headers, "Content-Type": "application/json"})
        assert context_response.request.content == source_body
        context = response("selection-context", context_response)
        assert type(context["context_json"]) is str and sha(context["context_json"]) == context["context_sha256"]
        parsed_context = json.loads(context["context_json"])
        assert parsed_context["quantity_basis"] == "frozen_inventory_not_current_scientific_acceptance"
        assert parsed_context["inventory_sha256"] == fixture["package"]["inventory_sha256"]
        assert parsed_context["distribution_record_sha256"] == fixture["package"]["record_sha256"]
        material = parsed_context["materials"][0]
        assert len(parsed_context["materials"]) == 1
        assert material["material"]["row_id"] == material_id
        assert {value["property_key"] for value in material["results"]} == set(projection.REGISTRY)
        assert material["structures"][1]["reference"]["row_id"] == str(fixture["source"]["structure"])
        assert "selected_assessment" not in material

        request = preparation_request(fixture, source, context)
        prepare_body = _bounded(request)
        retain("selection-prepare.request.wire.json", prepare_body)
        actual_prepared = await client.post(BASE + "/selection/prepare", content=prepare_body,
            headers={**headers, "Content-Type": "application/json"})
        assert actual_prepared.request.content == prepare_body
        prepared = response("selection-prepare", actual_prepared)
        assert all(prepared[key] is False for key in preparation.AUTHORITY)
        assert prepared["context_sha256"] == context["context_sha256"]
        for stem in ("payload", "preview", "commit"):
            assert type(prepared[stem + "_json"]) is str
            assert sha(prepared[stem + "_json"]) == prepared[stem + "_sha256"]
        payload = json.loads(prepared["payload_json"])
        assert payload["selection"] == fixture["selection"]
        cells = payload["rows"][0]["cells"]
        observations = [item for cell in cells for item in cell["observations"]]
        assert len(cells) == len(observations) == 8
        assert not any(item["scientific_scope_accepted"] for item in observations)
        assert {item["property"]["property_key"] for item in observations} == set(projection.REGISTRY)
        assert next(item for item in observations if item["property"]["property_key"] == "band_gap")["quantity"]["value"] == 0
        assert next(item for item in observations if item["property"]["property_key"] == "phonon_min_frequency")["quantity"]["value"] == -0.125
        assert next(item for item in observations if item["property"]["property_key"] == "superfluid_stiffness")["quantity"]["relation"] == "unreported"
        assert all(item["sample"] is not None and item["structure"] is not None for item in observations)

        preview_bytes = prepared["preview_json"].encode("utf-8")
        commit_bytes = prepared["commit_json"].encode("utf-8")
        retain("register-preview.request.wire.json", preview_bytes)
        retain("register-commit.request.wire.json", commit_bytes)
        assert json.loads(prepared["preview_json"]) == {**json.loads(prepared["commit_json"]), "dry_run": True}
        preview_response = await client.post(BASE + "/register", content=preview_bytes,
            headers={**headers, "Content-Type": "application/json"})
        assert preview_response.request.content == preview_bytes
        preview = response("register-preview", preview_response)
        assert preview["committed"] is False and preview["dry_run"] is True
        for key in ("request_sha256", "payload_sha256", "selection_sha256"):
            assert preview["result"][key] == prepared[key]
        assert before == await state(db_session)
        await db_session.rollback()
        query = {"operation": "register", "request_key": prepared["request_key"],
            "expected_request_sha256": prepared["request_sha256"]}
        retain("original-outcome.query.json", _bounded(query))
        response("original-outcome-absent",
            await client.get(BASE + "/outcome", params=query, headers=headers), status=404)
        assert before == await state(db_session)
        await db_session.rollback()

        commit_response = await client.post(BASE + "/register", content=commit_bytes,
            headers={**headers, "Content-Type": "application/json"})
        assert commit_response.request.content == commit_bytes
        committed = response("register-commit", commit_response)
        assert committed["committed"] is True and committed["result"]["committed"] is False
        for key in ("request_sha256", "payload_sha256", "selection_sha256"):
            assert committed["result"][key] == prepared[key]
        after = await state(db_session)
        assert len(after["discovery_projection_packages"]) == len(before["discovery_projection_packages"]) + 1
        for table in ("discovery_projection_reviews", "discovery_projection_actions", "scientific_result_decisions",
            "research_distribution_permissions", "research_distribution_reviews", "research_distribution_actions",
            "event_properties", "material_claims", "materials"):
            assert after[table] == before[table]
        await db_session.rollback()
        recovered = response("original-outcome", await client.get(BASE + "/outcome", params=query, headers=headers))
        assert recovered["committed"] is True and recovered["result"]["replayed"] is True
        assert recovered["result"]["id"] == committed["result"]["id"]
        replay = response("register-replay", await client.post(BASE + "/register", content=commit_bytes,
            headers={**headers, "Content-Type": "application/json"}))
        assert replay["result"]["replayed"] is True and replay["result"]["id"] == committed["result"]["id"]
        assert after == await state(db_session)
        await db_session.rollback()

        assert source_pins() == pins and checkout_head() == head
        assert not _denied_attempts
        metadata = {
            "version": "synthetic-discovery-selection-assets/1.0.0",
            "synthetic_fixture_only": True, "git_head": head, "run_id": _test_capability.run_id,
            "backend": "native_disposable_capability_owned_postgresql_and_redis",
            "capture_transport": "actual_in_process_ASGI_HTTP_with_ephemeral_fixture_curator_JWT_not_retained",
            "response_bytes_unmodified": True, "sent_request_bytes_unmodified": True,
            "embedded_JSON_strings_unmodified": True, "access_context_prepare_rehearsal_full_SQL_unchanged": True,
            "recovery_and_replay_full_SQL_unchanged": True,
            "committed_change": "one_projection_package_plus_existing_admission_epochs_only",
            "missing_outcome_is_not_rollback_proof": True,
            "scientific_property_count": 8, "structure_and_sample_present": True,
            "scientific_scope_accepted_count": 0, "scientific_review_performed": False,
            "real_scientific_pilot": False, "production_publication_performed": False, "ml_training_approved": False,
            "socket_policy": "owned_capability_loopback_ports_only_during_asset_test",
            "denied_external_socket_attempts": len(_denied_attempts),
            "pins": {key: prepared[key] for key in ("context_sha256", "request_sha256", "payload_sha256",
                "selection_sha256", "preview_sha256", "commit_sha256")},
            "public_bundle_text_sha256": source["expected_public_bundle_text_sha256"],
            "operation_record_sha256": committed["result"]["record_sha256"],
            "source_pins": pins, "asset_writer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "calls": calls, "files": files,
        }
        retain("provenance.json", json.dumps(metadata, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
        stable_output()
        print("SCLIB_DISCOVERY_SELECTION_FIXTURE_OUTPUT=" + str(OUTPUT), flush=True)
    finally:
        # All equality assertions precede fixture isolation. Preserve immutable
        # ledgers and hold only this test's own committed synthetic Material.
        await db_session.rollback()
        await read_settings(db_session)
        await db_session.execute(sa.text("UPDATE materials SET needs_review=true WHERE id=:id"), {"id": material_id})
        await db_session.commit()
        os.close(OUTPUT_FD)
