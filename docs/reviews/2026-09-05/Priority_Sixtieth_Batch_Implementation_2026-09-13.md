# Batch60 — operational private ML source-rights workbench

Historical batch60 evidence only. The later combined
[development checkpoint](Development_Checkpoint_2026-09-13.md) also contains
unfinished batch61 schema changes and does not inherit this passing status.

Base commit `cc769d8df206ba64f4633b3a4802199623dfd82b` on
`codex/sclib-research-v2`. The previous increment made concrete progress by
committing batch59 and verifying the clean worktree. Fresh read-only GitHub
inspection still finds **38 open issues**. ML06 #70, ML07 #68 and UX02 #73 were
read in full before this work. None is closed by a local browser component.

## Dependency and implementation

The existing 0073 registry supplied an API but no browser workflow. This batch
makes that prerequisite usable before independent run-approval/consumption:

- Private English-only dashboard navigation and `/dashboard/research/ml-rights`.
- Exact submission/inventory handoff; 25-resource pages with stable membership
  pins; separate artifact and row representations, origins, scopes and hashes.
- Single-resource independent allow/deny/revoke with documented evidence hash,
  explicit retention-bounded expiry, reviewer declaration and current head.
- Rollback-only preview followed by a separate original-intent-pinned commit.
- Unknown-commit locking, exact-key read recovery, explicit identical retry and
  manual recovery after reload. Historical receipts never become live permits.
- Current account/grant checks, session-change clearing, stale-response refusal,
  synchronous duplicate-write guards and Strict Mode-safe effect cleanup.
- Closed canonical integer-only response parsing; resource/intent/record hashes;
  negative authority checks; byte/stream/deadline limits; no redirects or storage.

The [operator contract](../../ML_USE_RIGHTS.md) describes exact usage and scope.
No backend production code or schema changes are made. The only API addition is
an executable native HTTP compatibility test. The existing 0073 migration receipt
remains the unchanged **batch59** whole-source checkpoint; it is not relabeled
as measuring this new test or frontend. Existing Discovery fixture pins remain
valid because their selected backend inputs are unchanged.

## Scientific and rights boundaries

This page does not infer licences from availability, merge distinct material
states, transform missing data into negative labels, count repeated evidence as
independent support, or treat RPS as superconductivity ground truth. It does not
ask an independent reviewer to use the owner's private reconstruction identity.
The 285-resource synthetic native fixture is not a reviewed real dataset. Its
intake compiler is explicitly doubled; SQL roles, resource inventory, independent
decisions and HTTP serialization are actual. The real reconstruction pipeline
remains separately covered by batch59 tests, not newly executed by browser mocks.

Evidence documents still live in the operator's controlled external record.
The UI records their hash and a human declaration, not evidence authenticity,
licence interpretation, real-world reviewer independence or scientific review.
Source validity and all-resource coverage require a fresh owner check; a run
requires additional independent authorization and guarded consumption.

## Native capture and integrity evidence

Guarded native run:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/bin/redis-server --suite api -- \
  -q tests/test_ml_use_rights_wire.py --maxfail=1
