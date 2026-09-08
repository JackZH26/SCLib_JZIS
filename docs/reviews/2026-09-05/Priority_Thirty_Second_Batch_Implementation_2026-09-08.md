# Thirty-second batch: exact-result evidence workbench

Date: 2026-09-08. Branch: `codex/sclib-research-v2`.
Base commit: `73afd05`.
Primary issue: [UX02 / #73](https://github.com/JackZH26/SCLib_JZIS/issues/73).
Related import boundary: [ML05 / #67](https://github.com/JackZH26/SCLib_JZIS/issues/67).

## Outcome and exact scope

The dashboard now has a real private, read-only scientific evidence workbench.
It reads canonical results created by actual pending import and other existing
canonical writers; runtime does not use mock candidates. Selection pairs one
property with its own event revision, material state, structure, producer run,
retained dependency artifact metadata and bounded downstream references.

This is a prerequisite implementation for scientific adjudication, **not UX02
completion**. The live issue was reread during this batch: accept, reject,
clarification, auditable versioned reasons, stale-write handling, bounded batch
decisions and correct public status propagation remain required. No GitHub issue
was closed. A read-only capability must not substitute for those acceptance
criteria. All #41–#78 issues were still open in this batch's read-only remote
inventory; that is a delivery/status observation, not a claim that all their
local engineering implementations remain absent.

## Implemented paths

- Three authenticated read-only endpoints: capabilities, UUID-keyset property
  inventory, and an exact result dossier. Current research curator/reviewer
  grants, active account/session and the existing feature flag are required;
  ordinary admin/publisher flags do not grant evidence access.
- Whole-current-row closure capture and descriptor hashing, including siblings,
  evidence edges and nested owned quality checks. Same transaction supplies the
  typed result and bounded reverse inventory. Private payload edits change the
  pin without leaking their contents.
- Typed reverse lookup through direct ML inputs, owning datasets, event
  memberships, one-hop derivations, frozen pins, publication proposals and
  exact distribution references. Scope omissions are explicit. No arbitrary
  JSON/formula matching, recursive causality or external cache state is claimed.
- Additive index-only `0066_result_impact_indexes`: eleven nonunique btree
  indexes for actual reverse predicates. Scientific schema fields, old capsule
  contracts and immutable importer receipts are unchanged.
- English dashboard entry and result/evidence side-by-side view, stacking on
  mobile. Strict wire validators, matched queue/detail identity and revision,
  current-access checks, cancellation and stale-response clearing. No source
  text, arbitrary metadata, original-file downloads or local persistence.

Detailed operator/scientific boundaries:
[workbench contract](../../SCIENTIFIC_EVIDENCE_WORKBENCH.md) and
[index migration](../../SCIENTIFIC_RESULT_IMPACT_INDEXES.md).

## Concrete defects caught during implementation

1. FastAPI query validation initially reached a generic handler and returned
   503. It now returns sanitized 422 without reflecting invalid input.
2. SQL/deadline errors wrapped by the impact reader initially looked like
   invalid evidence. A typed unavailable error now preserves sanitized 503.
3. Owned children must themselves be traversed. Native regression explicitly
   verifies event → claim → quality-check capture and hash changes.
4. The RPS prefix's underscore must be escaped in SQL `LIKE`, rather than
   accidentally matching any character.
5. Frontend source descriptions initially risked calling every captured artifact
   support for the selected property. They now explicitly identify dependency
   membership, which can include siblings and ancestor/state/run evidence.
6. Returned row limits do not bound a database scan. Native plans now verify
   usable reverse indexes, including an eight-way capsule `BitmapOr`. Dropping
   one branch's index demonstrates fallback under the exact OR predicate.
7. Reusing an entire snapshot's freeze traversal for one result caused unrelated
   corpus members to consume the 1,000-row limit. A separate dossier traversal
   captures exact memberships by reached event ID, but does not enumerate a
   shared snapshot's other events. A native 1,001-unrelated-member regression
   verifies bounded success, unchanged descriptor inputs and exact-occurrence
   edit detection. The 0054 freeze policy remains unchanged.

An attempted oversized-formula fixture was correctly rejected by the actual
`VARCHAR(200)` database field. The test now verifies that real bound; no
unnecessary source-text field or schema widening was added. Fixture-only key,
registry and timing errors were corrected before final runs, not waived as
product exceptions.

## Scientific and privacy checks

The synthetic native AlAs import retains the signed sampled phonon minimum
`-0.0299792458 THz`, source-scoped unknown pressure and temperature, a coordinate
structure, an extraction producer and pending statuses. This is neither a new
DFPT execution nor evidence of superconductivity. The exact actual SQL→HTTP
response is retained as a **synthetic test fixture** and consumed by the real
frontend validator/component without rewriting its fields. It is not production
material data or an accepted scientific result.

All artifact labels permit only validated numeric locator metadata, never
source bodies or URLs. Canary private source text is absent from successful and
failed responses. Whole-database comparisons establish that reads, errors and
retries do not alter science, guard epochs, grants or audit ledgers.

Descriptor hashes bind server-captured rows, not an independently checked
browser preimage. No write API accepts them as evidence that the reviewer read
original bytes. Parent event review does not approve unseen sibling properties.

## Verification record

Focused actual executions completed before final integration:

| Suite | Actual result |
|---|---|
| Dossier + reverse-impact, guarded native PostgreSQL | 56 passed; one existing warning; 22.30 s |
| Private HTTP/operator, guarded native PostgreSQL | 51 passed; one existing warning; 18.24 s |
| Native reverse-index catalog/plans | 14 passed; 3.50 s |
| Full frontend component suite | 564 passed across 28 files; includes 57 new workbench cases |
| Frontend source/English suite | 35 passed |
| TypeScript | `tsc --noEmit` passed |

Final targeted verification after the event-local snapshot traversal and native
driver UUID compatibility fixes: **123 passed**, one existing FastAPI warning,
46.28 s, across all four new API files. This includes the actual
1,001-unrelated-member regression and a real driver-returned UUID. The earlier
focused counts above are subsets, not additional unique tests.

| Additional completed execution | Actual result |
|---|---|
| Full scripts | 778 passed plus 36 subtests; 23.12 s |
| Full ingestion with inert PostgreSQL/Redis endpoints | 1,275 passed; 34 existing warnings; 20.00 s |
| Full native migration rehearsal | Passed; empty and populated index-only round trips, all older independent history guards, migrated plans and full row equality |
| Isolated Chromium, desktop 1440×1000 and mobile 390×844 | 2 passed; 14.7 s; keyboard selection, quantities/unknowns/scopes, no horizontal overflow and permission-loss clearing |
| Changed Python import/undefined-name checks and diff whitespace | Passed |

The browser test starts a fresh Next 15.5.21 server from an isolated temporary
source copy and existing dependencies. Every browser API uses the explicitly
synthetic actual-HTTP fixture; external browser traffic is blocked, the server
API is an inert endpoint, and fonts use an offline system fallback. This is
not a production login, service check or font-rendering canary. The owned test
server was stopped; the existing development server was not changed. Desktop
and mobile screenshots were inspected, not merely generated.

Reproduce browser checks from `frontend/`:

```bash
pnpm exec playwright test --config tests/e2e/scientific-review.config.ts
```

Native functional runs use the local Darwin/arm64 Python 3.12.14 environment;
they are not Linux locked-runtime/release-image parity evidence. Independent
EN04 auditing found development-tool inventory drift and an unbound final image
rebuild in the release workflow. Those limitations are retained as engineering
work, not hidden by a passing functional test total.

A full API integration run was started before the final event-local traversal
fix; its completed result will be recorded separately. It cannot replace the
123-test post-fix execution or be described as a full run of those final edits.

## Remaining implementation priorities

1. Implement the complete UX02 property-level immutable decision path, including
   current reviewer identity, exact revision/source pin, reason, stale CAS,
   replay and all-or-nothing enumerated batch limits. A clarification decision
   must not masquerade as approval or quietly mutate a source observation.
2. Preserve frozen facts and actual producer output IDs. Do not clone a result
   with an unchanged incompatible producer manifest or update an entire event's
   approval status after inspecting only one field. Define the review-to-original
   result binding and consumer status contract explicitly.
3. Apply that contract to real public/Timeline/Facts/ML readers and invalidation
   paths; verify old frozen releases remain intact while current serving status
   changes correctly. Rights, source-time, state/method compatibility and
   scientific acceptance remain separate decisions.
4. Continue ML05 reviewed bindings and bounded additional native property
   adapters; then use genuinely reviewed eligible observations for the pilot,
   dataset/baseline and RPS/active-learning acceptance gates.

The [next adjudication implementation design](Scientific_Result_Adjudication_Implementation_Design_2026-09-08.md)
specifies scoped decisions, a proposed immutable overlay, source-versus-impact
pins, producer-lineage preservation and exact consumer integrations. It is a
proposal, not an implemented or enabled `0067` migration.
The independent [EN02/EN04 acceptance audit](Engineering_Schema_Runtime_Closure_Audit_2026-09-08.md)
also identifies two bounded engineering follow-ups: retain the measured isolated
migration/rollback report, and bind final release-image package inventories to
the matching Test workflow's inventories. Neither requires scientific approval
or production deployment simply to implement and test the software.

No production migration, deployment, backfill, source disclosure, paid
computation, remote push/PR or issue-state change occurred. Local engineering
verification does not authorize those actions. The overall upgrade goal remains
active and incomplete.
