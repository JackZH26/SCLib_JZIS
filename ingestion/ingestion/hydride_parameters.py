"""Independent hydride parameter NER runner.

This job enriches hydrogen-rich superconductors with per-condition
Tc / pressure / lambda / mu* / omega_log rows in
``hydride_tc_parameters``. It does not rewrite ``papers.materials_extracted``
and does not rerun the generic materials aggregator.

Typical calibration run on VPS2::

    python -m ingestion.hydride_parameters --source all --limit 50 \\
      --checkpoint /opt/sclib_aps_manifests/hydride_params_50.jsonl

APS note: APS full text is fetched transiently, parsed in RAM, used for
NER, and deleted immediately via ``TempBagit``. A ``tdm_audit_log`` row is
written for non-dry runs as a deletion proof. The hydride parameter table
stores only derived structured facts and provenance metadata.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import Text, cast, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ingestion.aps_storage import TdmAudit, TempBagit, write_audit_log
from ingestion.collect.aps_harvest import ApsClient
from ingestion.extract.hydride_ner import extract_hydride_parameters
from ingestion.index.indexer import (
    _session_factory,
    chunks_table,
    dispose,
    hydride_tc_parameters_table,
    materials_table,
    papers_table,
)
from ingestion.models import ApsArticleMeta, PaperMetadata, ParsedPaper, Section
from ingestion.parse.aps_xml import parse_bagit_payload

log = logging.getLogger("sclib.hydride_parameters")

_HYDRIDE_RE = (
    r"hydride|superhydride|hydrogen-rich|hydrogen rich|clathrate hydride|"
    r"sulfur hydride|lanthanum hydride|yttrium hydride|"
    r"\bH[0-9]{1,3}[A-Z][a-z]?\b|\bD[0-9]{1,3}[A-Z][a-z]?\b|"
    r"\b[A-Z][a-z]?H[0-9]{1,3}\b"
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _candidate_rows(
    session: Any,
    *,
    source: str,
    limit: int | None,
    manifest: Path | None,
) -> list[dict[str, Any]]:
    cols = [
        papers_table.c.id,
        papers_table.c.source,
        papers_table.c.arxiv_id,
        papers_table.c.doi,
        papers_table.c.title,
        papers_table.c.authors,
        papers_table.c.abstract,
        papers_table.c.date_submitted,
        papers_table.c.date_published,
        papers_table.c.journal,
        papers_table.c.journal_abbrev,
        papers_table.c.publication_ref,
        papers_table.c.categories,
        papers_table.c.materials_extracted,
    ]
    stmt = select(*cols)

    if manifest is not None:
        ids, dois = _read_manifest(manifest)
        if ids or dois:
            stmt = stmt.where(or_(papers_table.c.id.in_(ids), papers_table.c.doi.in_(dois)))
        else:
            return []
    else:
        haystack = (
            papers_table.c.title.op("~*")(_HYDRIDE_RE)
            | papers_table.c.abstract.op("~*")(_HYDRIDE_RE)
            | cast(papers_table.c.materials_extracted, Text).ilike("%hydride%")
        )
        stmt = stmt.where(haystack)

    if source != "all":
        stmt = stmt.where(papers_table.c.source == source)

    stmt = stmt.order_by(
        func.coalesce(
            papers_table.c.date_published,
            papers_table.c.date_submitted,
        ).desc().nulls_last(),
        papers_table.c.id,
    )
    if limit is not None:
        stmt = stmt.limit(limit)

    rows = (await session.execute(stmt)).mappings().all()
    return [dict(r) for r in rows]


def _read_manifest(path: Path) -> tuple[list[str], list[str]]:
    ids: list[str] = []
    dois: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        if raw.startswith("{"):
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            raw = str(data.get("paper_id") or data.get("id") or data.get("doi") or "").strip()
            if not raw:
                continue
        if raw.startswith(("arxiv:", "aps:", "doi:")):
            ids.append(raw)
            if raw.startswith("doi:"):
                dois.append(raw.removeprefix("doi:"))
        elif raw.startswith("10."):
            dois.append(raw)
        elif re.match(r"^(?:[a-z-]+/)?\d{4}\.\d{4,5}", raw):
            ids.append(f"arxiv:{raw}")
        else:
            ids.append(raw)
    return ids, dois


def _load_seen(path: Path | None, *, retry_failed: bool) -> set[str]:
    if path is None or not path.exists():
        return set()
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        paper_id = event.get("paper_id")
        if not isinstance(paper_id, str):
            continue
        if retry_failed:
            if event.get("ok") is True:
                seen.add(paper_id)
        else:
            seen.add(paper_id)
    return seen


def _append_checkpoint(path: Path | None, event: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def _ensure_checkpoint_writable(path: Path | None) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8"):
        pass


async def _rebuild_parsed_from_chunks(session: Any, row: dict[str, Any]) -> ParsedPaper:
    chunk_rows = (await session.execute(
        select(chunks_table.c.section, chunks_table.c.chunk_index, chunks_table.c.text)
        .where(chunks_table.c.paper_id == row["id"])
        .order_by(chunks_table.c.section, chunks_table.c.chunk_index)
    )).all()
    sections_by_name: dict[str, list[str]] = defaultdict(list)
    for sec_name, _idx, text in chunk_rows:
        sections_by_name[sec_name or "Body"].append(text)
    sections = [
        Section(name=name, text="\n".join(parts))
        for name, parts in sections_by_name.items()
    ]
    arxiv_id = row.get("arxiv_id") or str(row["id"]).removeprefix("arxiv:")
    meta = PaperMetadata(
        arxiv_id=arxiv_id,
        title=row.get("title") or "",
        authors=list(row.get("authors") or []),
        abstract=row.get("abstract") or "",
        date_submitted=row.get("date_submitted"),
        categories=list(row.get("categories") or []),
        primary_category=None,
        doi=row.get("doi"),
    )
    return ParsedPaper(meta=meta, sections=sections, has_latex_source=False)


def _aps_meta_from_row(row: dict[str, Any]) -> ApsArticleMeta:
    ref = row.get("publication_ref") or {}
    return ApsArticleMeta(
        doi=row["doi"],
        title=row.get("title") or "",
        authors=list(row.get("authors") or []),
        abstract=row.get("abstract") or "",
        journal=row.get("journal"),
        journal_abbrev=row.get("journal_abbrev"),
        volume=ref.get("volume"),
        issue=ref.get("issue"),
        article_id=ref.get("article_id"),
        page=ref.get("page"),
        date_published=row.get("date_published"),
        categories=list(row.get("categories") or []),
    )


async def _extract_aps_records(
    client: ApsClient,
    row: dict[str, Any],
    *,
    dry_run: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    doi = row.get("doi")
    if not doi:
        return [], {"error": "missing DOI"}

    meta = _aps_meta_from_row(row)
    audit = TdmAudit(doi=doi, paper_id=row["id"], harvested_at=_now())
    work: TempBagit | None = None
    result: dict[str, Any] = {}
    try:
        with TempBagit(meta.doi_slug) as work:
            zip_bytes = await client.download_bagit(doi)
            work.extract(zip_bytes)
            payload = parse_bagit_payload(work.root, meta)
            result["parser_mode"] = payload.parser_mode
            result["text_source"] = payload.source_path.name
            records = await asyncio.to_thread(extract_hydride_parameters, payload.parsed)
            audit.processed_at = _now()
            audit.ner_record_count = len(records)
        audit.status = "deleted"
        if work is not None:
            audit.from_temp(work)
            result["deletion_confirmed"] = work.deleted
        if not dry_run:
            await write_audit_log(audit)
        return records, result
    except Exception as e:  # noqa: BLE001
        audit.status = "error"
        audit.error = str(e)[:1000]
        audit.processed_at = audit.processed_at or _now()
        if work is not None:
            audit.from_temp(work)
        if not dry_run:
            try:
                await write_audit_log(audit)
            except Exception as audit_error:  # noqa: BLE001
                log.error("%s: failed to write APS TDM audit: %s", doi, audit_error)
        raise


async def _material_id_for(session: Any, cache: dict[str, str | None], normalized: str) -> str | None:
    if normalized in cache:
        return cache[normalized]
    row = (await session.execute(
        select(materials_table.c.id)
        .where(materials_table.c.formula_normalized == normalized)
        .order_by(materials_table.c.id)
        .limit(1)
    )).first()
    cache[normalized] = row[0] if row else None
    return cache[normalized]


def _record_key(paper_id: str, record: dict[str, Any]) -> str:
    parts = [
        paper_id,
        str(record.get("formula_normalized") or ""),
        _fmt(record.get("tc_kelvin")),
        _fmt(record.get("pressure_gpa")),
        _fmt(record.get("lambda_eph")),
        _fmt(record.get("mu_star")),
        _fmt(record.get("omega_log_k")),
        str(record.get("method") or ""),
    ]
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
    return f"hydride:{digest}"


def _fmt(value: Any) -> str:
    return f"{float(value):.5g}" if isinstance(value, (int, float)) else ""


async def _upsert_records(
    session: Any,
    row: dict[str, Any],
    records: list[dict[str, Any]],
    material_cache: dict[str, str | None],
) -> int:
    if not records:
        return 0
    year = None
    date_value = row.get("date_published") or row.get("date_submitted")
    if date_value is not None:
        year = date_value.year

    values: list[dict[str, Any]] = []
    for rec in records:
        normalized = rec["formula_normalized"]
        values.append({
            **rec,
            "record_key": _record_key(row["id"], rec),
            "material_id": await _material_id_for(session, material_cache, normalized),
            "paper_id": row["id"],
            "source": row["source"],
            "doi": row.get("doi"),
            "arxiv_id": row.get("arxiv_id"),
            "year": year,
        })

    values = _dedupe_upsert_values(values)
    if not values:
        return 0

    stmt = pg_insert(hydride_tc_parameters_table).values(values)
    update_cols = {
        c.name: stmt.excluded[c.name]
        for c in hydride_tc_parameters_table.c
        if c.name not in {"id", "record_key", "created_at"}
    }
    update_cols["updated_at"] = func.now()
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[hydride_tc_parameters_table.c.record_key],
            set_=update_cols,
        )
    )
    await session.commit()
    return len(values)


def _dedupe_upsert_values(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for value in values:
        key = value["record_key"]
        existing = deduped.get(key)
        if existing is None or _confidence_score(value) > _confidence_score(existing):
            deduped[key] = value
    if len(deduped) < len(values):
        log.info(
            "deduped %d duplicate hydride records before upsert",
            len(values) - len(deduped),
        )
    return list(deduped.values())


def _confidence_score(value: dict[str, Any]) -> float:
    confidence = value.get("confidence")
    return float(confidence) if isinstance(confidence, (int, float)) else -1.0


async def _process_row(
    session: Any,
    row: dict[str, Any],
    *,
    aps_client: ApsClient | None,
    dry_run: bool,
    material_cache: dict[str, str | None],
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "ts": _now().isoformat(),
        "paper_id": row["id"],
        "source": row["source"],
        "doi": row.get("doi"),
        "ok": False,
        "dry_run": dry_run,
    }
    try:
        if row["source"] == "aps":
            if aps_client is None:
                raise RuntimeError("APS source selected but ApsClient is unavailable")
            records, extra = await _extract_aps_records(aps_client, row, dry_run=dry_run)
            event.update(extra)
        else:
            parsed = await _rebuild_parsed_from_chunks(session, row)
            records = await asyncio.to_thread(extract_hydride_parameters, parsed)

        event["n_records"] = len(records)
        event["n_flagged_records"] = sum(1 for r in records if r.get("validation_flags"))
        if dry_run:
            event["persisted"] = 0
        else:
            event["persisted"] = await _upsert_records(session, row, records, material_cache)
        event["ok"] = True
    except Exception as e:  # noqa: BLE001
        await session.rollback()
        event["error"] = str(e)
        log.exception("%s: hydride parameter NER failed", row["id"])
    return event


async def main_async(args: argparse.Namespace) -> int:
    checkpoint = Path(args.checkpoint) if args.checkpoint else None
    manifest = Path(args.manifest) if args.manifest else None
    _ensure_checkpoint_writable(checkpoint)
    seen = _load_seen(checkpoint, retry_failed=args.retry_failed)
    material_cache: dict[str, str | None] = {}

    Session = _session_factory()
    async with Session() as session:
        candidates = await _candidate_rows(
            session,
            source=args.source,
            limit=args.limit,
            manifest=manifest,
        )
        candidates = [r for r in candidates if r["id"] not in seen]
        log.info("hydride parameter candidates: %d", len(candidates))

        aps_needed = any(r["source"] == "aps" for r in candidates)
        aps_client_cm = ApsClient() if aps_needed else None
        if aps_client_cm is None:
            aps_client = None
            for row in candidates:
                event = await _process_row(
                    session,
                    row,
                    aps_client=aps_client,
                    dry_run=args.dry_run,
                    material_cache=material_cache,
                )
                _append_checkpoint(checkpoint, event)
                _log_event(event)
        else:
            async with aps_client_cm as aps_client:
                for row in candidates:
                    event = await _process_row(
                        session,
                        row,
                        aps_client=aps_client,
                        dry_run=args.dry_run,
                        material_cache=material_cache,
                    )
                    _append_checkpoint(checkpoint, event)
                    _log_event(event)

    await dispose()
    return 0


def _log_event(event: dict[str, Any]) -> None:
    if event.get("ok"):
        log.info(
            "OK %s records=%s persisted=%s flags=%s",
            event["paper_id"],
            event.get("n_records"),
            event.get("persisted"),
            event.get("n_flagged_records"),
        )
    else:
        log.error("ERR %s %s", event["paper_id"], event.get("error"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["all", "aps", "arxiv"], default="all")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--manifest", help="Optional paper_id/DOI manifest, one per line or JSONL")
    parser.add_argument(
        "--checkpoint",
        default="hydride_parameters_checkpoint.jsonl",
        help="JSONL checkpoint path. Use an absolute path on VPS2.",
    )
    parser.add_argument("--retry-failed", action="store_true",
                        help="Resume by skipping only prior OK rows, not prior errors")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run NER and checkpoint, but do not write DB/audit rows")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
