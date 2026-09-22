# Thirty-fourth batch: exact-result adjudication and live consumer holds

Date: 2026-09-08. Base: `11e674a` on `codex/sclib-research-v2`.
Primary issue: [UX02 / #73](https://github.com/JackZH26/SCLib_JZIS/issues/73),
still OPEN in this batch's read-only remote check.

## Outcome and scope

The private evidence workbench now supports explicit property-level accept,
reject and request-clarification decisions for three limited sampled-phonon
profiles. A decision binds an original result revision and its forward evidence;
it does not approve a parent event, clone a result, infer a superconducting state
or supply unknown physical conditions. Public publication/distribution admission
consumes exact negative/stale review effects without changing frozen bytes.

This is substantive local implementation of UX02, not closure of the full issue
or goal. Versioned ML review companions, task-specific admission, wider claim/Tc
profiles and exact RAG linkage remain separate work. No production migration,
real material review, source disclosure, backfill, vector refresh, remote issue
change, push, PR or deployment was performed.

The complete operator/scientific contract is
[SCIENTIFIC_RESULT_ADJUDICATION.md](../../SCIENTIFIC_RESULT_ADJUDICATION.md).
The existing [read dossier contract](../../SCIENTIFIC_EVIDENCE_WORKBENCH.md)
continues to describe read-only authority; its false flags are not reinterpreted
as the current result's historical review status.

## Implemented layers

### Exact immutable history and SQL enforcement

Migration `0067_scientific_adjudication` adds independent subjects, atomic
reviewer requests and ordered immutable decisions. Canonical request bytes
retain private rationale, explicitly checked evidence and bounded propositions.
The original scientific rows and frozen 0054/0064/0065 contracts remain unchanged.
Source SQL text hashes are not confused with Python/frozen-capsule row hashes.
Existing legitimate UUID4 subjects are reused by exact property/hash identity.

Direct SQL enforces active reviewer grants, source/hash and exact revision pins,
current predecessor CAS, independent import review, explicit resolution of a
negative predecessor and exact accepted fidelity dependencies for scientific
acceptance. Neither a forged JSON actor nor legacy administrator flags bypass
these checks. Negative history survives revocation of its author.

Four catalogue writer fences close concurrent material/source metadata gaps.
Forty-one 0067-owned assembly-writer triggers and bounded whole-request
completion checks prevent source/impact/governance changes from invalidating
an already assembled review within the same transaction, including after an
early constraint check. A newly appended fidelity successor cannot bypass an
earlier scientific request by consuming the earlier deferred callback. All
these guards are version-owned and removed by an empty 0067 downgrade; retained
adjudication history makes downgrade fail rather than deleting it.

This is not a permanent source freeze. A later independent transaction may
legitimately change source data, yielding stale/held review effects. A pending
parent event is not automatically approved by the new decision. Account-erasure
preflight includes both new actor-bearing audit tables.

### HTTP and unknown-outcome behavior

Separate context, preview, commit and actor-scoped receipt endpoints provide a
closed protocol. Context captures the displayed dossier, subject, impact and
live statuses in the same repeatable-read transaction. Preview rehearses the
actual SQL path with full rollback, including guard epochs. Commit rechecks all
pins under serializable isolation and returns success only after outer commit.

Identical request replay is a database/epoch no-op; changed bytes with the same
key conflict. A lost response is unknown, not failed or safe to retry. The
receipt endpoint recovers the same request without new writes; it does not claim
current scientific validity. HTTP tests simulate both outer rollback and an
actual commit followed by lost response. Rationale/source/SQL error canaries
are not echoed in responses.

Independent review and integration tests caught additional boundary defects:

- Explicit research-role checks now happen before body streaming, preventing
  ordinary verified accounts from occupying reviewer transactions with slow
  unauthorised submissions; the final write path still rechecks current roles.
- Commit has a separately bounded outer envelope (128 KiB + 256 bytes), while
  the canonical inner request remains limited to 128 KiB. Actual twenty-item
  multilingual SQL/HTTP tests verify the maximum-size preview and commit, and
  reject an inner request exceeding the limit by one byte.
- Exact publication review checks run after the original material/source
  pre-hydration budgets and before admission. The broader regression detected
  four ordering failures when the new check was placed first; production code
  was reordered, without relaxing the original size/inventory test assertions.

### Live publication/distribution and scientific limits

The two-scope live resolver verifies retained request/item/decision/subject
integrity, source governance, current positive reviewer grants and exact
fidelity-head dependencies. Invalid, unavailable or oversized state does not
fall back to unreviewed. Revoking a negative decision's author does not revive
an older positive decision. Private source access and public rights remain
distinct from scientific review.

Current metadata publication and RPS distribution gate only exact registered
property dependencies. Reviewed rejection, clarification, staleness or a
source/authority hold blocks current serving. Existing unreviewed policy remains
unchanged. Distribution receipts include the current scientific-review revision
for fresh authorization, including cached/conditional 304 responses. Unrelated
packages remain available and retained bundle bytes remain exact.

The consumer gate is deliberately separate from the twenty-item interaction
limit: it accepts up to 20,000 candidate property IDs and resolves at most 200
actually reviewed IDs using one shared ten-second/16 MiB subject budget. A real
21-property fixture checks every result, including a later rejection of the
twenty-first. There is no silent truncation; over-budget admission is unavailable.

Acceptance in this batch still means only a sampled-frequency proposition. It
does not prove full-zone stability, real DFPT execution, normal-state conditions,
convergence or source-time eligibility. The existing 0065 native importer
continues to produce pending extraction observations. No ML training or public
release authority is granted by this workflow.

### Browser workflow

The English UI allows an explicit selection of up to twenty results, then one
whole-context read. Evidence and editable checks share the same stable snapshot.
The form does not pre-attest source inspection. Profile, scope, rationale,
selection, identity or authorization changes invalidate an old preview.

Closed runtime validators admit an actual synthetic HTTP capture, not just
hand-built mock shapes. Commit, unknown and recovery states lock page controls.
Thirty-second client deadlines turn a blackholed commit into same-key unknown
recovery; abort-ignoring late responses cannot restore a stale preview/receipt.
Browser reload/close is warned while pending/unknown. No private rationale,
source evidence or token is persisted. SPA navigation or closing the page can
still lose in-memory recovery context; this is a documented limitation, not
claimed durable recovery storage.

Desktop and 390-pixel mobile browser checks exercise evidence, preview, unknown
recovery and authorization denial without external requests or production API
access. The existing local service on port 3105 was left untouched; isolated
browser port 32032 was stopped afterward.

## Verification record

All scientific fixtures and reviewer actions were explicitly synthetic. Counts
below describe executed tests, not reviewed real materials or production data.
Subtotals overlap and must not be added together.

- Independent native schema suite: 63 passed, one existing FastAPI warning,
  53.23 seconds; complete independent migration-chain execution also passed.
- Scripts suite: 945 passed, 36 subtests passed, 18.46 seconds. The focused 98
  schema/report tests are included, not an additional total.
- Frontend: 639 component tests in 29 files, 35 source checks, TypeScript and
  whitespace checks passed. Four isolated desktop/mobile browser tests passed
  on final timeout code in 21.2 seconds; screenshots were inspected.
- Initial actual HTTP suite: 22 passed; subsequent service/protocol suite:
  91 passed. These are intermediate checkpoints, not final-source totals.
- Eight-module native regression checkpoint: 298 passed, one existing warning,
  127.01 seconds, before the final early-role/envelope fix.
- Final protocol/HTTP boundary rerun after those fixes: 83 passed, one existing
  warning, 27.75 seconds, including maximum-size twenty-item commit.
- Final owned subject/effects/public-gate suite: 50 passed, one existing warning,
  33.33 seconds, on final 0067 guards and the separate 200-result consumer limit.
- Pre-ordering-fix measured whole migration rehearsal: exit 0, actual `0050` to `0067`,
  26,777 ms and successful owned-resource cleanup. The new
  [retained report](measurements/EN02_Schema_Rehearsal_2026-09-08-04.json) pins
  525 API/script input files. Closed report/body and then-current source inventory
  verification passed; full file SHA-256 is
  `a3ff06ee98d626ac52b015cab17599e30b93857dc5f7d9ff8c3238a799d1bd1f`.
  Its unchanged v1 named outcome/count schema is not a separate inventory of
  0067 tables; the extended source-pinned harness checks that new history.
- Broader twenty-module integration run: 701 passed, four failed, one existing
  warning, 335.21 seconds. All four failures were the existing publication
  material-byte/record preflight ordering checks. The production ordering fix
  is described above; this run is retained as a failed checkpoint, not relabelled
  as 705 passing tests.
- After the ordering fix: 69 publication/HTTP/resource/public-gate tests passed,
  one existing warning, 52.68 seconds. All four original ordering assertions
  are unchanged. A second full migration rehearsal passed on the final source:
  [retained report -05](measurements/EN02_Schema_Rehearsal_2026-09-08-05.json),
  26,210 ms, successful cleanup, all 525 source inputs independently verified.
  Full file SHA-256:
  `d65d8b6e66ce5df9aa94d49986e8441d05161ff82bd877e7ccb4a7eae71caf18`.
- Final rerun of the same twenty-module integration suite on unchanged final
  source: **705 passed**, one existing FastAPI deprecation warning, 332.34 seconds.
  The disposable runner verified and cleaned up only its owned services/data.
  This covers the new adjudication/subject/effects paths, previous dossier/impact,
  audit identity retention and existing publication/distribution/schema/HTTP
  resource and warm-cache gates. It is not the entire approximately 5,000-test
  API suite. Earlier failed checkpoints above remain identified as such.

One earlier concurrent frontend/browser run hit an unrelated Discovery test's
existing five-second timeout (635 passed, one timed out). Its timeout was not
weakened; the subsequent standalone complete frontend run passed all 639 tests.
During development, migration/test-only fixture mistakes were corrected rather
than weakening protections: source-time transaction setup, stale-status naming,
forward-claim association and the shared sanitized HTTP error envelope.

The historical batch32/33 full API run was not green and is not relabelled here:
5,033 passed, one invalid global-first-row fixture assertion failed, three opt-in
skips. That assertion was fixed and is exercised by the current targeted suites.
This batch's targeted tests are not a claim that a new whole API suite or actual
Linux deployment/runtime parity run has completed.

## Next dependency-ordered slice

The detailed [next-slice implementation proposal](ML_Review_Companion_Implementation_Design_2026-09-08.md)
records the inspected interfaces and twelve required acceptance scenarios. It
is explicitly a proposal; these new ML modules are not implemented in batch34.

Build a separately versioned, exact-property ML review companion and new
negative-review-aware compilation path. Preserve the twelve existing compiler
pins, frozen manifests, original producer identities and v1/v2 behavior. Derive
the review inventory from registered ML input edges; do not let a caller omit
an adverse feature. Rebuild cohorts, views and train-only preprocessing from
raw admitted data after a review exclusion, not by deleting a column after the
old training transformation has been fitted.

Even an accepted 0065 extraction must continue to fail existing physical-feature
admission when method, normal-state, P/T, source-known-by, protocol or actual
upstream execution evidence is absent. Positive review is not a waiver of those
scientific conditions. Facts/RAG currently lacks an exact canonical-property
bridge; no formula-matched withdrawal, vector refresh or Tc Timeline change is
claimed by this non-Tc slice. Real qualified review and authorized delivery are
still necessary before full issue acceptance.
