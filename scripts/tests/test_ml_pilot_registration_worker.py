"""Synthetic, offline upload adversaries and actual owned-child lifecycle checks."""

from __future__ import annotations

import asyncio
import base64
import json
import subprocess
import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from services import ml_pilot_accounting as accounting
from services import ml_pilot_documents as codec
from services import ml_pilot_registration_documents as documents
from services import ml_pilot_registration_worker as worker

from scripts.tests.test_pilot_review import selection


def envelope(*, operation="register", maximum=False):
    selected = selection()
    protocol = b"SYNTHETIC opaque bytes; not an approved study or executable code."
    if maximum:
        protocol = protocol.ljust(codec.MAX_BYTES, b" ")
    selected["protocol_sha256"] = documents.sha(protocol)
    selected["selection_sha256"] = accounting.selection_hash(selected)
    raw = accounting.canonical(selected)
    if maximum:
        raw = raw.ljust(codec.MAX_BYTES, b" ")
    parameters = {"request_key": "SYNTHETIC-upload", "dry_run": True}
    if operation == "register":
        parameters["curator_grant_id"] = str(uuid4())
    else:
        parameters.update(
            participant_id=str(uuid4()),
            participant_sha256="a" * 64,
            registration_sha256="b" * 64,
            reason_code="synthetic_only",
            supersedes_id=None,
            supersedes_sha256=None,
        )
    return {
        "version": worker.VERSION,
        "operation": operation,
        "parameters": parameters,
        "selection_base64": base64.b64encode(raw).decode(),
        "protocol_base64": base64.b64encode(protocol).decode(),
        "selection_file_sha256": documents.sha(raw),
        "protocol_file_sha256": documents.sha(protocol),
        "selection_sha256": selected["selection_sha256"],
        **(
            {
                "bindings": [
                    {
                        "reviewer_alias": r["id"],
                        "user_id": str(uuid4()),
                        "reviewer_grant_id": str(uuid4()),
                    }
                    for r in selected["reviewers"]
                ]
            }
            if operation == "register"
            else {}
        ),
    }


def encoded(value):
    # Upload envelope can exceed the separate 8 MiB document codec budget.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def test_declared_instants_are_normalized_without_losing_subsecond_precision():
    value = documents.chronology(
        {
            "selected_at": "2026-09-02T08:00:00+08:00",
            "frozen_at": "2026-09-02T00:00:00.000001Z",
        }
    )
    observed = datetime(2026, 9, 2, 0, 0, 0, 1, UTC)
    assert value == {
        "selected_at": "2026-09-02T00:00:00.000000+00:00",
        "frozen_at": "2026-09-02T00:00:00.000001+00:00",
    }
    documents.check_chronology(value, observed_at=observed)
    with pytest.raises(ValueError):
        documents.check_chronology(
            value, observed_at=observed - timedelta(microseconds=1)
        )
    with pytest.raises(ValueError):
        documents.check_chronology(value, observed_at=observed.replace(tzinfo=None))


@pytest.mark.parametrize(
    "kind", ["missing", "naive", "boolean", "noncanonical", "reversed", "extra"]
)
def test_chronology_requires_exact_normalized_aware_ordered_instants(kind):
    value = documents.chronology(selection())
    if kind == "missing":
        del value["frozen_at"]
    if kind == "naive":
        value["frozen_at"] = "2026-09-02T00:00:00"
    if kind == "boolean":
        value["frozen_at"] = True
    if kind == "noncanonical":
        value["frozen_at"] = "2026-09-02T08:00:00+08:00"
    if kind == "reversed":
        value["selected_at"] = "2027-09-02T00:00:00.000000+00:00"
    if kind == "extra":
        value["scientific_acceptance"] = True
    with pytest.raises(ValueError):
        documents.check_chronology(value)


