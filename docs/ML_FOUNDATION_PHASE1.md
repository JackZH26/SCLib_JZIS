# SCLib ML Foundation v1

Original foundation schema: `0044_ml_foundation`

Original design date: 2026-08-20

Additive shadow import increment: `0053_research_import` (ML03 / #61)

## Purpose

Phase 1 turns the existing `materials.records` JSONB feed into an auditable,
condition-aware foundation for future ML datasets without replacing the
production read path. The first release optimizes for provenance, explicit
missingness, work-level deduplication, and reproducible splits. It does not
claim that legacy extracted records are automatically ML labels.

The legacy JSONB data and API remain authoritative while the new path runs in
shadow mode.

## Foundation model and implemented shadow boundary

The diagram below describes the foundation model, not an automatically
approved loading or ML-release pipeline:

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

ML03 adds five separate append-only `research_import_*` tables for verified
capture snapshots, stable source occurrences, pending interpretation revisions,
exact snapshot memberships, and immutable import receipts. The bounded internal
loader writes **only** those five tables; it does not populate the canonical
tables in the diagram, apply work proposals, update composition aggregates, or
promote Tc/state/event copies. See [Bounded shadow research import](SHADOW_RESEARCH_IMPORT.md)
for the exact verification, review, transaction and canary protocol.

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
server-side cursors, and stable primary-key ordering. Source capture requires
separate environment authorization; this document supplies no production
connection or import invocation. Verify an already captured local bundle with:

```bash
api/.venv/bin/python scripts/export_ml_foundation_snapshot.py verify \
  --bundle /absolute/local/source-export
```

`DATABASE_URL` is read only from the environment and is never copied into the
manifest or logs. Its default legacy SQL export predicate excludes
NIMS-quarantined, `needs_review`, and zero-paper skeleton rows; this predicate
is not the complete current public-visibility or scientific-eligibility policy.
The shadow loader separately checks live governance before selecting records.
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
mode `0700`, and artifacts are mode `0600`. `source_snapshots.jsonl` is an
unchecksummed convenience proposal created after the plan manifest. The ML03
offline verifier independently derives the expected snapshot from pinned
source/plan manifests and replayed counts, and requires that file to match.
The shadow loader does not insert the proposal into legacy `source_snapshots`.

The hard shadow-parity report independently proves source-record accounting
and independently replays formula enrichment, accepted persisted work
identity, paper/work links, typed-claim mapping, snapshot lineage, retraction
propagation, Tc, pressure, explicit negative results, non-finite values, and
deterministic distributions. Timeline and material-headline parity are
explicitly deferred:
the typed v1 schema does not yet carry every legacy year and `tc_regime`
policy input. The proposed source snapshot therefore remains `building` even
when the offline hard gate passes. Neither a successful shadow dry-run nor a
committed shadow receipt advances it to `validated`/`frozen`. Scientific QC,
source-rights review, release policy and canonical promotion remain separate
unimplemented approval transitions in this increment.

If a source export contains an existing `paper_work_map`, only `accepted`
mappings are authoritative identity edges. `pending` and `rejected` mappings
remain in the warning audit; their old work IDs and decisions are not silently
transferred to a newly resolved pair.

Before a shadow import, the live material/paper/work must exist and the live
paper/work mapping must be `accepted` and agree with the proposal. The loader
does not create missing works or adjudicate proposed merges. Every shadow
interpretation remains `pending`; source capture and temporal diagnostics do
not confer known-by availability or accepted scientific labels.

## Read-only API

Migration 0044 introduced the following additive endpoints. The ML07 upgrade
restricts them to authenticated, explicitly authorized research operators; the
global feature switch alone no longer permits anonymous access:

- `GET /v1/claims`
- `GET /v1/claims/{claim_id}`
- `GET /v1/materials/{material_id}/claims`
- `GET /v1/works/{work_id}`
- `GET /v1/ml/source-snapshots`
- `GET /v1/ml/snapshots`
- `GET /v1/ml/snapshots/{snapshot_id}/manifest`

Claim collections use a UUID keyset cursor. The global claim endpoint applies
the same NIMS provenance quarantine as the existing materials API. Raw legacy
records and licensed source text are intentionally excluded from typed claim
responses.

ML01 adds an optional timezone-aware, inclusive `cutoff` to the two claim
collection routes, using only server-resolved source-version witnesses. Each
claim exposes a `temporal_provenance` assessment; `available_at` is a qualified
known-by UTC date or null, while `legacy_available_at` preserves the old,
unverified hint. This is a live filter, not an immutable historical snapshot or
ML-release approval. See [Temporal consumers](TEMPORAL_CONSUMERS.md) for trust
boundaries, dependency propagation and remaining release gates.

All ML Foundation routes fail closed with HTTP 404 while
`ML_FOUNDATION_PUBLIC_ENABLED=false` (the default). When enabled, these seven
raw routes additionally require a valid JWT/browser session, active verified
account and explicit unrevoked research role. Building/frozen JSON status is
not public release authority. Separate `/v1/ml/releases` routes expose only
independently admitted, metadata-only publication bodies. No scientific values
or training examples are released by that v1 policy. See
[Research publication access](RESEARCH_PUBLICATION_ACCESS.md); production still
requires separately approved source rights, review and rollout gates.

## Controlled operational acceptance order

1. Take and hash a database backup; record the dataset version and row counts.
2. Review and apply required migrations, including `0053_research_import`, only
   in the explicitly authorized disposable/canary environment.
3. Run and verify the single-transaction source exporter.
4. Run the offline planner only through `--source-export-manifest`.
5. Review formula status, work merges, mapper warnings, exact duplicates, and
   all failures. Run a distinct-formula audit for acronym/shorthand values
   misclassified as exact; known cuprate and claim shorthands must remain
   unresolved. Do not load a plan with unexplained failures.
6. Run the ML03 offline verifier with independently pinned source and plan
   hashes. Preview through the internal service and independently review the
   complete payload, preview/governance hash, selections and accounting.
7. Rehearse the separately approved **shadow-only** loader in a clean
   `SERIALIZABLE` transaction with full dry-run rollback. A non-dry run still
   requires caller-controlled outer commit; interpretation rows remain pending.
8. Compare typed rows with the legacy read path in shadow mode before enabling
   any public or ML export.
9. Create ML snapshots only after work/material/series/time leakage tests pass.

No production migration or backfill is performed by the development changes
in this branch.

The Phase-1 API remains read-only. The five new shadow tables reject
update/delete/truncate, and migration downgrade refuses a populated ledger.
These safeguards do not retroactively make legacy `source_snapshots` or
`ml_dataset_snapshots` immutable, nor protect against administrators disabling
database safeguards. A shadow receipt records historical processing, not a
frozen ML release or current eligibility.

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

The current increment provides an internal shadow writer but does not itself
load a real bundle into staging or production. Canonical v1 claim promotion
remains separate because existing claims have one source-snapshot lineage and
works/compositions do not carry this shadow load's ownership. Shadow writes use
insert-or-verify-identical semantics, a savepoint within a caller-owned clean
`SERIALIZABLE` transaction, full dry-run rollback, nonblocking advisory-lock
failure/retry, and no overwrite or generic post-commit delete rollback.

Canary verification is bounded to 1,000 raw occurrences, 1,000 materials and
2,000 papers, with separate byte limits. The existing full exporter may exceed
those limits because it retains every paper. Do not silently slice/reseal a
full export. An authorized controlled canary export or reviewed clone with
truthful provenance remains an operational gate. Public routes, production
import CLI, scientific acceptance, ML readiness and automatic known-by transfer
are not added by ML03; see the [shadow import protocol](SHADOW_RESEARCH_IMPORT.md).
