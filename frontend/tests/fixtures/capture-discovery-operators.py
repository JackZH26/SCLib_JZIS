"""Portable synthetic Discovery reviewer/publisher HTTP asset capture.

DO NOT run directly. Intended invocation, from the repository root:
  api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
    --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
    --redis-bin /opt/homebrew/bin/redis-server --suite api -- \
    -p tests.conftest -c pyproject.toml ABSOLUTE_PATH_TO_THIS_FILE -q -s \
    -p no:cacheprovider --basetemp FRESH_EXTERNAL_DIRECTORY/pytest

The unchanged parent runner owns all PostgreSQL/Redis services and cleanup.
No target, credentials, provider, source URL, or output argument is accepted.
Actual HTTP text is retained, never reconstructed as a claimed HTTP response.
All data and grants belong to an isolated synthetic fixture, not a real pilot.
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
from uuid import uuid4

import pytest
import sqlalchemy as sa

from tests.conftest import _test_capability

# This is the same capability-owned socket policy as the checked-in selection
# asset template. The explicit plugin validates the capability before app import.
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

from services import discovery_operator_history as history
from services import discovery_projection_governance as governance
from services import research_publication as publication
from services.research_distribution_contract import _bounded
from tests.test_discovery_projection_governance import reviewed_publication
from tests.test_discovery_projection_http import BASE, protected
from tests.test_discovery_scientific_cells import read_settings
from tests.test_research_distribution_operators import auth
from tests.test_research_freeze import db_session as db_session
from tests.test_research_freeze import state

ROOT = Path.cwd().resolve().parent
assert Path.cwd().resolve() == ROOT / "api", "asset_guarded_api_cwd_required"
assert all((ROOT / name).is_file() for name in (
    "api/pyproject.toml", "api/tests/conftest.py", "scripts/run_disposable_tests.py",
    "scripts/test_safety.py", "api/services/discovery_operator_history.py",
    "frontend/tests/fixtures/capture-discovery-selection.py",
)), "asset_repository_layout_required"
OUTPUT = None
OUTPUT_FD = None
OUTPUT_IDENTITY = None
OPERATIONS = ("review-approve", "publish", "review-reject", "withdraw")
FIXED_NAMES = {
    "reviewer-access.response.wire.json", "publisher-access.response.wire.json",
    "current-inspection.response.wire.json", "current-payload.exact.json",
    "held-inspection.response.wire.json", "provenance.json",
} | {
    f"{phase}-{kind}.response.wire.json"
    for phase in ("initial", "approved", "published", "held", "rejected", "withdrawn")
    for kind in ("governance", "reviews", "publisher-governance", "publisher-reviews")
} | {
    f"{operation}-{suffix}"
    for operation in OPERATIONS
    for suffix in ("preview.request.wire.json", "preview.response.wire.json",
        "commit.request.wire.json", "commit.response.wire.json", "outcome.query.json",
        "outcome.response.wire.json", "held-outcome.response.wire.json")
}
SOURCE_PATHS = [
    "scripts/run_disposable_tests.py", "scripts/test_safety.py", "api/tests/conftest.py", "api/pyproject.toml",
    "api/main.py", "api/config.py", "api/models/db.py", "api/models/discovery_projection_v1.py",
    "api/routers/discovery_projections.py", "api/routers/research_distributions.py",
    "api/services/discovery_operator_history.py", "api/tests/test_discovery_operator_history.py",
    "api/tests/test_discovery_projection_http.py", "api/tests/test_research_distribution_operators.py",
    "api/services/discovery_projection_governance.py", "api/services/discovery_scientific_cells.py",
    "api/services/discovery_scientific_projection.py", "api/services/research_distribution.py",
    "api/services/research_distribution_rights.py", "api/services/research_distribution_contract.py",
    "api/services/research_distribution_inputs.py", "api/services/research_access.py",
    "api/services/research_publication.py", "api/services/scientific_result_subject.py",
    "api/services/scientific_result_effects.py", "api/services/research_freeze.py",
    "api/services/priority_public_bundle.py", "api/tests/rps_distribution_fixtures.py",
    "api/tests/test_research_freeze.py", "api/tests/test_research_publication.py",
    "api/tests/test_discovery_projection_governance.py", "api/tests/test_discovery_scientific_cells.py",
    "api/tests/test_discovery_scientific_projection.py", "api/tests/test_scientific_adjudication_schema.py",
    "api/tests/test_priority_public_bundle.py", "frontend/tests/fixtures/capture-discovery-selection.py",
]


def admit_output(path):
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


def write_new(name, payload):
    assert name in FIXED_NAMES
    assert type(payload) is bytes and len(payload) <= 8 * 1024 * 1024
    stable_output()
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=OUTPUT_FD)
    with os.fdopen(fd, "wb") as handle:
        handle.write(payload)
    stable_output()
    return {"file": name, "sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload)}


def checkout_head():
    value = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
        capture_output=True, text=True, timeout=5).stdout.strip()
    assert re.fullmatch(r"[0-9a-f]{40}", value), "asset_repository_revision_required"
    return value


def source_pins():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCE_PATHS}


def exact_top_level_span(raw, key):
    """Slice original JSON text; numeric parsing is never used to remake bytes."""
    decoder = json.JSONDecoder()
    position, found = 1, {}
    assert raw.startswith("{") and raw.endswith("}")
    while position < len(raw) - 1:
        field, end = decoder.raw_decode(raw, position)
        assert type(field) is str and field not in found and raw[end] == ":"
        start = end + 1
        _, position = decoder.raw_decode(raw, start)
        found[field] = raw[start:position]
        if position == len(raw) - 1:
            break
        assert raw[position] == ","
        position += 1
    assert key in found and position == len(raw) - 1
    return found[key]


def no_private_history(value):
    if type(value) is dict:
        assert not set(value) & {"payload", "payload_json", "public_bundle_json", "selection_json",
            "scientific_pins_json", "rights_json", "request_key", "request_sha256"}
        for item in value.values():
            no_private_history(item)
    elif type(value) is list:
        for item in value:
            no_private_history(item)


@pytest.mark.asyncio
async def test_capture_actual_operator_workflow(client, db_session, tmp_path):
    admit_output(tmp_path)
    material_id = None
    files, calls, operations = [], [], {}
    pins, head = source_pins(), checkout_head()
    writer_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

    def retain(name, payload):
        files.append(write_new(name, payload))

    def response(name, actual, *, statuses=(200,)):
        assert actual.status_code in statuses, actual.text
        protected(actual)
        retain(name + ".response.wire.json", actual.content)
        calls.append({"response_file": name + ".response.wire.json", "method": actual.request.method,
            "path": actual.request.url.path, "query": actual.request.url.query.decode("ascii"),
            "status_code": actual.status_code,
            "headers": {key: actual.headers[key] for key in ("content-type", "cache-control", "x-content-type-options")}})
        return actual.json()

    async def snapshot():
        result = await state(db_session)
        await db_session.rollback()
        return result

    try:
        seeded = await reviewed_publication(db_session, publish=False)
        context, registered = seeded["fixture"], seeded["registered"]
        people, package_id = context["actors"], registered["package_id"]
        material_id = context["source"]["material"]
        # Complete the original 0067 assembly before any later governance change.
        await db_session.commit()
        await read_settings(db_session)
        second_review = await publication.grant_role(db_session, actor_user_id=people["admin"],
            user_id=people["member"], role="reviewer", reason_code="synthetic_operator_capture", dry_run=False)
        await db_session.commit()
        reviewer, publisher = people["member"], people["publisher"]
        assert len({reviewer, publisher, people["curator"], people["reviewer"]}) == 4
        reviewer_headers, publisher_headers = auth(reviewer), auth(publisher)
        baseline = await snapshot()

        for role, identifier, headers in (("reviewer", reviewer, reviewer_headers), ("publisher", publisher, publisher_headers)):
            access = response(role + "-access", await client.get(BASE + "/operator/access", headers=headers))
            assert access["actor_user_id"] == str(identifier)
            assert {row["role"] for row in access["grants"]} == {role}
            if role == "reviewer":
                assert access["grants"][0]["id"] == second_review["id"]
            assert access["admission_scope"] == "current_read_snapshot_role_only"
            assert all(access[key] is False for key in history.AUTHORITY)

        async def capture_history(phase, *, reviews, rejection=False, withdrawal=False):
            before = await snapshot()
            header = response(phase + "-governance", await client.get(f"{BASE}/{package_id}/governance", headers=reviewer_headers))
            page = response(phase + "-reviews", await client.get(f"{BASE}/{package_id}/reviews",
                params={"expected_history_sha256": header["history_sha256"]}, headers=reviewer_headers))
            publisher_header = response(phase + "-publisher-governance",
                await client.get(f"{BASE}/{package_id}/governance", headers=publisher_headers))
            publisher_page = response(phase + "-publisher-reviews", await client.get(f"{BASE}/{package_id}/reviews",
                params={"expected_history_sha256": publisher_header["history_sha256"]}, headers=publisher_headers))
            for value in (header, page, publisher_header, publisher_page):
                no_private_history(value)
                assert value["review_count"] == reviews and value["has_rejection"] is rejection
                assert value["has_withdrawal"] is withdrawal and value["package"]["id"] == package_id
                assert value["current_publication_eligibility"] == "not_checked"
                assert value["history_semantics"] == "append_only_any_rejection_holds"
                assert all(value[key] is False for key in history.AUTHORITY)
            for actor_id, actor_header, actor_page in ((reviewer, header, page),
                (publisher, publisher_header, publisher_page)):
                assert actor_header["actor_user_id"] == actor_page["actor_user_id"] == str(actor_id)
                assert actor_page["history_sha256"] == actor_header["history_sha256"] == header["history_sha256"]
                assert actor_page["next_after"] is None and actor_page["returned_count"] == reviews
            assert before == await snapshot()
            return header, page

        initial, initial_reviews = await capture_history("initial", reviews=1)
        assert initial_reviews["reviews"][0]["id"] == seeded["reviewed"]["id"]
        actual_inspection = await client.get(f"{BASE}/{package_id}", headers=reviewer_headers)
        inspection = response("current-inspection", actual_inspection)
        raw_payload = exact_top_level_span(actual_inspection.content.decode("utf-8"), "payload")
        assert hashlib.sha256(raw_payload.encode()).hexdigest() == inspection["payload_sha256"] == registered["payload_sha256"]
        assert inspection["selection_sha256"] == registered["selection_sha256"]
        retain("current-payload.exact.json", raw_payload.encode("utf-8"))
        observations = [item for row in inspection["payload"]["rows"] for cell in row["cells"] for item in cell["observations"]]
        assert len(observations) == 1 and observations[0]["property"]["property_key"] == "phonon_min_frequency"
        assert observations[0]["scientific_scope_accepted"] is True
        assert all(inspection[key] is False for key in governance.AUTHORITY)
        targets = inspection["rights_targets"]
        assert targets == sorted(targets, key=lambda value: value["dependency_id"])
        assert len(targets) == len(context["inventory"]["dependencies"])
        assert baseline == await snapshot()

        async def operation(name, operation_name, endpoint, body, headers):
            before = await snapshot()
            preview_bytes, commit_bytes = _bounded({**body, "dry_run": True}), _bounded({**body, "dry_run": False})
            retain(name + "-preview.request.wire.json", preview_bytes)
            retain(name + "-commit.request.wire.json", commit_bytes)
            actual = await client.post(endpoint, content=preview_bytes, headers={**headers, "Content-Type": "application/json"})
            assert actual.request.content == preview_bytes
            preview = response(name + "-preview", actual)
            assert preview["committed"] is False and preview["dry_run"] is True
            assert preview["result"]["operation"] == operation_name and preview["result"]["committed"] is False
            assert before == await snapshot()
            actual = await client.post(endpoint, content=commit_bytes, headers={**headers, "Content-Type": "application/json"})
            assert actual.request.content == commit_bytes
            committed = response(name + "-commit", actual)
            assert committed["committed"] is True and committed["dry_run"] is False
            result = committed["result"]
            assert result["operation"] == operation_name and result["package_id"] == package_id
            assert result["committed"] is False and result["replayed"] is False
            for key in ("request_sha256", "payload_sha256", "selection_sha256"):
                assert result[key] == preview["result"][key]
            assert all(result[key] is False for key in governance.AUTHORITY)
            after = await snapshot()
            ledger = "discovery_projection_reviews" if operation_name == "review" else "discovery_projection_actions"
            assert len(after[ledger]) == len(before[ledger]) + 1
            for name_ in ("discovery_projection_packages", "research_distribution_permissions", "research_distribution_reviews",
                "research_distribution_actions", "event_properties", "material_claims", "scientific_result_decisions", "materials"):
                assert after[name_] == before[name_]
            query = {"operation": operation_name, "request_key": body["request_key"], "expected_request_sha256": result["request_sha256"]}
            retain(name + "-outcome.query.json", _bounded(query))
            recovered = response(name + "-outcome", await client.get(BASE + "/outcome", params=query, headers=headers))
            assert recovered["committed"] is True and recovered["result"] == {**result, "replayed": True}
            assert after == await snapshot()
            operations[name] = {"operation": operation_name, "request_key": body["request_key"],
                "request_sha256": result["request_sha256"], "record_id": result["id"], "record_sha256": result["record_sha256"]}
            return result, query

        common = {"expected_payload_sha256": registered["payload_sha256"], "expected_selection_sha256": registered["selection_sha256"]}
        approve_body = {**common, "request_key": "synthetic-review-approve:" + uuid4().hex,
            "decision": "approve", "representative_selection_approved": True, "disclosure_approved": True,
            "reason_code": "synthetic_operator_capture", "rights": [{**target, "license_code": "permission-on-file",
                "basis_code": "synthetic_new_scope"} for target in targets]}
        approved, approve_query = await operation("review-approve", "review", f"{BASE}/{package_id}/reviews", approve_body, reviewer_headers)
        approved_header, _ = await capture_history("approved", reviews=2)
        assert approved_header["history_sha256"] != initial["history_sha256"]
        publish_body = {**common, "request_key": "synthetic-publish:" + uuid4().hex,
            "review_id": approved["id"], "kind": "publish", "reason_code": "synthetic_operator_capture"}
        published, publish_query = await operation("publish", "publish", f"{BASE}/{package_id}/actions", publish_body, publisher_headers)
        published_header, _ = await capture_history("published", reviews=2)
        assert published_header["actions"][0]["id"] == published["id"]

        # A later, genuine allowed governance update; never disable frozen guards.
        await read_settings(db_session)
        await db_session.execute(sa.text("UPDATE materials SET needs_review=true WHERE id=:id"), {"id": material_id})
        await db_session.commit()
        held_state = await snapshot()
        held, _ = await capture_history("held", reviews=2)
        assert held["history_sha256"] == published_header["history_sha256"]
        unavailable = response("held-inspection", await client.get(f"{BASE}/{package_id}", headers=reviewer_headers), statuses=(400, 409))
        no_private_history(unavailable)
        assert held_state == await snapshot()
        # Even after the hold, exact original-actor recovery is historical only.
        for name, query, headers, expected in (("review-approve", approve_query, reviewer_headers, approved),
            ("publish", publish_query, publisher_headers, published)):
            recovered = response(name + "-held-outcome", await client.get(BASE + "/outcome", params=query, headers=headers))
            assert recovered["result"] == {**expected, "replayed": True}
        assert held_state == await snapshot()
        reject_body = {**common, "request_key": "synthetic-review-reject:" + uuid4().hex,
            "decision": "reject", "representative_selection_approved": False, "disclosure_approved": False,
            "reason_code": "synthetic_source_hold", "rights": []}
        rejected, _ = await operation("review-reject", "review", f"{BASE}/{package_id}/reviews", reject_body, reviewer_headers)
        await capture_history("rejected", reviews=3, rejection=True)
        withdraw_body = {**common, "request_key": "synthetic-withdraw:" + uuid4().hex,
            "review_id": approved["id"], "kind": "withdraw", "reason_code": "synthetic_source_hold"}
        withdrawn, _ = await operation("withdraw", "withdraw", f"{BASE}/{package_id}/actions", withdraw_body, publisher_headers)
        final_header, final_reviews = await capture_history("withdrawn", reviews=3, rejection=True, withdrawal=True)
        assert {row["id"] for row in final_header["actions"]} == {published["id"], withdrawn["id"]}
        assert rejected["id"] in {row["id"] for row in final_reviews["reviews"]}
        assert source_pins() == pins and checkout_head() == head
        assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == writer_sha and not _denied_attempts
        metadata = {
            "version": "synthetic-discovery-operator-assets/1.0.0", "synthetic_fixture_only": True,
            "git_head": head, "run_id": _test_capability.run_id,
            "backend": "native_disposable_capability_owned_postgresql_and_redis",
            "capture_transport": "actual_in_process_ASGI_HTTP_with_ephemeral_fixture_JWT_not_retained",
            "response_bytes_unmodified": True, "sent_request_bytes_unmodified": True,
            "current_payload_exact_raw_span_verified": True,
            "history_metadata_only_after_hold": True, "historical_raw_payload_fallback": False,
            "preview_history_inspection_and_recovery_full_SQL_unchanged": True,
            "scientific_fixture": "one_synthetic_phonon_property_with_actual_0067_fidelity_and_scientific_decisions",
            "initial_disclosure_reviews": 1, "new_distinct_reviewer": True,
            "new_HTTP_records": {"approve": 1, "reject": 1, "publish": 1, "withdraw": 1},
            "later_material_hold": "owned_synthetic_material_needs_review_true",
            "scope": governance.SCOPE, "package_id": package_id,
            "payload_sha256": registered["payload_sha256"], "selection_sha256": registered["selection_sha256"],
            "rights_target_count": len(targets), "operations": operations,
            "real_scientific_pilot": False, "production_publication_performed": False, "ml_training_approved": False,
            "socket_policy": "owned_capability_loopback_ports_only_during_asset_test",
            "denied_external_socket_attempts": len(_denied_attempts),
            "parent_owns_service_cleanup": True, "source_pins": pins, "asset_writer_sha256": writer_sha,
            "calls": calls, "files": files,
        }
        retain("provenance.json", json.dumps(metadata, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
        stable_output()
        print("SCLIB_DISCOVERY_OPERATOR_FIXTURE_OUTPUT=" + str(OUTPUT), flush=True)
    finally:
        # Equality assertions precede teardown; never erase immutable records.
        try:
            await db_session.rollback()
            if material_id is not None:
                await read_settings(db_session)
                await db_session.execute(sa.text("UPDATE materials SET needs_review=true WHERE id=:id"), {"id": material_id})
                await db_session.commit()
        finally:
            if OUTPUT_FD is not None:
                os.close(OUTPUT_FD)