@pytest.mark.parametrize(
    "kind",
    ["alias", "same_account", "duplicate_alias", "foreign_role", "uuid", "unknown"],
)
def test_registration_bindings_cannot_invent_or_merge_declared_reviewers(kind):
    value = envelope()
    bindings = value["bindings"]
    if kind == "alias":
        bindings[0]["reviewer_alias"] = "FOREIGN"
    if kind == "same_account":
        bindings[1]["user_id"] = bindings[0]["user_id"]
    if kind == "duplicate_alias":
        bindings[1]["reviewer_alias"] = bindings[0]["reviewer_alias"]
    if kind == "foreign_role":
        bindings[0]["roles"] = ["secondary"]
    if kind == "uuid":
        bindings[0]["user_id"] = "not-an-account"
    if kind == "unknown":
        value["source_permissions_verified"] = True
    with pytest.raises(ValueError):
        worker.prepare(encoded(value))


@pytest.mark.parametrize(
    "kind",
    [
        "duplicate",
        "nonfinite",
        "unicode",
        "deep",
        "nodes",
        "base64",
        "raw_pin",
        "logical_pin",
        "protocol",
        "closed_commit",
        "encoding_alias",
    ],
)
def test_hostile_uploads_are_rejected_by_the_actual_parser(kind):
    value = envelope()
    if kind == "base64":
        value["selection_base64"] += "\n"
    if kind == "raw_pin":
        value["selection_file_sha256"] = "f" * 64
    if kind == "logical_pin":
        value["selection_sha256"] = "f" * 64
    if kind == "protocol":
        value["protocol_base64"] = base64.b64encode(b"OTHER").decode()
        value["protocol_file_sha256"] = documents.sha(b"OTHER")
    if kind == "closed_commit":
        value["parameters"]["dry_run"] = False
    if kind == "encoding_alias":
        value["protocol_base64"] = "YR=="  # same decoded byte as canonical YQ==
    raw = encoded(value)
    if kind == "duplicate":
        raw = raw.replace(b"{", b'{"version":"duplicate",', 1)
    if kind == "nonfinite":
        raw = b'{"x":1e999}'
    if kind == "unicode":
        raw = b'"\\ud800"'
    if kind == "deep":
        raw = b"[" * 65 + b"0" + b"]" * 65
    if kind == "nodes":
        raw = b"[" + b"0," * 400_000 + b"0]"
    with pytest.raises((ValueError, UnicodeError)):
        worker.prepare(raw)


