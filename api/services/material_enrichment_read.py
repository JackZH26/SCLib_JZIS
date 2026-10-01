"""Bounded read of source-scoped recovery candidates, outside scientific values."""
from __future__ import annotations

import asyncio
import hashlib
from collections import defaultdict
from weakref import WeakKeyDictionary

from sqlalchemy import func, select

from models.db import Chunk
from services.claim_support import is_derived_source_hint
from services.material_enrichment import build_enrichment_report, digest
from services.rag_evidence import resolve_chunk_evidence

MAX_PAPERS = 8
MAX_CHUNKS = 40
MAX_CHARS = 120000
MAX_RECORDS = 32
MAX_CPU_WORKERS = 2
_WORKER_LIMITS = WeakKeyDictionary()
_WORKER_TASKS = set()


def _sample_records(records):
    """Stratify across eligible papers and the whole retained record ordering.

    Allocation is round-robin across sorted paper IDs. Within each paper the
    selected positions span its current record inventory, including endpoints.
    No record scientific value or source status is changed by this sampling.
    """
    groups = defaultdict(list)
    unattributed = []
    for record in records:
        if type(record) is not dict:
            continue
        paper_id = record.get("paper_id")
        if type(paper_id) is str and paper_id and paper_id == paper_id.strip() and len(paper_id) <= 100 and not any(ord(char) < 32 for char in paper_id):
            groups[paper_id].append(record)
        else:
            unattributed.append(record)
    source_ids = sorted(groups)
    paper_ids = source_ids[:MAX_PAPERS]
    quotas = {paper: 0 for paper in paper_ids}
    remaining = MAX_RECORDS
    while remaining:
        progressed = False
        for paper in paper_ids:
            if remaining and quotas[paper] < len(groups[paper]):
                quotas[paper] += 1
                remaining -= 1
                progressed = True
        if not progressed:
            break
    sampled = {}
    for paper in paper_ids:
        count, available = quotas[paper], groups[paper]
        positions = [0] if count == 1 else [i * (len(available) - 1) // (count - 1) for i in range(count)]
        sampled[paper] = [available[position] for position in positions]
    selected = [sampled[paper][position] for position in range(max(quotas.values(), default=0))
                for paper in paper_ids if position < len(sampled[paper])]
    selected.extend(unattributed[:remaining])
    scope = {"version": "materials-enrichment-inspection/1.0.0",
             "records_total": len(records), "records_inspected": len(selected),
             "records_truncated": len(selected) < len(records), "records_limit": MAX_RECORDS,
             "papers_total": len(source_ids), "papers_inspected": len(paper_ids),
             "papers_truncated": len(paper_ids) < len(source_ids), "papers_limit": MAX_PAPERS,
             "record_sampling": "paper_round_robin_evenly_spaced_retained_positions"}
    return selected, source_ids, paper_ids, scope


def _compile_recovery_report(payload, sources, coverage, scope):
    """All synchronous parsing, hashing and public projection run in a worker."""
    report = build_enrichment_report([payload], sources, source_coverage=coverage, include_evidence_text=False)
    report["inspection_scope"] = scope
    report["counts"]["retained_records"] = scope["records_total"]
    report["counts"]["raw_retained_records"] = scope["raw_retained_records_total"]
    report["counts"]["retained_records_inspected"] = scope["records_inspected"]
    report["counts"]["retained_records_omitted"] = scope["records_total"] - scope["records_inspected"]
    for row in report["coverage"]:
        row["retained_record_count_total"] = scope["records_total"]
        row["record_scan_truncated"] = scope["records_truncated"]
        if scope["records_truncated"]:
            for field in row["fields"]:
                field["reason_codes"].append("retained_record_inventory_not_fully_inspected")
    report["candidates_truncated"] = len(report["candidates"]) > 100
    report["candidates"] = report["candidates"][:100]
    report["counts"]["candidate_facts_returned"] = len(report["candidates"])
    report.pop("report_sha256", None)
    report["report_sha256"] = digest(report)
    return report


async def _bounded_compile(payload, sources, coverage, scope):
    """A cancelled request cannot release a CPU slot before its thread finishes."""
    loop = asyncio.get_running_loop()
    semaphore = _WORKER_LIMITS.setdefault(loop, asyncio.Semaphore(MAX_CPU_WORKERS))
    await semaphore.acquire()
    try:
        task = asyncio.create_task(asyncio.to_thread(_compile_recovery_report, payload, sources, coverage, scope))
    except BaseException:
        semaphore.release()
        raise
    _WORKER_TASKS.add(task)

    def completed(finished):
        _WORKER_TASKS.discard(finished)
        semaphore.release()
        # A caller may have disconnected. Consume a failed worker exception to
        # avoid logging unhandled source-dependent errors after cancellation.
        if not finished.cancelled():
            finished.exception()

    task.add_done_callback(completed)
    return await asyncio.shield(task)


async def read_material_enrichment(db, material) -> dict:
    records = material.current_records()
    # Source lifecycle partition precedes retrieval; an excluded occurrence
    # cannot supply facts through enrichment. Always use exact linked papers.
    selected_records, source_ids, paper_ids, scope = _sample_records(records)
    raw_records = getattr(material, "records", records)
    scope["raw_retained_records_total"] = len(raw_records) if isinstance(raw_records, list) else len(records)
    scope["current_eligible_records_total"] = len(records)
    payload = {"id": material.id, "formula": material.formula, "records": selected_records}
    sources, coverage = [], {paper: {"fulltext_checked": False, "supplement_checked": False,
                                   "scope": "bounded_current_chunks_not_complete_source"}
                             for paper in source_ids}
    if paper_ids:
        # Prefer exact formula mentions and tables; return whole retained
        # chunks so headers, units and nearby context survive extraction.
        chunks = (await db.execute(select(Chunk).where(
            Chunk.paper_id.in_(paper_ids), func.char_length(Chunk.text) <= 20000,
        ).order_by(Chunk.text.contains(material.formula, autoescape=True).desc(),
                   Chunk.has_table.desc(), Chunk.paper_id, Chunk.chunk_index, Chunk.id)
          .limit(MAX_CHUNKS + 1))).scalars().all()
        truncated = len(chunks) > MAX_CHUNKS
        selected, chars = [], 0
        for chunk in chunks[:MAX_CHUNKS]:
            if chars + len(chunk.text) > MAX_CHARS:
                truncated = True
                break
            selected.append(chunk)
            chars += len(chunk.text)
        descriptors = await resolve_chunk_evidence(db, selected)
        excluded = 0
        for chunk in selected:
            descriptor = descriptors.get(chunk.id, {})
            if descriptor.get("permission_status") == "restricted" or descriptor.get("currentness") == "stale":
                excluded += 1
                continue
            kind = descriptor.get("chunk_kind", "legacy_unknown")
            # Derived facts do not substitute for their original source. Legacy
            # unknown text can produce unresolved retrieval candidates only.
            if (kind not in {"original_passage", "abstract", "legacy_unknown"}
                    or is_derived_source_hint(section=chunk.section, paper_id=chunk.paper_id, text=chunk.text)):
                excluded += 1
                continue
            content_hash = hashlib.sha256(chunk.text.encode()).hexdigest()
            raw_locator = descriptor.get("source_locator", {})
            locator = {key: value for key, value in raw_locator.items()
                       if key in {"page", "table", "figure", "section", "row", "column", "char_start", "char_end", "xml_xpath"}
                       and type(value) in {str, int}} if type(raw_locator) is dict else {}
            locator["chunk_id"] = chunk.id
            if chunk.section:
                locator.setdefault("section", chunk.section)
            sources.append({"id": chunk.id, "paper_id": chunk.paper_id, "text": chunk.text,
                            "content_sha256": content_hash, "source_revision":
                            str(descriptor.get("evidence_revision_id") or "retained-content:" + content_hash),
                            "source_revision_basis": "retained_chunk_capture_not_publication_version",
                            "publication_revision_verified": False,
                            "kind": kind, "source_status": "unknown",
                            "locator": locator})
        for paper in paper_ids:
            coverage[paper]["chunks_supplied"] = sum(source["paper_id"] == paper for source in sources)
            coverage[paper]["truncated"] = truncated or len(source_ids) > MAX_PAPERS
            coverage[paper]["excluded_chunks_total"] = excluded
    return await _bounded_compile(payload, sources, coverage, scope)
