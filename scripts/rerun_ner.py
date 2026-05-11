#!/usr/bin/env python3
"""Re-run Gemini NER extraction on all papers in Postgres.

Uses the CURRENT v2 prompt (with the ``family`` field) to re-extract
materials from every paper's stored LaTeX source in GCS. Updates
``papers.materials_extracted`` in-place. After completion, run
``sclib-ingest --mode aggregate-materials`` to rebuild the materials
table.

The script is **resumable**: it skips papers whose
``materials_extracted`` JSONB already contains a ``"family"`` key on
any record (meaning they were already processed with the new prompt).
Pass ``--force`` to re-extract even those.

Usage (inside ingestion container):
    python /app/scripts/rerun_ner.py [--limit N] [--concurrency 4] [--dry-run] [--force]

Follow with:
    sclib-ingest --mode aggregate-materials

Cost estimate: ~$20 for ~13k papers at Gemini 2.5 Flash pricing
               (3-4 hours at concurrency=4).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from datetime import date
from pathlib import Path

# Ensure the ingestion package is importable when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ingestion"))

from ingestion.models import PaperMetadata, ParsedPaper
from ingestion.extract.material_ner import extract_materials
from ingestion.parse.latex_parser import parse_source_tarball
from ingestion import storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def _async_db_url() -> str:
    """Get DATABASE_URL and ensure it uses the asyncpg driver."""
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://sclib:sclib@localhost:5432/sclib",
    )
    # .env typically has plain "postgresql://" — patch to asyncpg
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql+psycopg2://"):
        url = url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    return url


async def _load_papers(skip_already_done: bool = True) -> list[dict]:
    """Fetch all paper rows we need to re-extract from Postgres."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_async_engine(_async_db_url())
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        # Load papers that have at least some content in GCS
        # (chunk_count > 0 means we successfully parsed them before).
        if skip_already_done:
            # Skip papers where ANY record already has "family" set —
            # meaning they were already extracted with the new prompt.
            result = await session.execute(text("""
                SELECT id, arxiv_id, title, authors, abstract,
                       date_submitted, categories, doi
                FROM papers
                WHERE chunk_count > 0
                  AND NOT EXISTS (
                      SELECT 1 FROM jsonb_array_elements(
                          COALESCE(materials_extracted, '[]'::jsonb)
                      ) r
                      WHERE r.value ? 'family'
                  )
                ORDER BY date_submitted DESC NULLS LAST
            """))
        else:
            result = await session.execute(text("""
                SELECT id, arxiv_id, title, authors, abstract,
                       date_submitted, categories, doi
                FROM papers
                WHERE chunk_count > 0
                ORDER BY date_submitted DESC NULLS LAST
            """))
        rows = result.fetchall()

    await engine.dispose()

    papers = []
    for row in rows:
        papers.append({
            "paper_id": row[0],
            "arxiv_id": row[1],
            "title": row[2] or "",
            "authors": row[3] or [],
            "abstract": row[4] or "",
            "date_submitted": row[5],
            "categories": row[6] or [],
            "doi": row[7],
        })
    return papers


_engine = None
_SessionFactory = None


def _get_session_factory():
    """Lazy-init a shared async engine + session factory."""
    global _engine, _SessionFactory
    if _engine is None:
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.orm import sessionmaker
        _engine = create_async_engine(_async_db_url(), pool_size=8)
        _SessionFactory = sessionmaker(
            _engine, class_=AsyncSession, expire_on_commit=False,
        )
    return _SessionFactory


async def _update_materials_extracted(
    paper_id: str, materials: list[dict],
) -> None:
    """Write new materials_extracted JSON to the papers table."""
    from sqlalchemy import text
    import json

    Session = _get_session_factory()
    async with Session() as session:
        await session.execute(
            text("""
                UPDATE papers
                SET materials_extracted = :mats::jsonb,
                    updated_at = NOW()
                WHERE id = :pid
            """),
            {"mats": json.dumps(materials), "pid": paper_id},
        )
        await session.commit()


def _reconstruct_parsed(paper: dict) -> ParsedPaper | None:
    """Download source from GCS and parse into a ParsedPaper.

    Returns None if no source is available in GCS.
    """
    arxiv_id = paper["arxiv_id"]
    meta = PaperMetadata(
        arxiv_id=arxiv_id,
        title=paper["title"],
        authors=paper["authors"],
        abstract=paper["abstract"],
        date_submitted=paper["date_submitted"],
        categories=paper["categories"],
        primary_category=paper["categories"][0] if paper["categories"] else None,
        doi=paper["doi"],
    )
    yymm = meta.yymm

    # Try LaTeX source first, then fall back to abstract-only
    if storage.source_exists(arxiv_id, yymm):
        try:
            data = storage.download_source(arxiv_id, yymm)
            return parse_source_tarball(data, meta)
        except Exception as e:
            log.warning("%s: parse failed (%s) — using abstract-only", arxiv_id, e)
            return ParsedPaper(meta=meta, sections=[], has_latex_source=False)
    else:
        # No source archived — use abstract-only
        return ParsedPaper(meta=meta, sections=[], has_latex_source=False)