@pytest.mark.parametrize(
    "operation,maximum", [("register", False), ("accept", False), ("register", True)]
)
def test_real_isolated_child_exact_input_and_maximum_two_documents(
    monkeypatch, operation, maximum
):
    value = envelope(operation=operation, maximum=maximum)
    raw = encoded(value)
    processes = []
    create = asyncio.create_subprocess_exec
    monkeypatch.setenv("PRIVATE_REGISTRATION_SENTINEL", "MUST_NOT_REACH_CHILD")

    async def observed(*args, **kwargs):
        assert args[0] == sys.executable and args[1:4] == ("-I", "-B", "-c")
        assert kwargs["env"] == {"LANG": "C.UTF-8", "PYTHONHASHSEED": "0"}
        process = await create(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", observed)
    result = asyncio.run(worker.check_in_worker(raw))
    assert len(processes) == 1 and processes[0].returncode == 0
    assert (
        result["input_sha256"] == documents.sha(raw)
        and result["operation"] == operation
    )
    assert result["document_check"]["selection_chronology"] == documents.chronology(
        selection()
    )
    assert result["implementation"] == documents.implementation()
    assert "ml_use_reconstruction_worker.py" in result["implementation"]["files"]
    assert "MUST_NOT_REACH_CHILD" not in json.dumps(result)
    assert "synthetic-source-0" not in json.dumps(result)
    if maximum:
        assert len(base64.b64decode(value["selection_base64"])) == codec.MAX_BYTES
        assert len(base64.b64decode(value["protocol_base64"])) == codec.MAX_BYTES
        assert codec.MAX_BYTES < len(raw) <= documents.MAX_ENVELOPE_BYTES


@pytest.mark.parametrize("raw", [b"PRIVATE_INVALID", b'{"x":NaN}', b'"\\ud800"'])
def test_actual_child_rejects_private_bad_bytes_without_echo_or_orphan(
    monkeypatch, raw
):
    processes = []
    create = asyncio.create_subprocess_exec

    async def observed(*args, **kwargs):
        process = await create(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", observed)
    with pytest.raises(ValueError, match="^invalid_pilot_registration_documents$"):
        asyncio.run(worker.check_in_worker(raw))
    assert len(processes) == 1 and processes[0].returncode == 2


@pytest.mark.parametrize("operation", ["socket", "write", "spawn"])
def test_real_child_audit_guard_refuses_external_io(monkeypatch, tmp_path, operation):
    create = asyncio.create_subprocess_exec
    target = tmp_path / "must-not-exist"
    code = {
        "socket": "import socket;socket.socket()",
        "write": f"open({str(target)!r},'w')",
        "spawn": "import subprocess;subprocess.run(['must-not-execute'])",
    }[operation]
    processes = []

    async def guarded(*args, **kwargs):
        # Explicit adversarial child program, retaining the real installed guard.
        bootstrap = args[-1].split(";from services.ml_pilot_registration_worker", 1)[0]
        program = (
            bootstrap
            + ";from services.ml_use_reconstruction_worker import _io_guard;sys.addaudithook(_io_guard);"
            + code
        )
        process = await create(*args[:-1], program, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", guarded)
    with pytest.raises((ValueError, ExceptionGroup)):
        asyncio.run(worker.check_in_worker(b"{}"))
    assert len(processes) == 1 and processes[0].returncode != 0
    assert not target.exists()


@pytest.mark.parametrize(
    "mode", ["cancel", "cancel_during_spawn", "timeout", "output_limit"]
)
def test_owned_real_child_is_reaped_after_cancellation_timeout_or_output_overflow(
    monkeypatch, mode
):
    create = asyncio.create_subprocess_exec
    processes = []

    async def scenario():
        spawned, release = asyncio.Event(), asyncio.Event()

        async def adversarial(*args, **kwargs):
            # Installed parsing is not replaced in success tests. This separate
            # hostile child exercises the actual process supervisor and pipes.
            program = (
                "import sys;sys.stdin.buffer.read();sys.stdout.buffer.write(b'x'*131073);sys.stdout.flush()"
                if mode == "output_limit"
                else "import time;time.sleep(30)"
            )
            process = await create(*args[:-1], program, **kwargs)
            processes.append(process)
            spawned.set()
            if mode == "cancel_during_spawn":
                await release.wait()
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", adversarial)
        if mode == "timeout":
            monkeypatch.setattr(worker, "WALL_SECONDS", 0.1)
        task = asyncio.create_task(worker.check_in_worker(b"{}"))
        await asyncio.wait_for(spawned.wait(), 5)
        if mode.startswith("cancel"):
            task.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises((TimeoutError, ExceptionGroup)):
                await asyncio.wait_for(task, 5)
        assert len(processes) == 1 and processes[0].returncode is not None

    asyncio.run(scenario())


def test_preallocation_envelope_limit_precedes_process_creation(monkeypatch):
    async def forbidden(*_args, **_kwargs):
        pytest.fail("Child created before envelope limit")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    for raw in (b"", "{}", b" " * (documents.MAX_ENVELOPE_BYTES + 1)):
        with pytest.raises(ValueError):
            asyncio.run(worker.check_in_worker(raw))


def test_changed_installed_sources_during_check_cannot_be_resealed(monkeypatch):
    original = documents.implementation()
    different = deepcopy(original)
    different["files"]["ml_pilot_registration_documents.py"] = "f" * 64
    observed = iter([original, different])
    monkeypatch.setattr(documents, "implementation", lambda: next(observed))
    with pytest.raises(ValueError):
        worker.prepare(encoded(envelope()))


def test_installed_worker_probe_requires_isolation_and_rejects_repository_fallback():
    probe = (
        Path(__file__).resolve().parents[1] / "probe_ml_pilot_registration_install.py"
    )
    ordinary = subprocess.run(
        [sys.executable, str(probe)], capture_output=True, check=False, timeout=15
    )
    assert ordinary.returncode != 0 and b"requires_isolated_python" in ordinary.stderr
    isolated = subprocess.run(
        [sys.executable, "-I", str(probe)], capture_output=True, check=False, timeout=15
    )
    # The development environment is editable, not a separately installed wheel.
    assert (
        isolated.returncode != 0 and b"repository_fallback_forbidden" in isolated.stderr
    )
