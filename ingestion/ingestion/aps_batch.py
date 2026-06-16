"""Batch runner for APS DOI manifests with checkpoint/resume.

Manifest formats:

* text: one DOI per line, comments beginning with "#"
* CSV/TSV: a ``doi`` column if present, otherwise the first column
* JSON: a list of DOI strings, a list of objects, or {"dois": [...]}
* JSONL: one DOI string or object with a ``doi`` field per line

Checkpoint is append-only JSONL. The latest record per DOI is used on
resume, so a crash after a ``started`` row simply leaves that DOI pending.
Only full successful runs are marked ``ok``; dry-runs and skip-vector
smoke runs do not block a later full ingest.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ingestion.aps_pipeline import _normalize_doi, process_aps_paper
from ingestion.collect.aps_harvest import ApsClient
from ingestion.config import get_settings
from ingestion.index.indexer import dispose

log = logging.getLogger("ingestion.aps_batch")

_DOI_RE = re.compile(r"(?:https?://doi\.org/|doi:)?10\.1103/[^\s,;\"']+", re.I)
_FULL_OK_STATUSES = {"ok"}
_RETRYABLE_PRIOR_STATUSES = {
    "started",
    "dry_run_ok",
    "dry_run_error",
    "ok_no_vector",
    "ok_no_ner",
}


@dataclass(slots=True)
class BatchSummary:
    manifest_count: int
    selected_count: int
    ok: int = 0
    error: int = 0
    skipped: int = 0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_doi(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s.startswith("#"):
        return None
    m = _DOI_RE.search(s)
    doi = m.group(0) if m else s
    doi = doi.strip().rstrip(".,;)]}")
    if not doi:
        return None
    doi = _normalize_doi(doi)
    return doi if doi.lower().startswith("10.1103/") else None


def _dedupe(dois: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for doi in dois:
        key = doi.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(doi)
    return out


def load_manifest(path: Path) -> list[str]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return _dedupe(_dois_from_json(json.loads(path.read_text())))
    if suffix == ".jsonl":
        return _dedupe(_dois_from_jsonl(path))
    if suffix in {".csv", ".tsv"}:
        return _dedupe(_dois_from_delimited(path, delimiter="\t" if suffix == ".tsv" else ","))
    return _dedupe(_dois_from_text(path))


def _dois_from_json(obj: Any) -> Iterable[str]:
    if isinstance(obj, dict):
        obj = obj.get("dois") or obj.get("items") or obj.get("records") or []
    if isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict):
                doi = _clean_doi(
                    item.get("doi") or item.get("DOI") or item.get("aps_doi")
                    or item.get("article_doi")
                )
            else:
                doi = _clean_doi(item)
            if doi:
                yield doi


def _dois_from_jsonl(path: Path) -> Iterable[str]:
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            doi = _clean_doi(line)
        else:
            doi = next(iter(_dois_from_json(obj if isinstance(obj, list) else [obj])), None)
        if doi:
            yield doi


def _dois_from_delimited(path: Path, *, delimiter: str) -> Iterable[str]:
    with path.open(newline="") as f:
        sample = f.read(2048)
        f.seek(0)
        has_header = csv.Sniffer().has_header(sample) if sample.strip() else False
        if has_header:
            reader = csv.DictReader(f, delimiter=delimiter)
            for row in reader:
                doi = _clean_doi(
                    row.get("doi") or row.get("DOI") or row.get("aps_doi")
                    or row.get("article_doi") or next(iter(row.values()), "")
                )
                if doi:
                    yield doi
        else:
            for row in csv.reader(f, delimiter=delimiter):
                if row and (doi := _clean_doi(row[0])):
                    yield doi


def _dois_from_text(path: Path) -> Iterable[str]:
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        for m in _DOI_RE.finditer(line):
            if doi := _clean_doi(m.group(0)):
                yield doi
        if not _DOI_RE.search(line):
            if doi := _clean_doi(line):
                yield doi


def default_checkpoint_path(manifest: Path) -> Path:
    return manifest.with_name(f"{manifest.stem}.checkpoint.jsonl")


def load_checkpoint(path: Path) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return latest
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        doi = _clean_doi(rec.get("doi"))
        if doi:
            latest[doi.lower()] = rec
    return latest


def append_checkpoint(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
        f.write("\n")
        f.flush()


def select_pending(
    dois: list[str],
    checkpoint: dict[str, dict[str, Any]],
    *,
    limit: int | None = None,
    retry_failed: bool = False,
) -> tuple[list[str], int]:
    selected: list[str] = []
    skipped = 0
    for doi in dois:
        rec = checkpoint.get(doi.lower())
        status = str((rec or {}).get("status") or "")
        if status in _FULL_OK_STATUSES:
            skipped += 1
            continue
        if status and status not in _RETRYABLE_PRIOR_STATUSES and not retry_failed:
            skipped += 1
            continue
        selected.append(doi)
        if limit is not None and len(selected) >= limit:
            break
    return selected, skipped


def _final_status(result: dict[str, Any], *, dry_run: bool, skip_vector_search: bool,
                  skip_ner: bool) -> str:
    if not result.get("ok"):
        return "dry_run_error" if dry_run else "error"
    if dry_run:
        return "dry_run_ok"
    if skip_ner:
        return "ok_no_ner"
    if skip_vector_search:
        return "ok_no_vector"
    return "ok"


async def run_batch(
    manifest: Path,
    checkpoint: Path,
    *,
    limit: int | None = None,
    retry_failed: bool = False,
    dry_run: bool = False,
    skip_vector_search: bool = False,
    skip_ner: bool = False,
    stop_on_error: bool = False,
) -> BatchSummary:
    dois = load_manifest(manifest)
    checkpoint_state = load_checkpoint(checkpoint)
    selected, skipped = select_pending(
        dois, checkpoint_state, limit=limit, retry_failed=retry_failed,
    )
    summary = BatchSummary(
        manifest_count=len(dois),
        selected_count=len(selected),
        skipped=skipped,
    )
    settings = get_settings()
    log.info(
        "APS batch manifest=%s checkpoint=%s model=%s gemini_location=%s "
        "enterprise=%s selected=%d skipped=%d total=%d",
        manifest, checkpoint, settings.gemini_model, settings.gemini_location,
        settings.gemini_use_enterprise, len(selected), skipped, len(dois),
    )
    if not selected:
        return summary

    try:
        async with ApsClient() as client:
            for pos, doi in enumerate(selected, start=1):
                append_checkpoint(checkpoint, {
                    "doi": doi,
                    "status": "started",
                    "started_at": _utc_now(),
                    "position": pos,
                    "selected_count": len(selected),
                    "model": settings.gemini_model,
                    "dry_run": dry_run,
                    "skip_vector_search": skip_vector_search,
                    "skip_ner": skip_ner,
                })
                log.info("APS batch %d/%d start %s", pos, len(selected), doi)
                result = await process_aps_paper(
                    client,
                    doi,
                    skip_vector_search=skip_vector_search,
                    skip_ner=skip_ner,
                    dry_run=dry_run,
                )
                status = _final_status(
                    result,
                    dry_run=dry_run,
                    skip_vector_search=skip_vector_search,
                    skip_ner=skip_ner,
                )
                if result.get("ok"):
                    summary.ok += 1
                else:
                    summary.error += 1
                append_checkpoint(checkpoint, {
                    "doi": doi,
                    "status": status,
                    "finished_at": _utc_now(),
                    "position": pos,
                    "selected_count": len(selected),
                    "model": settings.gemini_model,
                    "dry_run": dry_run,
                    "skip_vector_search": skip_vector_search,
                    "skip_ner": skip_ner,
                    "result": result,
                    "error": result.get("error"),
                })
                log.info("APS batch %d/%d %s %s", pos, len(selected), status, doi)
                if stop_on_error and not result.get("ok"):
                    break
    finally:
        await dispose()

    return summary


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path,
                        help="APS DOI manifest: txt/csv/tsv/json/jsonl")
    parser.add_argument("--checkpoint", type=Path,
                        help="Append-only JSONL checkpoint. Defaults beside manifest.")
    parser.add_argument("--limit", "--batch-size", dest="limit", type=int,
                        help="Maximum pending DOIs to process in this run.")
    parser.add_argument("--retry-failed", action="store_true",
                        help="Retry DOIs whose latest checkpoint status is error-like.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Harvest+parse+NER+delete but no DB/VS writes.")
    parser.add_argument("--skip-vector-search", action="store_true",
                        help="Persist paper/chunks but skip embedding + Vertex VS.")
    parser.add_argument("--skip-ner", action="store_true",
                        help="Skip Gemini material NER.")
    parser.add_argument("--stop-on-error", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )
    checkpoint = args.checkpoint or default_checkpoint_path(args.manifest)
    summary = asyncio.run(run_batch(
        args.manifest,
        checkpoint,
        limit=args.limit,
        retry_failed=args.retry_failed,
        dry_run=args.dry_run,
        skip_vector_search=args.skip_vector_search,
        skip_ner=args.skip_ner,
        stop_on_error=args.stop_on_error,
    ))
    log.info(
        "APS batch done: selected=%d ok=%d error=%d skipped=%d manifest=%d",
        summary.selected_count, summary.ok, summary.error, summary.skipped,
        summary.manifest_count,
    )
    return 0 if summary.error == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
