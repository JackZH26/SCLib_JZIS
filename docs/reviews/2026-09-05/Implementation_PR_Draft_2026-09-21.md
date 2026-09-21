# Prepared draft PR — not submitted

Title: **SCLib research upgrade: reviewed evidence links and verified recovery**

Source: `codex/sclib-research-v2`; target: `main`. Related tracker: #41.

This accumulated upgrade adds atomic scientific result/source history, governed
Discovery projections, purpose-bound ML data and pilot workflows, and English
research interfaces. Test infrastructure uses owned disposable PostgreSQL/Redis;
schema migration is separate from API startup, with release-runtime inventory
checks and bounded native recovery rehearsals.

Mixed scientific Ask previously had no positive result-to-original-passage path.
Schema 0078 now records append-only reviewer decisions pinned to the exact
extraction, original passage, source snapshot and retained claim/sample context.
Private preview/commit/withdraw and receipt routes feed the final read-only Ask
snapshot. Withdrawn, stale and unauthorized links cannot remain positive. A
reviewer can durably withdraw an intact historical pair after its source changes;
both the service and SQL guard still refuse stale establishment.
The UI displays reviewed relations without generated numerical/causal synthesis
or scientific-acceptance claims. Historical version 1.0 saved responses retain
their original fields; new version 1.1 associations require complete or null pins.

The migration rehearsal now proves empty-ledger round trips, establish/withdraw
replay and nonempty downgrade refusal. Actual dump/restore retains both current
and withdrawn link histories. Verification selects the exact fixture paper and
reviewer, while retaining unrelated capsules unchanged. Source/target SQL, exact
receipts, retained artifact bytes and index reconstruction are checked. Seven refreshed native SQL/HTTP
archives and a 1.1 mixed-response capture retain separate identities from all
historical files. Exact synthetic request-key scanner exceptions are tied to
the immutable capture commit, not broad exclusions.

## Validation

- Focused SQL/API and seven native capture cases: **183 passed**.
- Restore-worker regression and seven final native captures: **21 passed**; wrong scope fails and unrelated history is unchanged.
- Complete offline scripts: **2,305 passed plus 91 subtests**.
- Native 0078 migration: **26 measured outcomes**, 741 unchanged input files,
  historical rows/definitions preserved and owned cleanup verified.
- Native release recovery: actual two-instance dump/copy/restore/verify/index
  rebuild/source recheck; 741 unchanged inputs and owned cleanup verified.
- Research browser interactions: **42 passed**.
- Full Git history scan: **561-commit full history plus two subsequent source commits,
  zero remaining findings**; exact scanner
  exception regression: **14 passed**. The staged delivery reports and retained
  test evidence also scan with zero findings.
- Complete frontend components: **1,890 passed**; source checks: **46 passed**;
  TypeScript no-emit check passed.
- Production public build and browser checks: **13 passed**, no skipped/flaky/unexpected cases.
- Explicit-path reference canaries: **3 passed**, using original retained source
  bytes; ordinary-suite opt-in skips remain reported separately.
- Complete ordinary API: **7,460 passed, 3 explicit opt-in skips**; all 224
  modules in 16 owned-service batches, unchanged 741-file source inventory,
  verified cleanup and coordinator exit 0. The three skipped reference cases
  separately passed with explicit original paths; they are not double-counted.
- These are native macOS results. Linux Test/Security and exact release-image
  parity must run on this branch; no local result substitutes for them.

## Review and remaining acceptance

Review this large accumulated branch by subsystem. Start with
`docs/reviews/2026-09-05/Delivery_2026-09-21.md` and the linked remaining audit.
The September 15 baseline remains historical evidence, not a new 0078 test run.

Real ML08 source selection and human review remain at zero. RG04's real reviewed
pairs, stratified gold questions and blinded evaluation, ML09's independent pilot
decision and guarded real-dataset execution, empirical RPS/ML evaluation, reviewed
Discovery rows and production recovery/cutover acceptance remain open.
Passing synthetic tests does not supply these scientific outcomes or permissions.

This draft does not merge, deploy, migrate production, resume ingestion, start
real model training or close the scientific issues. Preserve current production
pause state, immutable history, source-rights checks and independent feature gates.
