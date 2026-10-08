"""Closed, offline PBEsol input bindings; no worker dispatch or execution authority.

Only installed hash-pinned trust metadata is read. Caller artifacts are bounded
in-memory bytes; no caller path, executable, network or output file is accessed.
"""

from __future__ import annotations

import json
import math
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal

import build_sclib_pbesol_preparation as prep
from pydantic import Field, model_validator

from .contracts import Closed, FilePin, Identifier, Sha256, canonical

PINS_PATH = prep.PROFILE.with_name("pbesol-prepared-pins-v1.json")
PINS_SHA256 = "a4314696a2d4dc76714232d0a72ce84f37c85ef14eb2a5f0614b71592adafe13"
PREPARER_SHA256 = "0076c6714becc67315cad3075eee408aca71443f54fd4c8f61565b5d94986ffd"
BUNDLE_SHA256 = "93d99171d86c1d5f509b3f56582d95a52ba79657d56ce136b3f9afbfb01ea19d"
QE_COMMIT = "770a0b2d12928a67048e2f3da8d10d057e52179e"
MAX_METADATA_BYTES = 64 * 1024
MAX_UPF_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 4 * 1024 * 1024
Phase = Literal["initialize", "scf"]
SourceId = Literal["agm001228974", "agm002322068", "agm001828806", "agm001416090"]
CONTEXT_IDS = ("agm001228974", "agm002322068", "agm001828806", "agm001416090")
AUTHORITY_FALSE = ("execution_enabled", "queue_authorization", "scientific_acceptance")
CUSTODY_NULL = ("job_spec", "runtime_observation", "attempt_receipt")


class PseudopotentialBinding(Closed):
    element: Literal["Mo", "Nb", "Ta", "Ti"]
    file: FilePin


class PbesolInputBinding(Closed):
    """An input identity statement, never a native descriptor or process receipt."""

    schema_version: Literal["sclib-pbesol-input-binding/1"]
    method_profile: Literal["pbesol-source-coarse-qe75/1"]
    source_id: SourceId
    preparation_phase: Phase
    source_profile_sha256: Sha256
    preparer_sha256: Sha256
    preparation_manifest: FilePin
    source_deck: FilePin
    derived_deck: FilePin
    line_delta: FilePin
    pseudopotentials: Annotated[list[PseudopotentialBinding], Field(min_length=2, max_length=3)]
    prefix: Identifier
    geometry_sha256: Sha256
    expected_electrons: Annotated[int, Field(ge=1, le=100)]
    expected_nbnd: Annotated[int, Field(ge=1, le=100)]
    qe_version_expected: Literal["7.5"]
    qe_source_commit_expected: Literal["770a0b2d12928a67048e2f3da8d10d057e52179e"]
    execution_enabled: Literal[False]
    queue_authorization: Literal[False]
    scientific_acceptance: Literal[False]
    job_spec: None
    runtime_observation: None
    attempt_receipt: None

    @model_validator(mode="before")
    @classmethod
    def exact_authority(cls, value):
        # Literal[False] alone accepts integer zero in Pydantic.
        if isinstance(value, dict):
            for name in AUTHORITY_FALSE:
                prep.require(value.get(name) is False, "Authority must be explicit false: " + name)
            for name in CUSTODY_NULL:
                prep.require(name in value and value[name] is None, "Custody must be explicit null: " + name)
        return value


def _json_object(data: bytes) -> dict:
    prep.require(type(data) is bytes and len(data) <= MAX_METADATA_BYTES, "Expected bounded JSON bytes")

    def pairs(items):
        result = {}
        for key, value in items:
            prep.require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result

    def real(value):
        result = float(value)
        prep.require(math.isfinite(result), "Nonfinite JSON number")
        return result

    def invalid_constant(_):
        raise ValueError("Nonfinite JSON constant")

    try:
        result = json.loads(data, object_pairs_hook=pairs, parse_float=real, parse_constant=invalid_constant)
    except (RecursionError, UnicodeError) as error:
        raise ValueError("Malformed or excessively nested JSON") from error
    prep.require(type(result) is dict, "Expected JSON object")
    return result


def _same(actual, expected, message: str) -> None:
    # Canonical comparison preserves scalar types (False != 0, 52 != 52.0).
    prep.require(canonical(actual) == canonical(expected), message)


