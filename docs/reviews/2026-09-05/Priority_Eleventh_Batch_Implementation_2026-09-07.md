# Eleventh implementation batch — revision-aware shadow research import

Date: 2026-09-07. Branch: `codex/sclib-research-v2`.

Priority: [ML03 #61](https://github.com/JackZH26/SCLib_JZIS/issues/61), following
the ML01 checkpoint `9fb6139`. This is a bounded local implementation with
synthetic verification, not an operational canary, production backfill, or issue
closure. No production database, public website, source archive, vector index,
canonical scientific claim, or published ML dataset was modified.

## Why this is the next dependency

The offline exporter and typed-claim planner previously stopped at files. A
repeated capture needed to preserve the original source identity without
duplicating independent evidence; a new interpretation needed its own history
without rewriting a previously reviewed claim. ML01 now binds reviewed time
witnesses to exact claim content, so changing legacy claim metadata during
loading would also risk invalidating those witnesses.

This batch introduces an isolated shadow ledger. It deliberately leaves the
existing claim uniqueness boundary and public read model unchanged. The ledger
stores pending interpretations, not an alternative accepted Tc database.

## Delivered implementation

| Layer | Local delivery | Remaining boundary |
| --- | --- | --- |
| Schema | Additive migration `0053_research_import`; five append-only tables with exact composite links, content hashes and ten immutability triggers | No legacy uniqueness replacement or canonical event/state promotion |
| Offline verifier | Independently pinned source/plan manifests; bounded no-follow file capture; strict JSON; exact current-mapper replay and separate parity gate | Integrity is not source permission, processing approval or historical availability |
| Preview | Exact live exported-row comparison, accepted paper/work links, current governance, revision heads, and per-raw-occurrence disposition accounting | A forecast is not an authorized import |
| Internal loader | Reviewed preview/payload binding, clean `SERIALIZABLE` transaction, nonblocking advisory lock, savepoint rollback, insert-or-verify-identical writes | No public write endpoint, production CLI, automatic outer commit or authenticated reviewer UI |
| Revisions and receipts | Stable source occurrences, pending sequential interpretations, exact snapshot memberships, pinned post-load row hashes, zero-write historical replay | Repeated records are not replication; replay is not renewed scientific eligibility |
| Scientific parity | Unit-normalized Tc/pressure comparison, qualified negative upper bounds, complete original raw-record inventory | No automatic negative labels, ambient-pressure imputation or scientific acceptance |

The five shadow-only write targets are:

1. `research_import_snapshots`: verified source export identity and manifest.
2. `research_import_occurrences`: stable legacy source-record identity and links.
3. `research_import_revisions`: pending interpretation and exact predecessor.
4. `research_import_memberships`: exact snapshot/occurrence/revision and full raw
   records with their original ordinals.
5. `research_import_receipts`: reviewed plan binding, complete accounting and
   pinned persisted row identities/hashes.

The importer does not create works, accept bibliographic mappings, or insert
canonical `material_claims`, `source_snapshots`, research events, sample states,
structures, composition aggregates, temporal witnesses or releases. Existing
claim UUIDs remain stable references; a legacy claim row need not already exist.

## Scientific and identity safeguards

Only the mapper's documented derived annotations are excluded from source
identity. Full raw variants, including those annotations, remain in selected
memberships. Identity-bearing scientific or locator changes create a different
source occurrence. A changed interpretation appends a pending revision with an
exact predecessor rather than overwriting raw evidence. The same interpretation
can be reused under a later capture without duplicating a scientific result.
Historical memberships never silently move to the newest revision.

The parity audit now compares physical quantities in the same units: for
example, `39000 mK` against `39 K`, and `20 kbar`, `2000 MPa`, or `2e9 Pa` against
`2 GPa`. Explicit `<`/`<=` negative-result bounds are not treated as malformed
positive measurements. Missing/interval/bounded/ambiguous pressure and missing
Tc keep their original distinctions. Incomplete negative-result conditions
remain quarantined. None of these parser checks establish experimental truth.

Every original record is accounted for, including identical and derived-only
duplicates. A separate canonical JSONL inventory hash binds material IDs,
zero-based ordinals and complete original raw records, not only unique claims.
The accounting denominator is the sum of inserted, revised, reused,
quarantined and failed occurrences. Quarantined records are not silently selected;
their complete original provenance must be retained in the verified source bundle.

Legacy `available_at` proposals must remain null. Capture times, export
watermarks, bibliographic dates and source-provided annotations do not confer
result-level known-by time. Scientific approval, result/state association,
temporal witness review and training eligibility remain separate decisions.

## Review, transaction and failure behavior

The verifier reconstructs the received plan from captured source bytes and
rejects missing/tampered artifacts, unsupported versions, path aliases, duplicate
JSON keys, nonfinite values, incomplete accounting and plan failures. It
independently derives the non-authoritative convenience snapshot instead of
trusting `source_snapshots.jsonl`. The full verified payload receives its own
self-excluding fingerprint; this is an integrity binding, not authentication.

Preview compares every exported paper/material field with the live capture,
including unused papers and zero-record materials. Capture-level failure stops
preview; it does not manufacture a partial-success accounting report. A valid
preview separately reports record-level work-mapping, shape and governance
dispositions. Any failed occurrence prevents import. The complete forecast,
governance fingerprint, expected heads, payload and source/plan hashes must be
pinned by a separately registered internal-processing review artifact.

The service verifies that registered artifact's schema, declared verified hash,
exact review content and strict Boolean approval flags. It does not fetch the
external artifact bytes or authenticate a human; the trusted registration and
permissions workflow remains an operational prerequisite. Calling the review
payload helper or resealing an arbitrary dictionary grants no authority.

The loader takes a nonblocking transaction-scoped lock and owns only a savepoint
inside a dedicated caller-owned `SERIALIZABLE` transaction. Dry-run and errors
roll back its writes. Live success releases the savepoint but does not commit the
outer transaction. Busy/serialization failures require a fresh outer transaction.
Post-load checks reread exact shadow rows, compare expected fields/counts and
recompute hashes before recording the receipt. These storage checks supplement
offline semantic replay; they do not independently re-extract paper contents.

Receipt replay verifies the original review and pinned history and inserts zero
rows. It explicitly reports `current_eligibility_reassessed=false`. Later source
governance or interpretation changes do not rewrite a historical receipt.
UPDATE/DELETE/TRUNCATE are rejected on all five tables, and nonempty downgrade
fails closed. There is no generic delete-based post-commit rollback.

## Verification record

All database execution used the guarded disposable native PostgreSQL/Redis
runner, with capability-checked temporary services. External sources in tests
are synthetic; no real scientific gold dataset or provider verification is claimed.

Final integrated checks:

| Check | Result |
| --- | --- |
| API full suite | 1,500 passed; one pre-existing FastAPI `regex` deprecation warning |
| Ingestion full suite | 905 passed |
| Scripts | 102 passed, plus 36 separately reported subtests |
| Frontend source / unit suites | 35 / 245 passed |
| Total ordinary tests | 2,787 passed; excludes the 36 script subtests |
| TypeScript | `tsc --noEmit` passed |
| Migration rehearsal | Full head upgrade, empty downgrade/re-upgrade, legacy preservation and populated correction/source/shadow ledger downgrade refusal passed |
| Static checks | Scoped changed-module Ruff I/F and `git diff --check` passed |

The new API coverage includes 46 schema constraints/immutability checks and 45
loader/semantic cases. Baseline bundles actually pass the offline verifier;
some deliberately resealed in-memory fixtures simulate future independently
reviewed mapper outputs or rejection cases, not current-verifier approval of
another mapper version. Tests cover full dry-run table equality, committed
idempotence, repeated capture, revision chains, exact review binding, stale
governance/source/work mappings, source-row omissions, strict claim fields,
forced interruption and retry, nonblocking lock contention, unit/bound semantics,
and original-receipt replay after a newer interpretation exists.

No new browser/build acceptance or remote Linux/Docker CI run is claimed for this
backend-only batch. Website-owned copy remains English. Disposable services and
their temporary test data are removed by the guarded runner, not from any
production environment.

## Remaining acceptance gates and next priority

ML03 remains open. This bounded implementation is not an approved real canary.
Before using actual data, the following still require explicit operational and
scientific review:

1. A truthful controlled canary source capture or reviewed clone, accepted
   bibliographic work mappings, source-access/retention rights, independently
   registered processing review, backup and rollback/commit rehearsal.
2. Canary scope and representativeness. The verifier caps 1,000 raw occurrences,
   1,000 materials and 2,000 papers, plus byte/resource limits. The current
   exporter retains all papers and can exceed those limits; do not silently
   slice files, reseal counts or invent a capture identity to bypass the limit.
3. Explicit canonical result/event/state promotion and source-review
   correction/supersession contracts. Pending shadow interpretations do not
   solve ML01's historical witness amendment workflow.
4. Complete dependency closure and concurrency-safe release freezing (ML04),
   followed by release-only access and recursive permissions (ML07), reviewed
   pilot evidence (ML08), and leakage-safe task-specific datasets (ML06).
5. Real staging/production migrations and post-load legacy/API parity using the
   approved source capture. Development tests do not authorize those operations.

GitHub issue state was inspected but not changed. No push or deployment is
included. For the operational protocol and code entry points, see
[Bounded shadow research import](../../SHADOW_RESEARCH_IMPORT.md) and
[ML Foundation](../../ML_FOUNDATION_PHASE1.md).
