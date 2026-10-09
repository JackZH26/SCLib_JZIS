"""Synthetic custody graph tests only; never a real job, receipt or QE output."""

import json
import socket
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/tests"))

import test_sclib_pbesol_native_contract as envelope_tests
import test_sclib_pbesol_profile as binding_tests
from pbesol_init_fixtures import initialization_outputs
from sclib_compute import pbesol_result_custody as reader
from sclib_compute.contracts import Completion, JobSpec, canonical, digest
from sclib_compute.native_contract import NativeRuntime
from sclib_compute.pbesol_init_reader import decode_supported_xml
from test_sclib_pbesol_init_reader import optional_actual_files

synthetic = binding_tests.synthetic
IDS = tuple(binding_tests.profile.CONTEXT_IDS)


def seal(case):
    """Synthetic coordinator recapture only. Keep independent submission/runtime pins."""
    execution, export, outputs = case["execution"], case["export"], case["outputs"]
    outputs["execution.json"] = canonical(execution)
    pins = [reader.file_pin(n, b) for n, b in sorted(outputs.items())]
    completion = Completion(
        fencing_token=1,
        input_manifest_sha256=case["spec"].input_manifest_sha256,
        runtime_id=case["spec"].runtime_id,
        manifest=pins,
        solver_outcome=execution["solver_outcome"],
        elapsed_seconds=execution["elapsed_seconds"],
    )
    export["files"] = pins
    receipt = export["attempt"]["receipt"]
    receipt.update(
        completion_sha256=digest(completion.model_dump(mode="json")),
        manifest_sha256=digest(pins),
        solver_outcome=execution["solver_outcome"],
    )
    export["attempt"]["completion_sha"] = receipt["completion_sha256"]
    recapture(case)


def recapture(case):
    case["export_bytes"] = canonical(case["export"])
    case["expected"] = replace(case["expected"], export_sha256=reader.sha(case["export_bytes"]))


