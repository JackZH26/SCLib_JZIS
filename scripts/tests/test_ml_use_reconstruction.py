"""Exact-byte intake/unit adversaries; compiler doubles are not research evidence."""
from __future__ import annotations

import asyncio
import base64
import builtins
import hashlib
import json
import os
import stat
import sys
from copy import deepcopy
from uuid import uuid4

import pytest
from services import ml_use_reconstruction as service
from services import ml_use_reconstruction_worker as worker
from services.ml_audited_dataset import canonical, digest
from services.ml_baseline_rehearsal import _owned_fixture
from services.ml_dataset_builder import AUTHORITY
from services.ml_preparation_receipt import receipt

from scripts import ml_use_reconstruction as cli
from scripts.tests.test_ml_use_request import case as case


def options(case, tmp_path):
    args, _, _ = case
    cli.intake.run(**args)
    return {**args, "request_path": args["output_path"],
            "expected_request_sha256": hashlib.sha256(args["output_path"].read_bytes()).hexdigest(),
            "output_path": tmp_path / "upload.json", "requester_grant_id": str(uuid4()), "curator_grant_id": str(uuid4())}


def test_envelope_cli_preserves_exact_bytes_and_private_no_clobber(case, tmp_path):
    args = options(case, tmp_path)
    originals = {name: args[name + "_path"].read_bytes() for name in cli.INPUTS}
    result = cli.run(**args)
    raw = args["output_path"].read_bytes()
    envelope, _, _ = service.decode_envelope(raw)
    assert result["envelope_sha256"] == hashlib.sha256(raw).hexdigest() and not result["request_submitted"]
    assert stat.S_IMODE(args["output_path"].stat().st_mode) == 0o600
    assert {name: base64.b64decode(value) for name, value in envelope["inputs_base64"].items()} == originals
    with pytest.raises(FileExistsError):
        cli.run(**args)
    assert args["output_path"].read_bytes() == raw


@pytest.mark.parametrize("name", cli.INPUTS)
def test_envelope_cli_rejects_change_during_replay(case, tmp_path, monkeypatch, name):
    args = options(case, tmp_path)
    original = cli.intake.run

    def changed(**kwargs):
        result = original(**kwargs)
        args[name + "_path"].write_bytes(b"{}")
        return result
    monkeypatch.setattr(cli.intake, "run", changed)
    with pytest.raises(ValueError):
        cli.run(**args)
    assert not args["output_path"].exists()


@pytest.fixture
def payload(monkeypatch):
    _, config, prepared = _owned_fixture()
    values = {name: {"synthetic_only": name} for name in cli.INPUTS}
    values.update(manifest={"dataset_id": str(uuid4())}, companion={"base_release_id": str(uuid4()), "bindings": []}, config=config)
    pins = {name + "_sha256": digest(value) for name, value in values.items() if name != "preparation"}
    provenance = {"source_sha256": {"scripts/synthetic.py": "a" * 64}, "python": "synthetic",
                  "implementation": "synthetic", "machine": "synthetic", "byteorder": "little",
                  "verification": "exact_rebuild_in_recorded_runtime"}
    values["preparation"] = receipt(prepared, config, dict(pins), provenance)
    pins["preparation_sha256"] = digest(values["preparation"])
    request = service.prepare_request(manifest=values["manifest"], companion=values["companion"], input_pins=pins)
    envelope = {"version": service.VERSION, "request": request, "expected_request_sha256": digest(request),
                "expected_requester_grant_id": str(uuid4()), "expected_curator_grant_id": str(uuid4()),
                "inputs_base64": {name: base64.b64encode(canonical(value)).decode() for name, value in values.items()},
                "artifacts_base64": {}}
    calls = []

    def rebuild(package, **kwargs):
        calls.append(kwargs)
        assert package == values["package"] and kwargs["expected_package_sha256"] == pins["package_sha256"]
        for name in ("manifest", "task", "companion", "review_companion", "label_companion", "config"):
            assert kwargs[name] == values[name] and kwargs["expected_" + name + "_sha256"] == pins[name + "_sha256"]
        return deepcopy(prepared)
    monkeypatch.setattr(service, "prepare_audited_baseline_inputs", rebuild)
    return envelope, calls


def test_rebuild_does_not_authenticate_client_provenance_or_grant_any_authority(payload):
    envelope, calls = payload
    result = service.reconstruct(canonical(envelope))
    assert len(calls) == 1
    assert result["all_eight_input_bytes_verified"] is result["dataset_and_preparation_rebuilt"] is True
    assert not result["client_runtime_provenance_authenticated"]
    assert all(result[key] is False for key in (*AUTHORITY, "request_persisted", "source_permission_granted", "run_authorization_granted"))
    assert "synthetic_only" not in json.dumps(result)
    assert result["server_implementation_sha256"] == digest(result["server_implementation"])


