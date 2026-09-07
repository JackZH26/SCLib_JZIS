"""Bounded, offline verification of published v1 source and claim-plan bundles.

The caller must pin both manifest hashes independently of the bundles. Hashes
are integrity bindings, not authorization, scientific approval, source-rights
clearance, or proof of historical result availability. This module imports no
database clients and makes no database/network calls. Current mapper versions
only are replayed; older bundles must not silently receive new interpretations.

The CLI prints metadata only. ``verify_shadow_import`` returns bounded payloads
for a separately authorized shadow-only persistence workflow; its result is not
a capability token. Callers must not accept a user-supplied lookalike dictionary
in place of actually invoking this verifier.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "ingestion"))

from ingestion.claims.shadow_parity import build_shadow_parity_report

from scripts import export_ml_foundation_snapshot as exporter
from scripts import plan_typed_claim_backfill as planner

VERIFIER_VERSION = "sclib-shadow-import-verifier/1.0.0"
LIMITS = {
    "occurrences": 1000,
    "materials": 1000,
    "papers": 2000,
    "file_bytes": 8 * 1024 * 1024,
    "jsonl_row_bytes": 2 * 1024 * 1024,
    "combined_bytes": 64 * 1024 * 1024,
    "json_depth": 48,
    "json_nodes": 200000,
    "formula_chars": 4096,
}
_ROWS = ("works", "paper_work_map", "claims", "compositions", "failures", "warnings")
_OUTPUTS = {*(f"{key}.jsonl" for key in _ROWS), "summary.json", "parity_report.json"}
_PLAN_FILES = _OUTPUTS | {"manifest.json", "manifest.sha256", "source_snapshots.jsonl"}
_PLAN_FIELDS = {
    "schema_version",
    "source_snapshot_id",
    "dataset_version",
    "site_git_sha",
    "database_watermark",
    "chunk_count",
    "claim_mapper_version",
    "work_identity_version",
    "formula_parser_version",
    "license_manifest_sha256",
    "source_export_manifest_sha256",
    "source_alembic_revision",
    "inputs",
    "outputs",
    "summary",
}
_SOURCE_FIELDS = {
    "schema_version",
    "exporter_version",
    "source_snapshot_id",
    "dataset_version",
    "site_git_sha",
    "database_watermark",
    "alembic_revision",
    "chunk_count",
    "license_manifest_sha256",
    "material_scope",
    "scientific_semantics",
    "files",
    "counts",
    "queries",
    "database",
    "metadata",
}
_HASH = re.compile(r"^[0-9a-f]{64}$")
_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,100}$")


class ShadowImportVerificationError(ValueError):
    """No payload is eligible for the bounded shadow-import workflow."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ShadowImportVerificationError(message)


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=planner._json_default,
    ).encode("utf-8")


def _same(actual: Any, expected: Any, label: str) -> None:
    _require(_canonical(actual) == _canonical(expected), f"{label} mismatch")


