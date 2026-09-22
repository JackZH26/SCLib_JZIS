"""Probe a freshly installed SCLib API wheel, with no repository import fallback.

Run with that environment's Python -I. Only synthetic unreviewed candidates are
used. No services, scientific review, permission, registration or run is created.
"""
from __future__ import annotations

import hashlib
import importlib.abc
import importlib.metadata
import json
import sys
from pathlib import Path


def main():
    if not sys.flags.isolated:
        raise RuntimeError("pilot_install_probe_requires_isolated_python")

    class NoServerImports(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split(".")[0] in {"scripts", "main", "config", "models", "sqlalchemy", "redis", "httpx", "ingestion", "tiktoken"}:
                raise RuntimeError("pilot_install_probe_application_import_forbidden")

    def deny_external_io(event, args):
        if event in {"socket.__new__", "socket.connect", "socket.getaddrinfo", "subprocess.Popen", "os.system"}:
            raise RuntimeError("pilot_install_probe_external_io_forbidden")

    sys.meta_path.insert(0, NoServerImports())
    sys.addaudithook(deny_external_io)
    from services import ml_pilot_accounting as accounting
    from services import ml_pilot_documents as documents

    installed = Path(sys.prefix).resolve()
    for path in (Path(accounting.__file__), Path(documents.__file__), accounting.SCHEMA_PATH):
        if not path.resolve().is_relative_to(installed):
            raise RuntimeError("pilot_install_probe_repository_fallback_forbidden")
    protocol = b"SYNTHETIC install probe; no approved scientific protocol."
    sha = lambda raw: hashlib.sha256(raw).hexdigest()
    selection = {
        "schema_version": "ml08-selection/1.0.0", "pilot_id": "SYNTHETIC-wheel-probe",
        "protocol_status": "approved", "protocol_revision": "synthetic-only", "protocol_sha256": sha(protocol),
        "approval_reference": "Synthetic declaration, not approval", "selection_status": "frozen",
        "target_candidate_count": 60, "selection_method": "Synthetic install probe only",
        "strata": [{"id": "synthetic", "definition": "No scientific stratum"}],
        "candidates": [{"candidate_id": f"SYNTHETIC-{i}", "selection_kind": "actual_source_event",
            "stratum_id": "synthetic", "family": "synthetic", "source_class": "synthetic",
            "source_reference": "Not an actual paper", "event_locator": "Not an actual event",
            "selection_rationale": "Software installation fixture only"} for i in range(60)],
        "reviewers": [{"id": "synthetic-A", "kind": "human", "roles": ["primary"]},
                      {"id": "synthetic-B", "kind": "human", "roles": ["secondary"]}],
        "second_review_candidate_ids": ["SYNTHETIC-0"], "independence_plan": "No actual humans participated",
        "selected_at": "2026-09-01T00:00:00Z", "frozen_at": "2026-09-02T00:00:00Z", "selection_sha256": None,
    }
    selection["selection_sha256"] = accounting.selection_hash(selection)
    raw = accounting.canonical(selection)
    result = documents.inspect_documents(selection_raw=raw, reviews_raw=b"", protocol_raw=protocol,
        selection_file_sha256=sha(raw), reviews_file_sha256=sha(b""), protocol_file_sha256=sha(protocol),
        selection_sha256=selection["selection_sha256"], review_log_sha256=accounting.review_hash([]))
    report = result["accounting"]
    if (report["errors"] or not report["ready_for_review"] or report["ready_for_final_human_signoff"]
            or report["counts"]["unreviewed_candidates"] != 60 or any(result["authority"].values())
            or result["registration_recorded"] or result["context_bytes_checked"] or result["canary_replay_verified"]
            or result["training_execution"] != "disabled"):
        raise RuntimeError("pilot_install_probe_contract_mismatch")
    print(json.dumps({"probe": "ml08-installed-wheel/1.0.0", "synthetic": True,
        "package_version": importlib.metadata.version("sclib-api"), "python": sys.version.split()[0],
        "selected_candidates": 60, "unreviewed_candidates": 60,
        "schema_sha256": sha(accounting.SCHEMA_PATH.read_bytes()),
        "accounting_source_sha256": sha(Path(accounting.__file__).read_bytes()),
        "documents_source_sha256": sha(Path(documents.__file__).read_bytes()),
        "scientific_acceptance": False, "registration_recorded": False, "training_execution": "disabled"}, sort_keys=True))


if __name__ == "__main__":
    main()