def fixture_case(source_sets, sid=IDS[0]):
    spec, inputs = envelope_tests.fixture_job(sid, "initialize", source_sets[sid, "initialize"])
    runtime = NativeRuntime(
        runtime_id=spec.runtime_id,
        pw={"path": "/synthetic/qe/pw.x", "sha256": "1" * 64},
        mpiexec={"path": "/synthetic/mpi/mpirun", "sha256": "2" * 64},
    ).model_dump(mode="json")
    submitted, runtime_bytes = canonical(spec.model_dump(mode="json")), canonical(runtime)
    release = canonical({"synthetic_fixture": True, "installed_release": False})
    xml, stdout = initialization_outputs(json.loads(inputs["preparation.json"]))
    outputs = {"stdout.txt": stdout, "stderr.txt": b"", "data-file-schema.xml": ET.tostring(xml)}
    attempt_id, node_id = "fixture-attempt-init", "fixture-node-pbesol"
    attempt_root = "/synthetic/attempts/" + attempt_id
    execution = {
        "schema_version": "sclib-pbesol-qe-execution/1",
        "adapter_version": "pbesol-qe/1",
        "job_id": spec.job_id,
        "attempt_id": attempt_id,
        "fencing_token": 1,
        "kind": "qe_initialize",
        "runtime_id": spec.runtime_id,
        "runtime_pins": runtime,
        "runtime_config_sha256": digest(runtime),
        "input_manifest_sha256": spec.input_manifest_sha256,
        "input_manifest": [p.model_dump(mode="json") for p in spec.input_artifacts],
        "solver_outcome": "success",
        "elapsed_seconds": 4,
        "process": {
            "schema_version": "sclib-native-process/1",
            "reason": "completed",
            "exit_code": 0,
            "elapsed_seconds": 1.25,
            "peak_memory_bytes": 65290240,
            "argv": [
                runtime["mpiexec"]["path"],
                "-n",
                "2",
                runtime["pw"]["path"],
                "-in",
                attempt_root + "/work/input.in",
            ],
            "thread_environment": dict(reader.THREADS),
        },
        "capture": {n: {"present": True, "truncated": False, "original_bytes": len(b)} for n, b in outputs.items()},
        "checks": {
            "pwscf_7_5_seen": True,
            "job_done_seen": True,
            "xml_parseable": True,
            "scf_convergence_message": False,
        },
        "artifacts": [reader.file_pin(n, b) for n, b in sorted(outputs.items())],
        "restart_mode": "from_scratch",
        "checkpoint_resume": False,
        "shell_execution": False,
        "scientific_status": "not_assessed",
        "scientific_publication_authority": False,
        "limitations": ["SYNTHETIC FIXTURE; NOT A RETURNED PBEsol EXECUTION"],
        "input_binding": reader.file_pin(reader.BINDING_NAME, inputs[reader.BINDING_NAME]),
        "method_profile": "pbesol-source-coarse-qe75/1",
        "source_id": sid,
        "preparation_phase": "initialize",
        "adapter_release_manifest_sha256": reader.sha(release),
    }
    receipt = {
        "schema_version": "sclib-compute-receipt/1",
        "attempt_id": attempt_id,
        "job_id": spec.job_id,
        "node_id": node_id,
        "fencing_token": 1,
        "status": "returned",
        "reason": None,
        "completion_sha256": "0" * 64,
        "input_manifest_sha256": spec.input_manifest_sha256,
        "manifest_sha256": "0" * 64,
        "received_at_unix": 105.5,
        "solver_outcome": "success",
        "scientific_status": "not_assessed",
        "scientific_publication_authority": False,
        "production_database_access": False,
    }
    export = {
        "job": {
            "job_id": spec.job_id,
            "spec": spec.model_dump(mode="json"),
            "spec_sha": digest(spec.model_dump(mode="json")),
            "status": "returned",
            "fence": 1,
            "attempt_count": 1,
            "current_attempt": attempt_id,
            "created_at": 99.25,
        },
        "attempt": {
            "attempt_id": attempt_id,
            "job_id": spec.job_id,
            "node_id": node_id,
            "fence": 1,
            "status": "returned",
            "lease_until": 280.0,
            "started_at": 100.0,
            "phase": "uploading",
            "elapsed_seconds": 5,
            "memory_bytes": 0,
            "completion_sha": "0" * 64,
            "receipt": receipt,
            "failure_code": None,
        },
        "files": [],
    }
    expected = reader.CoordinatorPins(
        "0" * 64,
        reader.sha(submitted),
        reader.sha(runtime_bytes),
        reader.sha(release),
        node_id,
        attempt_id,
        1,
        attempt_root,
    )
    case = {
        "spec": spec,
        "inputs": inputs,
        "outputs": outputs,
        "execution": execution,
        "export": export,
        "submitted_spec_bytes": submitted,
        "runtime_config_bytes": runtime_bytes,
        "adapter_release_manifest_bytes": release,
        "expected": expected,
    }
    seal(case)
    return case


def run(case, **overrides):
    args = {
        k: case[k]
        for k in ("submitted_spec_bytes", "runtime_config_bytes", "adapter_release_manifest_bytes", "expected")
    }
    args.update(overrides)
    return reader.validate_returned_initialization(case["export_bytes"], case["inputs"], case["outputs"], **args)


def rejected(case, **overrides):
    report = run(case, **overrides)
    assert report["rejection"] is not None
    assert report["custody_verified"] is False
    assert report["custody_scope"] == "conditional_byte_graph_given_independent_coordinator_pins"
    assert report["coordinator_capture_authenticated"] is None
    assert report["execution_consistency_ready_for_review"] is False
    assert all(value is None for value in report["physical_outputs"].values())
    return report


@pytest.mark.parametrize("sid", IDS)
def test_four_synthetic_graphs_preserve_distinct_layers(synthetic, sid):
    case = fixture_case(synthetic[0], sid)
    report = run(case)
    assert report["rejection"] is None, report
    for key in (
        "input_binding_verified",
        "custody_verified",
        "transport_consistency_verified",
        "current_returned_attempt",
        "capture_complete",
        "process_outcome_consistent",
        "reported_limits_within_envelope",
    ):
        assert report[key] is True
    for key in (
        "execution_consistency_ready_for_review",
        "next_stage_ready",
        "installed_release_verified",
        "release_manifest_content_verified",
        "remote_runtime_attested",
        "scientific_acceptance",
        "candidate_grade_changed",
        "tc_calculated",
    ):
        assert report[key] is False
    assert report["semantic_reading_status"] == "initialization_only"
    assert report["current_state_scope"] == "as_of_pinned_export_only_not_live"
    assert report["custody_scope"] == "conditional_byte_graph_given_independent_coordinator_pins"
    assert report["coordinator_capture_authenticated"] is None
    assert report["solver_calls"] == report["queue_calls"] == 0
    assert all(value is None for value in report["physical_outputs"].values())
    assert case["export"]["attempt"]["elapsed_seconds"] != case["execution"]["elapsed_seconds"]
    assert case["export"]["attempt"]["memory_bytes"] != case["execution"]["process"]["peak_memory_bytes"]


