# SCLib ML Foundation v1

Status: implementation branch `codex/sclib-ml-foundation-v1`
Schema revision: `0044_ml_foundation`
Design date: 2026-08-20

## Purpose

Phase 1 turns the existing `materials.records` JSONB feed into an auditable,
condition-aware foundation for future ML datasets without replacing the
production read path. The first release optimizes for provenance, explicit
missingness, work-level deduplication, and reproducible splits. It does not
claim that legacy extracted records are automatically ML labels.

The legacy JSONB data and API remain authoritative while the new path runs in
shadow mode.

## Implemented data flow

```text
papers -----------------------> works + paper_work_map
                                  |
materials.records -- mapper ----> material_claims -- QC --> ML snapshot/examples
       |
       +-- formula parser ------> materials.composition_*
```

The new tables are:

- `source_snapshots`: versioned lineage anchor for a captured database state;
- `works` and `paper_work_map`: one scholarly work across arXiv/publisher
  versions;
- `material_claims`: typed Tc or explicit non-transition observations with
  pressure, sample, evidence, provenance, and value-relation semantics;
- `claim_qc`: automated and human review state kept separate from source data;
- `ml_dataset_snapshots`: versioned label/feature/split policy manifest;
- `ml_examples`: frozen examples carrying work, material, series, chemical
  system, and duplicate grouping keys.

`materials` gains only nullable `composition_status`, `composition_data`, and
`composition_enriched_at` columns. Exact formulas receive deterministic
composition descriptors. Variable formulas, interfaces, mixtures, and invalid
inputs remain explicitly non-exact.

## Safety invariants

- Missing pressure stays missing; it is never rewritten as ambient pressure.
- A legacy numeric `0 GPa` without independent ambient evidence is
  `ambiguous`, not `explicit_ambient`.
- Missing Tc is unknown, not a negative label.
- An accepted `not_detected` claim must have a minimum measurement
  temperature.
- Exact, interval, lower-bound, and upper-bound values are represented
  separately.
- Retraction state propagates from the source paper to the claim.
- DOI/arXiv/title metadata is never used as a physical model feature.
- Work matching uses exact DOI, explicit related-paper links, exact canonical
  arXiv IDs, or singleton fallback. Title fuzzy matching is not used.
- Existing `materials.records`, existing endpoints, and current aggregates are
  not deleted or rewritten by migration 0044.

## Review-only backfill planning

The initial planner is deliberately offline and never connects to PostgreSQL.
Export stable database-side JSONL snapshots first, then run:

```bash
ingestion/.venv/bin/python scripts/plan_typed_claim_backfill.py \
  --materials-jsonl /path/to/materials.jsonl \
  --papers-jsonl /path/to/papers.jsonl \
  --source-snapshot-id 11111111-1111-4111-8111-111111111111 \
  --dataset-version v2026.08.20 \
  --site-git-sha d26fc098565492b78b416fb30b6b1ec7087b24c7 \
  --chunk-count 1116128 \
  --output-dir /path/to/review-plan
```

Run this from the repository root after creating the ingestion virtual
environment. The planner requires Python 3.11 or newer; do not rely on a
system `python` whose version is unknown.

It writes deterministic `works.jsonl`, `paper_work_map.jsonl`, `claims.jsonl`,
`compositions.jsonl`, `failures.jsonl`, `warnings.jsonl`, and `summary.json`.
It also writes a hashed `manifest.json` and one proposed
`source_snapshots.jsonl` row. The command performs no database writes.
Repeated inputs produce stable claim UUIDs and hashes. Incremental runs should
pass the current paper/work export through `--existing-paper-work-jsonl` so a
later arXiv/publisher link cannot change an established work UUID.
That export must include `review_status` (and should retain `match_method` and
`relation_type`). Only `accepted` mappings are authoritative identity edges;
`pending` and `rejected` mappings are retained in the planner warning audit,
but their old work IDs and review decisions are not transferred to a newly
resolved paper/work pair.

## Read-only API

Migration 0044 enables the following additive endpoints:

- `GET /v1/claims`
- `GET /v1/claims/{claim_id}`
- `GET /v1/materials/{material_id}/claims`
- `GET /v1/works/{work_id}`
- `GET /v1/ml/source-snapshots`
- `GET /v1/ml/snapshots`
- `GET /v1/ml/snapshots/{snapshot_id}/manifest`

Claim collections use a UUID keyset cursor. The global claim endpoint applies
the same NIMS provenance quarantine as the existing materials API. Raw legacy
records and licensed source text are intentionally excluded from public claim
responses.

All ML Foundation routes fail closed with HTTP 404 while
`ML_FOUNDATION_PUBLIC_ENABLED=false` (the default). Staging may enable the flag
for shadow validation; production must not enable it until typed-claim QC,
license review, and legacy/typed parity gates have passed.

## Deployment order

1. Take and hash a database backup; record the dataset version and row counts.
2. Apply revision `0044_ml_foundation` in staging.
3. Run the offline planner against a stable database-side export.
4. Review formula status, work merges, mapper warnings, exact duplicates, and
   all failures. Run a distinct-formula audit for acronym/shorthand values
   misclassified as exact; known cuprate and claim shorthands must remain
   unresolved. Do not load a plan with unexplained failures.
5. Implement and canary an idempotent database writer in the order
   `source_snapshots -> works -> paper_work_map -> material_claims`.
6. Keep every loaded legacy claim `pending` until QC policy accepts it.
7. Compare typed rows with the legacy read path in shadow mode before enabling
   any public or ML export.
8. Create ML snapshots only after work/material/series/time leakage tests pass.

No production migration or backfill is performed by the development changes
in this branch.

The Phase-1 API is read-only and the loader policy must reject changes to a
frozen snapshot. Database-level triggers that prevent a privileged operator
from updating an already-frozen snapshot are intentionally deferred; until
those are added, “frozen” is an application and release-process invariant,
not an absolute PostgreSQL immutability guarantee.

## Acceptance gates before ML training

- every source record is mapped or has a machine-readable failure reason;
- repeated backfill planning is hash-identical;
- same-work arXiv/publisher versions cannot cross a dataset split;
- material/parent-series/duplicate groups cannot cross a configured split;
- no retracted claim enters the default training core;
- no unknown pressure becomes `0 GPa`;
- no missing observation becomes a negative sample;
- no audited material shorthand is emitted as an exact composition;
- every frozen snapshot has a manifest hash and source snapshot;
- feature policy is allowlist-based and excludes target-bearing text and
  material-level Tc aggregates.

## Explicitly deferred

Phase 1 does not rebuild the vector index, re-run all NER, resolve every
polymorph, import DFT/DFPT/EPC results, create full structure graphs, or train a
discovery model. Those activities depend on a reviewed claim layer and a
separate structure/calculation manifest.
