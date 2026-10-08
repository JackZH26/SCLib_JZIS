"""Synthetic JobSpecs only: this suite never creates or submits a real job."""

import copy
import json
import os
import socket
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/tests"))

import test_sclib_pbesol_profile as binding_tests
from sclib_compute import pbesol_native_contract as adapter
from sclib_compute.contracts import FilePin, JobSpec, Resources, canonical, digest
from sclib_compute.native_contract import NativeInput, validate_inputs
from sclib_compute.pbesol_profile import build_input_binding
from test_sclib_pbesol_profile import CONTEXTS, context_files, file_pin

RUNTIME = "fixture-pbesol-runtime"
synthetic = binding_tests.synthetic


def fixture_job(sid, phase, source_files):
    """An in-memory test envelope, never a live node/runtime or queue claim."""
    files = dict(source_files)
    binding = build_input_binding(sid, phase, files)
    files[adapter.BINDING_NAME] = canonical(binding.model_dump(mode="json"))
    spec = JobSpec(job_id="fixture-envelope-" + sid + "-" + phase,
                   kind="qe_" + phase, runtime_id=RUNTIME, case_ref="fixture-case",
                   state_ref=sid, action_ref="fixture-action", max_attempts=1,
                   input_artifacts=[FilePin(**file_pin(n, d)) for n, d in files.items()],
                   output_rules=[{"name": n, "max_bytes": cap} for n, cap in adapter.OUTPUT_CAPS.items()],
                   resources={"cpu_cores": 2, "wall_seconds": 180 if phase == "initialize" else 900,
                              "memory_bytes": 12 * 1024**3, "output_bytes": sum(adapter.OUTPUT_CAPS.values())},
                   deadline_unix=1)  # Deliberately past: offline consistency is not live admission.
    return spec, files


def check_projection(spec, files):
    result = adapter.validate_pbesol_inputs(spec, files, expected_runtime_id=RUNTIME)
    assert result.binding_document == files[adapter.BINDING_NAME]
    assert result.binding_sha256 == file_pin(adapter.BINDING_NAME, result.binding_document)["sha256"]
    assert result.binding_byte_length == len(result.binding_document)
    assert result.job_spec_sha256 == digest(spec.model_dump(mode="json"))
    assert result.input_manifest_sha256 == spec.input_manifest_sha256
    assert result.source_id == spec.state_ref
    assert result.kind == spec.kind
    assert result.input_name == "input.in" and result.source_manifest_name == "preparation.json"
    binding = json.loads(result.binding_document)
    assert all(binding[k] is False for k in ("execution_enabled", "queue_authorization", "scientific_acceptance"))
    assert all(binding[k] is None for k in ("job_spec", "runtime_observation", "attempt_receipt"))
    return result


@pytest.mark.parametrize(("sid", "phase"), CONTEXTS)
def test_eight_synthetic_envelopes(synthetic, sid, phase):
    source_sets, _, _ = synthetic
    spec, files = fixture_job(sid, phase, source_sets[sid, phase])
    result = check_projection(spec, files)
    assert len(files) == (8 if sid in {"agm001228974", "agm002322068"} else 7)
    assert result.preparation_phase == phase


@pytest.mark.parametrize(("sid", "phase"), CONTEXTS)
def test_eight_actual_frozen_inputs_in_synthetic_offline_envelope(sid, phase):
    root = os.environ.get("SCLIB_PBESOL_FORMAL_BUNDLE")
    if root is None:
        pytest.skip("Private actual inputs unavailable; explicitly set SCLIB_PBESOL_FORMAL_BUNDLE")
    files = context_files(Path(root), sid, phase)
    spec, files = fixture_job(sid, phase, files)
    check_projection(spec, files)  # JobSpec remains synthetic even with actual frozen input bytes.


@pytest.mark.parametrize("runtime", [None, True, 12, b"runtime", "", "/runtime", "../runtime", "x" * 81, "bad runtime"])
def test_independent_runtime_identifier_is_strict(synthetic, runtime):
    spec, files = fixture_job(*CONTEXTS[0], synthetic[0][CONTEXTS[0]])
    with pytest.raises(ValueError):
        adapter.validate_pbesol_inputs(spec, files, expected_runtime_id=runtime)


@pytest.mark.parametrize(("field", "value", "message"), [
    ("kind", "dummy", "job kind"), ("kind", "qe_relax", "job kind"), ("kind", "qe_ph", "job kind"),
    ("runtime_id", "other-runtime", "runtime expectation"), ("max_attempts", 2, "one attempt"),
    ("state_ref", "agm002322068", "source state"), ("kind", "qe_scf", "preparation stage"),
])
def test_supported_contract_but_wrong_pbesol_envelope(synthetic, field, value, message):
    spec, files = fixture_job(*CONTEXTS[0], synthetic[0][CONTEXTS[0]])
    raw = spec.model_dump(mode="python")
    raw[field] = value
    with pytest.raises(ValueError, match=message):
        adapter.validate_pbesol_inputs(JobSpec.model_validate(raw), files, expected_runtime_id=RUNTIME)


