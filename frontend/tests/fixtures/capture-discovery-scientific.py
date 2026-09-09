"""Portable, explicit-only synthetic public HTTP asset regeneration.

Intended filename: frontend/tests/fixtures/capture-discovery-scientific.py.
This is not automatically collected as a test. Invoke its absolute path only
through scripts/run_disposable_tests.py --suite api with -p tests.conftest and
-c pyproject.toml. The unchanged runner sets cwd to repo/api. No environment
variables, source paths, credentials or arbitrary DB targets are accepted.

The sole test writes exact response bytes to its fresh private pytest tmp_path,
prints the resolved output root, and does not replace any checked-in fixtures.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

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

from config import get_settings
from services import discovery_projection_governance as governance
from services import research_distribution as distribution
from services import research_distribution_rights as rights
from services.research_priority import digest
from tests.rps_distribution_fixtures import distribution_inputs
from tests.test_discovery_projection_governance import action_args, review_args
from tests.test_discovery_scientific_cells import read_settings
from tests.test_discovery_scientific_http import URL, safe
from tests.test_discovery_scientific_projection import add_assessment, projected_fixture, selection_for
from tests.test_priority_public_bundle import reseal_public_release
from tests.test_research_freeze import db_session as db_session
from tests.test_research_freeze import state

ROOT = Path.cwd().resolve().parent
assert Path.cwd().resolve() == ROOT / "api", "asset_guarded_api_cwd_required"
assert all((ROOT / name).is_file() for name in (
    "api/pyproject.toml", "api/tests/conftest.py", "scripts/run_disposable_tests.py",
    "scripts/test_safety.py", "api/routers/discovery_scientific.py",
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
    assert name in {"full-eight.catalogue.json", "full-eight.detail.json", "lower-score.catalogue.json",
                    "lower-score.detail.json", "provenance.json"}
    stable_output()
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=OUTPUT_FD)
    with os.fdopen(fd, "wb") as handle:
        handle.write(payload)
    stable_output()
    return {"file": name, "sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload)}


async def publish_fixture(db, fixture):
    """Same real rights/three-actor workflow as reviewed_publication, eight cells."""
    people, original = fixture["actors"], fixture["package"]
    for dependency in fixture["inventory"]["dependencies"]:
        args = {"actor_user_id": people["reviewer"], "request_key": "synthetic-asset-rights:" + uuid4().hex,
            "package_id": original["id"], "dependency_id": dependency["dependency_id"], "decision": "allow",
            "license_code": "permission-on-file", "basis_code": "synthetic_fixture_only",
            "reason_code": "synthetic_fixture_only", "expected_package_sha256": original["record_sha256"],
            "expected_inventory_sha256": original["inventory_sha256"],
            "expected_dependency_row_sha256": dependency["row_sha256"], "expected_head_id": None, "expected_head_sha256": None}
        preview = await rights.prepare_distribution_rights(db, **args)
        await rights.prepare_distribution_rights(db, **args, expected_intent_sha256=preview["intent_sha256"], dry_run=False)
    review = await distribution.review_distribution(db, actor_user_id=people["reviewer"], request_key=uuid4().hex,
        package_id=original["id"], expected_inventory_sha256=original["inventory_sha256"], disclosure_approved=True,
        reason_code="synthetic_asset_disclosure", dry_run=False)
    await distribution.distribution_action(db, actor_user_id=people["publisher"], request_key=uuid4().hex,
        package_id=original["id"], review_id=review["id"], expected_inventory_sha256=original["inventory_sha256"],
        kind="publish", reason_code="synthetic_asset_publication", dry_run=False)
    args = {**fixture["arguments"], "actor_user_id": people["curator"], "request_key": uuid4().hex}
    preview = await governance.register_projection(db, **args)
    registered = await governance.register_projection(db, **args, expected_payload_sha256=preview["payload_sha256"], dry_run=False)
    fixture["shared"] = {"actors": people, "source": fixture["source"]}
    fixture["registration"]["inventory"] = fixture["inventory"]
    reviewed = await governance.review_projection(db, **review_args(fixture, registered), dry_run=False)
    await governance.projection_action(db, **action_args(fixture, registered, reviewed), dry_run=False)
    return {"fixture": fixture, "registered": registered}


async def capture_public(client, db, monkeypatch, published, prefix):
    fixture, registered = published["fixture"], published["registered"]
    bundle, settings = fixture["bundle"], get_settings()
    monkeypatch.setattr(settings, "discovery_scientific_public_enabled", True)
    monkeypatch.setattr(settings, "discovery_scientific_approved_projections", {registered["package_id"]: registered["payload_sha256"]})
    monkeypatch.setattr(settings, "discovery_rps_public_enabled", True)
    monkeypatch.setattr(settings, "discovery_rps_approved_releases", {bundle["release"]["id"]: bundle["release"]["manifest_sha256"]})
    monkeypatch.setattr(settings, "discovery_rps_approved_public_bundles", {bundle["release"]["id"]: bundle["bundle_sha256"]})
    before = await state(db)
    await db.rollback()
    catalogue = await client.get(URL)
    detail = await client.get(URL + "/" + registered["package_id"])
    for response in (catalogue, detail):
        assert response.status_code == 200, response.text
        safe(response)
        assert not response.request.headers.get("authorization")
    assert catalogue.json()["status"] == "published"
    assert [row["package_id"] for row in catalogue.json()["items"]] == [registered["package_id"]]
    result = detail.json()
    assert result["payload_sha256"] == registered["payload_sha256"]
    row = result["payload"]["rows"][0]
    observations = [item for cell in row["cells"] for item in cell["observations"]]
    assert len(row["cells"]) == len(observations) == 8
    assert all(item["quantity"]["relation"] == "exact" for item in observations)
    accepted = [item for item in observations if item["scientific_scope_accepted"]]
    assert [item["property"]["property_key"] for item in accepted] == ["phonon_min_frequency"]
    assert {scope["scope"] for scope in accepted[0]["review"]["scopes"] if scope["effective_status"] == "accepted"} == {
        "extraction_fidelity", "scientific_result"}
    assert result["scientific_acceptance"] is result["ml_training_approved"] is False
    assert before == await state(db)
    await db.rollback()
    files = [write_new(prefix + ".catalogue.json", catalogue.content), write_new(prefix + ".detail.json", detail.content)]
    return files, row


@pytest.mark.asyncio
async def test_capture_two_actual_public_variants(client, db_session, monkeypatch, tmp_path):
    admit_output(tmp_path)
    pins, head = source_pins(), checkout_head()
    values = {"formation_energy_per_atom": -0.14, "energy_above_hull": 0.02, "band_gap": 0.0,
        "dos_at_fermi": 1.75, "electron_phonon_lambda": 1.1, "omega_log": 185.0,
        "phonon_min_frequency": -0.125, "superfluid_stiffness": 42.0}
    from tests import test_discovery_scientific_cells as fixture_module

    async def explicit_ambient(db, source):
        await db.execute(sa.text("UPDATE material_states SET pressure_status='explicit_ambient',pressure_gpa=0 WHERE id=:id"),
            {"id": source["state"]})

    original_seal = fixture_module.reseal_public_release

    def matching_ambient_release(value):
        value = deepcopy(value)
        for artifact in value["artifacts"]:
            if artifact["kind"] == "state":
                artifact["content"].update(pressure_status="explicit_ambient", pressure_gpa=0.0)
        for entry in value["assessments"]:
            entry["assessment"]["target_fit"] = "matches"
        return original_seal(value)

    # Adapt only the existing synthetic fixture's input data. No application
    # validator or admission function is patched: SQL and RPS pressure must
    # both genuinely match before their real immutable registration succeeds.
    with monkeypatch.context() as patch:
        patch.setattr(fixture_module, "reseal_public_release", matching_ambient_release)
        fixture = await projected_fixture(db_session, reviewed=True, structure=True, sample=True,
            before_freeze=explicit_ambient,
            properties=[{"property_key": key, "relation": "exact", "value": value} for key, value in values.items()])
    full = await publish_fixture(db_session, fixture)
    await db_session.commit()
    files, full_row = await capture_public(client, db_session, monkeypatch, full, "full-eight")
    assert full_row["state_context"]["pressure_status"] == "explicit_ambient"
    assert full_row["state_context"]["pressure_gpa"] == 0.0
    await read_settings(db_session)
    release = deepcopy(fixture["context"]["release"])
    release["id"] = "synthetic-lower-score-" + uuid4().hex
    add_assessment(release, "lower-score-explicit", lower_score=True)
    release = reseal_public_release(release)
    context = await distribution_inputs(db_session, release, shared=fixture["context"]["shared"])
    registration = await distribution.register_distribution(db_session, actor_user_id=fixture["actors"]["curator"],
        request_key=uuid4().hex, **context["arguments"], dry_run=False)
    package = await distribution._get(db_session, "packages", registration["package_id"], header=True)
    selection = selection_for(context["bundle"], choose="lower-score-explicit")
    selection["representatives"][0]["structure"] = deepcopy(fixture["selection"]["representatives"][0]["structure"])
    selection["representatives"][0]["cells"] = deepcopy(fixture["selection"]["representatives"][0]["cells"])
    alternate = {**fixture, "context": context, "bundle": context["bundle"], "registration": registration,
        "package": package, "inventory": registration["inventory"], "selection": selection,
        "arguments": {"distribution_package_id": str(package["id"]),
            "expected_distribution_record_sha256": package["record_sha256"], "expected_inventory_sha256": package["inventory_sha256"],
            "public_bundle": context["bundle"], "selection": selection, "expected_selection_sha256": digest(selection)}}
    lower = await publish_fixture(db_session, alternate)
    await db_session.commit()
    extra, lower_row = await capture_public(client, db_session, monkeypatch, lower, "lower-score")
    files.extend(extra)
    assert lower_row["representative"]["id"] == "lower-score-explicit"
    assert len(lower_row["alternatives"]) == 1
    assert lower_row["assessment"]["result"]["score_display"] < lower_row["alternatives"][0]["assessment"]["result"]["score_display"]
    assert lower_row["cells"] == full_row["cells"]
    assert source_pins() == pins and checkout_head() == head
    assert not _denied_attempts
    metadata = {"version": "synthetic-public-discovery-assets/1.0.0", "synthetic_fixture_only": True,
        "git_head": head, "run_id": _test_capability.run_id,
        "backend": "native_disposable_capability_owned_postgresql_and_redis",
        "capture_transport": "actual_in_process_ASGI_HTTP_GET_without_authentication",
        "fixture_adapter": "explicit_ambient/0 in actual SQL before freeze and matching RPS state before unchanged sealing and registration",
        "variants_share_same_synthetic_material_and_scientific_rows": True,
        "lower_score_explicit_selection_verified": True,
        "public_wire_is_unmodified": True, "public_GET_full_SQL_state_unchanged": True,
        "scientific_reviewed_keys": ["phonon_min_frequency"], "scientific_unreviewed_keys": sorted(set(values) - {"phonon_min_frequency"}),
        "review_scopes_for_phonon": ["extraction_fidelity", "scientific_result"],
        "publication_process": "actual_old_complete_dependency_rights_and_publication_then_new_three_account_projection_publication",
        "real_scientific_pilot": False, "production_publication_performed": False, "ml_training_approved": False,
        "socket_policy": "owned_capability_loopback_ports_only_during_asset_test", "denied_external_socket_attempts": len(_denied_attempts),
        "source_pins": pins, "asset_writer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "files": files}
    write_new("provenance.json", json.dumps(metadata, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
    # Retain all immutable records; only hold our own material after capture.
    await read_settings(db_session)
    await db_session.execute(sa.text("UPDATE materials SET needs_review=true WHERE id=:id"), {"id": fixture["source"]["material"]})
    await db_session.commit()

    stable_output()
    print("SCLIB_DISCOVERY_FIXTURE_OUTPUT=" + str(OUTPUT), flush=True)
    os.close(OUTPUT_FD)
