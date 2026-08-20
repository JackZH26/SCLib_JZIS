"""Offline Phase-1 work/claim backfill planner (never connects to a DB).

Input files are JSONL snapshots.  Each materials row must contain ``id`` and
``records``; papers rows use the existing papers-table shape.  Without
``--output-dir`` the command only validates and prints counts.  With an output
directory it writes proposed JSONL payloads for review, still with zero DB
writes.

Example::

    ingestion/.venv/bin/python scripts/plan_typed_claim_backfill.py \
      --materials-jsonl /tmp/materials.jsonl \
      --papers-jsonl /tmp/papers.jsonl \
      --source-snapshot-id 11111111-1111-4111-8111-111111111111 \
      --dataset-version v2026.08.20 \
      --site-git-sha d26fc098565492b78b416fb30b6b1ec7087b24c7 \
      --chunk-count 1116128 \
      --output-dir /tmp/sclib-phase1-plan

The planner requires Python 3.11 or newer.  The command above deliberately
uses the ingestion project's managed virtual environment instead of whichever
system ``python`` happens to be on ``PATH``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "ingestion"))

from ingestion.claims import (
    CLAIM_MAPPER_VERSION,
    WORK_IDENTITY_VERSION,
    map_record_to_claim,
    plan_work_identities,
)
from ingestion.extract.formula_enrichment import PARSER_VERSION, enrich_formula


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
            not isinstance(relation_type, str) or relation_type not in valid_relation_types
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
    work_by_paper = {row["paper_id"]: row["work_id"] for row in work_plan["paper_work_map"]}

    claims: list[dict[str, Any]] = []
    compositions: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    seen_source_keys: set[tuple[str, str]] = set()
    exact_duplicates = 0
    input_records = 0
    seen_material_ids: set[str] = set()
    planner_warnings: list[dict[str, Any]] = []

    for material in material_rows:
        material_id = str(material.get("id") or "").strip()
        if not material_id:
            failures.append({"material_id": None, "code": "missing_material_id"})
            continue
        if material_id in seen_material_ids:
            failures.append({"material_id": material_id, "code": "duplicate_material_id"})
            continue
        seen_material_ids.add(material_id)

        records = material.get("records")
        if records is None:
            records = []
        formula = material.get("formula") or material.get("formula_normalized") or ""
        enrichment = enrich_formula(formula)
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
                failures.append({"material_id": material_id, "code": "invalid_records_json"})
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
            "exact_compositions": sum(row["composition_status"] == "exact" for row in compositions),
            "exact_duplicate_records": exact_duplicates,
            "failures": len(failures),
        },
    }


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=_json_default) + "\n")


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
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
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
    if len(normalized) != 40 or any(char not in "0123456789abcdef" for char in normalized):
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
) -> str:
    """Write a deterministic review bundle and return its manifest hash."""
    dataset_version = _validate_dataset_version(dataset_version)
    site_git_sha = _validate_git_sha(site_git_sha)
    database_watermark = _validate_database_watermark(database_watermark)
    if chunk_count < 0:
        raise ValueError("chunk_count must be non-negative")
    license_manifest_sha256 = _validate_sha256(
        license_manifest_sha256,
        field="license_manifest_sha256",
    )
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
        "summary.json",
        "manifest.json",
        "manifest.sha256",
        "source_snapshots.jsonl",
    ]
    _validate_input_output_paths(
        output_dir=output_dir,
        input_paths=(materials_path, papers_path, existing_map_path),
        output_names=output_names,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, dict[str, Any]] = {}
    for name in row_files:
        path = output_dir / f"{name}.jsonl"
        write_jsonl(path, plan[name])
        outputs[path.name] = {
            "rows": len(plan[name]),
            "sha256": _sha256_file(path),
        }

    summary_path = output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(plan["summary"], indent=2, sort_keys=True) + "\n",
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
        "inputs": inputs,
        "outputs": outputs,
        "summary": plan["summary"],
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
        "status": "validated" if not plan["failures"] else "building",
        "metadata": {
            "planner": "plan_typed_claim_backfill.py",
            "manifest_file": "manifest.json",
            "failure_count": len(plan["failures"]),
        },
    }
    write_jsonl(output_dir / "source_snapshots.jsonl", [source_snapshot])
    return manifest_sha256


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--materials-jsonl", required=True, type=Path)
    parser.add_argument("--papers-jsonl", required=True, type=Path)
    parser.add_argument("--existing-paper-work-jsonl", type=Path)
    parser.add_argument("--source-snapshot-id", required=True, type=uuid.UUID)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--site-git-sha", required=True)
    parser.add_argument("--database-watermark")
    parser.add_argument("--chunk-count", required=True, type=int)
    parser.add_argument("--license-manifest-sha256")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="write reviewable JSONL plan files; still performs no database writes",
    )
    args = parser.parse_args()

    materials = load_jsonl(args.materials_jsonl)
    papers = load_jsonl(args.papers_jsonl)
    existing_map = (
        load_jsonl(args.existing_paper_work_jsonl) if args.existing_paper_work_jsonl else []
    )
    try:
        dataset_version = _validate_dataset_version(args.dataset_version)
        site_git_sha = _validate_git_sha(args.site_git_sha)
        database_watermark = _validate_database_watermark(args.database_watermark)
        if args.chunk_count < 0:
            raise ValueError("--chunk-count must be non-negative")
        license_hash = _validate_sha256(
            args.license_manifest_sha256,
            field="--license-manifest-sha256",
        )
    except ValueError as exc:
        parser.error(str(exc))
    plan = build_backfill_plan(
        materials,
        papers,
        source_snapshot_id=args.source_snapshot_id,
        existing_paper_work=existing_map,
    )
    print(json.dumps(plan["summary"], indent=2, sort_keys=True))
    print("DRY-RUN ONLY: no database connection or migration was attempted.")

    if args.output_dir:
        manifest_hash = write_plan_artifacts(
            plan,
            output_dir=args.output_dir,
            materials_path=args.materials_jsonl,
            papers_path=args.papers_jsonl,
            existing_map_path=args.existing_paper_work_jsonl,
            dataset_version=dataset_version,
            site_git_sha=site_git_sha,
            database_watermark=database_watermark,
            chunk_count=args.chunk_count,
            license_manifest_sha256=license_hash,
        )
        print(f"Plan written to {args.output_dir} (manifest {manifest_hash})")
    return 0 if not plan["failures"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