async def _process_one(
    paper: dict, semaphore: asyncio.Semaphore, dry_run: bool,
) -> tuple[str, int, float]:
    """Process a single paper. Returns (arxiv_id, n_materials, elapsed_s)."""
    async with semaphore:
        arxiv_id = paper["arxiv_id"]
        t0 = time.monotonic()

        try:
            parsed = await asyncio.to_thread(_reconstruct_parsed, paper)
            if parsed is None:
                return arxiv_id, 0, time.monotonic() - t0

            materials = await asyncio.to_thread(extract_materials, parsed)

            if not dry_run:
                await _update_materials_extracted(paper["paper_id"], materials)

            elapsed = time.monotonic() - t0
            return arxiv_id, len(materials), elapsed

        except Exception as e:
            log.error("%s: failed — %s", arxiv_id, e)
            return arxiv_id, -1, time.monotonic() - t0


async def main(
    limit: int | None = None,
    concurrency: int = 4,
    dry_run: bool = False,
    force: bool = False,
) -> None:
    log.info("Loading paper list from Postgres (skip_already_done=%s)…",
             not force)
    papers = await _load_papers(skip_already_done=not force)
    total = len(papers)

    if limit:
        papers = papers[:limit]
    log.info("Will %s %d/%d papers (concurrency=%d)",
             "DRY-RUN" if dry_run else "re-extract",
             len(papers), total, concurrency)

    if not papers:
        log.info("Nothing to do.")
        return

    sem = asyncio.Semaphore(concurrency)
    done = 0
    ok = 0
    total_materials = 0
    failed_ids: list[str] = []
    t_start = time.monotonic()

    # Process in batches of 50 for progress reporting
    batch_size = 50
    for i in range(0, len(papers), batch_size):
        batch = papers[i : i + batch_size]
        tasks = [_process_one(p, sem, dry_run) for p in batch]
        results = await asyncio.gather(*tasks)

        for arxiv_id, n_mat, elapsed in results:
            done += 1
            if n_mat >= 0:
                ok += 1
                total_materials += n_mat
            else:
                failed_ids.append(arxiv_id)

        elapsed_total = time.monotonic() - t_start
        rate = done / elapsed_total if elapsed_total > 0 else 0
        eta = (len(papers) - done) / rate if rate > 0 else 0
        log.info(
            "Progress: %d/%d (%.0f%%) | ok=%d fail=%d | "
            "materials=%d | %.1f papers/min | ETA %.0fm",
            done, len(papers), 100 * done / len(papers),
            ok, len(failed_ids),
            total_materials, rate * 60, eta / 60,
        )

    log.info("=" * 60)
    log.info(
        "%s COMPLETE: %d/%d papers, %d materials extracted, %d failed",
        "DRY-RUN" if dry_run else "RE-EXTRACTION",
        ok, len(papers), total_materials, len(failed_ids),
    )
    if failed_ids:
        log.info("Failed papers: %s", ", ".join(failed_ids[:20]))
        if len(failed_ids) > 20:
            log.info("  … and %d more", len(failed_ids) - 20)
    log.info("Elapsed: %.1f minutes", (time.monotonic() - t_start) / 60)

    # Clean up the shared DB engine
    if _engine is not None:
        await _engine.dispose()

    if not dry_run:
        log.info(
            "\nNext step: run aggregate-materials to rebuild the materials table:\n"
            "  sclib-ingest --mode aggregate-materials"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Re-run Gemini NER with the updated v2 prompt (family field).",
    )
    parser.add_argument("--limit", type=int, default=None,
                        help="Max papers to process (default: all)")
    parser.add_argument("--concurrency", type=int, default=4,
                        help="Max parallel Gemini calls (default: 4)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse + extract but don't write to DB")
    parser.add_argument("--force", action="store_true",
                        help="Re-extract even papers already done with new prompt")
    args = parser.parse_args()
    asyncio.run(main(
        limit=args.limit,
        concurrency=args.concurrency,
        dry_run=args.dry_run,
        force=args.force,
    ))
