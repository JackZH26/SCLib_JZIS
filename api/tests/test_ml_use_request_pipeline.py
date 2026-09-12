"""Actual SQL → offline preparation/request → authenticated online preflight.

Entirely synthetic data and accounts in owned disposable services. Offline child
processes refuse networking and predictive fitting. No scientific/rights grant.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import sqlalchemy as sa

from models.db import User
from models.ml_use_request import INPUTS
from services.research_release_manifest import canonical, digest
from tests.test_ml_baseline_preparation_sql import inputs, invoke, succeeded
from tests.test_ml_baseline_rehearsal_sql import baseline_fixture
from tests.test_ml_label_capture import db_session as db_session
from tests.test_ml_use_governance import arguments, decide
from tests.test_ml_use_preflight import enabled as enabled
from tests.test_research_distribution_operators import auth
from tests.test_research_freeze import state
from tests.test_research_publication import actors

ROOT = Path(__file__).resolve().parents[2]


def invoke_request(args, script_name="ml_use_request.py"):
    wrapper = """import runpy,sys
from pathlib import Path
script=sys.argv.pop(1)
sys.path.insert(0,str(Path(script).resolve().parents[1]/'api'))
def audit(event,args):
    if event in {'socket.connect','socket.getaddrinfo','subprocess.Popen','os.system','sqlite3.connect'}:
        raise RuntimeError('offline_io_forbidden')
sys.addaudithook(audit)
from services import ml_baseline_numerics as numerics, ml_baseline_rehearsal as rehearsal
def denied(*a,**k):
    raise RuntimeError('model_fitting_forbidden')
