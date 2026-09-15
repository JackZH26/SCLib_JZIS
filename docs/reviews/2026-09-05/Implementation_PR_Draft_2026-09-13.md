# Local draft — SCLib research-platform upgrade delivery

**Historical draft.** Current status and verification: [September 15 delivery](Delivery_2026-09-15.md).

2026-09-15: the user requested continuing the outstanding priorities, including
code delivery and draft PR preparation. The earlier pending authorization below
is historical; current verification and delivery are being prepared. Production
activation and scientific acceptance still require their own completed gates.
 This is a review/handoff draft for the complete accumulated
upgrade branch, not a published PR, merge request approval or issue-closure
receipt. Do not add automatic issue-closing keywords until each issue's own
criteria have been verified and linked to the delivered revision.

Suggested title: **SCLib research foundation: atomic evidence, governed Discovery,
provenance-aware ML interfaces and isolated verification**.

## Delivery identity to complete after authorization

- Proposed source branch: `codex/sclib-research-v2`; target: `main`.
- Current local base HEAD: `02949468802db042e56645e2932b08863a174074`.
- Last checked remote main: `d26fc098565492b78b416fb30b6b1ec7087b24c7`.
- Scope: 61 existing local commits beyond that base, plus preserved uncommitted
  batches 74–83. These are accumulated changes, not all newly written today.
- Delivery commit SHA: **pending — fill after the authorized commit**.
- PR URL and exact-revision Test/Security run URLs: **pending**.
- Publishing authorization: **pending**. No push, PR, merge, deployment,
  production migration or feature activation has been performed by this draft.

Keep API/script inputs and HEAD unchanged during source-pinned verification.
Commit only after the intended regression and captures are terminal: changing
HEAD during a coordinated run invalidates its final provenance check even if
bytes appear unchanged. Recheck remote main before publishing; do not force-push or silently
replace unrelated changes. Native dirty-worktree receipts keep their original
identity; they must not be relabeled as receipts produced by the future commit.

## Review map for the accumulated changes

This table groups review entry points; it is not a claim that every linked
scientific outcome is complete.

| Area | Review focus and evidence boundary | Entry point |
| --- | --- | --- |
| Scientific material/results model | Atomic quantities, conditions, source roles, uncertainty/missingness, review visibility and retained revision history | [Research v2 contracts](../../RESEARCH_V2_IMPLEMENTATION.md), [property evidence](../../PROPERTY_EVIDENCE_CONTRACT.md) |
| Discovery and RPS | Reviewed scientific matrix, representative actions, exact prerequisites, contribution semantics and independently gated distributions; scores are not superconductivity probabilities | [Scientific projections](../../DISCOVERY_SCIENTIFIC_PROJECTIONS.md) |
| ML source/use and pilot workflows | Purpose-bound rights, account participation, own-account declarations, original-byte reconstruction and currentness; no automatic scientific acceptance or execution authority | [Pilot evidence](../../ML_PILOT_EVIDENCE.md), [field-quality report](../../ML_PILOT_QUALITY_REPORT.md) |
| Genuine scientific-program intake | Exact source bytes, coordinate/context checks, pending observations, durable outcomes and no-write replay; unsupported inputs remain explicit | [Real-byte verification](Reference_Canary_Verification_Batch81_2026-09-13.md) |
| Public/private English interfaces | Evidence/rights/review workflows, mobile layout, production prefix/CSP, explicit synthetic transports and no live-API test dependency | [Browser test contract](../../RESEARCH_BROWSER_TESTING.md), [batch79 evidence](Priority_Seventy_Ninth_Batch_Implementation_2026-09-13.md) |
| Engineering and deployment boundaries | Owned disposable services, locked runtimes, exact-image parity gates, additive migrations and scoped private ingress | [Safe testing](../../TESTING_SAFELY.md), [private ingress](../../PRIVATE_INGRESS.md), [deployment](../../DEPLOYMENT.md) |