@pytest.mark.parametrize("sid", IDS)
def test_four_optional_actual_inputs_with_synthetic_returned_evidence(sid):
    case = fixture_case({(sid, "initialize"): optional_actual_files(sid)}, sid)
    report = run(case)
    assert report["rejection"] is None
    assert report["input_binding_verified"] is report["custody_verified"] is True
    assert report["custody_scope"] == "conditional_byte_graph_given_independent_coordinator_pins"
    assert report["coordinator_capture_authenticated"] is None
    assert report["semantic_reading_status"] == "initialization_only"
    assert report["execution_consistency_ready_for_review"] is report["scientific_acceptance"] is False
    assert report["implementation_status"] == "offline_synthetic_output_tests_only"
    assert all(value is None for value in report["physical_outputs"].values())


@pytest.mark.parametrize(
    "mode",
    ["os255", "stale", "quarantined", "rss_overrun", "wall_overrun", "prelaunch", "malformed_xml", "lost_quarantine"],
)
def test_negative_or_historical_captures_remain_nonready(synthetic, mode):
    case = fixture_case(synthetic[0])
    ex, exported = case["execution"], case["export"]
    if mode == "os255":
        ex["process"]["exit_code"], ex["solver_outcome"] = 255, "solver_failure"
    elif mode in {"stale", "quarantined", "lost_quarantine"}:
        exported["job"].update(current_attempt="different-attempt", fence=2, status="lost")
        if mode in {"quarantined", "lost_quarantine"}:
            exported["attempt"]["status"] = "quarantined"
            exported["attempt"]["receipt"].update(status="quarantined", reason="stale_attempt")
            if mode == "lost_quarantine":
                exported["attempt"]["failure_code"] = "lease_expired"
    elif mode == "rss_overrun":
        ex["process"]["peak_memory_bytes"] = case["spec"].resources.memory_bytes + 1
        ex["process"]["reason"], ex["solver_outcome"] = "memory_limit", "interrupted"
    elif mode == "wall_overrun":
        ex["elapsed_seconds"] = 181
        exported["job"].update(status="failed", fence=2)
        exported["attempt"]["status"] = "quarantined"
        exported["attempt"]["receipt"].update(status="quarantined", reason="reported_resource_limit_exceeded")
    elif mode == "prelaunch":
        ex["process"].update(
            argv=[],
            thread_environment={},
            reason="guardian_exit_without_result",
            exit_code=None,
            elapsed_seconds=0,
            peak_memory_bytes=0,
        )
        ex["solver_outcome"] = "interrupted"
        for name in reader.RAW_NAMES:
            case["outputs"][name] = b""
            ex["capture"][name] = {"present": False, "truncated": False, "original_bytes": None}
        ex["checks"] = dict.fromkeys(ex["checks"], False)
    else:
        case["outputs"]["data-file-schema.xml"] = b"<invalid"
        ex["capture"]["data-file-schema.xml"]["original_bytes"] = 8
        ex["checks"]["xml_parseable"], ex["solver_outcome"] = False, "solver_failure"
    ex["artifacts"] = [reader.file_pin(n, case["outputs"][n]) for n in sorted(reader.RAW_NAMES)]
    seal(case)
    report = run(case)
    assert report["rejection"] is None, report
    assert report["custody_verified"] is True
    assert report["execution_consistency_ready_for_review"] is False
    assert all(v is None for v in report["physical_outputs"].values())
    if mode == "os255":
        assert report["raw_process_exit_code"] == 255 and report["transport_solver_outcome"] == "solver_failure"
        assert report["semantic_reading_status"] == "initialization_only" and report["exit_requires_review"] is True
    if mode in {"stale", "quarantined", "lost_quarantine"}:
        assert report["current_returned_attempt"] is False
    if mode in {"rss_overrun", "wall_overrun"}:
        assert report["reported_limits_within_envelope"] is False
    if mode in {"prelaunch", "malformed_xml"}:
        assert report["semantic_reading_status"] == "unreadable"


