"""Re-run Gemini NER on specific papers already in Postgres.

One-shot admin tool, not part of the daily cron. Used to retrofit
older papers with the new NER prompt (in particular the
``evidence_type = primary | cited`` field introduced after the
YLuH₁₂ citation-conflation bug). Reconstructs the ParsedPaper
input from the DB (title + abstract + chunks) so the tool does not
have to re-download the arXiv source.

Usage::

    docker compose run --rm ingestion python -m ingestion.rener \\
      arxiv:2604.17712 arxiv:2603.22662 ...

At the end the script invokes ``aggregate_from_papers`` so the
materials table picks up the fresh ``materials_extracted`` values
in the same run. Safe to re-run; idempotent per paper.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Any

from sqlalchemy import select, update

from ingestion.extract.material_ner import extract_materials
from ingestion.extract.materials_aggregator import aggregate_from_papers
from ingestion.index.indexer import (
    _session_factory,
    chunks_table,
    dispose,
    papers_table,
)
from ingestion.models import PaperMetadata, ParsedPaper, Section

log = logging.getLogger("sclib.rener")


async def _rebuild_parsed(session, paper_id: str) -> ParsedPaper | None:
    """Read the paper + its chunks from Postgres and reassemble a
    minimal ParsedPaper so ``extract_materials`` can run without
    touching arXiv / GCS."""
    r = (await session.execute(
        select(
            papers_table.c.id,
            papers_table.c.arxiv_id,
            papers_table.c.title,
            papers_table.c.abstract,
            papers_table.c.authors,
            papers_table.c.date_submitted,
            papers_table.c.categories,
        ).where(papers_table.c.id == paper_id)
    )).first()
    if r is None:
        log.warning("%s: not found in papers table", paper_id)
        return None

    # Reassemble sections: one Section per distinct chunks.section,
    # text = chunks concatenated in chunk_index order. Matches what
    # the parser would have produced originally.
    chunk_rows = (await session.execute(
        select(chunks_table.c.section, chunks_table.c.chunk_index, chunks_table.c.text)
        .where(chunks_table.c.paper_id == paper_id)
        .order_by(chunks_table.c.section, chunks_table.c.chunk_index)
    )).all()

    sections_by_name: dict[str, list[str]] = {}
    for sec_name, _idx, text in chunk_rows:
        sections_by_name.setdefault(sec_name or "Body", []).append(text)
    sections = [Section(name=n, text="\n".join(parts))
                for n, parts in sections_by_name.items()]

    meta = PaperMetadata(
        arxiv_id=r.arxiv_id or r.id.replace("arxiv:", ""),
        title=r.title,
        authors=list(r.authors or []),
        abstract=r.abstract,
        date_submitted=r.date_submitted,
        categories=list(r.categories or []),
        primary_category=None,
    )
    return ParsedPaper(meta=meta, sections=sections)


async def rener_one(session, paper_id: str) -> dict[str, Any]:
    parsed = await _rebuild_parsed(session, paper_id)
    if parsed is None:
        return {"paper_id": paper_id, "ok": False, "reason": "missing"}
    # NER is a blocking Gemini call; keep it off the event loop.
    materials = await asyncio.to_thread(extract_materials, parsed)
    await session.execute(
        update(papers_table)
        .where(papers_table.c.id == paper_id)
        .values(materials_extracted=materials)
    )
    await session.commit()

    # Diagnostic: breakdown by evidence_type so a human can tell at a
    # glance whether the new prompt did its job.
    primary = sum(1 for m in materials if m.get("evidence_type") == "primary")
    cited = sum(1 for m in materials if m.get("evidence_type") == "cited")
    unset = sum(1 for m in materials if "evidence_type" not in m)
    log.info(
        "%s: re-NER → %d records (primary=%d cited=%d unset=%d)",
        paper_id, len(materials), primary, cited, unset,
    )
    return {
        "paper_id": paper_id, "ok": True,
        "n_records": len(materials),
        "primary": primary, "cited": cited, "unset": unset,
    }


async def main_async(paper_ids: list[str], run_aggregator: bool) -> int:
    Session = _session_factory()
    results: list[dict[str, Any]] = []
    async with Session() as db:
        for pid in paper_ids:
            try:
                r = await rener_one(db, pid)
            except Exception as e:  # noqa: BLE001
                log.exception("rener failed for %s", pid)
                r = {"paper_id": pid, "ok": False, "reason": str(e)}
            results.append(r)

    ok = sum(1 for r in results if r.get("ok"))
    log.info("rener summary: %d/%d ok", ok, len(paper_ids))

    if run_aggregator and ok > 0:
        log.info("running aggregator to propagate updated NER output…")
        n = await aggregate_from_papers()
        log.info("aggregator: %d materials upserted", n)

    await dispose()
    return 0 if ok == len(paper_ids) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paper_ids", nargs="+",
                        help="arxiv:... paper IDs to re-NER")
    parser.add_argument("--skip-aggregate", action="store_true",
                        help="Don't run aggregate_from_papers at the end")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return asyncio.run(main_async(args.paper_ids, not args.skip_aggregate))


if __name__ == "__main__":
    sys.exit(main())