Related tracker: [#41](https://github.com/JackZH26/SCLib_JZIS/issues/41).
The [complete 37-item execution backlog](README.md) remains in scope, including
its dependency chains and independent scientific requirements. The live review
issue inventory still had 38 open entries including the tracker when checked.

## Local evidence available now

Each result below keeps its own runtime and source scope. Local native runs do
not establish locked Linux image parity or successful remote CI.

| Observation | Actual result | Scope |
| --- | --- | --- |
| Ordinary API regression | Batch82 incomplete; batch83 same fifth-batch replay passed 1,032 tests | New independent eight-batch/223-module run is active. Startup refusal's root cause remains unknown; old/replay counts are not substituted |
| Previous 0077 migration rehearsal | 23 fixture checks passed, 734 batch82 API/script inputs bound, owned cleanup verified | Historical after batch83 safety-script edits; current-source refresh remains pending. Native CPython 3.12.14 / PostgreSQL 16.13 / Darwin arm64; bounded synthetic history |
| Complete offline scripts | 2,290 tests + 91 subtests passed | Batch83, including exact historical scan exceptions and static safety-refusal diagnostics |
| Genuine-file service/SQL canary | 3 passed; one pending observation, two quarantines; exact replay unchanged | Batch81, existing pinned local QE files; no new calculations, human review or ML admission |
| Private research browser suite | 42 passed across nine workbenches | Batch82 current captures/synthetic adapters, isolated development server |
| Public production-mode browser suite | 13 passed | Batch79 real `/sclib`, English/CSP/assets, synthetic anonymous session, blocked external browser requests |
| Frontend source checks | 45 passed | After the batch82 CI budget change |
| Frontend components and ingestion units | 1,887 current component tests passed; 1,275 ingestion tests passed historically | Components refreshed in batch82; ingestion remains batch79's unchanged-source historical result |
| Previous native interface captures | Seven SQL/HTTP capture cases passed; 3,852 selected source pins matched at capture time | Batch82 synthetic accounts and documented test doubles; current-source refresh after batch83 remains pending, earlier archives unchanged |
| Real review-payload capacity | Separate 32 MiB boundary/concurrent-admission case passed | Batch79; never combined with ordinary-suite retained quota history |
| Installed package and ingress checks | Actual native clean-wheel evidence replay and native Nginx transport checks passed | Batches78/77; not Linux image/deployed-ingress proof |

Current evidence and exact hashes: [batch82 recovery-test correction](Priority_Eighty_Second_Batch_Implementation_2026-09-13.md),
[batch80 integration record](Priority_Eightieth_Batch_Implementation_2026-09-13.md)
and their linked earlier artifacts. The original monolithic run was deliberately
interrupted after 3,290 passes and owned cleanup; do not present it as a complete
passing suite or add its count to the replacement run.

## Before this draft can become a reviewed delivery

- [ ] Obtain explicit authorization to commit/push this accumulated branch and
  open the proposed draft PR. That authorization must not be expanded to merge,
  deploy, migrate production, redistribute sources or activate research features.
- [x] Reproduce the original failure, correct exact run identity and pass the
  same full 28-module workload with the new interference regression.
- [ ] Complete an eight-batch regression; the batch82 attempt stopped at batch5
  before collection and is not a full pass. Inspect every JUnit batch,
  final source comparison, full module coverage and
  all skip/error accounting. The three explicit-reference cases stay separate.
- [x] Finish fresh native interface captures and current frontend compatibility
  checks without modifying the retained historical archives in place.
- [ ] Measure complete execution against the updated 180-minute API job and
  150-minute regression-step budgets. Native partial timings justify revising
  the old allocation but do not prove complete Linux fit. Do not weaken guards
  or omit tests to fit it.
- [ ] Review the final diff for source/fixture boundaries, secrets and unrelated
  changes, then fill in the delivered commit and compatibility references.
- [x] Resolve the 36 reviewed historical Gitleaks fingerprints with exact
  exceptions and matching security tests; the actual 61-commit range scan passed
  under the updated repository policy in batch83.
- [ ] Scan the eventual authorized commit and review any uncommitted-fixture
  findings using its real immutable fingerprints. Do not guess future SHAs or
  use broad ignores. See the [retained original triage](Secret_Scan_Triage_Batch82_2026-09-13.md).
- [ ] Run actual exact-revision Linux Test/Security checks and inspect the
  required runtime, schema, installed-wheel and browser artifacts. Verify final
  published image digests only in a separately authorized release workflow.
- [ ] For each issue considered for closure, map every acceptance criterion to
  that delivered source and actual evidence; keep unmet scientific criteria open.

The specific bounded engineering items EN01 #42, EN02 #58, EN03 #59, EN04 #52
and DR03 #56 can be reviewed using the existing
[engineering audit](Engineering_Issue_Closure_Audit_2026-09-08.md) and
[updated readiness record](Engineering_Delivery_Readiness_2026-09-12.md).
Their historic sections retain their dated scope. Genuine scientific pilot
approval is not newly imposed as a prerequisite for closing an otherwise fully
verified bounded engineering defect; conversely, engineering green checks cannot
close the pilot, source-rights or empirical-evaluation requirements.

The batch80 terminal result is retained as **incomplete**, not relabeled after
the batch82 fix. Its three ordinary-suite skips are exactly the Al, AlAs and BN
explicit-reference cases; their separate batch81 XML retains three actual passes.
Do not substitute them into ordinary-suite totals. Current source-specific
verification and live handles are recorded in batch82. No source receipt from
an earlier input inventory is silently upgraded to cover the corrected test.

## Compatibility and non-goals

- Use matching API/frontend contracts and preserve v1 history, immutable
  declarations, original-key recovery and explicit unavailable/stale states.
- Application startup checks the schema; it does not perform a production
  migration. Follow the documented migration-only authority and backup procedure.
  Retained-history downgrade refusal is intentional; do not delete history to
  make a rollback appear successful.
- Keep research permissions and each feature's independent gate intact. A role,
  hash, default-off flag, private declaration or reconstructed file is not
  scientific approval, a rights decision or authorization to train a model.
- Do not promote pending/unsupported scientific rows, interpret quarantines as
  non-superconducting labels, or convert unknown pressure/temperature/cost into zero.
- Preserve the all-English default website UI and the production `/sclib` path.
- This delivery does not claim an approved 60-event human pilot, real ML/RPS
  benchmark superiority, a calibrated superconductivity probability, full-corpus
  rights clearance, a production restore, deployment success or a production SLO.
