"""Ingestion pipeline orchestrator.

Usage:

    sclib-ingest --mode bulk --from 2023-01-01 --until 2023-01-31 --limit 30
    sclib-ingest --mode incremental
    sclib-ingest --mode smoke --limit 30
    sclib-ingest --mode retry [--limit 20]
    sclib-ingest --mode ids --ids 2602.22793,2505.00514

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
* ``ids`` — fetch and process an explicit, comma-separated list of arXiv
  identifiers. Intended for audited gap backfills; avoids replaying a broad
  historical OAI-PMH date range just to recover a handful of missing papers.

Per-paper sub-pipeline (see PROJECT_SPEC §9C):

    OAI-PMH metadata
        → arXiv source (.tar.gz) or pdf fallback
        → GCS immutable capture (fresh response; create-or-verify by digest)
        → LaTeX parse → Section list
        → Chunk (512/64 tokens, section-aware)
        → Embed (Google Gen AI text-embedding-005, batched)
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
import copy
import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from time import perf_counter
from typing import Any

from ingestion import storage
from ingestion.chunk.chunker import chunk_paper
from ingestion.collect.arxiv_oai import ArxivClient, ArxivError
from ingestion.config import get_settings
from ingestion.embed.embedder import embed_chunks
from ingestion.extract.affiliation_ner import extract_paper_geo
from ingestion.extract.fact_sentences import FactChunkLimitError
from ingestion.extract.material_ner import _MAX_CHARS, _assemble_text, extract_materials
from ingestion.extract.materials_aggregator import aggregate_from_papers
from ingestion.index.indexer import (
    dispose,
    upsert_chunks_to_vector_search,
    upsert_paper_geo,
    upsert_paper_with_chunks,
)
from ingestion.input_observation import new_input_observation, observe_chunks, observe_embeddings
from ingestion.models import PaperMetadata, ParsedPaper
from ingestion.parse.latex_parser import LatexParseError, parse_source_tarball
from ingestion.source_capture import build_ingestion_capture

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
    skip_geo: bool = False,
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
        "requested_version": meta.requested_version,
        "title": meta.title[:80],
        "ok": False,
        "strategy": strategy,
        "input_observation": new_input_observation(),
    }

    # Abstract-only skips artifact download/parsing, not the later service calls.
    if strategy == "abstract_only":
        parsed = ParsedPaper(meta=meta, sections=[], has_latex_source=False)
        return await _finish(parsed, skip_vector_search, skip_ner, skip_geo, result)

    # 1. Fetch once per invocation. Legacy unversioned work-key caches cannot
    # prove that their bytes belong to the current OAI metadata or selected vN.
    # Leave those objects untouched; never silently promote them to evidence.
    if strategy == "force_pdf":
        # Jump straight to PDF — used when a prior run's tar.gz was junk
        # or /src/ is persistently returning a PDF. This also bypasses
        # any already-polluted src/ cache blob.
        try:
            capture = await client.download_pdf_capture(meta.download_id)
            artifact = storage.archive_arxiv_capture(capture)
        except ArxivError as e:
            result.update({"stage": "download", "error": f"pdf: {e}"})
            return result
        parsed = ParsedPaper(meta=meta, sections=[], has_latex_source=False)
        parsed.ingestion_capture = {"artifact": artifact}
        return await _finish(parsed, skip_vector_search, skip_ner, skip_geo, result)
    else:
        try:
            capture = await client.download_source_capture(meta.download_id)
            artifact = storage.archive_arxiv_capture(capture)
        except ArxivError as e:
            log.warning("%s: no LaTeX source (%s) — falling back to PDF",
                        meta.arxiv_id, e)
            try:
                capture = await client.download_pdf_capture(meta.download_id)
                artifact = storage.archive_arxiv_capture(capture)
            except ArxivError as e2:
                result.update({"stage": "download", "error": f"{e2}"})
                return result
            # PDF fallback parser not implemented yet — chunk abstract only
            parsed = ParsedPaper(meta=meta, sections=[], has_latex_source=False)
            parsed.ingestion_capture = {"artifact": artifact}
            return await _finish(parsed, skip_vector_search, skip_ner, skip_geo, result)

    # 2. Parse LaTeX
    try:
        parsed = parse_source_tarball(capture.data, meta)
    except LatexParseError as e:
        log.warning("%s: latex parse failed (%s) — using abstract-only chunk",
                    meta.arxiv_id, e)
        parsed = ParsedPaper(meta=meta, sections=[], has_latex_source=False)

    parsed.ingestion_capture = {"artifact": artifact}
    return await _finish(parsed, skip_vector_search, skip_ner, skip_geo, result)


async def _finish(
    parsed: ParsedPaper,
    skip_vector_search: bool,
    skip_ner: bool,
    skip_geo: bool,
    result: dict[str, Any],
) -> dict[str, Any]:
    observation = result.setdefault("input_observation", new_input_observation())
    # Preserve the source observation and exact prepared NER document before a
    # downstream chunk/embed failure can discard the only capture timestamp.
    # Preparation is not evidence that a provider call actually occurred.
    try:
        parsed.ingestion_capture = build_ingestion_capture(
            parsed, ner_input=_assemble_text(parsed) if not skip_ner else None,
            document_char_limit=_MAX_CHARS,
        )
        if not skip_ner:
            parsed.ingestion_capture["ner_input"]["status"] = "prepared"
        manifest = storage.archive_arxiv_capture_manifest(parsed.ingestion_capture)
        parsed.ingestion_capture["manifest_object"] = manifest
        result["ingestion_capture"] = copy.deepcopy(parsed.ingestion_capture)
    except Exception as e:  # noqa: BLE001
        result.update({"stage": "capture", "error": f"capture archive: {e}"})
        return result

    # 3. Chunk
    stage_started = perf_counter()
    try:
        chunks = chunk_paper(parsed)
    except FactChunkLimitError:
        reason = FactChunkLimitError.reason_code
        observation["chunk"] = observe_chunks(status="failed", reason_code=reason,
                                               duration_seconds=perf_counter() - stage_started)
        result.update({"stage": "chunk", "error": reason, "reason_code": reason})
        return result
    except Exception as e:  # noqa: BLE001
        observation["chunk"] = observe_chunks(status="failed", reason_code="chunk_stage_failed",
                                               duration_seconds=perf_counter() - stage_started)
        result.update({"stage": "chunk", "error": f"{e}"})
        return result
    observation["chunk"] = observe_chunks(chunks, status="returned",
                                           duration_seconds=perf_counter() - stage_started)
    result["n_chunks"] = len(chunks)
    if not chunks:
        observation["chunk"].update(stage_status="failed", reason_code="no_chunks_produced")
        result.update({"stage": "chunk", "error": "no chunks produced"})
        return result

    # 4. Embed (sync SDK call — run in a thread to keep the event loop free)
    stage_started = perf_counter()
    try:
        await asyncio.to_thread(embed_chunks, chunks)
    except Exception as e:  # noqa: BLE001
        observation["embedding"] = observe_embeddings(chunks, status="failed",
            reason_code="embedding_stage_failed", duration_seconds=perf_counter() - stage_started)
        result.update({"stage": "embed", "error": f"{e}"})
        return result
    observation["embedding"] = observe_embeddings(chunks, status="returned",
                                                  duration_seconds=perf_counter() - stage_started)

    # 5. Material NER (optional — skipped for smoke runs without Gemini access)
    materials: list[dict[str, Any]] = []
    if not skip_ner:
        parsed.ingestion_capture["ner_input"]["status"] = "attempted"
        try:
            materials = await asyncio.to_thread(extract_materials, parsed)
        except Exception as e:  # noqa: BLE001
            log.warning("%s: NER failed: %s", parsed.meta.arxiv_id, e)
        # Keep the first immutable observation address separately. Never hash a
        # document containing its own final manifest address or overwrite it.
        parsed.ingestion_capture["prepared_manifest_object"] = parsed.ingestion_capture.pop("manifest_object")
        try:
            manifest = storage.archive_arxiv_capture_manifest(parsed.ingestion_capture)
            parsed.ingestion_capture["manifest_object"] = manifest
        except Exception as e:  # noqa: BLE001
            result.update({"stage": "capture", "error": f"capture archive: {e}"})
            return result
    materials = [{**r, "ingestion_capture": copy.deepcopy(parsed.ingestion_capture)}
                 for r in materials]
    result["ingestion_capture"] = copy.deepcopy(parsed.ingestion_capture)
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

    # 8. Author-geography NER — a separate NER flow from material NER
    #    (step 5), writing papers.affiliations + papers.paper_geo. Runs
    #    last and only logs on error, so a geo failure can never fail an
    #    otherwise-good paper.
    if not skip_geo:
        try:
            geo = await asyncio.to_thread(extract_paper_geo, parsed.meta.arxiv_id)
            await upsert_paper_geo(
                parsed.meta.paper_id, geo["affiliations"], geo["paper_geo"],
            )
            result["geo_status"] = geo["paper_geo"].get("status")
        except Exception as e:  # noqa: BLE001
            log.warning("%s: geo NER failed: %s", parsed.meta.arxiv_id, e)

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
    skip_geo: bool,
    arxiv_ids: list[str] | None = None,
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

    if mode == "ids":
        arxiv_ids = list(dict.fromkeys(
            arxiv_id.strip()
            for arxiv_id in (arxiv_ids or [])
            if arxiv_id.strip()
        ))
        if not arxiv_ids:
            raise ValueError("ids mode requires at least one --ids value")
        if limit is not None:
            arxiv_ids = arxiv_ids[:limit]
        from_date = None
        until_date = None

    elif mode in ("bulk", "smoke"):
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

    log.info(
        "pipeline: mode=%s from=%s until=%s limit=%s ids=%d skip_vs=%s skip_ner=%s",
        mode,
        from_date,
        until_date,
        limit,
        len(arxiv_ids or []),
        skip_vector_search,
        skip_ner,
    )

    pool = storage.load_failed_papers()
    pool_was_dirty = False

    results: list[dict[str, Any]] = []

    async def handle_meta(client: ArxivClient, meta: PaperMetadata) -> None:
        nonlocal pool_was_dirty
        try:
            result = await process_paper(
                client,
                meta,
                skip_vector_search=skip_vector_search,
                skip_ner=skip_ner,
                skip_geo=skip_geo,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("pipeline error on %s: %s", meta.arxiv_id, exc)
            result = {
                "arxiv_id": meta.arxiv_id,
                "ok": False,
                "stage": "unknown",
                "error": str(exc),
            }
        results.append(result)
        _print_status(result)

        if result.get("ok"):
            if storage.clear_failure(pool, meta.download_id):
                log.info(
                    "%s: recovered — removed from failure pool",
                    meta.arxiv_id,
                )
                pool_was_dirty = True
        else:
            failure = storage.record_failure(
                pool,
                meta,
                stage=result.get("stage", "unknown"),
                error=result.get("error", "unknown"),
                strategy="default",
            )
            _retain_capture_reference(failure, result)
            pool_was_dirty = True

    async with ArxivClient() as client:
        if mode == "ids":
            for arxiv_id in arxiv_ids or []:
                try:
                    meta = await client.get_record(arxiv_id)
                except Exception as exc:  # noqa: BLE001
                    log.exception("metadata lookup failed on %s: %s", arxiv_id, exc)
                    result = {
                        "arxiv_id": arxiv_id,
                        "ok": False,
                        "stage": "metadata",
                        "error": str(exc),
                    }
                    results.append(result)
                    _print_status(result)
                    continue
                await handle_meta(client, meta)
        else:
            assert from_date is not None and until_date is not None
            async for meta in client.list_records(
                from_date,
                until_date,
                max_records=limit,
            ):
                await handle_meta(client, meta)
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
            try:
                meta = PaperMetadata.from_dict(fp.meta)
                if meta.download_id != fp.arxiv_id:
                    raise ValueError("stored retry identifier does not match metadata")
            except (TypeError, ValueError, KeyError, AttributeError):
                # Legacy malformed/version-ambiguous metadata is not repaired by
                # guessing an identifier, and cannot abort unrelated retries.
                fp.status = "dead"
                fp.attempt_count += 1
                fp.last_failed_at = datetime.now(timezone.utc).isoformat()
                fp.last_stage = "metadata"
                fp.last_error = "Stored retry metadata is invalid; manual review required"
                result = {"arxiv_id": fp.arxiv_id, "ok": False, "stage": "metadata",
                          "error": fp.last_error, "terminal": True, "strategy": strategy}
                results.append(result)
                _print_status(result)
                continue
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
                failure = storage.record_failure(
                    pool, meta,
                    stage=r.get("stage", "unknown"),
                    error=r.get("error", "unknown"),
                    strategy=strategy,
                )
                _retain_capture_reference(failure, r)

    storage.save_failed_papers(pool)
    return results


def _retain_capture_reference(failure: storage.FailedPaper, result: dict[str, Any]) -> None:
    """Link retry diagnostics to an already archived, text-free observation.

    The failure metadata remains a retry record, not an authoritative result
    availability witness. PaperMetadata.from_dict deliberately ignores this key.
    """
    capture = result.get("ingestion_capture")
    manifest = capture.get("manifest_object") if isinstance(capture, dict) else None
    prefix = "captures/arxiv/manifests/sha256/"
    if (isinstance(failure.meta, dict) and isinstance(manifest, str)
            and manifest.startswith(prefix) and manifest.endswith(".json")):
        digest = manifest[len(prefix):-5]
        if len(digest) == 64 and all(char in "0123456789abcdef" for char in digest):
            failure.meta["last_capture_manifest_object"] = manifest


def _print_status(r: dict[str, Any]) -> None:
    status = "OK " if r.get("ok") else "ERR"
    extra = (
        f"chunks={r.get('n_chunks', 0)} mats={r.get('n_materials', 0)}"
        if r.get("ok")
        else f"err={r.get('error', '?')}"
    )
    log.info("[%s] %s %s — %s",
             status, r["arxiv_id"], r.get("title", ""), extra)
    if "input_observation" in r:
        log.info("input_observation=%s", json.dumps(r["input_observation"], sort_keys=True, allow_nan=False))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=[
            "bulk",
            "incremental",
            "smoke",
            "retry",
            "aggregate-materials",
            "ids",
        ],
        required=True,
    )
    parser.add_argument("--from", dest="from_date", type=_parse_date)
    parser.add_argument("--until", dest="until_date", type=_parse_date)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--ids",
        help="Comma-separated arXiv IDs for --mode ids.",
    )
    parser.add_argument("--skip-vector-search", action="store_true",
                        help="Skip Vertex VS upsert (DB-only).")
    parser.add_argument("--skip-ner", action="store_true",
                        help="Skip Gemini material NER.")
    parser.add_argument("--skip-geo", action="store_true",
                        help="Skip Gemini author-geography NER.")
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
                skip_geo=args.skip_geo,
                arxiv_ids=args.ids.split(",") if args.ids else None,
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
