"""Ingestion pipeline orchestrator.

Usage:

    sclib-ingest --mode bulk --from 2023-01-01 --until 2023-01-31 --limit 30
    sclib-ingest --mode incremental
    sclib-ingest --mode smoke --limit 30
    sclib-ingest --mode retry [--limit 20]

Modes:

* ``bulk`` — harvest metadata for an explicit date range. Use for
  historical back-fill (split into 8-hour windows externally).
* ``incremental`` — pick up where the last run left off, using
  ``harvest_state.json`` in GCS. Designed for the twice-daily cron.
* ``smoke`` — developer convenience. Harvests the most-recent ``--limit``
  papers from the last 30 days and runs the full pipeline against them.
  Intended for Phase 2 acceptance: ``--limit 30`` is the contract with
  PROJECT_SPEC §15 Phase 2 step 10.
* ``retry`` — drain the GCS failure pool. Each failed paper is re-tried
  with an escalating strategy (default → force_pdf → skip_ner → skip_vs
  → abstract_only). Papers that exhaust ``failure_max_attempts`` are
  marked ``dead`` and skipped on future runs. Safe to run in idle hours.

Per-paper sub-pipeline (see PROJECT_SPEC §9C):

    OAI-PMH metadata
        → arXiv source (.tar.gz) or pdf fallback
        → GCS upload (idempotent: skip if already present)
        → LaTeX parse → Section list
        → Chunk (512/64 tokens, section-aware)
        → Embed (Vertex text-embedding-005, batched)
        → Postgres upsert (papers, chunks) + Vertex VS upsert
        → Material NER (Gemini) → update papers.materials_extracted

Partial-failure policy:

    A batch run is considered successful (exit code 0) when the per-paper
    success ratio meets ``failure_success_threshold`` (default 0.66). Any
    failed paper lands in the GCS failure pool (``metadata/failed_papers.json``)
    and is transparently picked up by the next ``--mode retry`` run. This
    means a flaky arXiv endpoint or one bad paper can't block the whole
    twice-daily ingest.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ingestion.collect.arxiv_oai import ArxivClient, ArxivError
from ingestion.chunk.chunker import chunk_paper
from ingestion.config import get_settings
from ingestion.embed.embedder import embed_chunks
from ingestion.extract.material_ner import extract_materials
from ingestion.extract.materials_aggregator import aggregate_from_papers
from ingestion.index.indexer import (
    dispose,
    upsert_chunks_to_vector_search,
    upsert_paper_with_chunks,
)
from ingestion.models import PaperMetadata, ParsedPaper
from ingestion.parse.latex_parser import LatexParseError, parse_source_tarball
from ingestion import storage

log = logging.getLogger("ingestion.pipeline")


# ---------------------------------------------------------------------------
# Per-paper
# ---------------------------------------------------------------------------

async def process_paper(
    client: ArxivClient,
    meta: PaperMetadata,
    *,
    skip_vector_search: bool = False,
    skip_ner: bool = False,
    strategy: str = "default",
) -> dict[str, Any]:
    """Run the full per-paper pipeline. Returns a dict summarizing the work.

    ``strategy`` controls retry-time escalation; see ``FAILURE_STRATEGIES``
    in ``ingestion.storage``:

    * ``default`` — the normal path (tar.gz → LaTeX → full pipeline).
    * ``force_pdf`` — skip the /src/ endpoint entirely, go straight to
      PDF fallback (abstract-only chunk), then run the full pipeline.
    * ``skip_ner`` — same as default but force skip_ner=True.
    * ``skip_vs`` — same as default but force skip_vector_search=True.
    * ``abstract_only`` — don't even try to download; chunk the abstract
      we already have from OAI-PMH.

    On error, the result dict includes ``"stage"`` and ``"error"`` so the
    caller can feed the failure pool. Exceptions escape normally —
    ``run()`` wraps this in a try/except at the top level.
    """
    if strategy == "skip_ner":
        skip_ner = True
    elif strategy == "skip_vs":
        skip_vector_search = True

    result: dict[str, Any] = {
        "arxiv_id": meta.arxiv_id,
        "title": meta.title[:80],
        "ok": False,
        "strategy": strategy,
    }

    # Short-circuit: abstract_only never touches the network or the parser.
    if strategy == "abstract_only":
        parsed = ParsedPaper(meta=meta, sections=[], has_latex_source=False)
        return await _finish(parsed, skip_vector_search, skip_ner, result)

    # 1. Fetch + archive
    data: bytes | None = None
    if strategy != "force_pdf" and storage.source_exists(meta.arxiv_id, meta.yymm):
        log.info("%s: source already in GCS, re-downloading bytes for parse",
                 meta.arxiv_id)
        try:
            data = storage.download_source(meta.arxiv_id, meta.yymm)
        except Exception as e:  # noqa: BLE001
            result.update({"stage": "download", "error": f"gcs download: {e}"})
            return result
    elif strategy == "force_pdf":
        # Jump straight to PDF — used when a prior run's tar.gz was junk
        # or /src/ is persistently returning a PDF. This also bypasses
        # any already-polluted src/ cache blob.
        try:
            pdf = await client.download_pdf(meta.arxiv_id)
            storage.upload_pdf(meta.arxiv_id, meta.yymm, pdf)
        except ArxivError as e:
            result.update({"stage": "download", "error": f"pdf: {e}"})
            return result
        parsed = ParsedPaper(meta=meta, sections=[], has_latex_source=False)
        return await _finish(parsed, skip_vector_search, skip_ner, result)
    else:
        try:
            data = await client.download_source(meta.arxiv_id)
            storage.upload_source(meta.arxiv_id, meta.yymm, data)
        except ArxivError as e:
            log.warning("%s: no LaTeX source (%s) — falling back to PDF",
                        meta.arxiv_id, e)
            try:
                pdf = await client.download_pdf(meta.arxiv_id)
                storage.upload_pdf(meta.arxiv_id, meta.yymm, pdf)
            except ArxivError as e2:
                result.update({"stage": "download", "error": f"{e2}"})
                return result
            # PDF fallback parser not implemented yet — chunk abstract only
            parsed = ParsedPaper(meta=meta, sections=[], has_latex_source=False)
            return await _finish(parsed, skip_vector_search, skip_ner, result)

    # 2. Parse LaTeX
    try:
        parsed = parse_source_tarball(data, meta)
    except LatexParseError as e:
        log.warning("%s: latex parse failed (%s) — using abstract-only chunk",
                    meta.arxiv_id, e)
        parsed = ParsedPaper(meta=meta, sections=[], has_latex_source=False)

    return await _finish(parsed, skip_vector_search, skip_ner, result)


async def _finish(
    parsed: ParsedPaper,
    skip_vector_search: bool,
    skip_ner: bool,
    result: dict[str, Any],
) -> dict[str, Any]:
    # 3. Chunk
    try:
        chunks = chunk_paper(parsed)
    except Exception as e:  # noqa: BLE001
        result.update({"stage": "chunk", "error": f"{e}"})
        return result
    result["n_chunks"] = len(chunks)
    if not chunks:
        result.update({"stage": "chunk", "error": "no chunks produced"})
        return result

    # 4. Embed (sync SDK call — run in a thread to keep the event loop free)
    try:
        await asyncio.to_thread(embed_chunks, chunks)
    except Exception as e:  # noqa: BLE001
        result.update({"stage": "embed", "error": f"{e}"})
        return result

    # 5. Material NER (optional — skipped for smoke runs without Gemini access)
    materials: list[dict[str, Any]] = []
    if not skip_ner:
        try:
            materials = await asyncio.to_thread(extract_materials, parsed)
        except Exception as e:  # noqa: BLE001
            log.warning("%s: NER failed: %s", parsed.meta.arxiv_id, e)
    for c in chunks:
        # Attach paper-level materials to every chunk until we have a
        # proper per-chunk NER (Phase 5).
        c.materials_mentioned = materials
    result["n_materials"] = len(materials)

    # 6. DB upsert
    try:
        await upsert_paper_with_chunks(parsed, chunks, materials)
    except Exception as e:  # noqa: BLE001
        result.update({"stage": "db", "error": f"{e}"})
        return result

    # 7. Vertex VS upsert (the slow part of step 4 feeds step 7)
    if not skip_vector_search:
        try:
            await asyncio.to_thread(upsert_chunks_to_vector_search, parsed, chunks)
        except Exception as e:  # noqa: BLE001
            result.update({"stage": "vs", "error": f"{e}"})
            return result

    result["ok"] = True
    return result


# ---------------------------------------------------------------------------
# Batch loop
# ---------------------------------------------------------------------------

async def run(
    *,
    mode: str,
    from_date: date | None,
    until_date: date | None,
    limit: int | None,
    skip_vector_search: bool,
    skip_ner: bool,
) -> list[dict[str, Any]]:

    if mode == "retry":
        return await _run_retry(limit=limit)

    if mode == "aggregate-materials":
        # Roll per-paper NER output (papers.materials_extracted) up into
        # the materials table. Idempotent; safe to re-run.
        n = await aggregate_from_papers()
        log.info("aggregate-materials: %d materials upserted", n)
        return [{"arxiv_id": "aggregate-materials", "ok": True,
                 "n_materials": n}]

    if mode in ("bulk", "smoke"):
        if mode == "smoke":
            until_date = until_date or date.today()
            from_date = from_date or (until_date - timedelta(days=30))
            limit = limit or 30
        assert from_date and until_date, "bulk mode requires --from and --until"

    elif mode == "incremental":
        state = storage.load_harvest_state()
        if state.last_harvested_at:
            from_date = datetime.fromisoformat(state.last_harvested_at).date()
        else:
            from_date = date.today() - timedelta(days=2)
        until_date = date.today()
    else:
        raise ValueError(f"unknown mode: {mode}")

    log.info("pipeline: mode=%s from=%s until=%s limit=%s skip_vs=%s skip_ner=%s",
             mode, from_date, until_date, limit, skip_vector_search, skip_ner)

    pool = storage.load_failed_papers()
    pool_was_dirty = False

    results: list[dict[str, Any]] = []
    async with ArxivClient() as client:
        async for meta in client.list_records(
            from_date, until_date, max_records=limit,
        ):
            try:
                r = await process_paper(
                    client, meta,
                    skip_vector_search=skip_vector_search,
                    skip_ner=skip_ner,
                )
            except Exception as e:  # noqa: BLE001
                log.exception("pipeline error on %s: %s", meta.arxiv_id, e)
                r = {"arxiv_id": meta.arxiv_id, "ok": False,
                     "stage": "unknown", "error": str(e)}
            results.append(r)
            _print_status(r)

            # Failure pool bookkeeping: record new failures, clear the
            # paper if it just succeeded after a prior failure.
            if r.get("ok"):
                if storage.clear_failure(pool, meta.arxiv_id):
                    log.info("%s: recovered — removed from failure pool",
                             meta.arxiv_id)
                    pool_was_dirty = True
            else:
                storage.record_failure(
                    pool, meta,
                    stage=r.get("stage", "unknown"),
                    error=r.get("error", "unknown"),
                    strategy="default",
                )
                pool_was_dirty = True

            if limit is not None and len(results) >= limit:
                break

    if pool_was_dirty:
        storage.save_failed_papers(pool)

    # Persist harvest state for incremental runs.
    if mode == "incremental":
        state = storage.load_harvest_state()
        state.last_harvested_at = datetime.now(timezone.utc).isoformat()
        storage.save_harvest_state(state)

    return results


async def _run_retry(*, limit: int | None) -> list[dict[str, Any]]:
    """Drain the failure pool. For each pending paper, try the next
    strategy in ``FAILURE_STRATEGIES``; mark dead after max_attempts."""
    settings = get_settings()
    pool = storage.load_failed_papers()
    pending = [fp for fp in pool.values() if fp.status == "pending"]
    if not pending:
        log.info("retry: failure pool empty — nothing to do")
        return []

    # Oldest failures first so we don't starve them.
    pending.sort(key=lambda fp: fp.first_failed_at)
    if limit is not None:
        pending = pending[:limit]

    log.info("retry: %d papers pending (limit=%s, max_attempts=%d)",
             len(pending), limit, settings.failure_max_attempts)

    results: list[dict[str, Any]] = []
    async with ArxivClient() as client:
        for fp in pending:
            if fp.attempt_count >= settings.failure_max_attempts:
                fp.status = "dead"
                log.warning("%s: marked dead after %d attempts (last stage=%s)",
                            fp.arxiv_id, fp.attempt_count, fp.last_stage)
                continue

            # Pick the next strategy we haven't tried yet, in escalation
            # order. If everything's been tried, give it one more shot
            # at ``abstract_only`` so we at least persist the metadata.
            strategy = next(
                (s for s in storage.FAILURE_STRATEGIES
                 if s not in fp.strategies_tried),
                "abstract_only",
            )
            meta = PaperMetadata.from_dict(fp.meta)
            log.info("retry: %s attempt=%d strategy=%s (prev stage=%s)",
                     fp.arxiv_id, fp.attempt_count + 1, strategy, fp.last_stage)

            try:
                r = await process_paper(client, meta, strategy=strategy)
            except Exception as e:  # noqa: BLE001
                log.exception("retry error on %s: %s", fp.arxiv_id, e)
                r = {"arxiv_id": fp.arxiv_id, "ok": False,
                     "stage": "unknown", "error": str(e),
                     "strategy": strategy}
            results.append(r)
            _print_status(r)

            if r.get("ok"):
                storage.clear_failure(pool, fp.arxiv_id)
            else:
                storage.record_failure(
                    pool, meta,
                    stage=r.get("stage", "unknown"),
                    error=r.get("error", "unknown"),
                    strategy=strategy,
                )

    storage.save_failed_papers(pool)
    return results


def _print_status(r: dict[str, Any]) -> None:
    status = "OK " if r.get("ok") else "ERR"
    extra = (
        f"chunks={r.get('n_chunks', 0)} mats={r.get('n_materials', 0)}"
        if r.get("ok")
        else f"err={r.get('error', '?')}"
    )
    log.info("[%s] %s %s — %s",
             status, r["arxiv_id"], r.get("title", ""), extra)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=["bulk", "incremental", "smoke", "retry", "aggregate-materials"],
        required=True,
    )
    parser.add_argument("--from", dest="from_date", type=_parse_date)
    parser.add_argument("--until", dest="until_date", type=_parse_date)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--skip-vector-search", action="store_true",
                        help="Skip Vertex VS upsert (DB-only).")
    parser.add_argument("--skip-ner", action="store_true",
                        help="Skip Gemini material NER.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )

    async def _main_async() -> list[dict[str, Any]]:
        # dispose() must run on the *same* event loop as run(), otherwise
        # asyncpg's pooled connections try to close on a loop that no
        # longer exists. So we wrap both calls in a single asyncio.run.
        try:
            return await run(
                mode=args.mode,
                from_date=args.from_date,
                until_date=args.until_date,
                limit=args.limit,
                skip_vector_search=args.skip_vector_search,
                skip_ner=args.skip_ner,
            )
        finally:
            await dispose()

    results = asyncio.run(_main_async())

    ok = sum(1 for r in results if r.get("ok"))
    total = len(results)
    ratio = (ok / total) if total else 1.0
    threshold = get_settings().failure_success_threshold

    log.info("done: %d/%d ok (ratio=%.2f, threshold=%.2f)",
             ok, total, ratio, threshold)

    failed = [r for r in results if not r.get("ok")]
    if failed:
        log.info("failure pool: %d new/updated — retry with `--mode retry`",
                 len(failed))
        for r in failed[:10]:
            log.info("  - %s stage=%s err=%.80s",
                     r.get("arxiv_id"), r.get("stage"), r.get("error", ""))

    # Partial-failure policy: a run is considered successful as long as the
    # success ratio meets the configured threshold. The remaining failures
    # are already in the GCS failure pool and will be picked up by a later
    # `--mode retry` run, so we don't want them to page the cron.
    if total == 0:
        return 0
    return 0 if ratio >= threshold else 1


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


if __name__ == "__main__":
    sys.exit(main())
