"""Private, offline scientific-program package preflight, not a SQL importer.

An independently pinned inventory binds real input/output bytes. Context and
repository provenance remain unreviewed declarations; neither is a publication
date, authenticated execution, material/state association, or ML approval.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import urlsplit

from services.qe_matdyn_import import MatdynImportError, parse_matdyn
from services.research_release_manifest import canonical, digest

VERSION = "scientific-program-package/1.0.0"
REPORT_VERSION = "scientific-program-preflight/1.0.0"
ADAPTER = "qe-matdyn-flfrq"
MAX_FILES = 16
MAX_MANIFEST_BYTES = 65536
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_PACKAGE_BYTES = 8 * 1024 * 1024
HASH = re.compile(r"^[0-9a-f]{64}$")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")
AUTHORITY = {
    "scientific_accepted": False, "ml_training_approved": False,
    "execution_attested": False, "database_changed": False,
    "source_time_verified": False, "material_binding_verified": False,
    "redistribution_authorized": False, "public_release": False,
}


class ScientificProgramImportError(ValueError):
    """Bounded, machine-readable failure, never source content."""


def require(condition, reason):
    if not condition:
        raise ScientificProgramImportError(reason)


def _text(value, limit, nullable=False):
    return (nullable and value is None) or (
        type(value) is str and 0 < len(value) <= limit
        and all(ord(char) >= 32 and ord(char) != 127 for char in value)
    )


def validate_package(manifest, artifact_bytes, expected_manifest_sha256):
    require(type(expected_manifest_sha256) is str and HASH.fullmatch(expected_manifest_sha256),
            "independent_package_pin_required")
    payload = canonical(manifest)
    require(len(payload) <= MAX_MANIFEST_BYTES and digest(manifest) == expected_manifest_sha256,
            "package_manifest_pin_mismatch")
    require(type(manifest) is dict and set(manifest) == {
        "version", "adapter_id", "files", "context", "declarations"}, "package_fields_invalid")
    require(manifest["version"] == VERSION and manifest["adapter_id"] == ADAPTER,
            "unsupported_package_adapter")
    declarations = manifest["declarations"]
    require(type(declarations) is dict and set(declarations) == {
        "review_status", "execution_attested", "ml_training_approved"}
        and declarations["review_status"] == "unreviewed"
        and declarations["execution_attested"] is False
        and declarations["ml_training_approved"] is False, "unreviewed_package_required")
    context = manifest["context"]
    require(type(context) is dict and set(context) == {
        "material_formula", "material_id", "geometry_scope", "source_url", "source_revision", "license_spdx"},
        "package_context_fields_invalid")
    for key, limit in (("material_formula", 200), ("material_id", 100), ("source_revision", 160),
                       ("license_spdx", 120), ("source_url", 2048)):
        require(_text(context[key], limit, nullable=True), "package_context_value_invalid")
    require(type(context["geometry_scope"]) is str and context["geometry_scope"] in {
        "bulk_3d", "other", "unknown"}, "package_geometry_scope_invalid")
    if context["source_url"] is not None:
        try:
            parsed = urlsplit(context["source_url"])
            valid = parsed.scheme == "https" and bool(parsed.hostname) and parsed.username is None and parsed.password is None
        except ValueError:
            valid = False
        require(valid, "package_source_url_invalid")
    inventory = manifest["files"]
    require(type(inventory) is list and 2 <= len(inventory) <= MAX_FILES, "package_inventory_limit")
    require(type(artifact_bytes) is dict and len(artifact_bytes) <= MAX_FILES, "package_inventory_limit")
    names, hashes, counts, roles = set(), set(), {}, {}
    total = len(payload)
    for entry in inventory:
        require(type(entry) is dict and set(entry) == {"role", "logical_name", "sha256", "size_bytes"},
                "package_file_fields_invalid")
        role, name, sha, size = (entry[key] for key in ("role", "logical_name", "sha256", "size_bytes"))
        require(type(role) is str and role in {"input", "frequency", "license", "provenance"}, "package_role_invalid")
        require(type(name) is str and NAME.fullmatch(name) and ".." not in name and name not in names,
                "package_logical_name_invalid")
        require(type(sha) is str and HASH.fullmatch(sha), "package_file_pin_invalid")
        require(type(size) is int and 0 < size <= MAX_FILE_BYTES, "package_file_size_invalid")
        data = artifact_bytes.get(sha)
        require(type(data) is bytes and len(data) == size and hashlib.sha256(data).hexdigest() == sha,
                "package_file_pin_mismatch")
        names.add(name)
        hashes.add(sha)
        counts[role] = counts.get(role, 0) + 1
        roles[role] = entry
    require(counts.get("input") == 1 and counts.get("frequency") == 1, "exact_input_output_required")
    require(hashes == set(artifact_bytes), "package_complete_inventory_required")
    total += sum(len(data) for data in artifact_bytes.values())
    require(total <= MAX_PACKAGE_BYTES, "package_total_byte_limit")
    return roles


def _source_hashes():
    root = Path(__file__).resolve().parents[2]
    # These pins document the compiler actually used, not a scientific review.
    names = ("api/services/scientific_program_import.py", "api/services/qe_matdyn_import.py",
             "api/services/research_release_manifest.py", "api/services/research_release_spec.py",
             "scripts/scientific_program_preflight.py", "scripts/verify_research_release.py")
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}


def build_preflight(manifest, *, artifact_bytes, expected_manifest_sha256):
    roles = validate_package(manifest, artifact_bytes, expected_manifest_sha256)
    try:
        result = parse_matdyn(input_bytes=artifact_bytes[roles["input"]["sha256"]],
                              frequency_bytes=artifact_bytes[roles["frequency"]["sha256"]])
    except MatdynImportError as exc:
        # A captured but unsupported/malformed program file is counted, not
        # dropped from the canary denominator. No parser exception text leaks.
        code = str(exc)
        safe_code = code if re.fullmatch(r"[a-z][a-z0-9_]{0,159}", code) else "adapter_parse_rejected"
        result = {"version": "qe-matdyn-import/1.0.0", "adapter_id": ADAPTER,
                  "status": "quarantined", "reason_codes": [safe_code],
                  "property_candidates": [], "spectrum": None, "input_observations": {},
                  "files": {"input_sha256": roles["input"]["sha256"], "frequency_sha256": roles["frequency"]["sha256"]},
                  "authority": {"scientific_accepted": False, "ml_training_approved": False, "execution_attested": False}}
    reasons = list(result["reason_codes"])
    # An operator-provided file name does not prove the same execution, but an
    # explicit mismatch does refute this package's claimed input/output pairing.
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
    report = {
        "version": REPORT_VERSION, "status": status, "reason_codes": reasons,
        "package_sha256": expected_manifest_sha256, "adapter_id": ADAPTER,
        "source_code_sha256": _source_hashes(),
        "inventory": manifest["files"], "context_declarations": manifest["context"],
        "parse_result": result,
        "coverage": {"packages_seen": 1, "packages_parsed": int(status == "parsed"),
                     "packages_quarantined": int(status == "quarantined"),
                     "property_candidates": len(result["property_candidates"]),
                     "scientifically_accepted_properties": 0, "ml_admitted_properties": 0},
        "unresolved_gates": ["material_state_structure_binding", "actual_force_constant_ancestry",
            "program_run_identity_and_convergence", "scientific_review", "source_time_review", "source_rights_review"],
        "costs": {"calculation_cpu_seconds": None, "calculation_wall_seconds": None,
                  "calculation_monetary_cost": None, "import_elapsed_seconds": None,
                  "note": "Not measured by this deterministic offline preflight; missing is not zero."},
        "authority": dict(AUTHORITY),
    }
    require(len(canonical(report)) <= MAX_PACKAGE_BYTES, "preflight_report_byte_limit")
    return report