def replace_xml(case, raw):
    case["outputs"]["data-file-schema.xml"] = raw
    case["execution"]["capture"]["data-file-schema.xml"]["original_bytes"] = len(raw)
    case["execution"]["artifacts"] = [reader.file_pin(n, case["outputs"][n]) for n in sorted(reader.RAW_NAMES)]
    seal(case)


SMALL_ENTITY = (
    '<?xml version="1.0" encoding="UTF-16"?>'
    '<!DOCTYPE espresso [<!ENTITY probe "safe-small-entity">]><espresso>&probe;</espresso>'
)
UNSUPPORTED_XML = [
    pytest.param(SMALL_ENTITY.encode(encoding), id=encoding)
    for encoding in ("utf-16", "utf-16-le", "utf-16-be", "utf-32", "utf-32-le", "utf-32-be")
] + [
    pytest.param(SMALL_ENTITY.encode("utf-8"), id="utf8-dtd"),
    pytest.param(b'<?xml version="1.0" encoding="UTF-16"?><espresso/>', id="contradictory-encoding"),
    pytest.param(b'<?xml version="1.0" encoding="ISO-8859-1"?><espresso/>', id="unsupported-encoding"),
    pytest.param(
        b'<?xml version="1.0" encoding="UTF-8" encoding="UTF-16"?><espresso/>', id="duplicate-contradictory-encoding"
    ),
    pytest.param(b'<!DOCTYPE espresso [<!ENTITY probe "safe-small-entity">]><espresso>&probe;</espresso>', id="ascii-dtd"),
    pytest.param(b'<espresso>\x00</espresso>', id="nul"),
    pytest.param(b'<espresso>\xff</espresso>', id="invalid-utf8"),
]


@pytest.mark.parametrize("raw", UNSUPPORTED_XML)
def test_unsupported_xml_rejected_before_parse_without_rewriting_evidence(synthetic, monkeypatch, raw):
    case = fixture_case(synthetic[0])
    replace_xml(case, raw)
    execution_bytes = case["outputs"]["execution.json"]

    def forbidden(*_args, **_kwargs):
        raise AssertionError("unsupported returned XML reached parser")

    # Isolate returned-output parsing without patching shared ET input-UPF reads.
    monkeypatch.setattr(reader, "ET", SimpleNamespace(fromstring=forbidden, ParseError=ET.ParseError))
    assert reader.decode_supported_xml is decode_supported_xml
    report = rejected(case)
    assert report["rejection"]["type"] == "Rejected"
    assert report["semantic_reading"] is None
    assert case["outputs"]["execution.json"] == execution_bytes
    assert case["outputs"]["data-file-schema.xml"] == raw
    pinned = {pin["name"]: pin for pin in report["raw_pins"]["outputs"]}
    assert pinned["data-file-schema.xml"] == reader.file_pin("data-file-schema.xml", raw)
    assert pinned["execution.json"] == reader.file_pin("execution.json", execution_bytes)
    assert case["execution"]["checks"]["xml_parseable"] is True


@pytest.mark.parametrize("prefix", [b"\xef\xbb\xbf", b'<?xml version="1.0" encoding="UTF-8"?>'])
def test_supported_utf8_preserves_conditional_custody_and_original_pins(synthetic, prefix):
    case = fixture_case(synthetic[0])
    raw = prefix + case["outputs"]["data-file-schema.xml"]
    replace_xml(case, raw)
    report = run(case)
    assert report["rejection"] is None
    assert report["custody_verified"] is True
    assert report["custody_scope"] == "conditional_byte_graph_given_independent_coordinator_pins"
    assert report["coordinator_capture_authenticated"] is None
    assert report["execution_consistency_ready_for_review"] is False
    assert report["semantic_reading_status"] == "initialization_only"
    assert report["semantic_reading"]["output_pins"]["xml"]["sha256"] == reader.sha(raw)


def test_completed_process_cannot_have_missing_exit_even_with_coherent_failure_graph(synthetic):
    case = fixture_case(synthetic[0])
    case["execution"]["process"]["exit_code"] = None
    case["execution"]["solver_outcome"] = "solver_failure"
    seal(case)
    report = rejected(case)
    assert report["rejection"]["message"] == "completed process requires a concrete exit code"
    assert report["process_outcome_consistent"] is False