def _strict_json(payload: bytes, label: str) -> Any:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict:
        result: dict[str, Any] = {}
        for key, value in pairs:
            _require(key not in result, f"{label}: duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(_value: str) -> None:
        raise ShadowImportVerificationError(f"{label}: nonfinite JSON number")

    try:
        value = json.loads(
            payload.decode("utf-8"), object_pairs_hook=object_pairs, parse_constant=reject_constant
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        if isinstance(exc, ShadowImportVerificationError):
            raise
        raise ShadowImportVerificationError(f"{label}: invalid or excessive JSON") from exc
    pending = [(value, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        _require(
            depth <= LIMITS["json_depth"] and nodes <= LIMITS["json_nodes"],
            f"{label}: JSON resource limit exceeded",
        )
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, float):
            _require(math.isfinite(item), f"{label}: nonfinite JSON number")
        elif isinstance(item, str):
            try:
                item.encode("utf-8")
            except UnicodeError as exc:
                raise ShadowImportVerificationError(f"{label}: invalid Unicode") from exc
    return value


def _document(payload: bytes, label: str) -> dict:
    value = _strict_json(payload, label)
    _require(isinstance(value, dict), f"{label}: expected JSON object")
    return value


def _jsonl(payload: bytes, label: str, *, maximum: int) -> list[dict]:
    _require(not payload or payload.endswith(b"\n"), f"{label}: missing final newline")
    rows = []
    for line in payload.splitlines():
        _require(
            bool(line.strip()) and len(line) <= LIMITS["jsonl_row_bytes"],
            f"{label}: blank or oversized JSONL row",
        )
        _require(len(rows) < maximum, f"{label}: row limit exceeded")
        rows.append(_document(line, label))
    return rows


def _signature(info: os.stat_result) -> tuple:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _directory_fd(path: Path) -> int:
    """Walk every ancestor with O_NOFOLLOW, including the caller's root."""
    _require(
        path.is_absolute() and ".." not in path.parts,
        "manifest paths must be absolute and must not contain traversal",
    )
    descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_fd
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _capture(path: Path, *, manifest_name: str, byte_budget: int) -> tuple[dict, dict]:
    _require(path.name == manifest_name, f"manifest must be named {manifest_name}")
    descriptor = _directory_fd(path.parent)
    payloads, signatures = {}, {}
    try:
        names = _inventory(descriptor)
        _require(manifest_name in names, "invalid bundle inventory")
        for name in names:
            _require(bool(_FILENAME.fullmatch(name)), "unsafe artifact filename")
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
            try:
                before = os.fstat(fd)
                _require(
                    stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
                    "artifacts must be regular files without hard-link aliases",
                )
                _require(before.st_size <= LIMITS["file_bytes"], "file byte limit exceeded")
                _require(before.st_size <= byte_budget, "combined byte limit exceeded")
                chunks, size = [], 0
                while True:
                    chunk = os.read(fd, min(1024 * 1024, LIMITS["file_bytes"] - size + 1))
                    if not chunk:
                        break
                    size += len(chunk)
                    _require(
                        size <= LIMITS["file_bytes"] and size <= byte_budget,
                        "file grew beyond byte budget",
                    )
                    chunks.append(chunk)
                after = os.fstat(fd)
                _require(
                    _signature(before) == _signature(after) and size == before.st_size,
                    "artifact changed during capture",
                )
                signatures[name] = _signature(after)
                payloads[name] = b"".join(chunks)
                byte_budget -= size
            finally:
                os.close(fd)
        _require(names == _inventory(descriptor), "bundle inventory changed during capture")
        return payloads, signatures
    finally:
        os.close(descriptor)


def _inventory(descriptor: int) -> list[str]:
    # Do not materialize an unbounded directory listing before applying its cap.
    names = []
    with os.scandir(descriptor) as entries:
        for entry in entries:
            _require(len(names) < 11, "invalid bundle inventory")
            names.append(entry.name)
    return sorted(names)


def _source_rows(payloads: dict, manifest: dict) -> tuple[list, list, list]:
    entries = manifest["files"]
    materials = _jsonl(
        payloads[entries["materials"]["path"]], "materials", maximum=LIMITS["materials"]
    )
    papers = _jsonl(payloads[entries["papers"]["path"]], "papers", maximum=LIMITS["papers"])
    existing = (
        _jsonl(
            payloads[entries["paper_work_map"]["path"]],
            "existing paper-work map",
            maximum=LIMITS["papers"],
        )
        if "paper_work_map" in entries
        else []
    )
    for row in [*materials, *papers]:
        identifier = row.get("id")
        _require(
            isinstance(identifier, str)
            and identifier == identifier.strip()
            and 0 < len(identifier) <= 1024,
            "source row requires a bounded string ID",
        )
    occurrences = 0
    for material in materials:
        for field in ("formula", "formula_normalized"):
            value = material.get(field)
            _require(
                value is None or isinstance(value, str) and len(value) <= LIMITS["formula_chars"],
                "material formula must be bounded text or null",
            )
        records = material.get("records")
        if isinstance(records, str):
            records = _strict_json(records.encode("utf-8"), "embedded material records")
        _require(
            records is None or isinstance(records, list),
            "material records must be an array or null",
        )
        for record in records or []:
            _require(isinstance(record, dict), "source occurrence must be an object")
            occurrences += 1
            _require(occurrences <= LIMITS["occurrences"], "raw occurrence canary limit exceeded")
    _same(manifest["counts"]["material_records"], occurrences, "source occurrence count")
    return materials, papers, existing


def _expected_snapshot(source: dict, plan: dict, plan_hash: str, parity: dict) -> dict:
    return {
        "id": source["source_snapshot_id"],
        "dataset_version": source["dataset_version"],
        "site_git_sha": source["site_git_sha"],
        "database_watermark": source["database_watermark"],
        "paper_count": source["counts"]["papers"],
        "material_count": source["counts"]["materials"],
        "chunk_count": source["chunk_count"],
        "schema_version": "ml-foundation-v1",
        "manifest_sha256": plan_hash,
        "license_manifest_sha256": source["license_manifest_sha256"],
        "status": "building",
        "metadata": {
            "planner": "plan_typed_claim_backfill.py",
            "manifest_file": "manifest.json",
            "failure_count": 0,
            "parity_report_sha256": plan["outputs"]["parity_report.json"]["sha256"],
            "parity_gate_status": parity["gate_status"],
            "parity_gate_failures": len(parity["gate_failures"]),
            "source_export_manifest_sha256": plan["source_export_manifest_sha256"],
            "source_alembic_revision": source["alembic_revision"],
        },
    }


def verify_shadow_import(
    *,
    source_manifest: Path,
    plan_manifest: Path,
    expected_source_manifest_sha256: str,
    expected_plan_manifest_sha256: str,
) -> dict[str, Any]:
    """Return a normalized replay, or fail closed without any partial payload.

    Fixed limits are a canary safety boundary, not an approved scientific sample.
    JSON serialization of the returned dictionary preserves all payload values.
    ``payload_sha256`` covers canonical UTF-8 JSON of every other returned field;
    the self-excluding fingerprint is not a signature or authorization token.
    """
    try:
        return _verify(
            source_manifest=Path(source_manifest),
            plan_manifest=Path(plan_manifest),
            source_hash=expected_source_manifest_sha256,
            plan_hash=expected_plan_manifest_sha256,
        )
    except ShadowImportVerificationError:
        raise
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RecursionError,
        OverflowError,
    ) as exc:
        # Do not reflect source text, local file contents, or private locators.
        raise ShadowImportVerificationError(
            "bundle verification failed: " + type(exc).__name__
        ) from exc


def _verify(
    *, source_manifest: Path, plan_manifest: Path, source_hash: str, plan_hash: str
) -> dict:
    for value in (source_hash, plan_hash):
        _require(
            isinstance(value, str) and bool(_HASH.fullmatch(value)),
            "operator-pinned SHA-256 values must be lowercase 64-character hex",
        )
    source_bytes, source_signatures = _capture(
        source_manifest, manifest_name="export_manifest.json", byte_budget=LIMITS["combined_bytes"]
    )
    remaining = LIMITS["combined_bytes"] - sum(map(len, source_bytes.values()))
    plan_bytes, plan_signatures = _capture(
        plan_manifest, manifest_name="manifest.json", byte_budget=remaining
    )
    identities = [
        (entry[0], entry[1]) for entry in [*source_signatures.values(), *plan_signatures.values()]
    ]
    _require(len(set(identities)) == len(identities), "source and plan must not alias artifacts")
    _require(
        _hash(source_bytes["export_manifest.json"]) == source_hash,
        "pinned source manifest hash mismatch",
    )
    _require(_hash(plan_bytes["manifest.json"]) == plan_hash, "pinned plan manifest hash mismatch")
    _require(set(plan_bytes) == _PLAN_FILES, "plan file inventory mismatch")
    source = _document(source_bytes["export_manifest.json"], "source manifest")
    plan = _document(plan_bytes["manifest.json"], "plan manifest")
    _require(set(source) <= _SOURCE_FIELDS, "unexpected source manifest payload")
    _require(set(plan) == _PLAN_FIELDS, "unexpected or missing plan manifest fields")
    _same(plan["schema_version"], "sclib-ml-foundation-plan/v1", "plan schema")
    for field, version in (
        ("claim_mapper_version", planner.CLAIM_MAPPER_VERSION),
        ("work_identity_version", planner.WORK_IDENTITY_VERSION),
        ("formula_parser_version", planner.PARSER_VERSION),
    ):
        _same(plan[field], version, field)
    _same(
        plan_bytes["manifest.sha256"].decode("ascii"),
        f"{plan_hash}  manifest.json\n",
        "plan sidecar",
    )

    # Validate every source JSON value before using the published verifier,
    # whose historical v1 JSON parser did not reject duplicate object keys.
    entries = source.get("files")
    _require(isinstance(entries, dict), "source files must be an object")
    allowed_source = {"export_manifest.json", "export_manifest.sha256", "checksums.sha256"}
    for key, entry in entries.items():
        _require(
            key in {"materials", "papers", "paper_work_map", "license_manifest"}
            and isinstance(entry, dict)
            and set(entry) == {"path", "sha256", "rows", "bytes"},
            "unexpected source file entry",
        )
        for count_field in ("rows", "bytes"):
            count = entry[count_field]
            _require(type(count) is int and count >= 0, "invalid source file count")
        name = entry["path"]
        _require(
            isinstance(name, str)
            and bool(_FILENAME.fullmatch(name))
            and name not in allowed_source,
            "unsafe or duplicate source artifact path",
        )
        allowed_source.add(name)
        _require(name in source_bytes, "missing source artifact")
        if key == "license_manifest":
            _document(source_bytes[name], "license manifest")
        else:
            _jsonl(
                source_bytes[name],
                key,
                maximum=LIMITS["materials"] if key == "materials" else LIMITS["papers"],
            )
    _require(set(source_bytes) == allowed_source, "source file inventory mismatch")
    # Private copies bind the older exporter verifier to the exact bytes read
    # above, never to mutable originals. TemporaryDirectory owns cleanup only.
    with tempfile.TemporaryDirectory(prefix="sclib-shadow-verify-") as temp_name:
        temp_root = Path(temp_name)
        for name, payload in source_bytes.items():
            file = temp_root / name
            file.write_bytes(payload)
            file.chmod(0o600)
        checked = exporter.verify_export_bundle(temp_root)
        _same(checked, source, "source verifier replay")

    materials, papers, existing = _source_rows(source_bytes, source)
    for field in (
        "source_snapshot_id",
        "dataset_version",
        "site_git_sha",
        "database_watermark",
        "chunk_count",
        "license_manifest_sha256",
    ):
        _same(plan[field], source[field], "plan capture " + field)
    _same(plan["source_alembic_revision"], source["alembic_revision"], "source schema revision")
    _same(plan["source_export_manifest_sha256"], source_hash, "source capture hash")
    expected_inputs = {
        key: {"file_name": entries[key]["path"], "sha256": entries[key]["sha256"]}
        for key in ("materials", "papers")
    }
    if "paper_work_map" in entries:
        expected_inputs["existing_paper_work"] = {
            "file_name": entries["paper_work_map"]["path"],
            "sha256": entries["paper_work_map"]["sha256"],
        }
    expected_inputs["source_export_manifest"] = {
        "file_name": "export_manifest.json",
        "sha256": source_hash,
    }
    _same(plan["inputs"], expected_inputs, "plan inputs")
    _require(
        isinstance(plan["outputs"], dict) and set(plan["outputs"]) == _OUTPUTS,
        "plan outputs inventory mismatch",
    )
    actual_rows = {}
    for name, entry in plan["outputs"].items():
        expected_fields = {"rows", "sha256"} if name.endswith(".jsonl") else {"sha256"}
        _require(
            isinstance(entry, dict) and set(entry) == expected_fields,
            "unexpected plan output metadata",
        )
        _same(entry["sha256"], _hash(plan_bytes[name]), "plan leaf hash " + name)
        if name.endswith(".jsonl"):
            rows = _jsonl(plan_bytes[name], name, maximum=LIMITS["papers"] * 2)
            _same(entry["rows"], len(rows), "plan output count " + name)
            actual_rows[name[:-6]] = rows
    _require(
        not actual_rows["failures"],
        "plan failures must be zero; no exclusions are implicitly approved",
    )
    rebuilt = planner.build_backfill_plan(
        materials,
        papers,
        source_snapshot_id=source["source_snapshot_id"],
        existing_paper_work=existing,
    )
    _require(not rebuilt["failures"], "source replay has failures")
    for key in _ROWS:
        _same(actual_rows[key], rebuilt[key], "reconstructed " + key)
    # Audit the received rows separately from the freshly rebuilt plan. This
    # retains independent accounting/identity/negative-result parity gates.
    independent = build_shadow_parity_report(
        materials,
        papers,
        {**actual_rows, "summary": rebuilt["summary"]},
        existing_paper_work=existing,
    )
    _require(
        independent["gate_status"] == "pass" and not independent["gate_failures"],
        "independent parity gate failed",
    )
    _same(
        _document(plan_bytes["parity_report.json"], "parity report"),
        independent,
        "independent parity report",
    )
    summary = {**rebuilt["summary"], "parity_gate_status": "pass", "parity_gate_failures": 0}
    _same(_document(plan_bytes["summary.json"], "summary"), summary, "reconstructed summary")
    _same(plan["summary"], summary, "manifest summary")
    snapshot = _expected_snapshot(source, plan, plan_hash, independent)
    _same(
        _jsonl(plan_bytes["source_snapshots.jsonl"], "source snapshots", maximum=1),
        [snapshot],
        "non-authoritative convenience snapshot",
    )

    # Reject ordinary concurrent mutation as well as byte-preserving replacement.
    # This is not a cryptographic filesystem snapshot or hostile-OS guarantee.
    for path, name, old_bytes, old_signatures in (
        (source_manifest, "export_manifest.json", source_bytes, source_signatures),
        (plan_manifest, "manifest.json", plan_bytes, plan_signatures),
    ):
        fresh_bytes, fresh_signatures = _capture(
            path, manifest_name=name, byte_budget=LIMITS["combined_bytes"]
        )
        _require(
            fresh_bytes == old_bytes and fresh_signatures == old_signatures,
            "bundle changed during verification",
        )
    result = {
        "version": "verified-shadow-import/1.0.0",
        "verifier_version": VERIFIER_VERSION,
        "source_manifest": source,
        "plan_manifest": plan,
        "source_manifest_sha256": source_hash,
        "plan_manifest_sha256": plan_hash,
        "verified_metadata": {
            "source_manifest_sha256": source_hash,
            "plan_manifest_sha256": plan_hash,
            "source_snapshot_id": source["source_snapshot_id"],
            "dataset_version": source["dataset_version"],
            "site_git_sha": source["site_git_sha"],
            "database_watermark": source["database_watermark"],
            "source_alembic_revision": source["alembic_revision"],
            "material_scope": source["material_scope"],
            "license_manifest_sha256": source["license_manifest_sha256"],
            "claim_mapper_version": plan["claim_mapper_version"],
            "work_identity_version": plan["work_identity_version"],
            "formula_parser_version": plan["formula_parser_version"],
            "limits": dict(LIMITS),
            "counts": dict(source["counts"]),
            "verification_scope": "bounded_offline_integrity_and_replay",
            "scientific_acceptance": False,
            "permissions_verified": False,
            "historical_result_availability_verified": False,
            "database_verified": False,
            "public_release_authorized": False,
        },
        "materials": materials,
        "papers": papers,
        "existing_paper_work": existing,
        **{key: rebuilt[key] for key in _ROWS},
        "summary": summary,
        "parity_report": independent,
        "proposed_source_snapshot": snapshot,
    }
    normalized = json.loads(_canonical(result))
    normalized["payload_sha256"] = _hash(_canonical(normalized))
    return normalized


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", required=True, type=Path)
    parser.add_argument("--plan-manifest", required=True, type=Path)
    parser.add_argument("--expected-source-manifest-sha256", required=True)
    parser.add_argument("--expected-plan-manifest-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        result = verify_shadow_import(**vars(args))
    except ShadowImportVerificationError as exc:
        print(f"Shadow verification rejected: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "verifier_version": result["verifier_version"],
                "payload_sha256": result["payload_sha256"],
                "verified_metadata": result["verified_metadata"],
            },
            sort_keys=True,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
