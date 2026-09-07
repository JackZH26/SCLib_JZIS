"""Offline Phase-1 work/claim backfill planner (never connects to a DB).

Input files are JSONL snapshots.  Each materials row must contain ``id`` and
``records``; papers rows use the existing papers-table shape.  Without
``--output-dir`` the command only validates and prints counts.  With an output
directory it writes proposed JSONL payloads for review, still with zero DB
writes.

Example::

    ingestion/.venv/bin/python scripts/plan_typed_claim_backfill.py \
      --source-export-manifest /secure/export/export_manifest.json \
      --output-dir /tmp/sclib-phase1-plan

The planner requires Python 3.11 or newer.  The command above deliberately
uses the ingestion project's managed virtual environment instead of whichever
system ``python`` happens to be on ``PATH``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import uuid
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "ingestion"))

from ingestion.claims import (
    CLAIM_MAPPER_VERSION,
    WORK_IDENTITY_VERSION,
    map_record_to_claim,
    plan_work_identities,
)
from ingestion.claims.shadow_parity import build_shadow_parity_report
from ingestion.extract.formula_enrichment import (
    PARSER_VERSION,
    enrich_material_composition,
)

from scripts.export_ml_foundation_snapshot import (
    MANIFEST_FILE as SOURCE_EXPORT_MANIFEST_FILE,
)
from scripts.export_ml_foundation_snapshot import VerificationError as SourceExportError
from scripts.export_ml_foundation_snapshot import verify_export_bundle

SOURCE_EXPORT_SCHEMA = "sclib-source-export/v1"


def _legacy_available_at_hint(record: dict, paper: dict) -> date | None:
    """Reproduce the retired v1.3 date fallback for diagnostics, never admission."""
    def parsed(value: Any) -> date | None:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).date()
        except ValueError:
            return None

    explicit = parsed(record.get("available_at"))
    candidates = [parsed(paper.get(key)) for key in ("available_at", "date_submitted", "date_published")]
    return explicit or min((value for value in candidates if value is not None), default=None)


def _load_json_object(path: Path) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{path}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys
        )
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise TypeError(f"{path}: expected a JSON object")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(row, dict):
                raise TypeError(f"{path}:{line_number}: expected a JSON object")
            rows.append(row)
    return rows


def build_backfill_plan(
    materials: Iterable[dict[str, Any]],
    papers: Iterable[dict[str, Any]],
    *,
    source_snapshot_id: uuid.UUID | str,
    existing_paper_work: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    try:
        snapshot_id = uuid.UUID(str(source_snapshot_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("source_snapshot_id must be a valid UUID") from exc

    material_rows = list(materials)
    paper_rows = list(papers)
    existing_rows: dict[str, dict[str, Any]] = {}
    accepted_work_ids: dict[str, str] = {}
    valid_review_statuses = {"accepted", "pending", "rejected"}
    valid_match_methods = {
        "exact_doi",
        "related_paper",
        "exact_arxiv",
        "metadata",
        "manual",
        "singleton",
    }
    valid_relation_types = {
        "canonical_version",
        "preprint",
        "published_version",
        "supplement",
        "correction",
        "unknown",
    }
    for row in existing_paper_work:
        paper_id = str(row.get("paper_id") or "").strip()
        work_id = str(row.get("work_id") or "").strip()
        if not paper_id or not work_id:
            raise ValueError("existing paper-work rows require paper_id and work_id")
        try:
            uuid.UUID(work_id)
        except ValueError as exc:
            raise ValueError(f"invalid existing work_id for {paper_id!r}") from exc
        review_status = str(row.get("review_status") or "").strip().lower()
        if review_status not in valid_review_statuses:
            raise ValueError(
                f"existing paper-work row for {paper_id!r} requires a valid review_status"
            )
        if paper_id in existing_rows:
            raise ValueError(f"duplicate existing paper-work row for {paper_id!r}")
        normalized = dict(row)
        normalized.update(
            {
                "paper_id": paper_id,
                "work_id": str(uuid.UUID(work_id)),
                "review_status": review_status,
            }
        )
        match_method = normalized.get("match_method")
        if match_method is not None and (
            not isinstance(match_method, str) or match_method not in valid_match_methods
        ):
            raise ValueError(f"invalid existing match_method for {paper_id!r}")
        relation_type = normalized.get("relation_type")
        if relation_type is not None and (
            not isinstance(relation_type, str)
            or relation_type not in valid_relation_types
        ):
            raise ValueError(f"invalid existing relation_type for {paper_id!r}")
        existing_rows[paper_id] = normalized
        if review_status == "accepted":
            accepted_work_ids[paper_id] = normalized["work_id"]

    work_plan = plan_work_identities(paper_rows, existing_work_ids=accepted_work_ids)
    for mapping in work_plan["paper_work_map"]:
        existing = existing_rows.get(mapping["paper_id"])
        if existing is None:
            continue
        if existing["review_status"] == "accepted":
            mapping["review_status"] = "accepted"
            if existing.get("match_method") is not None:
                mapping["match_method"] = existing["match_method"]
            if existing.get("relation_type") is not None:
                mapping["relation_type"] = existing["relation_type"]
        else:
            # Review state belongs to the old paper/work pair.  Since a
            # non-accepted work ID is not an identity edge, the resolver may
            # generate a different pair; carrying ``rejected`` or ``pending``
            # onto that new pair would silently adjudicate a relationship
            # that was never reviewed.
            work_plan["warnings"].append(
                {
                    "code": "nonaccepted_existing_mapping_not_authoritative",
                    "paper_id": mapping["paper_id"],
                    "old_work_id": existing["work_id"],
                    "old_review_status": existing["review_status"],
                    "old_match_method": existing.get("match_method"),
                    "old_relation_type": existing.get("relation_type"),
                    "proposed_work_id": str(mapping["work_id"]),
                }
            )
    paper_by_id = {str(row.get("id") or row.get("paper_id")): row for row in paper_rows}
    work_by_paper = {
        row["paper_id"]: row["work_id"] for row in work_plan["paper_work_map"]
    }

    claims: list[dict[str, Any]] = []
    compositions: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    seen_source_keys: set[tuple[str, str]] = set()
    exact_duplicates = 0
    input_records = 0
    seen_material_ids: set[str] = set()
    planner_warnings: list[dict[str, Any]] = []
    temporal_audit_rows: list[dict[str, Any]] = []

    for material in material_rows:
        material_id = str(material.get("id") or "").strip()
        if not material_id:
            failures.append({"material_id": None, "code": "missing_material_id"})
            continue
        if material_id in seen_material_ids:
            failures.append(
                {"material_id": material_id, "code": "duplicate_material_id"}
            )
            continue
        seen_material_ids.add(material_id)

        records = material.get("records")
        if records is None:
            records = []
        formula = material.get("formula") or material.get("formula_normalized") or ""
        enrichment = enrich_material_composition(material)
        composition_status = enrichment.pop("composition_status")
        compositions.append(
            {
                "material_id": material_id,
                "composition_status": composition_status,
                "composition_data": enrichment,
            }
        )
        if isinstance(records, str):
            try:
                records = json.loads(records)
            except json.JSONDecodeError:
                failures.append(
                    {"material_id": material_id, "code": "invalid_records_json"}
                )
                continue
        if not isinstance(records, list):
            failures.append({"material_id": material_id, "code": "records_not_array"})
            continue

        for ordinal, record in enumerate(records):
            input_records += 1
            if not isinstance(record, dict):
                failures.append(
                    {
                        "material_id": material_id,
                        "record_ordinal": ordinal,
                        "code": "record_not_object",
                    }
                )
                continue
            paper_id = str(record.get("paper_id") or "").strip() or None
            if paper_id is not None and paper_id not in paper_by_id:
                failures.append(
                    {
                        "material_id": material_id,
                        "record_ordinal": ordinal,
                        "paper_id": paper_id,
                        "code": "unknown_paper_id",
                    }
                )
                # Keep the failure record for reconciliation, but do not emit
                # a payload that would violate the papers foreign key.
                continue
            try:
                claim = map_record_to_claim(
                    record,
                    material_id=material_id,
                    material_formula=formula,
                    paper=paper_by_id.get(paper_id) if paper_id else None,
                    work_id=work_by_paper.get(paper_id) if paper_id else None,
                    source_snapshot_id=snapshot_id,
                )
            except (OverflowError, TypeError, ValueError) as exc:
                failures.append(
                    {
                        "material_id": material_id,
                        "record_ordinal": ordinal,
                        "code": "mapping_error",
                        "error": str(exc),
                    }
                )
                continue
            if claim["chunk_id"] is not None:
                # Phase 1 intentionally does not export the million-row chunk
                # inventory.  Preserve the legacy locator in raw_record /
                # source_locator, but clear the unverified relational FK so a
                # validated bundle is loadable.  New dual-write ingestion can
                # set this column only after checking the chunk table.
                planner_warnings.append(
                    {
                        "material_id": material_id,
                        "record_ordinal": ordinal,
                        "code": "unverified_chunk_fk_cleared",
                        "chunk_id": claim["chunk_id"],
                    }
                )
                claim["chunk_id"] = None
            source_key = (material_id, claim["source_record_hash"])
            if source_key in seen_source_keys:
                exact_duplicates += 1
                continue
            seen_source_keys.add(source_key)
            legacy_date = _legacy_available_at_hint(record, paper_by_id.get(paper_id, {}))
            # Keep diagnostics outside proposed claim payloads so the shadow
            # parity verifier still compares exact mapper output unchanged.
            temporal_audit_rows.append({
                "claim_id": str(claim["id"]),
                "legacy_mapper_available_at_hint": legacy_date.isoformat() if legacy_date else None,
                "proposed_available_at": claim["available_at"].isoformat() if claim["available_at"] else None,
                "projection_change": "changed" if legacy_date != claim["available_at"] else "unchanged",
                "source_version_verifiable": False,
                "reason": "v1_source_export_has_no_reviewed_result_version_witness",
            })
            claims.append(claim)

    claims.sort(key=lambda row: (row["material_id"], row["source_record_hash"]))
    compositions.sort(key=lambda row: row["material_id"])
    failures.sort(key=lambda row: json.dumps(row, sort_keys=True))
    warnings = [*work_plan["warnings"], *planner_warnings]
    warnings.sort(key=lambda row: json.dumps(row, sort_keys=True))
    return {
        "works": work_plan["works"],
        "paper_work_map": work_plan["paper_work_map"],
        "claims": claims,
        "compositions": compositions,
        "failures": failures,
        "warnings": warnings,
        "summary": {
            "papers": len(paper_rows),
            "materials": len(material_rows),
            "works": len(work_plan["works"]),
            "source_snapshot_id": str(snapshot_id),
            "existing_paper_work_rows": len(existing_rows),
            "accepted_existing_paper_work_rows": len(accepted_work_ids),
            "input_records": input_records,
            "unique_claims": len(claims),
            "composition_rows": len(compositions),
            "exact_compositions": sum(
                row["composition_status"] == "exact" for row in compositions
            ),
            "exact_duplicate_records": exact_duplicates,
            "failures": len(failures),
            "temporal_projection_audit": {
                "version": "legacy-temporal-projection-audit/1.0.0",
                "comparison_scope": "retired_v1.3_mapper_not_live_database",
                "changed_projection_claims": sum(
                    row["projection_change"] == "changed" for row in temporal_audit_rows
                ),
                "unchanged_projection_claims": sum(
                    row["projection_change"] == "unchanged" for row in temporal_audit_rows
                ),
                "unverifiable_source_version_claims": len(claims),
                "unverifiable_is_separate_axis": True,
                "claims": sorted(temporal_audit_rows, key=lambda row: row["claim_id"]),
                "database_mutated": False,
            },
        },
    }


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(
                json.dumps(row, ensure_ascii=False, default=_json_default) + "\n"
            )


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime, uuid.UUID)):
        return value.isoformat() if not isinstance(value, uuid.UUID) else str(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_sha256(value: str | None, *, field: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(
        char not in "0123456789abcdef" for char in normalized
    ):
        raise ValueError(f"{field} must be a 64-character hexadecimal SHA-256")
    return normalized


def _validate_dataset_version(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("dataset_version must be non-empty")
    if len(normalized) > 50:
        raise ValueError("dataset_version must be at most 50 characters")
    return normalized


def _validate_git_sha(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 40 or any(
        char not in "0123456789abcdef" for char in normalized
    ):
        raise ValueError("site_git_sha must be a 40-character hexadecimal Git SHA")
    return normalized


def _validate_database_watermark(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        raise ValueError("database_watermark must be an ISO-8601 timestamp or omitted")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("database_watermark must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("database_watermark must include a timezone offset")
    return parsed.isoformat()


def _resolve_manifest_member(
    manifest_path: Path, relative_path: Any, *, field: str
) -> Path:
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ValueError(f"{field} must be a non-empty relative path")
    member = Path(relative_path)
    if member.is_absolute() or ".." in member.parts:
        raise ValueError(f"{field} must stay inside the source export directory")
    root = manifest_path.parent.resolve()
    resolved = (root / member).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{field} escapes the source export directory") from exc
    if not resolved.is_file():
        raise ValueError(f"{field} does not reference a regular file")
    return resolved


def _count_jsonl_objects(path: Path) -> int:
    return len(load_jsonl(path))


def load_source_export_manifest(manifest_path: Path) -> dict[str, Any]:
    """Validate a source export bundle and return normalized planner inputs.

    The exporter, rather than a human CLI invocation, owns every capture
    identity field.  This prevents a valid JSONL file from being paired with a
    different database watermark, snapshot UUID, or license manifest.
    """
    manifest_path = manifest_path.resolve()
    if manifest_path.name != SOURCE_EXPORT_MANIFEST_FILE:
        raise ValueError(
            f"source export manifest must be named {SOURCE_EXPORT_MANIFEST_FILE}"
        )
    try:
        manifest = verify_export_bundle(manifest_path.parent)
    except (OSError, SourceExportError) as exc:
        raise ValueError(f"invalid source export bundle: {exc}") from exc
    if manifest.get("schema_version") != SOURCE_EXPORT_SCHEMA:
        raise ValueError(
            f"source export schema_version must be {SOURCE_EXPORT_SCHEMA!r}"
        )

    sidecar_path = manifest_path.with_suffix(".sha256")
    if not sidecar_path.is_file():
        raise ValueError(f"missing source export manifest sidecar: {sidecar_path.name}")
    sidecar_parts = sidecar_path.read_text(encoding="utf-8").strip().split()
    if not sidecar_parts:
        raise ValueError("source export manifest sidecar is empty")
    if len(sidecar_parts) > 1 and sidecar_parts[1] not in {
        manifest_path.name,
        f"*{manifest_path.name}",
    }:
        raise ValueError("source export manifest sidecar names a different file")
    manifest_sha256 = _sha256_file(manifest_path)
    expected_manifest_sha256 = _validate_sha256(
        sidecar_parts[0], field="source export manifest sidecar"
    )
    if manifest_sha256 != expected_manifest_sha256:
        raise ValueError("source export manifest hash does not match its sidecar")

    try:
        snapshot_id = uuid.UUID(str(manifest["source_snapshot_id"]))
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError(
            "source export manifest requires a valid source_snapshot_id"
        ) from exc
    dataset_version = _validate_dataset_version(
        str(manifest.get("dataset_version") or "")
    )
    site_git_sha = _validate_git_sha(str(manifest.get("site_git_sha") or ""))
    database_watermark = _validate_database_watermark(
        manifest.get("database_watermark")
    )
    if database_watermark is None:
        raise ValueError("source export manifest requires database_watermark")
    alembic_revision = manifest.get("alembic_revision")
    if not isinstance(alembic_revision, str) or not alembic_revision.strip():
        raise ValueError("source export manifest requires alembic_revision")
    chunk_count = manifest.get("chunk_count")
    if (
        isinstance(chunk_count, bool)
        or not isinstance(chunk_count, int)
        or chunk_count < 0
    ):
        raise ValueError("source export manifest requires a non-negative chunk_count")
    license_manifest_sha256 = _validate_sha256(
        manifest.get("license_manifest_sha256"),
        field="source export license_manifest_sha256",
    )
    if license_manifest_sha256 is None:
        raise ValueError("source export manifest requires license_manifest_sha256")

    files = manifest.get("files")
    if not isinstance(files, dict):
        raise TypeError("source export manifest files must be an object")
    resolved_files: dict[str, Path] = {}
    file_rows: dict[str, int | None] = {}
    for name in ("materials", "papers", "license_manifest"):
        entry = files.get(name)
        if not isinstance(entry, dict):
            raise TypeError(f"source export manifest requires files.{name}")
        path = _resolve_manifest_member(
            manifest_path,
            entry.get("path"),
            field=f"files.{name}.path",
        )
        expected_hash = _validate_sha256(
            entry.get("sha256"), field=f"files.{name}.sha256"
        )
        if expected_hash is None or _sha256_file(path) != expected_hash:
            raise ValueError(f"source export file hash mismatch: {name}")
        expected_bytes = entry.get("bytes")
        if (
            isinstance(expected_bytes, bool)
            or not isinstance(expected_bytes, int)
            or expected_bytes < 0
            or path.stat().st_size != expected_bytes
        ):
            raise ValueError(f"source export file byte count mismatch: {name}")
        expected_rows = entry.get("rows")
        if name != "license_manifest":
            if (
                isinstance(expected_rows, bool)
                or not isinstance(expected_rows, int)
                or expected_rows < 0
                or _count_jsonl_objects(path) != expected_rows
            ):
                raise ValueError(f"source export file row count mismatch: {name}")
            file_rows[name] = expected_rows
        else:
            if expected_hash != license_manifest_sha256:
                raise ValueError("license manifest hash disagrees with its file entry")
            _load_json_object(path)
            file_rows[name] = None
        resolved_files[name] = path

    if len(set(resolved_files.values())) != len(resolved_files):
        raise ValueError("source export file entries must reference distinct files")

    existing_map_path: Path | None = None
    if "paper_work_map" in files:
        entry = files["paper_work_map"]
        if not isinstance(entry, dict):
            raise ValueError("files.paper_work_map must be an object")
        existing_map_path = _resolve_manifest_member(
            manifest_path,
            entry.get("path"),
            field="files.paper_work_map.path",
        )
        expected_hash = _validate_sha256(
            entry.get("sha256"), field="files.paper_work_map.sha256"
        )
        if expected_hash is None or _sha256_file(existing_map_path) != expected_hash:
            raise ValueError("source export file hash mismatch: paper_work_map")
        expected_bytes = entry.get("bytes")
        expected_rows = entry.get("rows")
        if (
            isinstance(expected_bytes, bool)
            or not isinstance(expected_bytes, int)
            or expected_bytes < 0
            or existing_map_path.stat().st_size != expected_bytes
        ):
            raise ValueError("source export file byte count mismatch: paper_work_map")
        if (
            isinstance(expected_rows, bool)
            or not isinstance(expected_rows, int)
            or expected_rows < 0
            or _count_jsonl_objects(existing_map_path) != expected_rows
        ):
            raise ValueError("source export file row count mismatch: paper_work_map")
        file_rows["paper_work_map"] = expected_rows

        paper_ids = {
            str(row.get("id") or row.get("paper_id") or "").strip()
            for row in load_jsonl(resolved_files["papers"])
        }
        map_paper_ids: set[str] = set()
        for row in load_jsonl(existing_map_path):
            paper_id = str(row.get("paper_id") or "").strip()
            if not paper_id or paper_id in map_paper_ids:
                raise ValueError(
                    "paper_work_map paper_id values must be non-empty and unique"
                )
            if paper_id not in paper_ids:
                raise ValueError(
                    f"paper_work_map references unknown paper_id {paper_id!r}"
                )
            map_paper_ids.add(paper_id)
        if existing_map_path in resolved_files.values():
            raise ValueError("source export file entries must reference distinct files")

    counts = manifest.get("counts")
    if not isinstance(counts, dict):
        raise TypeError("source export manifest counts must be an object")
    for name in ("materials", "papers"):
        if counts.get(name) != file_rows[name]:
            raise ValueError(f"source export top-level count mismatch: {name}")
    if counts.get("chunks") != chunk_count:
        raise ValueError("source export top-level count mismatch: chunks")
    if existing_map_path is not None and counts.get("paper_work_map") != file_rows.get(
        "paper_work_map"
    ):
        raise ValueError("source export top-level count mismatch: paper_work_map")

    return {
        "manifest": manifest,
        "manifest_path": manifest_path,
        "manifest_sha256": manifest_sha256,
        "materials_path": resolved_files["materials"],
        "papers_path": resolved_files["papers"],
        "existing_map_path": existing_map_path,
        "license_manifest_path": resolved_files["license_manifest"],
        "source_snapshot_id": snapshot_id,
        "dataset_version": dataset_version,
        "site_git_sha": site_git_sha,
        "database_watermark": database_watermark,
        "alembic_revision": alembic_revision.strip(),
        "chunk_count": chunk_count,
        "license_manifest_sha256": license_manifest_sha256,
    }


def _validate_input_output_paths(
    *,
    output_dir: Path,
    input_paths: Iterable[Path | None],
    output_names: Iterable[str],
) -> None:
    """Reject bundles that could overwrite one of their own source files."""
    inputs = [path.resolve() for path in input_paths if path is not None]
    targets = [(output_dir / name).resolve() for name in output_names]
    conflicts: set[Path] = set()
    for source in inputs:
        for target in targets:
            if source == target:
                conflicts.add(source)
                continue
            # ``resolve`` catches normal paths and symlinks.  ``samefile``
            # additionally catches an existing hard-link alias.
            if source.exists() and target.exists() and source.samefile(target):
                conflicts.add(source)
    if conflicts:
        rendered = ", ".join(str(path) for path in sorted(conflicts))
        raise ValueError(f"input path overlaps planned output: {rendered}")


def _verify_source_capture_identity(
    verified_source: dict[str, Any],
    *,
    plan: dict[str, Any],
    materials_path: Path,
    papers_path: Path,
    existing_map_path: Path | None,
    dataset_version: str,
    site_git_sha: str,
    database_watermark: str | None,
    chunk_count: int,
    license_manifest_sha256: str | None,
    source_alembic_revision: str | None,
    phase: str,
) -> None:
    """Bind every plan capture scalar/path to the authoritative export."""
    summary = plan.get("summary")
    if not isinstance(summary, dict):
        raise TypeError(f"plan summary is invalid during {phase}")
    try:
        plan_snapshot_id = uuid.UUID(str(summary.get("source_snapshot_id")))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"plan source_snapshot_id is invalid during {phase}") from exc

    expected_source_paths = {
        "materials_path": materials_path.resolve(),
        "papers_path": papers_path.resolve(),
        "existing_map_path": (
            existing_map_path.resolve() if existing_map_path is not None else None
        ),
    }
    for field, expected_path in expected_source_paths.items():
        if verified_source[field] != expected_path:
            raise ValueError(f"source export {field} disagrees during {phase}")

    scalar_bindings = {
        "source_snapshot_id": plan_snapshot_id,
        "dataset_version": dataset_version,
        "site_git_sha": site_git_sha,
        "database_watermark": database_watermark,
        "chunk_count": chunk_count,
        "alembic_revision": source_alembic_revision,
        "license_manifest_sha256": license_manifest_sha256,
    }
    for field, supplied_value in scalar_bindings.items():
        if verified_source[field] != supplied_value:
            raise ValueError(
                f"source export {field} disagrees with plan capture identity during {phase}"
            )


def _write_plan_artifacts_into_directory(
    plan: dict[str, Any],
    *,
    output_dir: Path,
    materials_path: Path,
    papers_path: Path,
    existing_map_path: Path | None,
    dataset_version: str,
    site_git_sha: str,
    database_watermark: str | None,
    chunk_count: int,
    license_manifest_sha256: str | None,
    source_export_manifest_path: Path | None = None,
    source_export_manifest_sha256: str | None = None,
    source_alembic_revision: str | None = None,
) -> str:
    """Write a deterministic review bundle and return its manifest hash."""
    dataset_version = _validate_dataset_version(dataset_version)
    site_git_sha = _validate_git_sha(site_git_sha)
    database_watermark = _validate_database_watermark(database_watermark)
    if (
        isinstance(chunk_count, bool)
        or not isinstance(chunk_count, int)
        or chunk_count < 0
    ):
        raise ValueError("chunk_count must be non-negative")
    license_manifest_sha256 = _validate_sha256(
        license_manifest_sha256,
        field="license_manifest_sha256",
    )
    source_export_manifest_sha256 = _validate_sha256(
        source_export_manifest_sha256,
        field="source_export_manifest_sha256",
    )
    if (source_export_manifest_path is None) != (source_export_manifest_sha256 is None):
        raise ValueError(
            "source export manifest path and SHA-256 must be provided together"
        )
    if source_alembic_revision is not None:
        if (
            not isinstance(source_alembic_revision, str)
            or not source_alembic_revision.strip()
        ):
            raise ValueError(
                "source_alembic_revision must be a non-empty string or omitted"
            )
        source_alembic_revision = source_alembic_revision.strip()
    row_files = (
        "works",
        "paper_work_map",
        "claims",
        "compositions",
        "failures",
        "warnings",
    )
    output_names = [
        *(f"{name}.jsonl" for name in row_files),
        "parity_report.json",
        "summary.json",
        "manifest.json",
        "manifest.sha256",
        "source_snapshots.jsonl",
    ]
    _validate_input_output_paths(
        output_dir=output_dir,
        input_paths=(
            materials_path,
            papers_path,
            existing_map_path,
            source_export_manifest_path,
        ),
        output_names=output_names,
    )
    if source_export_manifest_path is not None:
        verified_source = load_source_export_manifest(source_export_manifest_path)
        if verified_source["manifest_sha256"] != source_export_manifest_sha256:
            raise ValueError("source export manifest changed after initial validation")
        _verify_source_capture_identity(
            verified_source,
            plan=plan,
            materials_path=materials_path,
            papers_path=papers_path,
            existing_map_path=existing_map_path,
            dataset_version=dataset_version,
            site_git_sha=site_git_sha,
            database_watermark=database_watermark,
            chunk_count=chunk_count,
            license_manifest_sha256=license_manifest_sha256,
            source_alembic_revision=source_alembic_revision,
            phase="initial validation",
        )

    material_rows = load_jsonl(materials_path)
    paper_rows = load_jsonl(papers_path)
    existing_rows = (
        load_jsonl(existing_map_path) if existing_map_path is not None else []
    )
    parity_report = build_shadow_parity_report(
        material_rows,
        paper_rows,
        plan,
        existing_paper_work=existing_rows,
    )
    supplied_parity = plan.get("parity_report")
    if supplied_parity is not None and supplied_parity != parity_report:
        raise ValueError("source rows changed after the shadow parity report was built")

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, dict[str, Any]] = {}
    for name in row_files:
        path = output_dir / f"{name}.jsonl"
        write_jsonl(path, plan[name])
        outputs[path.name] = {
            "rows": len(plan[name]),
            "sha256": _sha256_file(path),
        }

    parity_path = output_dir / "parity_report.json"
    parity_path.write_text(
        json.dumps(parity_report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    outputs[parity_path.name] = {"sha256": _sha256_file(parity_path)}

    summary_payload = {
        **plan["summary"],
        "parity_gate_status": parity_report["gate_status"],
        "parity_gate_failures": len(parity_report["gate_failures"]),
    }
    summary_path = output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    outputs[summary_path.name] = {"sha256": _sha256_file(summary_path)}

    inputs: dict[str, dict[str, Any]] = {
        "materials": {
            "file_name": materials_path.name,
            "sha256": _sha256_file(materials_path),
        },
        "papers": {"file_name": papers_path.name, "sha256": _sha256_file(papers_path)},
    }
    if existing_map_path is not None:
        inputs["existing_paper_work"] = {
            "file_name": existing_map_path.name,
            "sha256": _sha256_file(existing_map_path),
        }
    if source_export_manifest_path is not None:
        # Re-run the complete bundle verifier after reading the source rows.
        # This closes the load/plan/write window: leaf files, license policy,
        # transaction metadata, and the manifest must still be the reviewed
        # capture immediately before the plan manifest is sealed.
        final_source = load_source_export_manifest(source_export_manifest_path)
        actual_export_manifest_hash = final_source["manifest_sha256"]
        if actual_export_manifest_hash != source_export_manifest_sha256:
            raise ValueError("source export manifest changed while building the plan")
        _verify_source_capture_identity(
            final_source,
            plan=plan,
            materials_path=materials_path,
            papers_path=papers_path,
            existing_map_path=existing_map_path,
            dataset_version=dataset_version,
            site_git_sha=site_git_sha,
            database_watermark=database_watermark,
            chunk_count=chunk_count,
            license_manifest_sha256=license_manifest_sha256,
            source_alembic_revision=source_alembic_revision,
            phase="final sealing",
        )
        inputs["source_export_manifest"] = {
            "file_name": source_export_manifest_path.name,
            "sha256": actual_export_manifest_hash,
        }

    manifest = {
        "schema_version": "sclib-ml-foundation-plan/v1",
        "source_snapshot_id": plan["summary"]["source_snapshot_id"],
        "dataset_version": dataset_version,
        "site_git_sha": site_git_sha,
        "database_watermark": database_watermark,
        "chunk_count": chunk_count,
        "claim_mapper_version": CLAIM_MAPPER_VERSION,
        "work_identity_version": WORK_IDENTITY_VERSION,
        "formula_parser_version": PARSER_VERSION,
        "license_manifest_sha256": license_manifest_sha256,
        "source_export_manifest_sha256": source_export_manifest_sha256,
        "source_alembic_revision": source_alembic_revision,
        "inputs": inputs,
        "outputs": outputs,
        "summary": summary_payload,
    }
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_bytes(manifest_bytes)
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    (output_dir / "manifest.sha256").write_text(
        f"{manifest_sha256}  manifest.json\n",
        encoding="utf-8",
    )

    source_snapshot = {
        "id": plan["summary"]["source_snapshot_id"],
        "dataset_version": dataset_version,
        "site_git_sha": site_git_sha,
        "database_watermark": database_watermark,
        "paper_count": plan["summary"]["papers"],
        "material_count": plan["summary"]["materials"],
        "chunk_count": chunk_count,
        "schema_version": "ml-foundation-v1",
        "manifest_sha256": manifest_sha256,
        "license_manifest_sha256": license_manifest_sha256,
        # The planner can prove only that a bundle is internally shaped.  A
        # source snapshot remains building until offline parity, license, and
        # post-load database verification have all passed.
        "status": "building",
        "metadata": {
            "planner": "plan_typed_claim_backfill.py",
            "manifest_file": "manifest.json",
            "failure_count": len(plan["failures"]),
            "parity_report_sha256": outputs["parity_report.json"]["sha256"],
            "parity_gate_status": parity_report["gate_status"],
            "parity_gate_failures": len(parity_report["gate_failures"]),
            "source_export_manifest_sha256": source_export_manifest_sha256,
            "source_alembic_revision": source_alembic_revision,
        },
    }
    write_jsonl(output_dir / "source_snapshots.jsonl", [source_snapshot])
    return manifest_sha256


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_plan_artifacts(
    plan: dict[str, Any],
    *,
    output_dir: Path,
    materials_path: Path,
    papers_path: Path,
    existing_map_path: Path | None,
    dataset_version: str,
    site_git_sha: str,
    database_watermark: str | None,
    chunk_count: int,
    license_manifest_sha256: str | None,
    source_export_manifest_path: Path | None = None,
    source_export_manifest_sha256: str | None = None,
    source_alembic_revision: str | None = None,
) -> str:
    """Atomically publish a private, review-only plan bundle."""
    supplied_output = output_dir.expanduser()
    if supplied_output.is_symlink():
        raise ValueError("output_dir must not be a symlink")
    final_dir = supplied_output.resolve(strict=False)
    if not final_dir.name or final_dir == final_dir.parent:
        raise ValueError("output_dir must name a dedicated plan directory")
    output_names = (
        "works.jsonl",
        "paper_work_map.jsonl",
        "claims.jsonl",
        "compositions.jsonl",
        "failures.jsonl",
        "warnings.jsonl",
        "parity_report.json",
        "summary.json",
        "manifest.json",
        "manifest.sha256",
        "source_snapshots.jsonl",
    )
    _validate_input_output_paths(
        output_dir=final_dir,
        input_paths=(
            materials_path,
            papers_path,
            existing_map_path,
            source_export_manifest_path,
        ),
        output_names=output_names,
    )
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    if final_dir.exists() or final_dir.is_symlink():
        raise FileExistsError(f"plan output directory already exists: {final_dir}")
    partial_dir = final_dir.parent / f".{final_dir.name}.partial-{uuid.uuid4().hex}"
    partial_dir.mkdir(mode=0o700)
    try:
        manifest_sha256 = _write_plan_artifacts_into_directory(
            plan,
            output_dir=partial_dir,
            materials_path=materials_path,
            papers_path=papers_path,
            existing_map_path=existing_map_path,
            dataset_version=dataset_version,
            site_git_sha=site_git_sha,
            database_watermark=database_watermark,
            chunk_count=chunk_count,
            license_manifest_sha256=license_manifest_sha256,
            source_export_manifest_path=source_export_manifest_path,
            source_export_manifest_sha256=source_export_manifest_sha256,
            source_alembic_revision=source_alembic_revision,
        )
        for artifact in partial_dir.iterdir():
            if not artifact.is_file() or artifact.is_symlink():
                raise ValueError("plan bundle contains a non-regular artifact")
            os.chmod(artifact, 0o600)
            with artifact.open("rb") as handle:
                os.fsync(handle.fileno())
        _fsync_directory(partial_dir)
        os.replace(partial_dir, final_dir)
        _fsync_directory(final_dir.parent)
        return manifest_sha256
    except BaseException:
        if partial_dir.exists() and partial_dir.parent == final_dir.parent:
            shutil.rmtree(partial_dir)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-export-manifest",
        type=Path,
        help=(
            "validated sclib-source-export/v1 manifest; mutually exclusive "
            "with all manual source identity arguments"
        ),
    )
    parser.add_argument("--materials-jsonl", type=Path)
    parser.add_argument("--papers-jsonl", type=Path)
    parser.add_argument("--existing-paper-work-jsonl", type=Path)
    parser.add_argument("--source-snapshot-id", type=uuid.UUID)
    parser.add_argument("--dataset-version")
    parser.add_argument("--site-git-sha")
    parser.add_argument("--database-watermark")
    parser.add_argument("--chunk-count", type=int)
    parser.add_argument("--license-manifest-sha256")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="write reviewable JSONL plan files; still performs no database writes",
    )
    args = parser.parse_args()

    manual_values = {
        "--materials-jsonl": args.materials_jsonl,
        "--papers-jsonl": args.papers_jsonl,
        "--existing-paper-work-jsonl": args.existing_paper_work_jsonl,
        "--source-snapshot-id": args.source_snapshot_id,
        "--dataset-version": args.dataset_version,
        "--site-git-sha": args.site_git_sha,
        "--database-watermark": args.database_watermark,
        "--chunk-count": args.chunk_count,
        "--license-manifest-sha256": args.license_manifest_sha256,
    }
    source_export: dict[str, Any] | None = None
    if args.source_export_manifest is not None:
        mixed = [name for name, value in manual_values.items() if value is not None]
        if mixed:
            parser.error(
                "--source-export-manifest cannot be combined with " + ", ".join(mixed)
            )
        try:
            source_export = load_source_export_manifest(args.source_export_manifest)
        except (OSError, TypeError, ValueError) as exc:
            parser.error(str(exc))
        materials_path = source_export["materials_path"]
        papers_path = source_export["papers_path"]
        existing_map_path = source_export["existing_map_path"]
        source_snapshot_id = source_export["source_snapshot_id"]
        dataset_version = source_export["dataset_version"]
        site_git_sha = source_export["site_git_sha"]
        database_watermark = source_export["database_watermark"]
        chunk_count = source_export["chunk_count"]
        license_hash = source_export["license_manifest_sha256"]
    else:
        required_manual = (
            "--materials-jsonl",
            "--papers-jsonl",
            "--source-snapshot-id",
            "--dataset-version",
            "--site-git-sha",
            "--chunk-count",
        )
        missing = [name for name in required_manual if manual_values[name] is None]
        if missing:
            parser.error("manual source mode requires " + ", ".join(missing))
        materials_path = args.materials_jsonl
        papers_path = args.papers_jsonl
        existing_map_path = args.existing_paper_work_jsonl
        source_snapshot_id = args.source_snapshot_id
        # Required-manual checks above narrow these values at runtime.
        assert materials_path is not None
        assert papers_path is not None
        assert source_snapshot_id is not None
        assert args.dataset_version is not None
        assert args.site_git_sha is not None
        assert args.chunk_count is not None
        try:
            dataset_version = _validate_dataset_version(args.dataset_version)
            site_git_sha = _validate_git_sha(args.site_git_sha)
            database_watermark = _validate_database_watermark(args.database_watermark)
            if args.chunk_count < 0:
                raise ValueError("--chunk-count must be non-negative")
            chunk_count = args.chunk_count
            license_hash = _validate_sha256(
                args.license_manifest_sha256,
                field="--license-manifest-sha256",
            )
        except ValueError as exc:
            parser.error(str(exc))

    materials = load_jsonl(materials_path)
    papers = load_jsonl(papers_path)
    existing_map = load_jsonl(existing_map_path) if existing_map_path else []
    plan = build_backfill_plan(
        materials,
        papers,
        source_snapshot_id=source_snapshot_id,
        existing_paper_work=existing_map,
    )
    plan["parity_report"] = build_shadow_parity_report(
        materials,
        papers,
        plan,
        existing_paper_work=existing_map,
    )
    print(json.dumps(plan["summary"], indent=2, sort_keys=True))
    print(
        "Shadow parity gate: "
        f"{plan['parity_report']['gate_status']} "
        f"({len(plan['parity_report']['gate_failures'])} failure groups)"
    )
    print("DRY-RUN ONLY: no database connection or migration was attempted.")

    if args.output_dir:
        manifest_hash = write_plan_artifacts(
            plan,
            output_dir=args.output_dir,
            materials_path=materials_path,
            papers_path=papers_path,
            existing_map_path=existing_map_path,
            dataset_version=dataset_version,
            site_git_sha=site_git_sha,
            database_watermark=database_watermark,
            chunk_count=chunk_count,
            license_manifest_sha256=license_hash,
            source_export_manifest_path=(
                source_export["manifest_path"] if source_export else None
            ),
            source_export_manifest_sha256=(
                source_export["manifest_sha256"] if source_export else None
            ),
            source_alembic_revision=(
                source_export["alembic_revision"] if source_export else None
            ),
        )
        print(f"Plan written to {args.output_dir} (manifest {manifest_hash})")
    return (
        0
        if not plan["failures"] and plan["parity_report"]["gate_status"] == "pass"
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
