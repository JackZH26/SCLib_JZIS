"""Real SQL-to-offline preparation, with entirely synthetic scientific values.

Only guarded capability-owned services may execute this test. Every preparation
command then runs without database/network access and with model fitting blocked.
No real human review, source permission or training authorization is asserted.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from services.ml_audited_dataset import canonical, digest
from services.ml_dataset_builder import AUTHORITY
from tests.test_ml_baseline_rehearsal_sql import baseline_fixture
from tests.test_ml_label_capture import db_session as db_session
from tests.test_research_freeze import state

ROOT = Path(__file__).resolve().parents[2]


def invoke(arguments):
    wrapper = """import runpy,sys
from pathlib import Path
path=sys.argv.pop(1)
sys.path.insert(0,str(Path(path).resolve().parents[1]/'api'))
def audit(event,args):
    if event in {'socket.connect','socket.getaddrinfo','subprocess.Popen','os.system','sqlite3.connect'}:
        raise RuntimeError('offline_io_forbidden')
sys.addaudithook(audit)
from services import ml_baseline_numerics as numerics, ml_baseline_rehearsal as rehearsal
def denied(*a,**k):
    raise RuntimeError('model_fitting_forbidden_in_preparation')
numerics.fit_select=numerics.predict=denied
rehearsal._evaluate_prepared=rehearsal.run_synthetic_rehearsal=denied
runpy.run_path(path,run_name='__main__')
"""
    return subprocess.run(
        [sys.executable, "-c", wrapper, str(ROOT / "scripts/ml_baseline_preparation.py"), *arguments],
        cwd=ROOT, capture_output=True, text=True, timeout=60, check=False,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONHASHSEED": "0",
             "DATABASE_URL": "postgresql://unused:unused@127.0.0.1:1/unused",
             "REDIS_URL": "redis://127.0.0.1:1/0"},
    )


def inputs(tmp_path, fixture):
    directory = tmp_path.resolve()
    capsule = directory / "capsule"
    capsule.mkdir()
    for sha, payload in fixture["arguments"]["artifact_bytes"].items():
        (capsule / (sha + ".bin")).write_bytes(payload)
    args, paths = [], {}
    for name in ("manifest", "task", "companion", "review_companion", "label_companion", "package"):
        paths[name] = (capsule if name == "manifest" else directory) / (name + ".json")
        value = fixture["package"] if name == "package" else fixture["arguments"][name]
        raw = canonical(value)
        paths[name].write_bytes(raw)
        if name != "package":
            assert hashlib.sha256(raw).hexdigest() == fixture["arguments"]["expected_" + name + "_sha256"]
        flag = "--" + name.replace("_", "-")
        args.extend([flag, str(paths[name]), flag + "-sha256", hashlib.sha256(raw).hexdigest()])
    return args, paths


def succeeded(result):
    assert result.returncode == 0, result.stderr
    assert not result.stderr
    summary = json.loads(result.stdout)
    assert summary["training_execution"] == "disabled"
    assert summary["independent_support_count"] is None
    assert all(summary[key] is False for key in AUTHORITY)
    return summary


@pytest.mark.parametrize("features,feature_budget,arm_count", [
    (False, "composition", 1), (True, "composition_conditions", 10),
])
async def test_native_capsule_draft_prepare_replay_no_training_or_sql_writes(
    db_session, tmp_path, features, feature_budget, arm_count
):
    fixture = await baseline_fixture(db_session, features=features, feature_budget=feature_budget)
    before = await state(db_session)
    arguments, paths = inputs(tmp_path, fixture)
    original = {name: path.read_bytes() for name, path in paths.items()}
    config_path = tmp_path.resolve() / "baseline-config.json"
    draft = succeeded(invoke(["draft", *arguments, "--output", str(config_path)]))
    assert draft["draft_requires_independent_review_and_pin"]
    config = json.loads(config_path.read_bytes())
    assert draft["config_sha256"] == digest(config)
    assert config["input_sha256"] == digest(fixture["package"])
    assert len(config["arms"]) == arm_count
    configured = [*arguments, "--config", str(config_path), "--config-sha256", digest(config)]
    output = tmp_path.resolve() / "preparation.json"
    summary = succeeded(invoke(["prepare", *configured, "--output", str(output)]))
    receipt = json.loads(output.read_bytes())
    assert summary["arm_count"] == arm_count and summary["receipt_sha256"] == digest(receipt)
    assert all(value is False for value in receipt["authority"].values())
    assert receipt["training_blockers"] == summary["training_blockers"]
    assert receipt["prepared_sha256"] == digest(receipt["prepared"])
    for arm in receipt["diagnostics"]["arms"]:
        assert arm["row_count"] == 5 and arm["train_row_count"] == 3
        assert [entry["row_count"] for entry in arm["by_split"]] == [3, 1, 1]
        assert arm["reason_codes"] == []
        for field in arm["features"]:
            assert all(c["row_count"] == c["present_count"] + c["missing_count"] for c in field["by_split"])
    checked = succeeded(invoke(["verify", *configured, "--receipt", str(output),
                                "--receipt-sha256", digest(receipt)]))
    assert checked["preparation_replay_verified"] and not checked["output_written"]
    assert "numerical_replay_verified" not in checked
    assert original == {name: path.read_bytes() for name, path in paths.items()}
    assert await state(db_session) == before
    assert stat.S_IMODE(output.stat().st_mode) == stat.S_IMODE(config_path.stat().st_mode) == 0o600
    for command in (["draft", *arguments, "--output", str(config_path)],
                    ["prepare", *configured, "--output", str(output)]):
        refused = invoke(command)
        assert refused.returncode == 2 and not refused.stdout
    assert json.loads(output.read_bytes()) == receipt
    # Full receipt reconstruction, not validation of a self-reported checksum.
    tampered = deepcopy(receipt)
    tampered["diagnostics"]["arms"][0]["by_split"][0]["captured_component_count"] = 999
    altered = tmp_path.resolve() / "resealed.json"
    altered.write_bytes(canonical(tampered))
    denied = invoke(["verify", *configured, "--receipt", str(altered), "--receipt-sha256", digest(tampered)])
    assert denied.returncode == 2 and not denied.stdout
    assert json.loads(denied.stderr) == {"status": "invalid", "output_written": False}
    assert await state(db_session) == before


async def test_resealed_audit_or_false_feature_scope_cannot_enter_preparation(db_session, tmp_path):
    fixture = await baseline_fixture(db_session, feature_budget="composition_conditions")
    before = await state(db_session)
    arguments, paths = inputs(tmp_path, fixture)
    config_path = tmp_path.resolve() / "config.json"
    succeeded(invoke(["draft", *arguments, "--output", str(config_path)]))
    config = json.loads(config_path.read_bytes())
    arm = next(a for a in config["arms"] if "reported_pressure_gpa" in a["feature_names"])
    arm["feature_scope"] = "composition"
    config_path.write_bytes(canonical(config))
    output = tmp_path.resolve() / "must-not-exist.json"
    denied = invoke(["prepare", *arguments, "--config", str(config_path), "--config-sha256", digest(config),
                     "--output", str(output)])
    assert denied.returncode == 2 and not output.exists()
    altered = deepcopy(fixture["package"])
    altered["identity_audit"]["counts"][0]["rows"] += 1
    altered["identity_audit_sha256"] = digest(altered["identity_audit"])
    paths["package"].write_bytes(canonical(altered))
    arguments[arguments.index("--package-sha256") + 1] = digest(altered)
    denied = invoke(["draft", *arguments, "--output", str(output)])
    assert denied.returncode == 2 and not output.exists()
    assert json.loads(denied.stderr) == {"status": "invalid", "output_written": False}
    assert await state(db_session) == before