numerics.fit_select=numerics.predict=denied
rehearsal._evaluate_prepared=rehearsal.run_synthetic_rehearsal=denied
runpy.run_path(script,run_name='__main__')
"""
    return subprocess.run([sys.executable, "-c", wrapper, str(ROOT / "scripts" / script_name), *args],
        cwd=ROOT, capture_output=True, text=True, timeout=90, check=False,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONHASHSEED": "0",
             "DATABASE_URL": "postgresql://unused:unused@127.0.0.1:1/unused", "REDIS_URL": "redis://127.0.0.1:1/0"})


async def test_registered_feature_sources_cannot_be_omitted_from_real_verified_request(client, db_session, tmp_path):
    fixture = await baseline_fixture(db_session, features=True, feature_budget="composition_conditions")
    # The capture helper deliberately leaves a read-only inspection snapshot.
    # End it before creating this test's separate administrative identities.
    await db_session.rollback()
    people = await actors(db_session)
    await db_session.execute(sa.update(User).where(User.id == people["curator"]).values(is_admin=True))
    role = await decide(db_session, arguments(people, user_id=str(people["curator"])))
    await db_session.commit()
    before = await state(db_session)
    await db_session.rollback()
    flags, paths = inputs(tmp_path, fixture)
    config = tmp_path.resolve() / "baseline-config.json"
    succeeded(invoke(["draft", *flags, "--output", str(config)]))
    config_hash = digest(json.loads(config.read_bytes()))
    preparation = tmp_path.resolve() / "baseline-preparation.json"
    succeeded(invoke(["prepare", *flags, "--config", str(config), "--config-sha256", config_hash,
                      "--output", str(preparation)]))
    paths.update(config=config, preparation=preparation)
    originals = {name: path.read_bytes() for name, path in paths.items()}
    request_flags = []
    for name in INPUTS:
        flag = "--" + name.replace("_", "-")
        request_flags.extend([flag, str(paths[name]), flag + "-sha256", digest(json.loads(originals[name]))])
    output = tmp_path.resolve() / "ml-use-request.json"
    result = invoke_request(["prepare", *request_flags, "--output", str(output)])
    assert result.returncode == 0 and not result.stderr, result.stderr
    request = json.loads(output.read_bytes())
    assert json.loads(result.stdout)["request_sha256"] == digest(request)
    assert request["feature_binding_pins"] and request["purpose"] == "private_baseline_evaluation"
    verified = invoke_request(["verify", *request_flags, "--request", str(output), "--request-sha256", digest(request)])
    assert verified.returncode == 0 and json.loads(verified.stdout)["request_replay_verified"], verified.stderr
    payload = {"request": request, "expected_request_sha256": digest(request),
               "expected_requester_grant_id": role["decision"]["id"],
               "expected_curator_grant_id": str(people["grants"]["curator"])}
    response = await client.post("/v1/ml/use/preflight", json=payload, headers=auth(people["curator"]))
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["feature_binding_count"] == len(request["feature_binding_pins"])
    requirements = {(r["table"], r["row_id"]) for r in report["requirements"]}
    companion = fixture["arguments"]["companion"]
    for binding in companion["bindings"]:
        assert ("source_captures", binding["capture_id"]) in requirements
        assert ("source_revisions", binding["source_revision_id"]) in requirements
        assert ("works", binding["work_id"]) in requirements
        assert ("evidence_artifacts", binding["review_artifact_id"]) in requirements
    assert report["source_permission_granted"] is report["ml_training_approved"] is False
    assert report["online_private_input_reconstruction_verified"] is False
    assert await state(db_session) == before
    await db_session.rollback()
    assert originals == {name: path.read_bytes() for name, path in paths.items()}
    omitted = json.loads(canonical(payload))
    omitted["request"]["feature_binding_pins"].pop()
    omitted["expected_request_sha256"] = digest(omitted["request"])
    refused = await client.post("/v1/ml/use/preflight", json=omitted, headers=auth(people["curator"]))
    assert refused.status_code == 409, refused.text
    assert await state(db_session) == before
    await db_session.rollback()

    # Actual private bytes, not the declaration-only preflight above. The server
    # launches its real resource-bounded offline worker, then rereads current SQL.
    from services.ml_audited_dataset import canonical as upload_canonical
    from services.ml_use_reconstruction import VERSION
    envelope = {**payload, "version": VERSION,
        "inputs_base64": {name: base64.b64encode(raw).decode("ascii") for name, raw in originals.items()},
        "artifacts_base64": {pin: base64.b64encode(raw).decode("ascii")
                             for pin, raw in fixture["arguments"]["artifact_bytes"].items()}}
    upload = tmp_path.resolve() / "private-upload.json"
    packaged = invoke_request([*request_flags, "--request", str(output), "--request-sha256", digest(request),
        "--requester-grant-id", payload["expected_requester_grant_id"],
        "--curator-grant-id", payload["expected_curator_grant_id"], "--output", str(upload)],
        script_name="ml_use_reconstruction.py")
    assert packaged.returncode == 0 and not packaged.stderr, packaged.stderr
    assert upload.read_bytes() == upload_canonical(envelope)
    assert json.loads(packaged.stdout)["request_submitted"] is False
    rebuilt = await client.post("/v1/ml/use/preflight/reconstruct", content=upload.read_bytes(),
        headers={**auth(people["curator"]), "Content-Type": "application/json"})
    assert rebuilt.status_code == 200, rebuilt.text
    report = rebuilt.json()
    assert report["online_private_input_reconstruction_verified"] is True
    assert report["reconstruction"]["dataset_and_preparation_rebuilt"] is True
    assert report["reconstruction"]["prepared_sha256"] == json.loads(originals["preparation"])["prepared_sha256"]
    assert report["reconstruction"]["client_runtime_provenance_authenticated"] is False
    assert report["decision"] == "not_authorized" and not report["request_persisted"]
    assert not report["source_permission_granted"] and not report["ml_training_approved"]
    assert not report["companion_observations_rechecked_online"]
    assert "private_input_bytes_not_rebuilt_online" not in report["blockers"]
    assert "companion_observations_not_rechecked_online" in report["blockers"]
    assert rebuilt.headers["cache-control"] == "private, no-store"
    assert originals == {name: path.read_bytes() for name, path in paths.items()}
    assert await state(db_session) == before
    await db_session.rollback()
    missing = json.loads(upload_canonical(envelope))
    assert missing["artifacts_base64"]
    missing["artifacts_base64"].pop(next(iter(missing["artifacts_base64"])))
    rejected = await client.post("/v1/ml/use/preflight/reconstruct", content=upload_canonical(missing),
        headers={**auth(people["curator"]), "Content-Type": "application/json"})
    assert rejected.status_code == 400, rejected.text
    assert await state(db_session) == before
    await db_session.rollback()
    current = await client.post("/v1/ml/use/preflight/reconstruct/current", content=upload.read_bytes(),
        headers={**auth(people["curator"]), "Content-Type": "application/json"})
    assert current.status_code == 200, current.text
    report = current.json()
    assert report["online_private_input_reconstruction_verified"] and report["companion_observations_rechecked_online"]
    assert report["review_observation_sha256"] == fixture["arguments"]["review_companion"]["observation_sha256"]
    assert report["label_observation_sha256"] == fixture["arguments"]["label_companion"]["observation_sha256"]
    assert report["dependency_inventory_sha256"] == digest(report["dependency_inventory"])
    assert not report["historical_capture_session_authenticated"] and not report["request_persisted"]
    assert report["decision"] == "not_authorized" and report["ml_training_approved"] is False
    assert report["admission"]["actor_user_id"] != report["companion_capture_identity_claim"]["actor_user_id"]
    assert await state(db_session) == before
    assert originals == {name: path.read_bytes() for name, path in paths.items()}
    await db_session.rollback()
    candidate = fixture["seeded"]["fixture"]["candidates"]["one"]
    await db_session.execute(sa.text("UPDATE papers SET status='retracted' WHERE id=:id"), {"id": candidate["paper"]["id"]})
    await db_session.commit()
    after_hold = await state(db_session)
    await db_session.rollback()
    stale = await client.post("/v1/ml/use/preflight/reconstruct/current", content=upload.read_bytes(),
        headers={**auth(people["curator"]), "Content-Type": "application/json"})
    assert stale.status_code == 409, stale.text
    assert await state(db_session) == after_hold
    assert originals == {name: path.read_bytes() for name, path in paths.items()}
