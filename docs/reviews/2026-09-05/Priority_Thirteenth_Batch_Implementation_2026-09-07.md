# Thirteenth implementation batch — research access and metadata publication

Date: 2026-09-07. Branch: `codex/sclib-research-v2`.
Base checkpoint: `44a12bf` (ML04 freeze and EN02 schema admission).
Priority: [ML07 #68](https://github.com/JackZH26/SCLib_JZIS/issues/68).

This is a bounded local security/publication implementation. ML07 remains open
for scientific-value projections, real permission/human review, curator workflow
and operational acceptance. No production migration, role provisioning, source
redistribution, public feature activation, push or deployment was performed.

## Outcome and scope choice

The global research feature flag previously admitted anonymous reads to raw
claims, works and snapshots, including direct IDs and optional unfrozen/archive
filters. It now acts only as a kill switch. All seven original raw research
routes additionally require authenticated, explicitly granted research access.

A separate public route family serves only reviewed, published and currently
admitted **metadata inventories**. It does not turn unresolved scientific rows
into public training data. This narrow first projection is deliberate: scientific
values, cross-family features, task/split definitions and licensed source content
need their own scientific and rights contracts, not a broader JSON allowlist.

## Implemented boundaries

| Area | Local implementation | Remaining boundary |
| --- | --- | --- |
| Raw research reads | JWT/browser session, verified active account and explicit unrevoked role; filters/direct IDs share the gate | No anonymous raw research endpoint or API-key-only operator access |
| Role governance | Append-only administrator-issued grants and revocations; separate curator/reviewer/publisher roles | No automatic real role assignment or public role-management API |
| Proposal/review/publication | Exact capsule/payload hashes, distinct proposer/reviewer/publisher accounts, immutable decisions | Distinct accounts do not prove different natural persons or independent scientific judgment |
| Recursive permissions | Exact current permission for every one of the capsule's pins, with scope/license/basis/actor bindings | Reviewed assertions are not independently verified legal permissions |
| Public body | Fixed metadata-only schema, table counts and opaque object/permission receipts; all flexible JSON excluded | No scientific values, source identities/text, URIs, coordinates or training examples |
| Public reads | Same live admission for collection/count/detail/manifest/download; identical canonical bytes | No public external-source resolver or artifact download |
| Withdrawal | Permission/role/account/source holds, negative reviews and capsule notices remove access without changing old bytes | Cross-system correction propagation remains SC08/DR02 work |
| Resource limits | Batched grant checks, minimal user fields, live-material byte/count/ancestry limits, read-only request snapshots and timeouts | No representative production throughput/latency validation |
| Account deletion | Read-only audit-reference preflight, friendly 409 and real concurrent-FK rollback | Pseudonymization/privacy/retention workflow needs separate review |

Schema `0055_research_publication` adds seven tables: publication epoch, role
grants, role revocations, per-object permission decisions, proposals, disclosure
reviews and publish/withdraw actions. All six history tables are append-only.
The new schema leaves 0054 capsules, old source exports and canonical scientific
rows unchanged. A populated governance history cannot be destructively downgraded.

## Authority and scientific semantics

Legacy administrator/reviewer flags are not research role grants. An administrator
can manage grants, but must receive an explicit research role to use raw research
reads or act in that role. Multiple role grants do not waive account separation.
Database guards check current grants, exact capsule/pin bindings, permission
successor chains, closed public fields, count/reference integrity and actor roles.
The public service additionally rechecks hashes and current governance.

Internal write services expect an already-authenticated actor identity from a
trusted caller. There is no HTTP write endpoint, source-file upload flow or
curator UI in this batch. A supplied UUID, JSON flag or recomputed checksum does
not authenticate a human. Real identity/rights review and the interactive
approval workflow remain operational/UX02 work. Internal writes default to dry
run, roll back failures and never commit the caller's outer transaction.

Each metadata body is built from actual verified ML04 capsule/artifact bytes,
not arbitrary caller-provided JSON. Every capsule row requires an exact reviewed
metadata grant, even when that row's source bytes/fields are excluded. Unknown,
denied or superseded permissions fail closed. The four supported license codes
are identifiers for reviewed decisions, not automatic clearance inferred from
source names or repository licensing.

The public body intentionally contains no Tc, pressure, material formula/ID,
source locator, reviewer/account ID, run settings, flexible JSON or external
artifact bytes. Opaque hashes are integrity references, not an anonymization
guarantee. `scientific_acceptance` and `ml_training_approved` remain false. This
metadata inventory is not a research dataset or proof of superconductivity.

## Current availability and compatibility

The collection and three detail/download aliases use the same admission policy.
They run in dedicated REPEATABLE READ/read-only transactions and do not reuse
cross-request authorization caches. All responses and errors are private/no-store;
If-None-Match cannot cause a 304 or bypass permission checks.

Any negative disclosure review permanently holds its immutable proposal. Later
approval cannot erase that rejection; a new proposal/review is required.
Withdrawal, permission supersession/revocation, actor role revocation or account
deactivation/unverification, current catalogue/source holds and ML04 notices
also stop access. Source files are verified at proposal creation, not re-fetched
on each metadata read. Historical manifests are never rewritten to match current
governance, and withdrawn IDs are not republished in place.

No frontend called the seven raw research routes in the audited checkout; their
three existing scientific HTTP test suites now explicitly use real synthetic
operators/grants/JWTs. The default test client remains anonymous. Unrelated legacy
material, paper, Timeline and RPS routes are not newly made research-operator-only.
RPS's existing filesystem release path remains a separate later integration.

The source exporter still labels its raw nested records as not cleared for public
release. Its retained bytes/schema were not rewritten. Account deletion for new
audit participants now returns a clear 409 before private data/session changes;
the final exact-FK race guard rolls back all deletion effects. Ordinary accounts
retain their existing deletion behavior. This does not create a legal retention
policy or a completed account deidentification process.

## Verification record

All DB/Redis execution used the capability-checked disposable native runner.
The actual Alembic rehearsal exercised a complete synthetic capsule and
metadata-permission/proposal/review/publication/withdrawal flow on migrated
tables, then verified preserved history and nonempty downgrade refusal.
It did not use `create_all` as a substitute for the migration path.

Final checks:

| Check | Result |
| --- | --- |
| API full suite | 1,838 passed |
| Final publication/service/limit verification | 53 passed, including one additional corrupt-capsule HTTP regression added after full-suite collection |
| Ingestion full suite | 905 passed |
| Scripts | 264 passed, plus 36 separately reported subtests |
| Frontend source / unit suites | 35 / 245 passed |
| Distinct ordinary tests verified | 3,288; repeated focused cases are not double-counted; excludes the 36 script subtests |
| TypeScript | `tsc --noEmit` passed |
| Migration rehearsal | Actual head/admission, empty round trips, old-data preservation, freeze/publication/withdrawal and nonempty-history downgrade guards passed |
| Static checks | Scoped changed-module Ruff I/F and `git diff --check` passed |

The API full run reports the existing FastAPI `regex` deprecation and 19 Alembic
legacy path-separator warnings. The first full run exposed a test that incorrectly
assumed no prior committed publication history. It now compares the inventory
and admission-query set before/after 101 draft insertions instead of asserting
a global count of one. The full rerun passed. Final focused verification also
checks that an unverifiable retained capsule is hidden without breaking the
collection or leaking internal error details.

Focused adversarial coverage includes direct SQL resealed nested payloads,
missing/duplicate/stale receipts, Unicode/escaping hash parity, role/account
checks, concurrent writers/stale snapshots, negative-review holds, real capsule
notice bytes, consistent collection/count/download admission, minimal profile
reads, oversized material ancestors, batch-query cost, read/dependency timeout
handling and real concurrent grant versus account deletion.

No real Linux/Docker CI, browser redesign, full production build, live source
review or production performance acceptance is claimed. Website-owned copy
remains English. Disposable services and their temporary data were removed by
the test runner; no production or user research data was removed.

## Remaining gates and next priority

1. Complete SC08 / #66 correction/retraction propagation with explicit source
   review and canonical revision/promotion semantics; do not rewrite frozen
   results or silently move historical memberships. RG02 / #65 original-versus-
   derived evidence typing can proceed independently.
2. Extend ML07 only after defining scientifically useful, typed structured-value
   projections, qualified labels, field-level source attribution and reviewed
   artifact/source permissions. Metadata disclosure is not full issue closure.
3. Complete the authenticated curator/reviewer/publisher UI and independently
   reviewed human-rights/identity decisions (UX02); resolve privacy/retention
   and exact staging/runtime-role procedures before granting real access.
4. Run the authorized 60-event ML08 pilot; synthetic tests add no reviewed
   scientific events. ML05 property validation and ML06 leakage-safe task
   datasets still precede ML09 baselines and AL01 calibrated policy evaluation.
5. Rehearse real staging source parity, review/withdrawal, backup/restore and
   performance. Keep production feature flags and role provisioning unchanged
   until separately authorized.

Operational specification and entry points:
[Research publication access](../../RESEARCH_PUBLICATION_ACCESS.md).