EXECUTION_MUTATIONS = [
    ("schema_version", "sclib-native-qe-execution/1"),
    ("adapter_version", "native-qe/1"),
    ("fencing_token", True),
    ("fencing_token", 2),
    ("job_id", "wrong"),
    ("attempt_id", "wrong"),
    ("runtime_id", "wrong"),
    ("runtime_config_sha256", "0" * 64),
    ("input_manifest_sha256", "0" * 64),
    ("method_profile", "PBE"),
    ("source_id", IDS[-1]),
    ("preparation_phase", "scf"),
    ("adapter_release_manifest_sha256", "0" * 64),
    ("scientific_publication_authority", 0),
    ("shell_execution", True),
    ("checkpoint_resume", True),
    ("solver_outcome", "solver_failure"),
    ("elapsed_seconds", 0),
    ("elapsed_seconds", True),
    ("unexpected_authority", True),
]


@pytest.mark.parametrize(("field", "value"), EXECUTION_MUTATIONS)
def test_coherently_rehashed_execution_cannot_bless_its_own_claims(synthetic, field, value):
    case = fixture_case(synthetic[0])
    case["execution"][field] = value
    # For an invalid Completion scalar retain valid transport time/fence and alter only its artifact.
    if field == "elapsed_seconds" and type(value) is bool:
        case["outputs"]["execution.json"] = canonical(case["execution"])
        case["export"]["files"] = [reader.file_pin(n, b) for n, b in sorted(case["outputs"].items())]
        case["export"]["attempt"]["receipt"]["manifest_sha256"] = digest(case["export"]["files"])
        recapture(case)
    else:
        seal(case)
    rejected(case)


@pytest.mark.parametrize(
    "attack", ["runtime", "submitted", "release", "export", "expected_shape", "expected_bool_fence", "expected_path"]
)
def test_separate_coordinator_references_are_required(synthetic, attack):
    case = fixture_case(synthetic[0])
    if attack in {"runtime", "submitted", "release"}:
        name = {
            "runtime": "runtime_config_bytes",
            "submitted": "submitted_spec_bytes",
            "release": "adapter_release_manifest_bytes",
        }[attack]
        case[name] += b" "
    elif attack == "export":
        case["export_bytes"] += b" "
    elif attack == "expected_shape":
        rejected(case, expected={"verified": True})
        return
    elif attack == "expected_bool_fence":
        case["expected"] = replace(case["expected"], fencing_token=True)
    else:
        case["expected"] = replace(case["expected"], attempt_root="/synthetic/../" + case["expected"].attempt_id)
    rejected(case)


@pytest.mark.parametrize(
    "attack",
    [
        "job",
        "node",
        "fence",
        "receipt_authority",
        "receipt_reason",
        "completion",
        "manifest_order",
        "duplicate_pin",
        "missing_stderr",
        "raw_pin",
        "receipt_manifest",
        "input_pin",
    ],
)
def test_transport_edges_reject_even_after_coordinator_recapture(synthetic, attack):
    case = fixture_case(synthetic[0])
    export = case["export"]
    if attack == "job":
        export["job"]["spec"]["state_ref"] = IDS[-1]
        export["job"]["spec_sha"] = digest(export["job"]["spec"])
    elif attack == "node":
        export["attempt"]["node_id"] = export["attempt"]["receipt"]["node_id"] = "other-node"
    elif attack == "fence":
        export["attempt"]["fence"] = 2
    elif attack == "receipt_authority":
        export["attempt"]["receipt"]["scientific_publication_authority"] = 0
    elif attack == "receipt_reason":
        export["attempt"]["receipt"]["reason"] = "stale_attempt"
    elif attack == "completion":
        export["attempt"]["completion_sha"] = export["attempt"]["receipt"]["completion_sha256"] = "0" * 64
    elif attack == "manifest_order":
        export["files"].reverse()
        export["attempt"]["receipt"]["manifest_sha256"] = digest(export["files"])
    elif attack == "duplicate_pin":
        export["files"][-1] = export["files"][0]
    elif attack == "missing_stderr":
        del case["outputs"]["stderr.txt"]
    elif attack == "raw_pin":
        case["outputs"]["stdout.txt"] += b"x"
    elif attack == "receipt_manifest":
        export["attempt"]["receipt"]["manifest_sha256"] = "0" * 64
    else:
        case["inputs"]["input.in"] += b" "
    recapture(case)
    rejected(case)


