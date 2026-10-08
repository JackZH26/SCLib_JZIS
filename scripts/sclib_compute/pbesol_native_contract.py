"""Inert JobSpec adapter for the closed PBEsol input profile; never dispatches.

The supplied runtime ID is an independent expectation, not proof of installation
or authorization. No native-v1 descriptor or new serialized format is produced.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from pydantic import TypeAdapter

from .contracts import Identifier, JobSpec, canonical, digest
from .pbesol_profile import (
    MAX_METADATA_BYTES,
    MAX_TOTAL_BYTES,
    MAX_UPF_BYTES,
    validate_input_binding,
)

BINDING_NAME = "pbesol-input-binding.json"
OUTPUT_CAPS = {
    "stdout.txt": 8 * 1024**2,
    "stderr.txt": 1024**2,
    "data-file-schema.xml": 8 * 1024**2,
    "execution.json": 128 * 1024,
}
MAX_OUTPUT_BYTES = 32 * 1024**2
ARTIFACT_NAMES = {
    BINDING_NAME, "source.in", "input.in", "delta.json", "preparation.json",
    "Mo.upf", "Nb.upf", "Ta.upf", "Ti.upf",
}


@dataclass(frozen=True, slots=True)
class ValidatedPbesolInput:
    """Immutable projection; the verified binding is retained as exact bytes.

    No mutable Pydantic/list/dict object or caller reference is retained. The
    binding SHA/length cover these original bytes, not a reserialized document.
    """

    binding_document: bytes
    binding_name: str
    binding_sha256: str
    binding_byte_length: int
    input_name: str
    source_manifest_name: str
    prefix: str
    pseudo_names: tuple[str, ...]
    source_id: str
    preparation_phase: str
    kind: str
    runtime_id: str
    input_manifest_sha256: str
    job_spec_sha256: str


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _snapshot_job(spec: JobSpec) -> JobSpec:
    # model_validate(existing_model) may skip validation. Serialize into detached
    # plain values first, then revalidate every nested field and model validator.
    # This also catches model_construct and mutations of frozen models' lists.
    _require(type(spec) is JobSpec, "Expected an exact JobSpec instance")
    raw = spec.model_dump(mode="python", warnings="error")
    snapshot = JobSpec.model_validate(raw)
    _require(canonical(raw) == canonical(snapshot.model_dump(mode="python")),
             "JobSpec must not depend on scalar coercion")
    return snapshot


def validate_pbesol_inputs(
    spec: JobSpec, files: dict[str, bytes], *, expected_runtime_id: str,
) -> ValidatedPbesolInput:
    """Check envelope consistency only; no lease, budget or runtime admission."""
    _require(type(expected_runtime_id) is str, "Expected an independent runtime Identifier")
    expected_runtime_id = TypeAdapter(Identifier).validate_python(expected_runtime_id, strict=True)
    spec = _snapshot_job(spec)
    _require(spec.kind in {"qe_initialize", "qe_scf"}, "Unsupported PBEsol job kind")
    _require(spec.runtime_id == expected_runtime_id, "PBEsol runtime expectation mismatch")
    _require(spec.max_attempts == 1, "PBEsol source jobs require one attempt")
    _require(type(files) is dict and len(files) in {7, 8}, "Expected seven or eight exact artifacts")
    files = dict(files)  # Caller mapping/list mutations cannot change the snapshot.
    total = 0
    for name, content in files.items():
        _require(type(name) is str and name in ARTIFACT_NAMES, "Unexpected PBEsol artifact basename")
        _require(type(content) is bytes, "PBEsol artifacts require immutable bytes")
        limit = MAX_UPF_BYTES if name.endswith(".upf") else MAX_METADATA_BYTES
        _require(len(content) <= limit, "PBEsol artifact exceeded byte bound")
        total += len(content)
    _require(total <= MAX_TOTAL_BYTES, "PBEsol input envelope exceeded byte bound")
    _require(BINDING_NAME in files, "Missing PBEsol input binding")
    _require(set(files) == {pin.name for pin in spec.input_artifacts}, "PBEsol JobSpec artifact inventory mismatch")
    for pin in spec.input_artifacts:
        content = files[pin.name]
        _require(len(content) == pin.bytes and hashlib.sha256(content).hexdigest() == pin.sha256,
                 "PBEsol JobSpec artifact pin mismatch")
    rules = {rule.name: rule.max_bytes for rule in spec.output_rules}
    _require(set(rules) == set(OUTPUT_CAPS), "PBEsol output contract mismatch")
    _require(all(0 < cap <= OUTPUT_CAPS[name] for name, cap in rules.items()), "PBEsol output cap exceeded")
    _require(sum(rules.values()) <= spec.resources.output_bytes <= MAX_OUTPUT_BYTES,
             "PBEsol output envelope exceeded byte bound")
    binding_bytes = files.pop(BINDING_NAME)
    binding = validate_input_binding(binding_bytes, files)
    expected_phase = "initialize" if spec.kind == "qe_initialize" else "scf"
    _require(binding.preparation_phase == expected_phase, "PBEsol job/preparation stage mismatch")
    _require(spec.state_ref == binding.source_id, "PBEsol job/source state mismatch")
    return ValidatedPbesolInput(
        binding_document=binding_bytes, binding_name=BINDING_NAME,
        binding_sha256=hashlib.sha256(binding_bytes).hexdigest(), binding_byte_length=len(binding_bytes),
        input_name=binding.derived_deck.name, source_manifest_name=binding.preparation_manifest.name,
        prefix=binding.prefix, pseudo_names=tuple(p.file.name for p in binding.pseudopotentials),
        source_id=binding.source_id, preparation_phase=binding.preparation_phase,
        kind=spec.kind, runtime_id=spec.runtime_id,
        input_manifest_sha256=spec.input_manifest_sha256, job_spec_sha256=digest(spec.model_dump(mode="json")),
    )
