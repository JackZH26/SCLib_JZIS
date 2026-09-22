"""Run the real registration upload worker from a separately installed API wheel.

Only synthetic unreviewed declarations are checked. No SQL, actual accounts,
registration, source permissions, scientific review or training is performed.
"""

from __future__ import annotations

import asyncio
import base64
import importlib.abc
import importlib.metadata
import json
import sys
from pathlib import Path


def main():
    if not sys.flags.isolated:
        raise RuntimeError("pilot_worker_probe_requires_isolated_python")

    class NoServerImports(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split(".")[0] in {
                "scripts",
                "main",
                "config",
                "models",
                "sqlalchemy",
                "redis",
                "httpx",
                "ingestion",
                "tiktoken",
            }:
                raise RuntimeError("pilot_worker_probe_application_import_forbidden")

    sys.meta_path.insert(0, NoServerImports())
    from services import ml_pilot_accounting as accounting
    from services import ml_pilot_registration_documents as documents
    from services import ml_pilot_registration_worker as worker

    installed, root = (
        Path(sys.prefix).resolve(),
        Path(worker.__file__).resolve().parents[1],
    )
    implementation = documents.implementation()
    for name in implementation["files"]:
        if (
            not Path(documents.__file__)
            .with_name(name)
            .resolve()
            .is_relative_to(installed)
        ):
            raise RuntimeError("pilot_worker_probe_repository_fallback_forbidden")
    bootstrap = (
        "import sys;sys.path.insert(0,"
        + repr(str(root))
        + ");from services.ml_pilot_registration_worker import main;main()"
    )
    expected_args = [sys.executable, "-I", "-B", "-c", bootstrap]
    observed_spawns = []

    def only_owned_worker(event, args):
        if event == "subprocess.Popen":
            executable, argv, cwd, env = args
            if (
                executable != sys.executable
                or list(argv) != expected_args
                or cwd is not None
                or env != {"LANG": "C.UTF-8", "PYTHONHASHSEED": "0"}
            ):
                raise RuntimeError("pilot_worker_probe_unowned_child_forbidden")
            observed_spawns.append(True)
        elif event in {
            "socket.__new__",
            "socket.connect",
            "socket.getaddrinfo",
            "os.system",
            "os.fork",
            "os.posix_spawn",
            "os.exec",
        }:
            raise RuntimeError("pilot_worker_probe_external_io_forbidden")

    # asyncio's local wakeup socketpair is established before denying sockets;
    # subsequent source/network access is forbidden, not replaced with a double.
    loop = asyncio.new_event_loop()
    sys.addaudithook(only_owned_worker)
    protocol = b"SYNTHETIC installed-worker probe; not an approved research protocol."
    selection = {
        "schema_version": "ml08-selection/1.0.0",
        "pilot_id": "SYNTHETIC-installed-worker",
        "protocol_status": "approved",
        "protocol_revision": "synthetic-only",
        "protocol_sha256": documents.sha(protocol),
        "approval_reference": "Synthetic declaration, not approval",
        "selection_status": "frozen",
        "target_candidate_count": 60,
        "selection_method": "Synthetic installation check only",
        "strata": [{"id": "synthetic", "definition": "No scientific stratum"}],
        "candidates": [
            {
                "candidate_id": f"SYNTHETIC-{i}",
                "selection_kind": "actual_source_event",
                "stratum_id": "synthetic",
                "family": "synthetic",
                "source_class": "synthetic",
                "source_reference": "Not an actual paper",
                "event_locator": "Not an actual event",
                "selection_rationale": "Installation fixture only",
            }
            for i in range(60)
        ],
        "reviewers": [
            {"id": "synthetic-A", "kind": "human", "roles": ["primary"]},
            {"id": "synthetic-B", "kind": "human", "roles": ["secondary"]},
        ],
        "second_review_candidate_ids": ["SYNTHETIC-0"],
        "independence_plan": "No actual humans participated",
        "selected_at": "2026-09-01T00:00:00Z",
        "frozen_at": "2026-09-02T00:00:00Z",
        "selection_sha256": None,
    }
    selection["selection_sha256"] = accounting.selection_hash(selection)
    raw = accounting.canonical(selection)
    common = {
        "version": worker.VERSION,
        "selection_base64": base64.b64encode(raw).decode(),
        "protocol_base64": base64.b64encode(protocol).decode(),
        "selection_file_sha256": documents.sha(raw),
        "protocol_file_sha256": documents.sha(protocol),
        "selection_sha256": selection["selection_sha256"],
    }
    operations = []
    try:
        for operation in ("register", "accept"):
            control = {
                "request_key": "SYNTHETIC-installed-" + operation,
                "dry_run": True,
            }
            value = {**common, "operation": operation, "parameters": control}
            if operation == "register":
                control["curator_grant_id"] = "00000000-0000-4000-8000-000000000001"
                value["bindings"] = [
                    {
                        "reviewer_alias": r["id"],
                        "user_id": f"00000000-0000-4000-8000-{i + 2:012d}",
                        "reviewer_grant_id": f"00000000-0000-4000-8000-{i + 4:012d}",
                    }
                    for i, r in enumerate(selection["reviewers"])
                ]
            else:
                control.update(
                    participant_id="00000000-0000-4000-8000-000000000006",
                    participant_sha256="a" * 64,
                    registration_sha256="b" * 64,
                    reason_code="synthetic_only",
                    supersedes_id=None,
                    supersedes_sha256=None,
                )
            uploaded = accounting.canonical(value)
            result = loop.run_until_complete(worker.check_in_worker(uploaded))
            if (
                result["operation"] != operation
                or result["input_sha256"] != documents.sha(uploaded)
                or result["implementation"] != implementation
                or result["document_check"]["selected_candidates"] != 60
            ):
                raise RuntimeError("pilot_worker_probe_contract_mismatch")
            if result["document_check"]["selection_chronology"] != documents.chronology(
                selection
            ):
                raise RuntimeError("pilot_worker_probe_chronology_mismatch")
            operations.append(
                {
                    "operation": operation,
                    "input_sha256": result["input_sha256"],
                    "worker_exit_code": 0,
                    "selected_candidates": 60,
                }
            )
    finally:
        loop.close()
    if len(observed_spawns) != 2:
        raise RuntimeError("pilot_worker_probe_child_count_mismatch")
    print(
        json.dumps(
            {
                "probe": "ml08-installed-registration-worker/1.0.0",
                "synthetic": True,
                "package_version": importlib.metadata.version("sclib-api"),
                "python": sys.version.split()[0],
                "implementation": implementation,
                "operations": operations,
                "exact_owned_child_count": 2,
                "scientific_acceptance": False,
                "registration_recorded": False,
                "account_participation_recorded": False,
                "database_clock_checked": False,
                "training_execution": "disabled",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