@pytest.mark.parametrize(
    "attack",
    [
        "argv",
        "path",
        "threads",
        "absent",
        "exit_bool",
        "exit_claim",
        "elapsed",
        "memory_bool",
        "capture_bool",
        "capture_absent",
        "capture_size",
        "capture_truncated",
        "artifact_order",
        "artifact_self",
        "input_order",
        "binding_whitespace",
        "runtime_binary",
        "checks",
    ],
)
def test_nested_execution_edges_reject_after_full_digest_rebinding(synthetic, attack):
    case = fixture_case(synthetic[0])
    ex = case["execution"]
    if attack == "argv":
        ex["process"]["argv"].append("--extra")
    elif attack == "path":
        ex["process"]["argv"][-1] = "/wrong/" + case["expected"].attempt_id + "/work/input.in"
    elif attack == "threads":
        ex["process"]["thread_environment"]["OMP_NUM_THREADS"] = "2"
    elif attack == "absent":
        ex["process"].update(argv=[], thread_environment={})
    elif attack == "exit_bool":
        ex["process"]["exit_code"] = False
    elif attack == "exit_claim":
        ex["process"]["exit_code"] = 255
    elif attack == "elapsed":
        ex["process"]["elapsed_seconds"] = -1
    elif attack == "memory_bool":
        ex["process"]["peak_memory_bytes"] = True
    elif attack == "capture_bool":
        ex["capture"]["stderr.txt"]["present"] = 1
    elif attack == "capture_absent":
        ex["capture"]["stdout.txt"].update(present=False, original_bytes=None)
    elif attack == "capture_size":
        ex["capture"]["stdout.txt"]["original_bytes"] += 1
    elif attack == "capture_truncated":
        ex["capture"]["stdout.txt"]["truncated"] = True
    elif attack == "artifact_order":
        ex["artifacts"].reverse()
    elif attack == "artifact_self":
        ex["artifacts"].append(reader.file_pin("execution.json", b""))
    elif attack == "input_order":
        ex["input_manifest"].reverse()
    elif attack == "binding_whitespace":
        ex["input_binding"] = reader.file_pin(reader.BINDING_NAME, case["inputs"][reader.BINDING_NAME] + b" ")
    elif attack == "runtime_binary":
        ex["runtime_pins"]["pw"]["sha256"] = "3" * 64
        ex["runtime_config_sha256"] = digest(ex["runtime_pins"])
    else:
        ex["checks"]["xml_parseable"] = False
    seal(case)
    rejected(case)


@pytest.mark.parametrize(
    "attack", ["duplicate", "nan", "mutable_output", "extra_output", "oversized", "binding_object"]
)
def test_bounded_strict_bytes_not_caller_objects(synthetic, attack):
    case = fixture_case(synthetic[0])
    if attack in {"duplicate", "nan"}:
        raw = case["export_bytes"]
        case["export_bytes"] = (
            b'{"job":null,' + raw[1:]
            if attack == "duplicate"
            else raw.replace(b'"created_at":99.25', b'"created_at":NaN')
        )
        case["expected"] = replace(case["expected"], export_sha256=reader.sha(case["export_bytes"]))
    elif attack == "mutable_output":
        case["outputs"]["stderr.txt"] = bytearray()
    elif attack == "extra_output":
        case["outputs"]["extra"] = b""
    elif attack == "oversized":
        case["outputs"]["execution.json"] = b"x" * (reader.OUTPUT_CAPS["execution.json"] + 1)
    else:
        case["inputs"][reader.BINDING_NAME] = json.loads(case["inputs"][reader.BINDING_NAME])
    rejected(case)


def test_caller_map_mutation_cannot_change_validated_snapshot(synthetic, monkeypatch):
    case = fixture_case(synthetic[0])
    original = reader.validate_pbesol_inputs

    def mutate_after_check(*args, **kwargs):
        checked = original(*args, **kwargs)
        case["inputs"]["input.in"] = b"caller replaced"
        case["outputs"]["stdout.txt"] = b"caller replaced"
        return checked

    monkeypatch.setattr(reader, "validate_pbesol_inputs", mutate_after_check)
    result = run(case)
    assert result["rejection"] is None and result["custody_verified"] is True
    assert result["semantic_reading_status"] == "initialization_only"
    assert case["inputs"]["input.in"] == b"caller replaced"


