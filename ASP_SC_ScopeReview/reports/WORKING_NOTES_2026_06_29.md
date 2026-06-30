# Working Notes

## What Was Read

- Completed arXiv manuscript:
  `/Users/jackzhou/Documents/Superconductivity/Superconductivity_Scoping_Review/latex/Zhou_LLM-Extracted-Bibliometric-Scaffold-Superconductivity_2026.tex`
- arXiv stats macro file:
  `/Users/jackzhou/Documents/Superconductivity/Superconductivity_Scoping_Review/latex/sclib_2026_06_15_stats.tex`
- SCLib APS docs and scripts:
  - `docs/APS_INGESTION_PLAN.md`
  - `docs/APS_OPENCLAW_FULLTEXT_INGEST_RUNBOOK.md`
  - `docs/APS_VALIDATION_FOR_OPENCLAW.md`
  - `scripts/build_aps_superconductivity_manifest.py`
  - `scripts/build_aps_harvest_ready_yearly.py`
  - `ingestion/ingestion/aps_pipeline.py`
  - `ingestion/ingestion/aps_storage.py`
  - `ingestion/ingestion/aps_batch.py`
  - migrations `0038_aps_source_identity`, `0039_tdm_audit_log`

## Key arXiv Manuscript Lessons To Preserve

- Use frozen exports, not live services, for manuscript denominators.
- Separate corpus denominator from strict Tc denominator.
- Report validation as agreement diagnostics, not ground-truth accuracy.
- Carry interpretation classes through every result:
  value-conditional, selection-sensitive, coverage-conditioned.
- Treat null pressure as missing pressure, not ambient pressure.
- Keep `primary` evidence separate from `primary_experimental`.
- Do not overinterpret country participation counts as national capability.

## Key APS-Specific Lessons

- APS full text is transient TDM input only.
- Persistent APS outputs are metadata, abstract, derived structured
  records, fact chunks, and deletion audit logs.
- The APS freeze has to include compliance evidence, not just scientific
  data.
- The candidate DOI universe is larger than the successfully ingested
  manuscript corpus.
- The final paper should be a peer-reviewed-corpus replication and
  arXiv-vs-APS comparison.

## User Corrections Incorporated

- APS validation sample is Golden-400, not Golden-500, to match the arXiv
  study design and make comparison cleaner.
- Geography is a central manuscript component. The APS paper should map
  country/region-specific superconductivity research focus and timelines,
  not only report aggregate country counts.