@pytest.mark.parametrize("change", ["missing", "extra", "path", "mutable", "overlong_binding", "overlong_upf", "corrupt",
                                  "missing_pin", "wrong_pin", "wrong_size", "wrong_binding"])
def test_artifact_envelope_rejections(synthetic, change):
    spec, files = fixture_job(*CONTEXTS[0], synthetic[0][CONTEXTS[0]])
    if change == "missing":
        del files["Ti.upf"]
    elif change == "extra":
        files["native.json"] = b"{}"
    elif change == "path":
        files["../input.in"] = files.pop("input.in")
    elif change == "mutable":
        files["input.in"] = bytearray(files["input.in"])
    elif change == "overlong_binding":
        files[adapter.BINDING_NAME] = b" " * (adapter.MAX_METADATA_BYTES + 1)
    elif change == "overlong_upf":
        files["Ti.upf"] = b" " * (adapter.MAX_UPF_BYTES + 1)
    elif change == "corrupt":
        files["input.in"] += b" "
    elif change == "missing_pin":
        spec.input_artifacts.pop()
    elif change == "wrong_pin":
        p = spec.input_artifacts[0]
        spec.input_artifacts[0] = p.model_copy(update={"sha256": "f" * 64})
    elif change == "wrong_size":
        p = spec.input_artifacts[0]
        spec.input_artifacts[0] = p.model_copy(update={"bytes": p.bytes + 1})
    else:
        b = json.loads(files[adapter.BINDING_NAME])
        b["execution_enabled"] = True
        files[adapter.BINDING_NAME] = canonical(b)
        spec = spec.model_copy(update={"input_artifacts": [FilePin(**file_pin(n, d)) for n, d in files.items()]})
    with pytest.raises(ValueError):
        adapter.validate_pbesol_inputs(spec, files, expected_runtime_id=RUNTIME)


@pytest.mark.parametrize("change", ["duplicate_input", "duplicate_output", "empty_output", "bad_resources", "bool_resources",
                                  "bad_pin", "float_pin", "negative_deadline", "coerced_false", "true_authority"])
def test_revalidates_construct_copy_and_nested_mutation(synthetic, change):
    spec, files = fixture_job(*CONTEXTS[0], synthetic[0][CONTEXTS[0]])
    if change == "duplicate_input":
        spec.input_artifacts.append(spec.input_artifacts[0])
    elif change == "duplicate_output":
        spec.output_rules.append(spec.output_rules[0])
    elif change == "empty_output":
        spec.output_rules.clear()
    elif change in {"bad_resources", "bool_resources"}:
        raw = spec.resources.model_dump()
        raw["cpu_cores"] = 65 if change == "bad_resources" else True
        spec = spec.model_copy(update={"resources": Resources.model_construct(**raw)})
    elif change in {"bad_pin", "float_pin"}:
        raw = spec.input_artifacts[0].model_dump()
        raw["bytes"] = -1 if change == "bad_pin" else 1.0
        spec.input_artifacts[0] = FilePin.model_construct(**raw)
    elif change == "negative_deadline":
        spec = JobSpec.model_construct(**{**{name: getattr(spec, name) for name in JobSpec.model_fields}, "deadline_unix": -1})
    else:
        spec = spec.model_copy(update={"scientific_publication_authority": 0 if change == "coerced_false" else True})
    with pytest.raises(ValueError):
        adapter.validate_pbesol_inputs(spec, files, expected_runtime_id=RUNTIME)


@pytest.mark.parametrize("change", ["missing", "extra", "over_cap", "under_total", "over_total"])
def test_exact_bounded_output_contract(synthetic, change):
    spec, files = fixture_job(*CONTEXTS[0], synthetic[0][CONTEXTS[0]])
    raw = spec.model_dump(mode="python")
    if change == "missing":
        raw["output_rules"].pop()
    elif change == "extra":
        raw["output_rules"][0]["name"] = "a2Fsave"
    elif change == "over_cap":
        raw["output_rules"][1]["max_bytes"] += 1
        raw["resources"]["output_bytes"] += 1
    elif change == "under_total":
        raw["resources"]["output_bytes"] = 1
    else:
        raw["resources"]["output_bytes"] = adapter.MAX_OUTPUT_BYTES + 1
    # All raw reconstruction and profile constraints must fail before use.
    with pytest.raises(ValueError):
        unsafe = JobSpec.model_validate(raw)
        adapter.validate_pbesol_inputs(unsafe, files, expected_runtime_id=RUNTIME)


