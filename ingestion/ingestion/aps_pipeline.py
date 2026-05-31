"""APS ingestion orchestrator (TDM-compliant).

The APS counterpart of ``ingestion.pipeline``, but with a fundamentally
different storage posture: APS full text is **transient** working data.
Per the APS agreement the only persistent outputs are (a) authorized
metadata/abstract and (b) extracted structured data — the raw Licensed
Materials (BagIt ZIP, full-text XML, PDF, OCR) are deleted immediately
after NER and a ``tdm_audit_log`` row proves it.

Per-paper flow (process_aps_paper):

    Harvest API: authorized metadata + abstract            [persistent]
      → download BagIt ZIP                                  [transient]
      → extract to 0700 tmpfs temp dir                      [transient]
      → parse JATS <body> → ParsedPaper(sections)           [transient, in-RAM]
      → material NER on full text → materials_extracted     [persistent]
      → ★ force-delete temp dir + verify gone               [deletion proof]
      → build AUTHORIZED chunks (abstract only; fact-
        sentences added in Phase 5) — never full-text body
      → embed + Vertex VS upsert (source='aps' restrict)    [persistent, authorized]
      → upsert papers(source='aps', journal, doi) + chunks  [persistent]
      → DOI overlap → link related arXiv preprint
      → write tdm_audit_log (DOI, timestamps, deletion)     [persistent proof]

CRITICAL INVARIANTS:
* The full-text ParsedPaper feeds NER only. It is NEVER chunked into
  Postgres ``chunks.text`` or Vertex VS. Vectorised/stored chunks come
  from the authorized abstract (+ Phase-5 fact sentences) exclusively.
* APS content never touches GCS (no ``ingestion.storage`` calls here).
* The temp dir is force-deleted in TempBagit.__exit__ even on error, and
  an audit row is always written (status='deleted' or 'error').

CLI (for VPS2 validation — the egress IP must be on the APS allow-list):

    python -m ingestion.aps_pipeline --doi 10.1103/PhysRevB.104.014501 -v
    python -m ingestion.aps_pipeline --doi <DOI> --dry-run   # parse+NER+delete, no DB/VS
    python -m ingestion.aps_pipeline --doi <DOI> --skip-vector-search
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from ingestion.aps_storage import TdmAudit, TempBagit, write_audit_log
from ingestion.collect.aps_harvest import ApsClient
from ingestion.chunk.chunker import chunk_paper
from ingestion.embed.embedder import embed_chunks
from ingestion.extract.material_ner import extract_materials
from ingestion.index.indexer import (
    dispose,
    find_related_arxiv_paper,
    upsert_aps_chunks_to_vector_search,
    upsert_aps_paper_with_chunks,
)
from ingestion.models import ApsArticleMeta, ParsedPaper
from ingestion.parse.aps_xml import parse_bagit_dir

log = logging.getLogger("ingestion.aps_pipeline")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _build_authorized_chunks(meta: ApsArticleMeta) -> list[Any]:
    """Build the chunks that are allowed to persist / be vectorised.

    Phase 4: the authorized abstract only. ``chunk_paper`` on a
    sections-less ParsedPaper hits its abstract-only fallback, producing
    one ``Section: Abstract`` chunk keyed ``aps:{doi}_chunk_000``.

    Phase 5 (extract/fact_sentences) will extend this with NER
    fact-sentence chunks. Deliberately does NOT take the full-text
    ParsedPaper — that body must never be chunked.
    """
    abstract_only = ParsedPaper(meta=meta, sections=[], has_latex_source=False)
    return chunk_paper(abstract_only)


async def process_aps_paper(
    client: ApsClient,
    doi: str,
    *,
    skip_vector_search: bool = False,
    skip_ner: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run the full TDM-compliant per-paper pipeline for one DOI.

    ``dry_run`` exercises harvest → parse → NER → delete → audit but skips
    all persistence (DB + VS) — useful to validate the compliance loop
    without mutating the catalogue. Returns a summary dict; the audit row
    is always written (even on failure) unless ``dry_run`` is set, in
    which case the audit is logged but not persisted.
    """
    result: dict[str, Any] = {"doi": doi, "ok": False, "dry_run": dry_run}
    audit = TdmAudit(doi=doi)
    work: TempBagit | None = None

    try:
        # 1. Authorized metadata (persistent slice).
        audit.harvested_at = _now()
        meta = await client.get_article(doi)
        audit.paper_id = meta.paper_id
        result["paper_id"] = meta.paper_id
        result["journal_abbrev"] = meta.journal_abbrev
        log.info("%s: harvested metadata (%s, %s)",
                 doi, meta.journal_abbrev, meta.title[:60])

        # 2-4. Transient full text → NER, then forced deletion.
        materials: list[dict[str, Any]] = []
        with TempBagit(meta.doi_slug) as work:
            zip_bytes = await client.download_bagit(doi)
            work.extract(zip_bytes)
            parsed_full = parse_bagit_dir(work.root, meta)
            result["n_sections"] = len(parsed_full.sections)
            if not skip_ner:
                # NER is a blocking Gemini call — keep it off the loop.
                materials = await asyncio.to_thread(extract_materials, parsed_full)
            audit.processed_at = _now()
            audit.ner_record_count = len(materials)
            # parsed_full (full text, in RAM) goes out of scope at block end;
            # the on-disk copy is force-deleted by TempBagit.__exit__ next.
        # --- temp dir is now purged + verified ---
        result["n_materials"] = len(materials)
        result["deletion_confirmed"] = work.deleted
        if not work.deleted:
            log.error("%s: COMPLIANCE — temp dir not confirmed deleted!", doi)

        # 5. Authorized chunks (abstract only — never full-text body).
        chunks = _build_authorized_chunks(meta)
        result["n_chunks"] = len(chunks)

        if dry_run:
            audit.status = "deleted"
            audit.from_temp(work)
            log.info("%s: DRY RUN — skipping DB/VS. audit=%s", doi, audit.to_values())
            result["ok"] = True
            return result

        # 6. Embed (only if we intend to upsert vectors).
        if not skip_vector_search and chunks:
            await asyncio.to_thread(embed_chunks, chunks)

        # 7. Cross-source DOI link to an existing arXiv preprint.
        related_id = await find_related_arxiv_paper(doi)
        result["related_arxiv"] = related_id

        # 8. Persist authorized data: paper + chunks (source='aps').
        await upsert_aps_paper_with_chunks(
            meta, chunks, materials, related_paper_id=related_id,
        )

        # 9. Vertex VS upsert (source='aps' restrict).
        if not skip_vector_search and chunks:
            await asyncio.to_thread(upsert_aps_chunks_to_vector_search, meta, chunks)

        audit.status = "deleted"
        result["ok"] = True
        return result

    except Exception as e:  # noqa: BLE001 — record (incl. ApsError) then summarise
        audit.status = "error"
        audit.error = str(e)[:1000]
        result["error"] = str(e)
        log.exception("%s: APS pipeline failed: %s", doi, e)
        return result
    finally:
        # The temp dir is already purged by the context manager; copy its
        # deletion facts into the audit and persist the proof (unless this
        # was a dry run, where we logged it above instead).
        if work is not None:
            audit.from_temp(work)
        if not dry_run:
            try:
                await write_audit_log(audit)
            except Exception as e:  # noqa: BLE001
                log.error("%s: failed to write tdm_audit_log: %s", doi, e)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

