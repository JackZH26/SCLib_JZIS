"""Offline evidence routing, never scientific/training/publication admission.

classify_candidate_evidence(state, reported_source, evidence_requests, artifact_root)
returns a closed, payload-free routing result. The only native adapter initially
supported is the frozen, already replayed nine-job QE pilot. New engine/results
need an explicit reader adapter, not a self-reported ``verified`` boolean.

CLI: --request JSON --artifact-root DIR (stdout JSON only; no writes/network).
Native request: kind=native_calculation, adapter=retained_qe_pilot_v1,
reading_sha256, quantities, bundle/capture/readback relative directories.
State uses the existing ResearchStateInput contract verbatim. Its exact approved
state is read from the frozen research-case export, not reconstructed by formula.
Literature and provider captures route to review even when bytes are pinned.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
VERSION = "discovery-candidate-evidence-routing/1.0.0"
SUMMARY_PATH = "frontend/public/research-pilots/discovery-qe-pilot-2026-10-06.json"
SUMMARY_SHA = "64b9273b553cf3a4790f7bb64f497dbcbf5a3eb142ebea79c83a7a026aec8d29"
MAX_FILE = 8 * 1024 * 1024
MAX_TOTAL = 96 * 1024 * 1024
MAX_REQUEST = 1024 * 1024
HASH = re.compile(r"[a-f0-9]{64}\Z")
AUTHORITY = {
    "scientific_acceptance": False, "observed_origin_promoted": False,
    "ml_training_approved": False, "publication_approved": False,
    "properties_inherited": False, "rps_score": None, "rank": None,
}


class AdmissionError(ValueError):
    """Only stable codes, never source text, paths or native data."""


def require(value, code):
    if not value:
        raise AdmissionError(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def _nonfinite(_):
    raise AdmissionError("nonfinite_json")


def decode(raw):
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_nonfinite)
    except (UnicodeError, ValueError, RecursionError):
        raise AdmissionError("invalid_json") from None


def relative(path):
    require(type(path) is str and 0 < len(path) <= 512, "invalid_relative_path")
    parts = path.split("/")
    require(not PurePosixPath(path).is_absolute() and all(x not in ("", ".", "..") for x in parts)
            and "\\" not in path and "\x00" not in path, "invalid_relative_path")
    return parts


class Files:
    """Bounded reads through one fd; no symlink in any relative component."""
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        self.total = 0

    def read(self, path, expected=None, size=None, maximum=MAX_FILE):
        parts = relative(path)
        descriptors = []
        try:
            descriptors.append(os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW))
            for part in parts[:-1]:
                descriptors.append(os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                           dir_fd=descriptors[-1]))
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=descriptors[-1])
            descriptors.append(fd)
            before = os.fstat(fd)
            require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= maximum,
                    "artifact_not_regular_or_size_limit")
            chunks, remaining = [], maximum + 1
            while remaining:
                chunk = os.read(fd, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            after = os.fstat(fd)
            require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                    and len(raw) == before.st_size and len(raw) <= maximum, "artifact_changed_or_size_limit")
            self.total += len(raw)
            require(self.total <= MAX_TOTAL, "aggregate_read_limit")
            require(size is None or (type(size) is int and len(raw) == size), "artifact_size_mismatch")
            require(expected is None or (type(expected) is str and HASH.fullmatch(expected)
                                         and digest(raw) == expected), "artifact_hash_mismatch")
            return raw
        except OSError:
            raise AdmissionError("artifact_unavailable_or_unsafe") from None
        finally:
            for fd in reversed(descriptors):
                os.close(fd)

    def pinned(self, base, pin):
        require(type(pin) is dict and set(pin) >= {"path", "sha256", "bytes"}, "artifact_pin_missing")
        return self.read("/".join([base, pin["path"]]) if base else pin["path"], pin["sha256"], pin["bytes"])


def _keys(value, allowed, required):
    require(type(value) is dict and set(value) <= set(allowed) and set(required) <= set(value), "invalid_shape")


def _source(reported):
    _keys(reported, ["kind", "labels", "source_sha256"], ["kind", "labels"])
    require(reported["kind"] in ["heuristic_prescreen", "literature", "provider_metadata", "unknown"], "source_kind_invalid")
    _keys(reported["labels"], ["evidence_level", "checker_status", "source_type", "claim_level", "review_status"], [])
    require(all(v is None or (type(v) is str and len(v) <= 512) for v in reported["labels"].values()), "source_label_invalid")
    if "source_sha256" in reported:
        require(type(reported["source_sha256"]) is str and HASH.fullmatch(reported["source_sha256"]), "source_hash_invalid")
    return json.loads(canonical(reported))


def retained_pilot_references(repository_root=ROOT):
    """Frozen trust root; user-supplied self-hashes cannot register new results.

    This reads existing public artefacts; it does not claim to replay the native
    TS parser here. The original readback recipe and native bytes are checked
    separately below. Changing this root is a code-reviewed adapter extension.
    """
    files = Files(repository_root)
    summary = decode(files.read(SUMMARY_PATH, SUMMARY_SHA))
    entries = {}
    for state in summary["states"]:
        comp = decode(files.read("frontend/public" + state["comparison_download_url"], state["comparison_sha256"]))
        pin = state["case_exports"]["prepared"]
        case = decode(files.read("frontend/public" + pin["download_url"], pin["sha256"]))["record"]
        for point in state["points"]:
            key = point["file_hashes"]["reading"]
            reading = next(r for r in comp["readings"] if r["sha256"] == key)
            require(key not in entries, "duplicate_frozen_reading")
            entries[key] = {"state": case["definition"]["state"], "point": point,
                            "comparison": state, "report": reading["report"], "summary": summary}
    require(len(entries) == 9, "frozen_pilot_shape")
    return entries


def _native(state, request, files, repository_root):
    _keys(request, ["kind", "adapter", "reading_sha256", "quantities", "bundle", "capture", "readback"],
          ["kind", "adapter", "reading_sha256", "quantities", "bundle", "capture", "readback"])
    require(request["adapter"] == "retained_qe_pilot_v1", "unsupported_native_reader")
    refs = retained_pilot_references(repository_root)
    key = request["reading_sha256"]
    require(type(key) is str and key in refs, "unregistered_native_reading")
    ref = refs[key]
    require(type(state) is dict and canonical(state) == canonical(ref["state"]), "candidate_state_or_source_mismatch")
    quantities = request["quantities"]
    allowed = {"total_energy", "fermi_energy", "valence_electrons", "scf_error", "scf_iterations"}
    require(type(quantities) is list and 0 < len(quantities) <= len(allowed)
            and all(type(q) is str and q in allowed for q in quantities)
            and len(set(quantities)) == len(quantities), "unsupported_named_quantity")
    bundle, capture, readback = (request[k] for k in ["bundle", "capture", "readback"])
    for p in (bundle, capture, readback):
        relative(p)
    summary, point, report = ref["summary"], ref["point"], ref["report"]
    Files(repository_root).read("frontend/public/research-pilots/structure-cifs/"
                                + report["source_reference"]["original_cif_filename"],
                                report["source_reference"]["source"]["file_sha256"])
    read_summary = decode(files.read(readback + "/reading-summary.json", summary["reader_summary_sha256"]))
    plan = decode(files.read(bundle + "/pilot-plan.json", summary["protocol"]["plan_sha256"]))
    bundle_manifest = decode(files.read(bundle + "/bundle-manifest.json", read_summary["bundle_manifest_sha256"]))
    for pin in bundle_manifest["files"]:
        if pin["path"].startswith(("states/", "source-receipts/")):
            files.pinned(bundle, pin)
    job = next(j for j in plan["jobs"] if j["catalogue_state_id"] == state["catalogue_reference"]["catalog_state_id"]
               and j["mesh"] == point["mesh"])
    require(report["candidate_id"] == job["lineage"]["generated_candidate_id"]
            and report["candidate_cif_sha256"] == state["structure"]["sha256"]
            and report["preparation_id"] == job["qe_preparation_id"], "frozen_method_or_identity_mismatch")
    # Pin original pre-run recipe and post-run reader recipe. Neither is silently
    # replaced with the newer repaired runner/read harness in the current repo.
    for pin in plan["recipe_files"]:
        files.pinned(bundle, pin)
    for pin in read_summary["files"]:
        if pin["path"].startswith("reader-recipe/"):
            files.pinned(readback, pin)
    reading_pin = next(p for p in read_summary["files"] if p["sha256"] == key)
    reading = decode(files.pinned(readback, reading_pin))
    require(canonical(reading) == canonical(report), "frozen_reading_mismatch")
    receipt = decode(files.read(capture + "/jobs/" + job["id"] + "/execution-receipt.json",
                                point["file_hashes"]["execution_receipt"]))
    for kind, expected in (("execution-started.json", read_summary["execution_started_sha256"]),
                           ("execution-finished.json", summary["execution_finished_sha256"])):
        files.read(capture + "/" + kind, expected)
    files.read(capture + "/_operator/executed-runner.py", read_summary["runner_sha256"])
    require(receipt["runner_sha256"] == read_summary["runner_sha256"]
            and receipt["pw_sha256"] == read_summary["runtime_pw_sha256"] == summary["runtime_pw_sha256"]
            and receipt["plan_sha256"] == summary["protocol"]["plan_sha256"]
            and receipt["catalogue_state_id"] == job["catalogue_state_id"], "runtime_or_state_binding_mismatch")
    files.pinned(bundle, job["preparation_manifest"])
    for which in ["execution_input", "initialization_input"]:
        files.pinned(bundle, job[which])
    for pseudo in job["pseudopotentials"]:
        files.read(bundle + "/" + job["directory"] + "/pseudo/" + pseudo["filename"],
                   pseudo["sha256"], pseudo["byte_length"])
    require([s["kind"] for s in receipt["steps"]] == ["initialization", "execution"], "execution_step_mismatch")
    for step in receipt["steps"]:
        require(step["exit_code"] == 0 and step["timed_out"] is False, "execution_failed")
        require(step["input_sha256"] == job[step["kind"] + "_input"]["sha256"], "execution_input_mismatch")
        for kind in ["xml", "stdout"]:
            files.pinned(capture, step[kind])
    require(report["settings"]["calculation"] == "scf" and report["status"] == "scf_reported_converged",
            "unsupported_native_method_or_status")
    values = {q: report["observations"][q] for q in quantities if q in report["observations"]}
    if "scf_error" in quantities:
        values["scf_error"] = {"value": report["convergence"]["scf_error_hartree"], "unit": "Hartree/cell"}
    if "scf_iterations" in quantities:
        values["scf_iterations"] = {"value": report["convergence"]["scf_steps"], "unit": "count"}
    return {"classification": "native_candidate_calculation_bytes_verified", "reason_codes": [],
            "named_quantities": values, "reading_sha256": key, "state_structure_sha256": state["structure"]["sha256"],
            "method": {"engine": report["engine"], "settings": report["settings"]},
            "custody": {"executed_runner_sha256": read_summary["runner_sha256"],
                        "original_reader_summary_sha256": summary["reader_summary_sha256"],
                        "runtime_pw_sha256_recorded_by_coordinator": summary["runtime_pw_sha256"],
                        "runtime_binary_locally_rehashed": False, "native_parser_rerun_by_classifier": False,
                        "adapter": "retained_qe_pilot_v1"},
            "review_status": "scientific_review_required", "basis_sampling_convergence_established": False,
            "mesh_window_assessment": ref["comparison"]["assessment"],
            "limitations": ["Frozen reader and coordinator custody, not independent execution authentication.",
                            "Named outputs only; no Tc, physical stability, bandwidth or mobile carrier density inference.",
                            "Valence electrons are a model electron count, not mobile carriers.",
                            "Numerical smearing is not physical temperature; pressure remains unknown."]}


def _source_artifact(request, files):
    _keys(request, ["kind", "artifact", "locator"], ["kind", "artifact"])
    raw = files.pinned("", request["artifact"])
    if request["kind"] == "literature":
        locator = request.get("locator")
        _keys(locator, ["start_byte", "end_byte", "sha256"], ["start_byte", "end_byte", "sha256"])
        a, b = locator["start_byte"], locator["end_byte"]
        require(type(a) is int and type(b) is int and 0 <= a < b <= len(raw) and b - a <= 32768,
                "passage_locator_invalid")
        require(digest(raw[a:b]) == locator["sha256"], "passage_hash_mismatch")
        classification = "pinned_literature_passage_requires_review"
    else:
        require("locator" not in request, "invalid_shape")
        classification = "pinned_provider_metadata_requires_review"
    return {"classification": classification, "artifact_sha256": digest(raw),
            "reason_codes": ["candidate_state_association_not_reviewed", "source_claim_not_adjudicated"],
            "review_status": "source_and_state_review_required", "named_quantities": {}}


def classify_candidate_evidence(candidate_identity, reported_source, evidence_requests, artifact_root,
                                *, repository_root=ROOT):
    """Preserve source claims; admit only the narrowly named byte-verified outputs.

    A blocked item is data, not an exception permitting fallback to reported DFT.
    No result from this function grants scientific, training or publish rights.
    """
    source = _source(reported_source)
    require(type(evidence_requests) is list and len(evidence_requests) <= 64, "evidence_count_limit")
    require(len(canonical(candidate_identity)) <= 65536, "state_size_limit")
    files, results = Files(artifact_root), []
    for request in evidence_requests:
        try:
            require(type(request) is dict, "invalid_shape")
            if request.get("kind") == "native_calculation":
                result = _native(candidate_identity, request, files, repository_root)
            elif request.get("kind") in ["literature", "provider_metadata"]:
                result = _source_artifact(request, files)
            else:
                raise AdmissionError("unsupported_evidence_kind")
        except (AdmissionError, KeyError, StopIteration, TypeError) as error:
            code = str(error) if isinstance(error, AdmissionError) else "artifact_contract_incomplete"
            result = {"classification": "blocked", "reason_codes": [code], "named_quantities": {},
                      "review_status": "evidence_review_required"}
        results.append(result)
    source_class = "heuristic_only" if source["kind"] == "heuristic_prescreen" else "source_reported_metadata"
    return {"schema_version": VERSION, "reported_source": source,
            "reported_source_verified": False, "source_classification": source_class,
            "evidence": results, "authority": dict(AUTHORITY)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        raw = Files(args.request.parent).read(args.request.name, maximum=MAX_REQUEST)
        request = decode(raw)
        _keys(request, ["candidate_identity", "reported_source", "evidence_requests"],
              ["candidate_identity", "reported_source", "evidence_requests"])
        result = classify_candidate_evidence(**request, artifact_root=args.artifact_root)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
        return 0
    except (AdmissionError, OSError, ValueError, TypeError, RecursionError):
        print('{"error":"candidate_evidence_request_rejected"}')
        return 2


if __name__ == "__main__":
    sys.exit(main())