@pytest.mark.parametrize("name", cli.INPUTS)
@pytest.mark.parametrize("change", ["omit", "bytes", "encoding", "noncanonical"])
def test_every_exact_input_required_before_compiler(payload, name, change):
    envelope, calls = payload
    if change == "omit":
        del envelope["inputs_base64"][name]
    elif change == "bytes":
        envelope["inputs_base64"][name] = "e30="
    elif change == "encoding":
        envelope["inputs_base64"][name] += "\n"
    else:
        value = base64.b64decode(envelope["inputs_base64"][name]) + b"\n"
        envelope["inputs_base64"][name] = base64.b64encode(value).decode()
        envelope["request"]["input_pins"][name + "_sha256"] = hashlib.sha256(value).hexdigest()
        envelope["expected_request_sha256"] = digest(envelope["request"])
    with pytest.raises(ValueError):
        service.reconstruct(canonical(envelope))
    assert not calls


@pytest.mark.parametrize("field", ["prepared", "diagnostics", "authority", "training_execution", "scope", "input_pins", "config", "extra"])
def test_resealed_preparation_cannot_replace_server_reconstruction(payload, field):
    envelope, calls = payload
    data = json.loads(base64.b64decode(envelope["inputs_base64"]["preparation"]))
    data[field] = {"injected": True}
    envelope["inputs_base64"]["preparation"] = base64.b64encode(canonical(data)).decode()
    envelope["request"]["input_pins"]["preparation_sha256"] = digest(data)
    envelope["expected_request_sha256"] = digest(envelope["request"])
    with pytest.raises(ValueError):
        service.reconstruct(canonical(envelope))
    assert len(calls) == 1


@pytest.mark.parametrize("change", ["extra", "version", "artifact_name", "artifact_bytes", "artifact_alias", "total_limit"])
def test_closed_envelope_artifact_and_byte_bounds(payload, monkeypatch, change):
    envelope, calls = payload
    if change == "extra": envelope["approved"] = True
    if change == "version": envelope["version"] = "future"
    if change == "artifact_name": envelope["artifacts_base64"] = {"../../secret": "YWJj"}
    if change == "artifact_bytes": envelope["artifacts_base64"] = {"a" * 64: "YWJj"}
    if change == "artifact_alias": envelope["artifacts_base64"] = {hashlib.sha256(b"a").hexdigest(): "YR=="}
    if change == "total_limit": monkeypatch.setattr(service, "MAX_DECODED_BYTES", 2)
    with pytest.raises(ValueError):
        service.reconstruct(canonical(envelope))
    assert not calls


@pytest.mark.parametrize("event,args", [("socket.__new__", ()), ("subprocess.Popen", ()), ("os.fork", ()),
    ("os.exec", ()), ("sqlite3.connect", ()), ("os.remove", ()), ("open", ("private", "w", 0)),
    ("open", ("private", None, os.O_CREAT)), ("open", ("private", "r+", os.O_RDWR))])
def test_worker_refuses_network_subprocess_and_writes(event, args):
    with pytest.raises(RuntimeError):
        worker._io_guard(event, args)


@pytest.mark.parametrize("mode", ["timeout", "cancel", "cancel_start", "oversized_output"])
def test_owned_worker_is_reaped_on_deadline_cancellation_and_output_overflow(monkeypatch, mode):
    original = asyncio.create_subprocess_exec
    processes = []

    async def launch(*_args, **kwargs):
        assert set(kwargs["env"]) == {"LANG", "PYTHONHASHSEED"}
        program = ("import sys;sys.stdout.write('a'*200000);sys.stdout.flush()" if mode == "oversized_output" else
                   "import time;time.sleep(30)")
        proc = await original(sys.executable, "-I", "-c", program, **kwargs)
        processes.append(proc)
        if mode == "cancel_start":
            await asyncio.sleep(0.1)
        return proc
    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    monkeypatch.setattr(worker, "WALL_SECONDS", 0.2 if mode == "timeout" else 3)

    async def check():
        task = asyncio.create_task(worker.reconstruct_in_worker(b"{}"))
        if mode in {"cancel", "cancel_start"}:
            while not processes:
                await asyncio.sleep(0.01)
            task.cancel()
        with pytest.raises((TimeoutError, asyncio.CancelledError, builtins.ExceptionGroup)):
            await task
        assert processes and all(p.returncode is not None for p in processes)
    asyncio.run(check())


def test_real_worker_refuses_malformed_input_without_returning_private_content():
    with pytest.raises(ValueError, match="reconstruction_failed"):
        asyncio.run(worker.reconstruct_in_worker(b'{"secret":"do-not-echo"}'))