def _pin(name: str, data: bytes) -> FilePin:
    return FilePin(name=name, bytes=len(data), sha256=prep.sha256(data))


def _load_trust() -> tuple[dict, dict]:
    """Fixed installed paths only; callers cannot choose a trust file or profile."""
    profile = prep.load_profile()
    code = Path(prep.__file__).resolve()
    prep.require(prep.sha256(prep.read_regular(code.parent, code.name)) == PREPARER_SHA256,
                 "Pinned preparation implementation changed")
    raw = prep.read_regular(PINS_PATH.parent, PINS_PATH.name)
    prep.require(prep.sha256(raw) == PINS_SHA256, "Pinned prepared context table changed")
    table = _json_object(raw)
    _same({k: table.get(k) for k in ("schema_version", "source_profile_sha256", "preparer_sha256", "bundle_manifest_sha256")},
          {"schema_version": "sclib-pbesol-prepared-pins/1", "source_profile_sha256": prep.PROFILE_SHA256,
           "preparer_sha256": PREPARER_SHA256, "bundle_manifest_sha256": BUNDLE_SHA256}, "Installed trust identity mismatch")
    prep.require(set(table) == {"schema_version", "source_profile_sha256", "preparer_sha256", "bundle_manifest_sha256", "contexts"},
                 "Unexpected installed trust fields")
    contexts = table["contexts"]
    expected = {(sid, phase) for sid in CONTEXT_IDS for phase in ("initialize", "scf")}
    prep.require(type(contexts) is list and len(contexts) == 8
                 and {(x["source_id"], x["phase"]) for x in contexts} == expected, "Installed context inventory mismatch")
    return profile, table


def _bounded_files(files: dict[str, bytes]) -> None:
    prep.require(type(files) is dict and 6 <= len(files) <= 7, "Expected six or seven exact artifacts")
    total = 0
    for name, data in files.items():
        prep.require(type(name) is str and type(data) is bytes, "Artifacts require string names and immutable bytes")
        prep.require(name in {"source.in", "input.in", "delta.json", "preparation.json", "Mo.upf", "Nb.upf", "Ta.upf", "Ti.upf"},
                     "Unexpected artifact basename")
        limit = MAX_UPF_BYTES if name.endswith(".upf") else MAX_METADATA_BYTES
        prep.require(len(data) <= limit, "Artifact exceeded byte bound")
        total += len(data)
    prep.require(total <= MAX_TOTAL_BYTES, "Artifacts exceeded total byte bound")


