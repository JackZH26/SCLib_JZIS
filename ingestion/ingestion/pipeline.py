"""Ingestion pipeline orchestrator.

Usage:

    sclib-ingest --mode bulk --from 2023-01-01 --until 2023-01-31 --limit 30
    sclib-ingest --mode incremental
    sclib-ingest --mode smoke --limit 30

Modes:

* ``bulk`` — harvest metadata for an explicit date range. Use for
  historical back-fill (split into 8-hour windows externally).
* ``incremental`` — pick up where the last run left off, using
  ``harvest_state.json`` in GCS. Designed for the twice-daily cron.
* ``smoke`` — developer convenience. Harvests the most-recent ``--limit``
  papers from the last 30 days and runs the full pipeline against them.
  Intended for Phase 2 acceptance: ``--limit 30`` is the contract with
  PROJECT_SPEC §15 Phase 2 step 10.

Per-paper sub-pipeline (see PROJECT_SPEC §9C):

    OAI-PMH metadata
        → arXiv source (.tar.gz) or pdf fallback
        → GCS upload (idempotent: skip if already present)
        → LaTeX parse → Section list
        → Chunk (512/64 tokens, section-aware)
        → Embed (Vertex text-embedding-005, batched)
        → Postgres upsert (papers, chunks) + Vertex VS upsert
        → Material NER (Gemini) → update papers.materials_extracted
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
from ingestion.embed.embedder import embed_chunks
from ingestion.extract.material_ner import extract_materials
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
) -> dict[str, Any]:
    """Run the full per-paper pipeline. Returns a dict summarizing the work."""
    result: dict[str, Any] = {
        "arxiv_id": meta.arxiv_id,
        "title": meta.title[:80],
        "ok": False,
    }

    # 1. Fetch + archive
    data: bytes | None = None
    if storage.source_exists(meta.arxiv_id, meta.yymm):
        log.info("%s: source already in GCS, re-downloading bytes for parse",
                 meta.arxiv_id)
        data = storage.download_source(meta.arxiv_id, meta.yymm)
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
                result["error"] = f"download failed: {e2}"
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
    chunks = chunk_paper(parsed)
    result["n_chunks"] = len(chunks)
    if not chunks:
        result["error"] = "no chunks produced"
        return result

    # 4. Embed (sync SDK call — run in a thread to keep the event loop free)
    await asyncio.to_thread(embed_chunks, chunks)

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
    await upsert_paper_with_chunks(parsed, chunks, materials)

    # 7. Vertex VS upsert (the slow part of step 4 feeds step 7)
    if not skip_vector_search:
        await asyncio.to_thread(upsert_chunks_to_vector_search, parsed, chunks)

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
                r = {"arxiv_id": meta.arxiv_id, "ok": False, "error": str(e)}
            results.append(r)
            _print_status(r)
            if limit is not None and len(results) >= limit:
                break

    # Persist harvest state for incremental runs.
    if mode == "incremental":
        state = storage.load_harvest_state()
        state.last_harvested_at = datetime.now(timezone.utc).isoformat()
        storage.save_harvest_state(state)

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
    parser.add_argument("--mode", choices=["bulk", "incremental", "smoke"], required=True)
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
    log.info("done: %d/%d ok", ok, len(results))
    return 0 if ok == len(results) else 1


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


if __name__ == "__main__":
    sys.exit(main())
