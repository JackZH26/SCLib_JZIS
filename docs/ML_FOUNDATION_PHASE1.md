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

## Stable source export

Do not build an ML snapshot from the public offset API or from separate
`psql` commands. Those reads do not share one database snapshot. The Phase-1
exporter uses one PostgreSQL `REPEATABLE READ READ ONLY` transaction,
server-side cursors, and stable primary-key ordering:

```bash
DATABASE_URL='postgresql://...' api/.venv/bin/python \
  scripts/export_ml_foundation_snapshot.py export \
  --output-dir /secure/sclib-exports/v2026.08.20 \
  --dataset-version v2026.08.20 \
  --site-git-sha d26fc098565492b78b416fb30b6b1ec7087b24c7

api/.venv/bin/python scripts/export_ml_foundation_snapshot.py verify \
  --bundle /secure/sclib-exports/v2026.08.20
```

`DATABASE_URL` is read only from the environment and is never copied into the
manifest or logs. The default export scope matches the public material list:
NIMS-quarantined, `needs_review`, and zero-paper skeleton rows are excluded.
All paper rows are retained so every exported record can resolve its source.
The million-row chunk text/vector inventory is not exported; only its count is
bound to the snapshot.

The exporter and verifier share one exact JSONL field contract for materials,
papers, and paper/work mappings. Missing fields and unknown fields are both
rejected, so a bundle cannot be made to pass by inserting abstracts, authors,
chunk text, or another undeclared payload and then recomputing its checksums.

The exporter publishes a directory atomically only after it has written and
re-verified `materials.jsonl`, `papers.jsonl`, optional
`paper_work_map.jsonl`, `license_manifest.json`, `export_manifest.json`, and
their checksums. A production/staging container must receive a dedicated,
mode-0700 writable export volume before this command is used there; the
repository script mount is intentionally read-only.

## Review-only backfill planning

The initial planner is deliberately offline and never connects to PostgreSQL.
Export stable database-side JSONL snapshots first, then run:

```bash
ingestion/.venv/bin/python scripts/plan_typed_claim_backfill.py \
  --source-export-manifest \
    /secure/sclib-exports/v2026.08.20/export_manifest.json \
  --output-dir /path/to/review-plan
```

Run this from the repository root after creating the ingestion virtual
environment. The planner requires Python 3.11 or newer; do not rely on a
system `python` whose version is unknown.

Manifest mode verifies the source manifest sidecar, every leaf-file hash,
byte/row count, safe relative path, capture UUID, database watermark, schema
revision, and license manifest. It is strictly mutually exclusive with the
legacy manual source arguments, so capture metadata cannot be accidentally
paired with different JSONL bytes.

The planner writes deterministic `works.jsonl`, `paper_work_map.jsonl`,
`claims.jsonl`, `compositions.jsonl`, `failures.jsonl`, `warnings.jsonl`,
`summary.json`, and `parity_report.json`. It also writes a hashed
`manifest.json` and one proposed `source_snapshots.jsonl` row. The command
performs no database writes. Repeated inputs produce stable claim UUIDs,
work identities, reports, and manifest hashes.

Plan publication is atomic and fail-closed: the final directory must not
already exist, partial directories are removed on failure, the directory is
mode `0700`, and artifacts are mode `0600`. `source_snapshots.jsonl` is a
convenience proposal created after the plan manifest; a future loader must
derive and verify the authoritative snapshot row from the reviewed manifest
rather than trusting that convenience file by itself.

The hard shadow-parity report independently proves source-record accounting
and independently replays formula enrichment, accepted persisted work
identity, paper/work links, typed-claim mapping, snapshot lineage, retraction
propagation, Tc, pressure, explicit negative results, non-finite values, and
deterministic distributions. Timeline and material-headline parity are
explicitly deferred:
the typed v1 schema does not yet carry every legacy year and `tc_regime`
policy input. The proposed source snapshot therefore remains `building` even
when the offline hard gate passes. Only license review, an idempotent database
dry-run, and post-load parity may advance it to `validated`/`frozen`.

If a source export contains an existing `paper_work_map`, only `accepted`
mappings are authoritative identity edges. `pending` and `rejected` mappings
remain in the warning audit; their old work IDs and decisions are not silently
transferred to a newly resolved pair.

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
3. Run and verify the single-transaction source exporter.
4. Run the offline planner only through `--source-export-manifest`.
5. Review formula status, work merges, mapper warnings, exact duplicates, and
   all failures. Run a distinct-formula audit for acronym/shorthand values
   misclassified as exact; known cuprate and claim shorthands must remain
   unresolved. Do not load a plan with unexplained failures.
6. Implement and canary an idempotent database writer in the order
   `source_snapshots -> works -> paper_work_map -> material_claims`.
7. Keep every loaded legacy claim `pending` until QC policy accepts it.
8. Compare typed rows with the legacy read path in shadow mode before enabling
   any public or ML export.
9. Create ML snapshots only after work/material/series/time leakage tests pass.

No production migration or backfill is performed by the development changes
in this branch.

The Phase-1 API is read-only and the loader policy must reject changes to a
frozen snapshot. Database-level triggers that prevent a privileged operator
from updating an already-frozen snapshot are intentionally deferred; until
those are added, “frozen” is an application and release-process invariant,
not an absolute PostgreSQL immutability guarantee.

## Acceptance gates before ML training

- every source record is mapped or has a machine-readable failure reason;
- source JSONL files come from one read-only repeatable-read transaction;
- source/plan manifests and all leaf-file hashes verify byte-for-byte;
- hard shadow parity reports `pass` with no unexplained failure group;
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

The current increment also does not load a bundle into staging or production.
The database writer remains a separate gate because v1 claims have one source
snapshot lineage and existing works/compositions do not yet carry load-run
ownership. Its required policy is `insert-or-verify-identical`, one
`SERIALIZABLE` transaction, full dry-run rollback, no overwrite upsert, and no
generic post-commit delete rollback.