def test_projection_and_hashes_are_detached_immutable_and_preserve_declared_order(synthetic):
    spec, files = fixture_job(*CONTEXTS[0], synthetic[0][CONTEXTS[0]])
    result = check_projection(spec, files)
    for name in ("prefix", "binding_document", "pseudo_names"):
        with pytest.raises(FrozenInstanceError):
            setattr(result, name, "changed")
    assert type(result.pseudo_names) is tuple and type(result.binding_document) is bytes
    assert not hasattr(result, "__dict__")
    old_digest = result.input_manifest_sha256
    old_binding = result.binding_document
    spec.input_artifacts.reverse()
    reordered = check_projection(spec, files)
    assert reordered.input_manifest_sha256 != old_digest
    assert result.input_manifest_sha256 == old_digest
    files[adapter.BINDING_NAME] = b"{}"
    assert result.binding_document == old_binding
    detached = json.loads(result.binding_document)
    detached["pseudopotentials"].reverse()
    assert json.loads(result.binding_document)["pseudopotentials"] != detached["pseudopotentials"]


@pytest.mark.parametrize("phase", ["initialize", "scf"])
def test_full_legacy_v1_wrapper_still_rejects_exact_pbesol_deck(synthetic, phase):
    sid = CONTEXTS[0][0]
    spec, files = fixture_job(sid, phase, synthetic[0][sid, phase])
    projected = check_projection(spec, files)
    descriptor = NativeInput(input_name=projected.input_name, source_manifest_name="source-manifest.json",
                             prefix=projected.prefix, pseudo_names=list(projected.pseudo_names))
    native_files = {n: files[n] for n in ("input.in", *projected.pseudo_names)}
    native_files["native.json"] = canonical(descriptor.model_dump(mode="json"))
    native_files["source-manifest.json"] = canonical({
        "version": "discovery-qe-input/1.0.0", "settings": {"calculation": "scf"},
        "files": {"initialization" if phase == "initialize" else "execution": {
            "filename": "input.in", "sha256": file_pin("input.in", files["input.in"])["sha256"]}},
        "pseudopotentials": [{"filename": n, "byte_length": len(files[n]), "sha256": file_pin(n, files[n])["sha256"]}
                             for n in projected.pseudo_names],
    })
    raw = spec.model_dump(mode="python")
    raw["input_artifacts"] = [file_pin(n, d) for n, d in native_files.items()]
    with pytest.raises(ValueError, match="unreviewed/duplicate QE assignment"):
        validate_inputs(JobSpec.model_validate(raw), native_files)


def test_validator_has_no_admission_process_network_or_output_write(synthetic, monkeypatch):
    spec, files = fixture_job(*CONTEXTS[0], synthetic[0][CONTEXTS[0]])
    before = copy.deepcopy(spec.model_dump())
    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected live admission or side effect")
    from sclib_compute.native_contract import NativeRuntime
    monkeypatch.setattr(NativeRuntime, "validate_job", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    for method in ("write_text", "write_bytes", "mkdir", "unlink"):
        monkeypatch.setattr(Path, method, forbidden)
    check_projection(spec, files)
    assert spec.model_dump() == before and spec.deadline_unix == 1


def test_valid_constructed_model_revalidated_and_artifacts_are_not_normalized(synthetic):
    spec, files = fixture_job(*CONTEXTS[0], synthetic[0][CONTEXTS[0]])
    constructed = JobSpec.model_construct(**{name: getattr(spec, name) for name in JobSpec.model_fields})
    assert check_projection(constructed, files) == check_projection(spec, files)
    # Whitespace in a binding document is retained as exact envelope bytes.
    files[adapter.BINDING_NAME] += b"\n"
    altered = spec.model_copy(update={"input_artifacts": [FilePin(**file_pin(n, d)) for n, d in files.items()]})
    result = check_projection(altered, files)
    assert result.binding_document.endswith(b"\n")
    assert result.input_manifest_sha256 != spec.input_manifest_sha256


def test_too_large_envelopes_stop_before_profile_parser(synthetic, monkeypatch):
    spec, files = fixture_job(*CONTEXTS[0], synthetic[0][CONTEXTS[0]])
    # Lower only the test envelope cap; valid production inputs cannot fill the
    # full4MiB cap with3x1MiB UPFs and five64KiB metadata files.
    monkeypatch.setattr(adapter, "MAX_TOTAL_BYTES", sum(map(len, files.values())) - 1)
    def forbidden(*args, **kwargs):
        raise AssertionError("Profile parser must not run for a rejected envelope")
    monkeypatch.setattr(adapter, "validate_input_binding", forbidden)
    with pytest.raises(ValueError, match="input envelope exceeded"):
        adapter.validate_pbesol_inputs(spec, files, expected_runtime_id=RUNTIME)