def build_input_binding(source_id: str, phase: str, files: dict[str, bytes]) -> PbesolInputBinding:
    """Validate one fixed source/phase and return its non-executable identity."""
    prep.require(type(source_id) is str and source_id in CONTEXT_IDS, "Unsupported source ID")
    prep.require(type(phase) is str and phase in {"initialize", "scf"}, "Unsupported preparation phase")
    _bounded_files(files)
    profile, table = _load_trust()
    state = next(s for s in profile["states"] if s["id"] == source_id)
    context = next(c for c in table["contexts"] if (c["source_id"], c["phase"]) == (source_id, phase))
    species = [row.split()[0] for row in state["species_rows"]]
    selected = [pin for pin in profile["upfs"] if pin["element"] in species]
    prep.require([pin["element"] for pin in selected] == species, "UPF/species order mismatch")
    prep.require(set(files) == {"source.in", "input.in", "delta.json", "preparation.json", *(p["filename"] for p in selected)},
                 "Source-specific artifact inventory mismatch")
    prep.check_pin(files["source.in"], state["source_deck"])
    parsed = prep.parse_source(files["source.in"], state)
    headers = {p["element"]: prep.validate_upf(files[p["filename"]], p) for p in selected}
    electrons = sum(prep.scalar(headers[row.split()[0]]["z_valence"].strip()) for row in state["position_rows"])
    prep.require(electrons == Decimal(state["valence_electrons"]), "Composition-weighted UPF electron mismatch")
    expected_inventory = (52, 31) if state["formula"] == "TiNb2Mo" else (94, 56)
    _same([int(electrons), state["nbnd"]], list(expected_inventory), "Pinned electron/band inventory mismatch")
    derived, delta, settings = prep.derive(files["source.in"], parsed, state, phase)
    prep.require(files["input.in"] == derived, "Derived input differs from exact source-preserving derivation")
    # Parse before equality to give duplicate/nonfinite JSON an explicit rejection.
    _json_object(files["delta.json"])
    prep.require(files["delta.json"] == prep.encoded(delta), "Line delta differs from exact derivation")
    manifest = _json_object(files["preparation.json"])
    for field, name in (("source_deck", "source.in"), ("derived_deck", "input.in"),
                        ("line_delta", "delta.json"), ("preparation_manifest", "preparation.json")):
        _same(_pin(name, files[name]).model_dump(), context[field], "Frozen context pin mismatch: " + field)

    # The manifest is externally pinned above; these checks bind its internal
    # claims to independently re-parsed source/UPF/deck semantics as well.
    prefix = f"prepared/{source_id}/{phase}"
    expected_manifest = {
        "schema_version": prep.SCHEMA, "status": "native_profile_pending", **prep.AUTHORITY,
        "source_id": source_id, "formula": state["formula"], "role": state["role"], "preparation_phase": phase,
        "source_dataset": profile["source_dataset"], "qe75_source_audit": profile["qe75_source_audit"],
        "source_qe_version": state["source_qe_version"], "proposed_qe_version": "7.5",
        "derived_settings": settings,
        "source_namelist_literals": {g: {key: item["literal"] for key, item in fields.items()}
                                     for g, fields in parsed["namelists"].items()},
        "expected_valence_electrons": int(electrons), "expected_nbnd": state["nbnd"],
        "xc_from_exact_upfs": "PBESOL", "native_manifest": None, "job_spec": None,
    }
    for field, name, path in (("source_file", "source.in", f"source/{source_id}/scf_coarse.in"),
                              ("derived_file", "input.in", prefix + "/input.in"),
                              ("line_delta", "delta.json", prefix + "/delta.json")):
        expected_manifest[field] = {"path": path, "sha256": prep.sha256(files[name]), "bytes": len(files[name])}
    geom = prep.geometry(state)
    geom_sha = prep.sha256(prep.encoded(geom))
    prep.require(geom_sha == context["geometry_sha256"], "Frozen geometry pin mismatch")
    expected_manifest["geometry"] = {"source": geom, "derived": geom, "source_sha256": geom_sha,
                                     "derived_sha256": geom_sha, "changed": False}
    expected_manifest["pseudopotentials"] = [
        {**p, "prepared_file": {"path": prefix + "/pseudo/" + p["filename"], "bytes": p["bytes"], "sha256": p["sha256"]},
         "validated_header": headers[p["element"]]} for p in selected
    ]
    for field, expected_value in expected_manifest.items():
        prep.require(field in manifest, "Missing prepared manifest field: " + field)
        _same(manifest[field], expected_value, "Prepared manifest semantic mismatch: " + field)
    prep.require(profile["qe75_source_audit"]["runtime_source_commit"] == QE_COMMIT, "Unexpected intended QE source")
    return PbesolInputBinding(
        schema_version="sclib-pbesol-input-binding/1", method_profile="pbesol-source-coarse-qe75/1",
        source_id=source_id, preparation_phase=phase, source_profile_sha256=prep.PROFILE_SHA256, preparer_sha256=PREPARER_SHA256,
        preparation_manifest=_pin("preparation.json", files["preparation.json"]), source_deck=_pin("source.in", files["source.in"]),
        derived_deck=_pin("input.in", files["input.in"]), line_delta=_pin("delta.json", files["delta.json"]),
        pseudopotentials=[PseudopotentialBinding(element=p["element"], file=_pin(p["filename"], files[p["filename"]])) for p in selected],
        prefix=settings["prefix"], geometry_sha256=geom_sha, expected_electrons=int(electrons), expected_nbnd=state["nbnd"],
        qe_version_expected="7.5", qe_source_commit_expected=QE_COMMIT,
        execution_enabled=False, queue_authorization=False, scientific_acceptance=False,
        job_spec=None, runtime_observation=None, attempt_receipt=None,
    )


def validate_input_binding(binding_json: bytes, files: dict[str, bytes]) -> PbesolInputBinding:
    """Rebuild from installed authority; caller-supplied pins never grant trust."""
    binding = PbesolInputBinding.model_validate(_json_object(binding_json))
    expected = build_input_binding(binding.source_id, binding.preparation_phase, files)
    _same(binding.model_dump(mode="json"), expected.model_dump(mode="json"), "Input binding disagrees with installed authority")
    return expected
