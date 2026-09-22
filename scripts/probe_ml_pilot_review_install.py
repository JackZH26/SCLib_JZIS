"""Exercise the review checker from a separately installed, dependency-free wheel.

Only synthetic complete-failure documents are generated. No actual human review,
database clock, account admission, signature, source rights or training is checked.
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
        raise RuntimeError("pilot_review_probe_requires_isolated_python")

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
                raise RuntimeError("pilot_review_probe_application_import_forbidden")

    sys.meta_path.insert(0, NoServerImports())
    from services import ml_pilot_accounting as accounting
    from services import ml_pilot_attestation_contract as contract
    from services import ml_pilot_review_documents as documents
    from services import ml_pilot_review_worker as worker

    installed = Path(sys.prefix).resolve()
    implementation = documents.implementation()
    for name in implementation["files"]:
        if (
            not Path(documents.__file__)
            .with_name(name)
            .resolve()
            .is_relative_to(installed)
        ):
            raise RuntimeError("pilot_review_probe_repository_fallback_forbidden")
    root = str(Path(worker.__file__).resolve().parents[1])
    bootstrap = (
        "import sys;sys.path.insert(0,"
        + repr(root)
        + ");from services.ml_pilot_review_worker import main;main()"
    )
    expected = [sys.executable, "-I", "-B", "-c", bootstrap]
    expected_attestation = [
        *expected[:-1],
        bootstrap.replace("main()", "main(attestation=True)"),
    ]
    spawned = []

    def guard(event, args):
        if event == "subprocess.Popen":
            executable, argv, cwd, env = args
            if (
                executable != sys.executable
                or list(argv) != (expected if not spawned else expected_attestation)
                or len(spawned) >= 2
                or cwd is not None
                or env != {"LANG": "C.UTF-8", "PYTHONHASHSEED": "0"}
            ):
                raise RuntimeError("pilot_review_probe_unowned_child_forbidden")
            spawned.append(True)
        elif event in {
            "socket.__new__",
            "socket.connect",
            "socket.getaddrinfo",
            "os.system",
            "os.fork",
            "os.posix_spawn",
            "os.exec",
        }:
            raise RuntimeError("pilot_review_probe_external_io_forbidden")

    loop = asyncio.new_event_loop()  # Establish asyncio's local wakeup pair first.
    sys.addaudithook(guard)
    protocol = b"SYNTHETIC installed review checker; not an approved study."
    selection = {
        "schema_version": "ml08-selection/1.0.0",
        "pilot_id": "SYNTHETIC-review-probe",
        "protocol_status": "approved",
        "protocol_revision": "synthetic-only",
        "protocol_sha256": documents.sha(protocol),
        "approval_reference": "Not a real approval",
        "selection_status": "frozen",
        "target_candidate_count": 60,
        "selection_method": "Software fixture only",
        "strata": [{"id": "synthetic", "definition": "No actual scientific stratum"}],
        "candidates": [
            {
                "candidate_id": f"SYNTHETIC-{i}",
                "selection_kind": "actual_source_event",
                "stratum_id": "synthetic",
                "family": "synthetic",
                "source_class": "synthetic",
                "source_reference": "No actual paper",
                "event_locator": "No actual event",
                "selection_rationale": "Synthetic fixture",
            }
            for i in range(60)
        ],
        "reviewers": [
            {"id": "synthetic-A", "kind": "human", "roles": ["primary"]},
            {"id": "synthetic-B", "kind": "human", "roles": ["secondary"]},
        ],
        "second_review_candidate_ids": ["SYNTHETIC-0"],
        "independence_plan": "No actual humans",
        "selected_at": "2026-09-01T00:00:00Z",
        "frozen_at": "2026-09-02T00:00:00Z",
        "selection_sha256": None,
    }
    selection["selection_sha256"] = accounting.selection_hash(selection)
    reviews = [
        {
            "schema_version": "ml08-review/1.0.0",
            "review_id": f"SYNTHETIC-r{i}",
            "candidate_id": f"SYNTHETIC-{i}",
            "selection_sha256": selection["selection_sha256"],
            "reviewer_id": "synthetic-A",
            "reviewer_kind": "human",
            "role": "primary",
            "revision": 1,
            "supersedes_review_id": None,
            "completed_at": "2026-09-03T00:00:00Z",
            "active_minutes": None,
            "active_minutes_by_field": {},
            "outcome": "inaccessible",
            "outcome_reason": "Synthetic failure",
            "independent_assessment": False,
            "requires_second_review": False,
            "compares_review_ids": [],
            "comparison": "not_compared",
            "disagreement_codes": [],
            "results": [],
        }
        for i in range(60)
    ]
    reviews.append(
        {
            **reviews[0],
            "review_id": "SYNTHETIC-second",
            "reviewer_id": "synthetic-B",
            "role": "secondary",
            "independent_assessment": True,
            "compares_review_ids": [reviews[0]["review_id"]],
            "comparison": "agreement",
        }
    )
    conclusion = {
        "schema_version": "ml08-conclusion/1.0.0",
        "status": "submitted_for_signoff",
        "selection_sha256": selection["selection_sha256"],
        "review_log_sha256": accounting.review_hash(reviews),
        "reviewer_id": "synthetic-B",
        "completed_at": "2026-09-04T00:00:00Z",
        "recommendation": "stop",
        "rationale": "Synthetic failure only",
        "field_actions": [
            {"field": field, "action": "defer", "reason": "Synthetic only"}
            for field in accounting.FIELDS
        ],
        "canary_bundle_reference": "Synthetic unopened canary",
        "canary_bundle_sha256": "c" * 64,
        "limitations": ["No actual scientific review"],
    }
    raw = {
        "selection": accounting.canonical(selection),
        "reviews": b"\n".join(accounting.canonical(r) for r in reviews),
        "protocol": protocol,
        "conclusion": accounting.canonical(conclusion),
    }
    upload = {
        "version": worker.VERSION,
        "parameters": {
            "participant_id": "00000000-0000-4000-8000-000000000001",
            "participant_sha256": "a" * 64,
            "registration_sha256": "b" * 64,
        },
        "selection_sha256": selection["selection_sha256"],
        "review_log_sha256": conclusion["review_log_sha256"],
        **{
            name + "_base64": base64.b64encode(value).decode()
            for name, value in raw.items()
        },
        **{name + "_file_sha256": documents.sha(value) for name, value in raw.items()},
    }
    try:
        result = loop.run_until_complete(
            worker.check_in_worker(accounting.canonical(upload))
        )
        upload["version"] = worker.ATTESTATION_VERSION
        upload["parameters"].update(
            request_key="synthetic-installed-attestation",
            reason_code="synthetic",
            supersedes_id=None,
            supersedes_sha256=None,
            declaration_version="ml08-own-review-declaration/1.0.0",
            declaration_sha256=contract.SHA256,
            declaration_acknowledged=True,
            expected_intent_sha256=None,
            dry_run=True,
        )
        attestation = loop.run_until_complete(
            worker.check_in_worker(accounting.canonical(upload), attestation=True)
        )
    finally:
        loop.close()
    checked = result["document_check"]
    if (
        len(spawned) != 2
        or attestation["document_check"] != result["document_check"]
        or attestation["implementation"] != implementation
        or result["implementation"] != implementation
        or checked["selected_candidates"] != 60
        or checked["review_record_count"] != 61
        or checked["recommendation"] != "stop"
    ):
        raise RuntimeError("pilot_review_probe_contract_mismatch")
    print(
        json.dumps(
            {
                "probe": "ml08-installed-review-worker/1.1.0",
                "synthetic": True,
                "package_version": importlib.metadata.version("sclib-api"),
                "python": sys.version.split()[0],
                "implementation": implementation,
                "input_sha256": result["input_sha256"],
                "attestation_upload_sha256": attestation["input_sha256"],
                "exact_owned_child_count": 2,
                "selected_candidates": 60,
                "review_record_count": 61,
                "database_clock_checked": False,
                "account_attribution_checked": False,
                "attestation_recorded": False,
                "canary_replay_verified": False,
                "scientific_acceptance": False,
                "training_execution": "disabled",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
