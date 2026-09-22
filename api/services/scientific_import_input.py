"""Immutable in-process inputs/results for the pending scientific import worker.

The MAC only prevents a caller from replacing an in-process parser result with
an arbitrary dictionary; it never authenticates upstream execution or science.
This module opens no database, network connection or imported program path.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from services.qe_force_constants_import import parse_force_constants
from services.qe_matdyn_import import MatdynImportError, parse_matdyn
from services.research_release_manifest import canonical, digest
from services.scientific_program_import import validate_package

VERSION = "scientific-pending-import/1.0.0"
CONTEXT_VERSION = "scientific-import-context/1.0.0"
MAX_FORCE_BYTES = 8 * 1024 * 1024
MAX_SOURCE_BYTES = 16 * 1024 * 1024 + 131072
AUTHORITY = {key: False for key in ("scientific_accepted", "ml_training_approved", "public_release",
                                   "execution_attested", "source_time_verified", "redistribution_authorized")}
_KEY = secrets.token_bytes(32)
_SHA = re.compile(r"^[0-9a-f]{64}$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")


class ScientificImportError(ValueError):
    """A static private-operation error code, never source contents."""


def require(condition, code):
    if not condition:
        raise ScientificImportError(code)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def _seal(kind, value):
    return hmac.new(_KEY, kind.encode() + b"\0" + canonical(value), hashlib.sha256).digest()


def compiler_inventory():
    # The API image/wheel has services/ and models/, not a repository-level
    # api/ or scripts/. Preserve stable inventory labels, resolve actual files.
    root = Path(__file__).resolve().parents[1]
    paths = ("api/services/scientific_import_input.py", "api/services/scientific_pending_import.py",
             "api/models/scientific_import_v1.py", "api/services/qe_force_constants_import.py",
             "api/services/qe_matdyn_import.py", "api/services/scientific_program_import.py",
             "api/services/ml_coordinate_features.py", "api/services/research_release_manifest.py",
             "api/services/research_release_spec.py", "api/services/ml_composition.py",
             "api/services/_composition/formula_enrichment.py", "api/services/_composition/formula_validator.py")
    return {path: sha((root / path.removeprefix("api/")).read_bytes()) for path in paths}


def runtime_preflight(manifest, *, artifact_bytes, expected_manifest_sha256):
    """Installed-API counterpart of the frozen repository-only batch30 CLI.

    Reuses its closed package validator and native parser. This separately
    versioned envelope pins API sources actually installed, not nonexistent
    repository scripts. Parity tests keep parsing/pairing/quarantine identical.
    """
    roles = validate_package(manifest, artifact_bytes, expected_manifest_sha256)
    try:
        result = parse_matdyn(input_bytes=artifact_bytes[roles["input"]["sha256"]],
                              frequency_bytes=artifact_bytes[roles["frequency"]["sha256"]])
    except MatdynImportError as exc:
        code = str(exc)
        reason = code if re.fullmatch(r"[a-z][a-z0-9_]{0,159}", code) else "adapter_parse_rejected"
        result = {"version": "qe-matdyn-import/1.0.0", "adapter_id": "qe-matdyn-flfrq",
            "status": "quarantined", "reason_codes": [reason], "property_candidates": [],
            "spectrum": None, "input_observations": {},
            "files": {"input_sha256": roles["input"]["sha256"], "frequency_sha256": roles["frequency"]["sha256"]},
            "authority": {"scientific_accepted": False, "ml_training_approved": False, "execution_attested": False}}
    reasons = list(result["reason_codes"])
    declared = result["input_observations"].get("declared_flfrq")
    if declared is not None and declared != roles["frequency"]["logical_name"]:
        reasons.append("input_output_filename_mismatch")
    if manifest["context"]["geometry_scope"] == "other":
        reasons.append("nonbulk_context_declared")
    reasons = sorted(set(reasons))
    status = "quarantined" if reasons or result["status"] == "quarantined" else "parsed"
    if status == "quarantined":
        for candidate in result["property_candidates"]:
            candidate["disposition"] = "quarantined"
    report = {"version": "scientific-import-native-preflight/1.0.0", "status": status, "reason_codes": reasons,
        "package_sha256": expected_manifest_sha256, "adapter_id": "qe-matdyn-flfrq",
        "source_code_sha256": compiler_inventory(), "inventory": manifest["files"],
        "context_declarations": manifest["context"], "parse_result": result,
        "coverage": {"packages_seen": 1, "packages_parsed": int(status == "parsed"),
            "packages_quarantined": int(status == "quarantined"), "property_candidates": len(result["property_candidates"]),
            "scientifically_accepted_properties": 0, "ml_admitted_properties": 0},
        "unresolved_gates": ["material_state_structure_binding", "actual_force_constant_ancestry",
            "program_run_identity_and_convergence", "scientific_review", "source_time_review", "source_rights_review"],
        "costs": {"calculation_cpu_seconds": None, "calculation_wall_seconds": None,
            "calculation_monetary_cost": None, "import_elapsed_seconds": None,
            "note": "Not measured by this deterministic offline preflight; missing is not zero."},
        "authority": {**AUTHORITY, "database_changed": False, "material_binding_verified": False}}
    require(len(canonical(report)) <= MAX_FORCE_BYTES, "preflight_report_byte_limit")
    return report


@dataclass(frozen=True)
class InputPackage:
    request_bytes: bytes
    sources: tuple[tuple[str, str, str, bytes], ...]
    signature: bytes

    @property
    def request(self):
        return json.loads(self.request_bytes)

    @property
    def package_key(self):
        return sha(self.request_bytes)


@dataclass(frozen=True)
class PreparedImport:
    package: InputPackage
    report_bytes: bytes
    coordinate_bytes: bytes | None
    import_wall_ms: int
    import_cpu_ms: int
    signature: bytes

    @property
    def report(self):
        return json.loads(self.report_bytes)


def _input_body(package):
    return {"request_sha256": sha(package.request_bytes), "sources": [
        [role, name, checksum, sha(data)] for role, name, checksum, data in package.sources]}


def verify_input(package):
    require(type(package) is InputPackage, "server_prepared_input_required")
    require(hmac.compare_digest(package.signature, _seal("input", _input_body(package))), "input_capture_changed")
    return package


def _prepared_body(prepared):
    return {"request_sha256": prepared.package.package_key, "report_sha256": sha(prepared.report_bytes),
            "coordinate_sha256": sha(prepared.coordinate_bytes) if prepared.coordinate_bytes is not None else None,
            "import_wall_ms": prepared.import_wall_ms, "import_cpu_ms": prepared.import_cpu_ms}


def verify_prepared(prepared):
    require(type(prepared) is PreparedImport, "server_parser_result_required")
    verify_input(prepared.package)
    require(hmac.compare_digest(prepared.signature, _seal("prepared", _prepared_body(prepared))),
            "parser_result_changed")
    return prepared


def prepare_input(*, manifest, artifact_bytes, expected_manifest_sha256, context, force_constants_bytes=None):
    """Capture all caller containers into immutable bytes before any await."""
    manifest = json.loads(canonical(manifest))
    context = json.loads(canonical(context))
    artifact_bytes = dict(artifact_bytes) if type(artifact_bytes) is dict else artifact_bytes
    validate_package(manifest, artifact_bytes, expected_manifest_sha256)
    require(type(context) is dict and set(context) == {
        "version", "material_id", "expected_material_row_sha256", "force_constants"}, "import_context_fields")
    require(context["version"] == CONTEXT_VERSION, "import_context_version")
    require(type(context["material_id"]) is str and 0 < len(context["material_id"]) <= 100
            and context["material_id"].strip() == context["material_id"]
            and all(ord(char) >= 32 and ord(char) != 127 for char in context["material_id"]), "import_material_id")
    require(type(context["expected_material_row_sha256"]) is str
            and _SHA.fullmatch(context["expected_material_row_sha256"]), "independent_material_row_pin_required")
    fc = context["force_constants"]
    if fc is None:
        require(force_constants_bytes is None, "undeclared_force_constants_bytes")
    else:
        require(type(fc) is dict and set(fc) == {"logical_name", "sha256", "size_bytes"}, "force_constants_fields")
        require(type(fc["logical_name"]) is str and _NAME.fullmatch(fc["logical_name"])
                and ".." not in fc["logical_name"], "force_constants_logical_name")
        require(type(fc["sha256"]) is str and _SHA.fullmatch(fc["sha256"]), "force_constants_pin_required")
        require(type(fc["size_bytes"]) is int and 0 < fc["size_bytes"] <= MAX_FORCE_BYTES,
                "force_constants_byte_limit")
        require(type(force_constants_bytes) is bytes and len(force_constants_bytes) == fc["size_bytes"]
                and sha(force_constants_bytes) == fc["sha256"], "force_constants_bytes_mismatch")
    sources = [(entry["role"], "package/" + entry["logical_name"], entry["sha256"], artifact_bytes[entry["sha256"]])
               for entry in manifest["files"]]
    for role, name, data in (("manifest", "import/package.json", canonical(manifest)),
                             ("context", "import/context.json", canonical(context))):
        sources.append((role, name, sha(data), data))
    if fc is not None:
        sources.append(("force_constants", "force_constants/" + fc["logical_name"], fc["sha256"], force_constants_bytes))
    require(sum(len(data) for data in {checksum: data for _, _, checksum, data in sources}.values()) <= MAX_SOURCE_BYTES,
            "import_source_byte_limit")
    request = {"version": VERSION, "manifest_sha256": expected_manifest_sha256,
        "context_sha256": digest(context), "compiler_sha256": digest(compiler_inventory()),
        "manifest": manifest, "context": context,
        "files": [{"role": role, "logical_name": name, "sha256": checksum, "size_bytes": len(data)}
                  for role, name, checksum, data in sources]}
    result = InputPackage(canonical(request), tuple(sources), b"")
    return InputPackage(result.request_bytes, result.sources, _seal("input", _input_body(result)))


def compile_input(package):
    """Bounded worker work; actual native-program execution remains unattested."""
    verify_input(package)
    start, cpu = time.monotonic_ns(), time.thread_time_ns()
    request = package.request
    require(request["compiler_sha256"] == digest(compiler_inventory()), "import_compiler_changed")
    manifest, context = request["manifest"], request["context"]
    originals = {checksum: data for role, _, checksum, data in package.sources
                 if role not in {"manifest", "context", "force_constants"}}
    preflight = runtime_preflight(manifest, artifact_bytes=originals,
                                 expected_manifest_sha256=request["manifest_sha256"])
    reasons = list(preflight["reason_codes"])
    force, coordinates = None, None
    declared_formula = manifest["context"]["material_formula"]
    declared_material = manifest["context"]["material_id"]
    if declared_material is not None and declared_material != context["material_id"]:
        reasons.append("declared_material_binding_mismatch")
    if not declared_formula:
        reasons.append("source_formula_unreported")
    if context["force_constants"] is None:
        reasons.append("force_constants_unavailable")
    elif declared_formula:
        fc = context["force_constants"]
        fc_bytes = next(data for role, _, _, data in package.sources if role == "force_constants")
        try:
            force = parse_force_constants(payload=fc_bytes, expected_sha256=fc["sha256"], source_formula=declared_formula)
        except ValueError as exc:
            code = str(exc)
            reasons.append(code if re.fullmatch(r"[a-z][a-z0-9_]{0,159}", code) else "force_constants_rejected")
        if force is not None:
            reasons.extend(force["reason_codes"])
            if force["coordinates"] is not None:
                coordinates = canonical(force["coordinates"])
            observations = preflight["parse_result"]["input_observations"]
            if observations.get("declared_flfrc") != fc["logical_name"]:
                reasons.append("force_constants_filename_mismatch")
            spectrum = preflight["parse_result"].get("spectrum")
            if spectrum is not None and spectrum["mode_count"] != 3 * force["header"]["nat"]:
                reasons.append("force_constants_mode_count_mismatch")
    if coordinates is None:
        reasons.append("validated_coordinates_unavailable")
    if manifest["context"]["geometry_scope"] != "bulk_3d":
        reasons.append("bulk_context_not_declared")
    reasons = sorted(set(reasons))
    report = {"version": "scientific-pending-import-report/1.0.0", "request_sha256": package.package_key,
        "status": "quarantined" if reasons else "pending_context_and_review", "reason_codes": reasons,
        "preflight": preflight, "force_constants": force,
        "coordinate_sha256": sha(coordinates) if coordinates is not None else None,
        "coverage": {"source_packages_seen": 1, "parsed_candidates": preflight["coverage"]["property_candidates"],
                     "scientifically_accepted_properties": 0, "ml_admitted_properties": 0},
        "cost_scope": "parser_worker_only", "actual_calculation_costs": None,
        "limitations": ["input_output_name_and_geometry_matching_not_execution_attestation",
            "no_force_constant_eigenvalue_recomputation", "no_pressure_temperature_field_or_phase_inference",
            "no_phonon_treatment_or_upstream_convergence_attestation"], "authority": dict(AUTHORITY)}
    report_bytes = canonical(report)
    require(len(report_bytes) <= MAX_FORCE_BYTES, "import_report_byte_limit")
    require(request["compiler_sha256"] == digest(compiler_inventory()), "import_compiler_changed")
    result = PreparedImport(package, report_bytes, coordinates, (time.monotonic_ns() - start) // 1000000,
                            (time.thread_time_ns() - cpu) // 1000000, b"")
    return PreparedImport(result.package, result.report_bytes, result.coordinate_bytes,
                          result.import_wall_ms, result.import_cpu_ms, _seal("prepared", _prepared_body(result)))