async def _run(dois: list[str], **kw: Any) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    try:
        async with ApsClient() as client:
            for doi in dois:
                r = await process_aps_paper(client, doi, **kw)
                _print_status(r)
                results.append(r)
    finally:
        await dispose()
    return results


def _print_status(r: dict[str, Any]) -> None:
    status = "OK " if r.get("ok") else "ERR"
    if r.get("ok"):
        extra = (f"journal={r.get('journal_abbrev')} secs={r.get('n_sections')} "
                 f"mats={r.get('n_materials')} chunks={r.get('n_chunks')} "
                 f"deleted={r.get('deletion_confirmed')} "
                 f"related_arxiv={r.get('related_arxiv')}")
    else:
        extra = f"err={r.get('error', '?')[:120]}"
    log.info("[%s] %s — %s", status, r["doi"], extra)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--doi", action="append", dest="dois", required=True,
                        help="APS DOI to ingest (repeatable). Accepts bare "
                             "10.1103/... or a doi.org URL.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Harvest+parse+NER+delete+audit, but no DB/VS writes.")
    parser.add_argument("--skip-vector-search", action="store_true",
                        help="Persist paper+chunks but skip embed + Vertex VS.")
    parser.add_argument("--skip-ner", action="store_true",
                        help="Skip Gemini material NER (smoke test).")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )

    # Normalise doi.org URLs / "doi:" prefixes to a bare DOI.
    dois = [_normalize_doi(d) for d in args.dois]

    results = asyncio.run(_run(
        dois,
        skip_vector_search=args.skip_vector_search,
        skip_ner=args.skip_ner,
        dry_run=args.dry_run,
    ))
    ok = sum(1 for r in results if r.get("ok"))
    log.info("done: %d/%d ok", ok, len(results))
    return 0 if ok == len(results) else 1


def _normalize_doi(doi: str) -> str:
    d = doi.strip()
    for pre in ("https://doi.org/", "http://doi.org/", "doi:"):
        if d.lower().startswith(pre):
            return d[len(pre):]
    return d


if __name__ == "__main__":
    sys.exit(main())