def test_no_process_network_executable_or_queue_admission(synthetic, monkeypatch):
    case = fixture_case(synthetic[0])

    def forbidden(*_args, **_kwargs):
        raise AssertionError("unexpected execution or network/admission")

    for module, name in [
        (subprocess, "run"),
        (subprocess, "Popen"),
        (socket, "socket"),
        (NativeRuntime, "validate_job"),
    ]:
        monkeypatch.setattr(module, name, forbidden)
    assert run(case)["custody_verified"] is True


@pytest.mark.parametrize("mode", ["physical_xml", "convergence", "stderr_stop", "opaque_release"])
def test_transport_consistency_does_not_grant_semantic_or_release_acceptance(synthetic, mode):
    case = fixture_case(synthetic[0])
    if mode in {"physical_xml", "convergence"}:
        root = ET.fromstring(case["outputs"]["data-file-schema.xml"])
        if mode == "physical_xml":
            ET.SubElement(root.find("output"), "electric_field")
        else:
            root.find("output/convergence_info/scf_conv/convergence_achieved").text = "true"
        case["outputs"]["data-file-schema.xml"] = ET.tostring(root)
    elif mode == "stderr_stop":
        case["outputs"]["stderr.txt"] = b"MPI_ABORT\n"
    else:
        case["adapter_release_manifest_bytes"] = b"{}"
        case["expected"] = replace(case["expected"], adapter_release_sha256=reader.sha(b"{}"))
        case["execution"]["adapter_release_manifest_sha256"] = reader.sha(b"{}")
    for name in reader.RAW_NAMES:
        case["execution"]["capture"][name]["original_bytes"] = len(case["outputs"][name])
    case["execution"]["artifacts"] = [reader.file_pin(n, case["outputs"][n]) for n in sorted(reader.RAW_NAMES)]
    seal(case)
    report = run(case)
    assert report["custody_verified"] is True and report["rejection"] is None
    assert report["semantic_reading_status"] == ("initialization_only" if mode == "opaque_release" else "rejected")
    assert report["release_manifest_content_verified"] is report["installed_release_verified"] is False
    assert report["execution_consistency_ready_for_review"] is False


def test_frozen_reference_caller_mutation_cannot_rebind_the_returned_attempt(synthetic, monkeypatch):
    case = fixture_case(synthetic[0])
    original = reader.validate_pbesol_inputs

    def mutate_reference(*args, **kwargs):
        checked = original(*args, **kwargs)
        object.__setattr__(case["expected"], "node_id", "hostile-rebind")
        return checked

    monkeypatch.setattr(reader, "validate_pbesol_inputs", mutate_reference)
    report = run(case)
    assert report["custody_verified"] is True and report["rejection"] is None
    assert case["expected"].node_id == "hostile-rebind"


def test_attempt_count_cannot_exceed_single_attempt_job(synthetic):
    case = fixture_case(synthetic[0])
    case["export"]["job"]["attempt_count"] = 2
    recapture(case)
    rejected(case)


def test_valid_truncated_capture_is_retained_as_interrupted_evidence(synthetic):
    case = fixture_case(synthetic[0])
    raw_spec = case["spec"].model_dump(mode="json")
    for rule in raw_spec["output_rules"]:
        if rule["name"] == "stdout.txt":
            rule["max_bytes"] = 5
    case["spec"] = JobSpec.model_validate(raw_spec)
    case["submitted_spec_bytes"] = canonical(raw_spec)
    case["expected"] = replace(case["expected"], submitted_spec_sha256=reader.sha(case["submitted_spec_bytes"]))
    case["export"]["job"].update(spec=raw_spec, spec_sha=digest(raw_spec))
    case["outputs"]["stdout.txt"] = case["outputs"]["stdout.txt"][:5]
    case["execution"]["capture"]["stdout.txt"]["truncated"] = True
    case["execution"]["solver_outcome"] = "interrupted"
    case["execution"]["checks"].update(pwscf_7_5_seen=False, job_done_seen=False)
    case["execution"]["artifacts"] = [reader.file_pin(n, case["outputs"][n]) for n in sorted(reader.RAW_NAMES)]
    seal(case)
    report = run(case)
    assert report["rejection"] is None and report["custody_verified"] is True
    assert report["capture_complete"] is False
    assert report["transport_solver_outcome"] == "interrupted"
    assert report["semantic_reading_status"] == "rejected"
    assert report["execution_consistency_ready_for_review"] is False
