# Proposed next increment: exact RPS dependency rights preparation

Date: 2026-09-09. Issue: [ML07 / #68](https://github.com/JackZH26/SCLib_JZIS/issues/68).
Status: implementation handoff only; **not implemented or exercised**.
Current contract: [RPS distribution governance](../../RPS_DISTRIBUTION_GOVERNANCE.md).

Subsequent implementation: [rights preparation operator contract](../../RPS_RIGHTS_PREPARATION.md).
The status above records the original handoff; batch 44 implements the bounded
workflow. Actual verification and remaining acceptance are recorded separately
in its implementation report, not inferred from this design.

## Evidenced gap and priority

The existing governed RPS distribution workflow requires a stored exact rights
review artifact before recording an `allow` permission. The operator currently
has no corresponding preparation endpoint. The positive HTTP integration test
in `api/tests/test_research_distribution_operators.py` constructs that artifact
directly in SQL before calling the real permission route. The governance guide
explicitly leaves its preparation interface as subsequent work.

The reusable pieces already exist:

- `services.research_distribution.rights_review_payload` defines exact fixed
  schema bytes bound to a registered package, inventory and dependency.
- `decide_distribution_permission` validates those bytes against the stored
  artifact and records allow/revoke decisions with append-only history.
- `routers.research_distributions` supplies authentication, role/session
  rechecks, serializable governance fencing, bounded requests, preview rollback,
  outer-commit receipts and no-store redacted responses.
- Existing package review/publication requires the remaining complete permission
  manifest and distinct reviewer/publisher accounts. Source changes and revoked
  rights continue to hold public admission.

Live #68 was read on 2026-09-09 and remains OPEN. Completing this small P1
operator dependency is more useful next than inventing a general ML approval
flag. The batch-43 real-dataset baseline entry point must continue to refuse.

## Bounded implementation

Add an authenticated preparation operation for **one exact dependency of an
already registered RPS package**. Reuse the existing rights schema, permission
record and governance roles. Prefer an additive service/router surface, checking
historical source pins before modifying any existing implementation.

The request declares the exact package/inventory/dependency pins, reviewer
intent, existing allowed license/basis/reason codes, bounded request key and
explicit predecessor where replacing a permission. The server derives actor
identity from the authenticated session. It must not accept an actor UUID,
arbitrary artifact document, unrestricted metadata, source text, URL, filesystem
path or a self-declared role/approval override.

Preparation renders the fixed canonical rights intent for review and returns
its exact hash. A commit must match the previewed intent and current relevant
heads/pins. Preview must not persist an artifact, permission or guard-epoch
change. Do not require the random artifact UUID created during a rolled-back
preview to be reused as an independent intent anchor.

For a new allow operation, commit the restricted review artifact and existing
permission row in **one outer transaction**. The actual stored canonical
metadata/record/byte hashes must pass the unchanged permission validator; do
not replace that validator with a client-supplied pass flag. Define how those
small fixed-schema bytes are retrieved/reconstructed and independently verified.
`hash_status=verified` means their actual bytes were checked, not that the
reviewer's legal conclusion was proved by software.

Resolve an exact existing request before creating another artifact. Same actor,
key and intent must recover the durable result without duplicate artifacts,
new permission history or guard-epoch writes. A different intent under the same
key, stale predecessor, changed package/dependency or revoked/expired actor
authority must not silently become a new decision. Preserve existing protective
revocation behavior without requiring obsolete source bytes or renewed positive
source eligibility.

A request timeout or failed outer commit is not a success receipt. Preserve
uncertain-state recovery with the same key and exact intent; do not blindly
retry under a new key or infer that no write happened.

## Operator interaction

After the backend boundary passes native tests, expose a compact English-only
private form: exact dependency and pins, fixed rights-intent preview, allowed
decision fields, explicit commit and durable receipt/replay status. Reuse the
site's existing authentication/CSRF and operator interaction conventions.
Changing fields invalidates the preview. The form must not auto-commit after
loading or receiving a preview, preselect a favorable legal decision, grant
roles, automatically approve the package, or publish it.

The operator remains responsible for resolving lawful source permission outside
the software. A recorded rights review is not a blanket conclusion that all
APS/arXiv content is distributable. Restricted text and real reviewer private
data remain outside public bundles. This operation is limited to the existing
RPS disclosure purpose, not ML training, scientific acceptance, source capture
or upstream descriptor creation.

## Minimum acceptance tests

1. Anonymous, nonreviewer, legacy-admin-only, expired/revoked grant and changed
   session requests fail before mutation; late authority changes fail again
   within the actual transaction.
2. Real native package/dependency preview retains complete SQL state and epochs.
   Fixed canonical rights bytes are derived from that exact package, not mocks.
3. Actual HTTP commit atomically creates the restricted artifact and permission;
   the existing validator and subsequent independent package review accept the
   exact synthetic fixture without direct SQL seeding of the rights artifact.
4. Identical retry returns the same durable IDs/hashes with zero writes; changed
   intent/key conflicts, stale heads and changed dependency pins are rejected.
5. Injected artifact/permission/serialization/outer-commit failures do not leave
   a confirmed success or an orphan created by a rolled-back transaction.
   Unknown outcomes remain explicit and recover only through exact intent.
6. Unknown fields, raw/private text, arbitrary upload/path/URL, forged role and
   unsupported license values fail the closed wire contract and safe error path.
7. Existing revocation, third-account publication, current-source withdrawal,
   cache bypass and immutable historical replay regressions remain passing.
8. Browser tests exercise preview invalidation, no automatic mutation, single
   explicit submit, uncertain-response recovery and English accessible states.

All implementation tests use owned synthetic fixtures and the guarded disposable
database runner. No real rights decision, role grant, deployment, publication,
production backfill or model fit is authorized by this design. Local software
acceptance remains distinct from remote delivery and the issue's full closure.