```

Result: **1 passed**, 25.82s, with owned service cleanup. One existing FastAPI
`regex` deprecation warning remains visible. A pre-run Ruff check caught an
uninitialized loop predecessor variable in the new test; explicit initialization
and an assertion corrected it before any API test ran.

`frontend/tests/fixtures/ml-use-rights-native.wire.json` is byte-identical to
the successful native output: **206,034 bytes**, SHA-256
`79ad4248be9d5b75d9655a62064b5a4a8a9ab599e3887225cf6e745924e19f21`.
It retains **15 raw HTTP strings** for access, two inventory pages and each
allow/revoke/deny preview, commit, inspection and outcome. All **551 selected
backend/test/harness source pins** are checked by the frontend test. This pin
inventory is not a claim that every listed module executed.

Browser transport doubles only reseal the browser-generated request key and
derived intent/record hashes. They are explicitly labeled synthetic and are
not fresh native responses or additional independent reviews.

## Frontend verification and corrections

- First scoped run: **78 passed, 1 failed**, 8.70s. The duplicate-click test
  asserted the receipt before asynchronous cryptographic verification completed.
  It now awaits the visible verified receipt; the synchronous write guard is
  unchanged. The next scoped run passed **79 tests**, 6.91s.
- First full frontend run passed **41 files / 1,432 tests**, 94.07s. It predates
  three numeric-token cases and the Strict Mode regression added below.
- Raw integer aliases (`285.0`, `285e0`, a fractional token rounded by JS) are
  now refused through exact canonical byte equality. The scoped **82 tests**
  passed in 9.54s.
- Actual isolated-browser QA exposed a real Strict Mode lifecycle defect:
  aborted mount-effect requests retired their sequence but not the synchronous
  busy ref, preventing the replayed setup from checking access. Cleanup now
  retires both. A Strict Mode regression was added; scoped **83 tests** passed
  in 6.74s, followed by a successful nonincremental TypeScript check.
- The first browser run failed all four scenarios at initial admission, 45s
  each, against its unchanged isolated pre-fix source copy. After the lifecycle
  fix, the next run passed admission, inventory and keyboard focus checks but
  stopped at a test locator: exact `getByLabel` included descendant option text
  for a wrapping select label. The accessibility tree already exposed the
  correct combobox name; the test now uses that role/name. This second run was
  **1 failed / 3 not run**, with fail-fast enabled; no application invariant
  was relaxed to resolve the locator.
- Final full frontend run: **41 files / 1,436 tests passed**, 83.82s, including
  all **83 new cases**. Source checks: **38 passed**. Nonincremental TypeScript
  passed both in the final combined check and again after the browser locator
  change. Scoped API-test Ruff and `git diff --check` passed.
- Final isolated Chromium run: **4 passed**, 29.3s, at 1440×1000 and 390×844.
  Both sizes cover inventory, keyboard focus below the sticky header, explicit
  preview, one lost-reply commit, 404-not-observed recovery, successful read-only
  recovery, and admission-denial clearing. No document/control horizontal
  overflow, unexpected synthetic API calls or external browser requests were
  observed. Workflow page-error lists were empty. The first three screenshots
  inspected visually were desktop inventory, mobile preview and mobile unknown
  outcome; text, controls and long hashes remained readable within the viewport.

Reproduction:

```bash
cd frontend
pnpm exec vitest run --maxWorkers=2
pnpm test:source
pnpm exec tsc --noEmit --incremental false
pnpm exec playwright test --config tests/e2e/ml-use-rights.config.ts --max-failures=1
```

The successful run's local diagnostic screenshots are under
`/var/folders/m0/ztnj2ywn613cqhtb3_ym0xyc0000gn/T/sclib-ml-rights-browser-artifacts-J69NFT/`.
This temporary path is not a portable release artifact. Exact native wire,
source pins and executable tests are retained in the repository; synthetic
screenshots do not attest production behavior. Final native fixture byte
equality, its 551 source pins and the existing 271-pin Discovery fixture were
independently rechecked. All 109 relative links in changed documentation resolve.

Browser QA uses an isolated source copy, installed dependencies and local
synthetic routes, with external browser traffic blocked and optional font
network calls replaced by the existing offline font hook. It does not contact
production APIs, provision accounts or make real rights decisions. Existing
frontend build output and unrelated running servers are not reused or changed.

## Remaining acceptance work

1. Controlled, resolvable rights-document evidence and owner-facing live input/
   coverage checking; real reviewers must supply lawful decisions.
2. Independent exact run approval, revocation/expiry and guarded consumption of
   the same task, data, environment, current permissions and resource budget.
3. Real ML08 independent scientific pilot and authorized reproducible baselines;
   leakage-safe evaluation and an inconclusive/no-go result remain acceptable.
4. Exact-revision remote PR/CI/runtime and issue-specific acceptance evidence.

No production migration, flag change, real grant, redistribution, model fit,
paid computation, push, deployment or remote issue closure is performed.
