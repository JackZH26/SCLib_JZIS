"""Inert, offline initialization custody reader; synthetic-output tests only.

CoordinatorPins must come from separate coordinator custody records, never from
the returned metadata being checked. Pins authenticate no origin by themselves.
All supplied bytes are revalidated; no verified-object or success-flag shortcut.
The release manifest is only hash-bound here. Its contents and installation are
unverified, so execution readiness remains false even for consistent captures.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from pathlib import PurePosixPath

from sclib_compute.contracts import Completion, FilePin, JobSpec, canonical, digest
from sclib_compute.native_contract import NativeRuntime
from sclib_compute.pbesol_init_reader import decode_supported_xml, read_initialization
from sclib_compute.pbesol_native_contract import (
    BINDING_NAME,
    OUTPUT_CAPS,
    validate_pbesol_inputs,
)

THREADS = {
    key: "1"
    for key in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    )
}
RAW_NAMES = set(OUTPUT_CAPS) - {"execution.json"}
SHA = re.compile(r"[0-9a-f]{64}")
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}")


@dataclass(frozen=True, slots=True)
class CoordinatorPins:
    """Independent reference values, not a verified or authenticated authority token."""

    export_sha256: str
    submitted_spec_sha256: str
    runtime_config_sha256: str
    adapter_release_sha256: str
    node_id: str
    attempt_id: str
    fencing_token: int
    attempt_root: str


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def integer(value, lower=0, upper=2**63 - 1):
    require(type(value) is int and lower <= value <= upper, "bounded exact integer required")


def number(value, lower=0, upper=2**63 - 1):
    require(
        type(value) in {int, float} and math.isfinite(value) and lower <= value <= upper,
        "bounded finite number required",
    )


def keys(value, expected):
    require(type(value) is dict and set(value) == set(expected.split()), "closed object fields required")


def bounded(raw, maximum):
    require(type(raw) is bytes and len(raw) <= maximum, "bounded immutable bytes required")


def strict_json(raw, maximum):
    bounded(raw, maximum)

    def pairs(rows):
        result = {}
        for key, value in rows:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def constant(_value):
        raise ValueError("nonfinite JSON constant")

    return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)


def path(value):
    require(
        type(value) is str and 0 < len(value) <= 1024 and "\x00" not in value and "\\" not in value,
        "bounded POSIX path required",
    )
    parsed = PurePosixPath(value)
    require(
        parsed.is_absolute() and str(parsed) == value and ".." not in parsed.parts and not value.startswith("//"),
        "canonical absolute POSIX path required",
    )
    return parsed


def snapshot(files, maximum_count, maximum_total):
    require(type(files) is dict and 0 < len(files) <= maximum_count, "bounded exact file map required")
    copied = files.copy()
    require(
        all(type(k) is str and ID.fullmatch(k) and type(v) is bytes for k, v in copied.items()),
        "bounded artifact names and immutable bytes required",
    )
    require(sum(len(v) for v in copied.values()) <= maximum_total, "file map exceeds total cap")
    return copied


def file_pin(name, raw):
    return {"name": name, "bytes": len(raw), "sha256": sha(raw)}


def validate_references(expected, export, submitted, runtime, release):
    require(type(expected) is CoordinatorPins, "exact independent coordinator reference required")
    for name in ("export_sha256", "submitted_spec_sha256", "runtime_config_sha256", "adapter_release_sha256"):
        value = getattr(expected, name)
        require(type(value) is str and SHA.fullmatch(value), "independent SHA256 required")
    for value in (expected.node_id, expected.attempt_id):
        require(type(value) is str and ID.fullmatch(value), "independent bounded identifier required")
    integer(expected.fencing_token, 1)
    require(path(expected.attempt_root).name == expected.attempt_id, "attempt root identity mismatch")
    for raw, maximum, pin in (
        (export, 1024**2, expected.export_sha256),
        (submitted, 65536, expected.submitted_spec_sha256),
        (runtime, 65536, expected.runtime_config_sha256),
        (release, 256 * 1024, expected.adapter_release_sha256),
    ):
        bounded(raw, maximum)
        require(sha(raw) == pin, "independent raw reference pin mismatch")
    # The release content is not an installed-release verifier or transport format.
    require(type(strict_json(release, 256 * 1024)) is dict, "release record must be an object")


def validate_returned_initialization(
    export_bytes: bytes,
    input_files: dict[str, bytes],
    output_files: dict[str, bytes],
    *,
    submitted_spec_bytes: bytes,
    runtime_config_bytes: bytes,
    adapter_release_manifest_bytes: bytes,
    expected: CoordinatorPins,
):
    """Check one pinned historical export; never assert live server freshness.

    Separate coordinator capture/submission/installation records are a caller
    precondition. A caller cannot replace them with returned execution fields.
    This function performs no filesystem fetch, network, process or queue action.
    Installed input validation still reads its three fixed hash-pinned trust files.
    """
    report = {
        "schema_version": "sclib-pbesol-returned-init-custody-candidate/1",
        "implementation_status": "offline_synthetic_output_tests_only",
        "input_binding_verified": False,
        "custody_verified": False,
        "custody_scope": "conditional_byte_graph_given_independent_coordinator_pins",
        "transport_consistency_verified": False,
        "current_returned_attempt": None,
        "current_state_scope": "as_of_pinned_export_only_not_live",
        "capture_complete": None,
        "semantic_reading_status": "not_read",
        "process_outcome_consistent": False,
        "reported_limits_within_envelope": None,
        "execution_consistency_ready_for_review": False,
        "next_stage_ready": False,
        "installed_release_verified": False,
        "release_manifest_content_verified": False,
        "remote_runtime_attested": False,
        "coordinator_capture_authenticated": None,
        "scientific_acceptance": False,
        "candidate_grade_changed": False,
        "tc_calculated": False,
        "physical_outputs": {
            key: None
            for key in (
                "total_energy_hartree",
                "forces",
                "stress",
                "fermi_energy_hartree",
                "electrons",
                "scf_error_hartree",
            )
        },
        "solver_calls": 0,
        "queue_calls": 0,
        "rejection": None,
        "raw_pins": {},
        "semantic_reading": None,
        "limitations": [
            "Independent coordinator pins are a trust precondition, not remote cryptographic attestation.",
            "Opaque release-manifest bytes do not verify installed worker/guardian/trust contents.",
            "Reported binary hashes and sampled RSS do not prove loaded BLAS/shared libraries or resource history.",
            "No real PBEsol output has been assessed by this offline reader.",
        ],
    }
    try:
        require(type(expected) is CoordinatorPins, "exact independent coordinator reference required")
        expected = replace(expected)  # Detach even frozen references from a hostile caller.
        inputs = snapshot(input_files, 8, 4 * 1024**2)
        outputs = snapshot(output_files, 4, sum(OUTPUT_CAPS.values()))
        bounded(export_bytes, 1024**2)
        report["raw_pins"] = {
            "server_export": file_pin("server-export.json", export_bytes),
            "outputs": [file_pin(n, b) for n, b in sorted(outputs.items())],
        }
        validate_references(
            expected, export_bytes, submitted_spec_bytes, runtime_config_bytes, adapter_release_manifest_bytes
        )
        export = strict_json(export_bytes, 1024**2)
        keys(export, "job attempt files")
        job, attempt = export["job"], export["attempt"]
        keys(job, "job_id spec spec_sha status fence attempt_count current_attempt created_at")
        keys(
            attempt,
            "attempt_id job_id node_id fence status lease_until started_at phase elapsed_seconds memory_bytes completion_sha receipt failure_code",
        )
        submitted = strict_json(submitted_spec_bytes, 65536)
        spec = JobSpec.model_validate(submitted)
        require(
            canonical(submitted) == canonical(spec.model_dump(mode="json")), "submission uses default/coerced fields"
        )
        require(canonical(job["spec"]) == canonical(submitted), "export differs from independent submitted JobSpec")
        require(spec.kind == "qe_initialize", "initialization-only custody profile")
        require(job["spec_sha"] == digest(submitted), "job canonical digest mismatch")
        runtime_raw = strict_json(runtime_config_bytes, 65536)
        runtime = NativeRuntime.model_validate(runtime_raw)
        require(
            canonical(runtime_raw) == canonical(runtime.model_dump(mode="json")), "runtime uses default/coerced fields"
        )
        for executable in (runtime.pw, runtime.mpiexec):
            path(executable.path)
        projection = validate_pbesol_inputs(spec, inputs, expected_runtime_id=runtime.runtime_id)
        require(
            spec.resources.cpu_cores <= runtime.max_cpu_cores
            and spec.resources.wall_seconds <= runtime.max_wall_seconds
            and spec.resources.memory_bytes <= runtime.max_memory_bytes,
            "independent runtime envelope exceeded",
        )
        report["input_binding_verified"] = True
        require(spec.job_id == job["job_id"] == attempt["job_id"], "job identity mismatch")
        require(
            attempt["attempt_id"] == expected.attempt_id and attempt["node_id"] == expected.node_id,
            "independent attempt/node mismatch",
        )
        integer(attempt["fence"], 1)
        require(attempt["fence"] == expected.fencing_token, "independent attempt fence mismatch")
        integer(job["fence"], attempt["fence"])
        integer(job["attempt_count"], 1, spec.max_attempts)
        require(
            type(job["current_attempt"]) is str and ID.fullmatch(job["current_attempt"]), "current attempt ID required"
        )
        require(job["status"] in {"queued", "leased", "lost", "returned", "failed", "cancelled"}, "unknown job status")
        for key in ("created_at",):
            number(job[key])
        for key in ("lease_until", "started_at"):
            number(attempt[key])
        integer(attempt["elapsed_seconds"], 0, 86400)
        integer(attempt["memory_bytes"], 0, 1024**4)
        require(attempt["phase"] in {"leased", "preparing", "running", "uploading"}, "unknown attempt phase")
        receipt = attempt["receipt"]
        keys(
            receipt,
            "schema_version attempt_id job_id node_id fencing_token status reason completion_sha256 input_manifest_sha256 manifest_sha256 received_at_unix solver_outcome scientific_status scientific_publication_authority production_database_access",
        )
        require(receipt["schema_version"] == "sclib-compute-receipt/1", "receipt version mismatch")
        for key, value in {
            "job_id": spec.job_id,
            "attempt_id": expected.attempt_id,
            "node_id": expected.node_id,
        }.items():
            require(receipt[key] == value, "receipt identity mismatch")
        integer(receipt["fencing_token"], 1)
        require(receipt["fencing_token"] == expected.fencing_token, "receipt fence mismatch")
        status = receipt["status"]
        require(
            attempt["status"] == status and status in {"returned", "quarantined"},
            "returned/quarantined receipt required",
        )
        require(
            (status == "returned" and receipt["reason"] is None)
            or (
                status == "quarantined"
                and receipt["reason"]
                in {"stale_attempt", "input_or_runtime_mismatch", "reported_resource_limit_exceeded"}
            ),
            "receipt status/reason mismatch",
        )
        failure = attempt["failure_code"]
        require(
            failure is None
            or (
                status == "quarantined"
                and failure
                in {
                    "lease_expired",
                    "download_interrupted",
                    "upload_interrupted",
                    "worker_crash",
                    "execution_timeout",
                    "solver_failure",
                    "not_converged",
                }
            ),
            "failure history is inconsistent with receipt",
        )
        require(
            receipt["scientific_status"] == "not_assessed"
            and receipt["scientific_publication_authority"] is False
            and receipt["production_database_access"] is False,
            "receipt authority mismatch",
        )
        number(receipt["received_at_unix"], attempt["started_at"])
        require(receipt["input_manifest_sha256"] == spec.input_manifest_sha256, "receipt input manifest mismatch")
        require(type(export["files"]) is list and len(export["files"]) == 4, "four returned FilePins required")
        pins = [FilePin.model_validate(v) for v in export["files"]]
        require([p.name for p in pins] == sorted(OUTPUT_CAPS), "exact lexical output manifest required")
        require(set(outputs) == set(OUTPUT_CAPS), "exact four output bytes required")
        rules = {p.name: p.max_bytes for p in spec.output_rules}
        for pin in pins:
            raw = outputs[pin.name]
            require(
                len(raw) <= rules[pin.name] and pin.model_dump(mode="json") == file_pin(pin.name, raw),
                "returned output pin mismatch",
            )
        require(sum(len(b) for b in outputs.values()) <= spec.resources.output_bytes, "returned output total exceeded")
        manifest = [p.model_dump(mode="json") for p in pins]
        require(receipt["manifest_sha256"] == digest(manifest), "receipt output manifest digest mismatch")
        execution = strict_json(outputs["execution.json"], OUTPUT_CAPS["execution.json"])
        keys(
            execution,
            "schema_version adapter_version job_id attempt_id fencing_token kind runtime_id runtime_pins runtime_config_sha256 input_manifest_sha256 input_manifest solver_outcome process elapsed_seconds capture checks artifacts restart_mode checkpoint_resume shell_execution scientific_status scientific_publication_authority limitations input_binding method_profile source_id preparation_phase adapter_release_manifest_sha256",
        )
        contract = {
            "schema_version": "sclib-pbesol-qe-execution/1",
            "adapter_version": "pbesol-qe/1",
            "job_id": spec.job_id,
            "attempt_id": expected.attempt_id,
            "kind": "qe_initialize",
            "runtime_id": runtime.runtime_id,
            "runtime_pins": runtime_raw,
            "runtime_config_sha256": digest(runtime_raw),
            "input_manifest_sha256": spec.input_manifest_sha256,
            "input_manifest": [p.model_dump(mode="json") for p in spec.input_artifacts],
            "artifacts": [p for p in manifest if p["name"] != "execution.json"],
            "restart_mode": "from_scratch",
            "checkpoint_resume": False,
            "shell_execution": False,
            "scientific_status": "not_assessed",
            "scientific_publication_authority": False,
            "input_binding": file_pin(BINDING_NAME, inputs[BINDING_NAME]),
            "method_profile": "pbesol-source-coarse-qe75/1",
            "source_id": projection.source_id,
            "preparation_phase": "initialize",
            "adapter_release_manifest_sha256": expected.adapter_release_sha256,
        }
        for key, value in contract.items():
            require(canonical(execution[key]) == canonical(value), "execution contract mismatch: " + key)
        integer(execution["fencing_token"], 1)
        require(execution["fencing_token"] == expected.fencing_token, "execution fence mismatch")
        integer(execution["elapsed_seconds"], 0, 86400)
        if execution["elapsed_seconds"] > spec.resources.wall_seconds:
            require(
                status == "quarantined" and receipt["reason"] == "reported_resource_limit_exceeded",
                "server resource quarantine contradicts reported elapsed",
            )
        elif receipt["reason"] == "reported_resource_limit_exceeded":
            raise ValueError("resource quarantine has no reported elapsed overrun")
        require(
            type(execution["limitations"]) is list
            and len(execution["limitations"]) <= 10
            and all(type(x) is str and len(x) <= 512 for x in execution["limitations"]),
            "bounded execution limitations required",
        )
        process = execution["process"]
        keys(process, "schema_version reason exit_code elapsed_seconds peak_memory_bytes argv thread_environment")
        require(process["schema_version"] == "sclib-native-process/1", "process version mismatch")
        require(type(process["reason"]) is str and 0 < len(process["reason"]) <= 160, "bounded process reason required")
        if process["exit_code"] is not None:
            integer(process["exit_code"], -255, 255)
        require(
            process["reason"] != "completed" or process["exit_code"] is not None,
            "completed process requires a concrete exit code",
        )
        number(process["elapsed_seconds"], 0, 86400)
        integer(process["peak_memory_bytes"], 0, 1024**4)
        require(
            execution["elapsed_seconds"] >= math.ceil(process["elapsed_seconds"]),
            "completion elapsed is shorter than solver process",
        )
        argv, threads = process["argv"], process["thread_environment"]
        require(type(argv) is list and type(threads) is dict, "process observations must be list/object")
        if argv or threads:
            require(
                argv
                == [
                    runtime.mpiexec.path,
                    "-n",
                    str(spec.resources.cpu_cores),
                    runtime.pw.path,
                    "-in",
                    expected.attempt_root + "/work/" + projection.input_name,
                ]
                and threads == THREADS,
                "fixed MPI command or threads mismatch",
            )
        else:
            require(
                process["reason"] != "completed"
                and process["exit_code"] is None
                and process["elapsed_seconds"] == 0
                and process["peak_memory_bytes"] == 0,
                "absent launch observations cannot describe completed execution",
            )
        capture = execution["capture"]
        require(type(capture) is dict and set(capture) == RAW_NAMES, "exact raw capture inventory required")
        complete = True
        for name, row in capture.items():
            keys(row, "present truncated original_bytes")
            require(type(row["present"]) is bool and type(row["truncated"]) is bool, "exact capture booleans required")
            size = len(outputs[name])
            if not row["present"]:
                require(
                    not row["truncated"] and row["original_bytes"] is None and size == 0, "absent capture contradiction"
                )
            else:
                integer(row["original_bytes"])
                require(
                    (row["truncated"] and size == rules[name] and row["original_bytes"] > size)
                    or (not row["truncated"] and row["original_bytes"] == size),
                    "capture byte count contradiction",
                )
            complete = complete and row["present"] and not row["truncated"]
        stdout = outputs["stdout.txt"].decode("utf-8", errors="replace")
        parseable = False
        xml_text = decode_supported_xml(outputs["data-file-schema.xml"])
        if xml_text and not capture["data-file-schema.xml"]["truncated"]:
            try:
                ET.fromstring(xml_text)
                parseable = True
            except ET.ParseError:
                pass
        checks = {
            "pwscf_7_5_seen": bool(re.search(r"Program\s+PWSCF\s+v\.7\.5(?:\s|\b)", stdout)),
            "job_done_seen": "JOB DONE." in stdout,
            "xml_parseable": parseable,
            "scf_convergence_message": bool(re.search(r"convergence has been achieved", stdout, re.IGNORECASE)),
        }
        require(canonical(execution["checks"]) == canonical(checks), "execution checks differ from raw capture")
        negative = bool(re.search(r"convergence NOT achieved|convergence has NOT been achieved", stdout, re.IGNORECASE))
        if process["reason"] != "completed" or any(row["truncated"] for row in capture.values()):
            outcome = "interrupted"
        elif negative:
            outcome = "not_converged"
        elif (
            process["exit_code"] != 0
            or not all(checks[k] for k in ("pwscf_7_5_seen", "job_done_seen", "xml_parseable"))
            or not complete
        ):
            outcome = "solver_failure"
        else:
            outcome = "success"
        require(
            execution["solver_outcome"] == receipt["solver_outcome"] == outcome, "raw process/capture outcome mismatch"
        )
        completion = Completion(
            fencing_token=expected.fencing_token,
            input_manifest_sha256=spec.input_manifest_sha256,
            runtime_id=runtime.runtime_id,
            manifest=pins,
            solver_outcome=outcome,
            elapsed_seconds=execution["elapsed_seconds"],
        )
        require(
            digest(completion.model_dump(mode="json")) == attempt["completion_sha"] == receipt["completion_sha256"],
            "reconstructed Completion digest mismatch",
        )
        semantic = read_initialization(
            inputs[BINDING_NAME],
            {n: b for n, b in inputs.items() if n != BINDING_NAME},
            xml=outputs["data-file-schema.xml"],
            stdout=outputs["stdout.txt"],
            stderr=outputs["stderr.txt"],
            process_exit_code=process["exit_code"],
        )
        report.update(
            custody_verified=True,
            transport_consistency_verified=True,
            current_returned_attempt=status == "returned"
            and job["status"] == "returned"
            and job["current_attempt"] == expected.attempt_id
            and job["fence"] == expected.fencing_token,
            capture_complete=complete,
            semantic_reading_status=semantic["semantic_reading_status"],
            semantic_reading=semantic,
            process_outcome_consistent=True,
            reported_limits_within_envelope=execution["elapsed_seconds"] <= spec.resources.wall_seconds
            and process["peak_memory_bytes"] <= spec.resources.memory_bytes,
            raw_process_exit_code=process["exit_code"],
            process_reason=process["reason"],
            transport_solver_outcome=outcome,
            xml_exit_status=semantic.get("xml_exit_status"),
            exit_requires_review=process["exit_code"] != 0,
            completion_sha256=digest(completion.model_dump(mode="json")),
            receipt_sha256=digest(receipt),
            runtime_config_file_sha256=sha(runtime_config_bytes),
            adapter_release_file_sha256=sha(adapter_release_manifest_bytes),
        )
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError) as error:
        report["rejection"] = {"type": type(error).__name__, "message": str(error)[:240]}
    return report
