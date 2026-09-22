# Batch62 — owner / independent approver browser workbench

Base: `c4b8fb5` on `codex/sclib-research-v2`. The previous turn made concrete
progress by committing the user's requested checkpoint: completed batch61 and
the unfinished batch62 workbench. This increment completes its targeted client
verification, hardens seven inconsistent-response cases and documents the
operator workflow. The overall platform goal is not complete.

Fresh read-only GitHub inspection found **38 open issues**. UX02 #73 and ML09
#76 were read in full. This work advances revision-aware independent operator
workflows and baseline-authorization dependencies; it does not by itself meet
their complete scientific, dependency, delivery or acceptance criteria.

## Implemented and verified scope

- English-only application controls at `/dashboard/research/ml-runs`, with
  distinct requester and independent reviewer admission. A role selector does
  not grant roles, switch accounts or borrow the requester's identity.
- Original submission ID/hash/inventory lookup, exact input/task/configuration
  and source/host documents, explicit CPU/wall/memory budgets with no presets,
  consent, rollback-only preview and separate exact-intent commit.
- Independent conditional approval, denial and exact-head revocation. No
  default approval; approval evidence and expiry are explicit. The database
  remains authoritative for identity, time, role grants and concurrent heads.
- Historical receipts and manual/original-key recovery for both operation
  kinds. Unknown outcomes lock further changes; a 404 is not treated as
  rollback. Identical retry is explicit and only offered while the original
  request is retained in memory. Authentication changes abort/ignore late
  replies, erase private state and the write body, and hide the opaque recovery
  reference from a different account. No local/session-storage persistence.
- Explicit owner-only current-condition checking, separately displaying plan
  review, purpose-bound rights counts, source validity, combined source gate,
  implementation/host matches and the remaining execution blockers.
- Fixed-path, cookie-authenticated, no-store, redirect-refusing transport with
  request/response/chunk/UTF-8 bounds and actual fetch/stream cancellation.
  Tests cover ordinary 30-second and readiness 95-second deadlines, caller
  interruption and the absence of automatic retries or raw-error disclosure.

The [operator guide](../../ML_USE_RUNS.md) contains the exact steps, failure
handling, retention/recovery limits and protocol interpretation. Browser API
wrappers and response validation remain separate from UI state transitions.

## Seven additional fail-closed response checks

Each case was first demonstrated by a failing adversarial test before its
client fix. These are protocol/display consistency defects, not evidence of
production exploitation or an ability to execute a model:

1. Reject impossible calendar timestamps that JavaScript would normalize.
2. Reject displayed blocked-status subtotals exceeding full-inventory counts.
3. Reject an `expired` label when the approval is still in the future at the
   recorded snapshot, even if the outward flags/blocker text agree.
4. Reject a decision naming itself as its historical predecessor.
5. Reject approval expiry beyond original input retention in the inspection.
6. Reject approval expiry at or before the decision's creation time.
7. Reject a snapshot predating the decision it claims to observe.

Tests preserve valid expired/approver-unavailable states, changed fingerprints
and even a satisfied source-permission gate, without turning them into
execution authority. Original native host-document strings are hashed directly;
Python floating-point numerical-policy values are not reserialized through the
integer-only intent codec.

## Evidence and verification history

- Native archive compatibility uses **23 original raw HTTP responses** and
  **556 backend/harness source pins**. The archive is 173,875 bytes, SHA-256
  `1cabdf1fc608c169a82b3b9942a6e672595c860a00b264b339f54e867dd9419f`.
  Every source pin is checked against its current file. The archive was captured
  before the user checkpoint and is retained byte-for-byte, not resealed.
- Initial protocol run: **65 passed / 2 failed**. Both new negative tests
  accidentally assigned the fixture's existing 512 MiB value; they now perform
  a real change. The first combined run was **118 passed / 1 failed** because
  an unanchored CPU-label regex also matched wall-budget help text. The
  selector now identifies the field precisely. No application validation was
  relaxed to fix these test-authoring mistakes.
- First six additional consistency cases: **67 passed / 6 failed**, confirming
  the missing client guards. After fixes: **125 targeted tests passed**, 5.47s,
  with successful nonincremental TypeScript checking.
- First complete frontend regression: **44 files / 1,561 passed**, 47.30s,
  followed by **38 passing source checks** and nonincremental TypeScript.
- First isolated Chromium run: **4 passed**, 26.3s. Desktop 1440×1000 and
  mobile 390×844 used separate browser contexts/accounts for owner → exact
  plan handoff → approval → revocation → denial, then checked each result from
  the owner page. Separate cases tested lost commit replies, a 404 recovery
  snapshot, read-only exact recovery and admission-denial clearing. Expected
  API requests, no automatic checks/writes, keyboard focus below the sticky
  header, English defaults and no horizontal overflow were asserted.
- The additional temporal-snapshot test then demonstrated **77 passed /
  1 failed** before the seventh fix. The synthetic browser readiness adapter
  now takes the native snapshot from the matching decision stage, rather than
  incorrectly reusing the earlier unreviewed timestamp. This correction changes
  only the explicitly synthetic test adapter, not any archived native response.
- Guarded disposable native API repeat: **1 passed**, 28.58s, running
  `tests/test_ml_use_runs_wire.py`. It exercised native SQL/HTTP with synthetic
  identities and the explicitly doubled intake compiler; no real human review,
  model fitting or production permission grant is asserted. The existing
  FastAPI `regex` deprecation warning remains. Owned services/test data were
  cleaned up. Production API and schema sources were not changed this turn.

### Final verification after all seven guards

- Full frontend: **44 files / 1,566 passed**, 55.83s, including all **130 new
  run-workbench protocol, transport and component tests**. All **38 source
  checks** and nonincremental TypeScript also passed.
- Isolated Chromium: **4 passed**, 31.7s, repeating both viewports and distinct
  accounts after the temporal guard/adapter correction. No unexpected API
  requests, external browser traffic or handoff page errors were observed.
- Final desktop owner-preview and mobile approved-but-held readiness
  screenshots were visually inspected. Long hashes wrap, controls fit the
  viewport, and conditional review remains distinct from missing source rights
  and disabled execution. Earlier mobile recovery/approval-preview and desktop
  readiness screenshots were also inspected.
- The owned browser port 32062 was no longer listening after completion.
  **119 relative Markdown links resolve**, `git diff --check` passes, and the
  active run/ML-rights/Discovery fixtures remain byte-identical to the checkpoint
  with all **556 / 555 / 274** selected source pins matching.

All test processes above have terminal outcomes. The final local screenshots
are under
`/var/folders/m0/ztnj2ywn613cqhtb3_ym0xyc0000gn/T/sclib-ml-runs-browser-artifacts-ryLP9n/`;
the earlier browser run is under the adjacent `sclib-ml-runs-browser-artifacts-1K7QBF/`
directory. These are temporary diagnostic locations, not committed portable
artifacts. This increment was uncommitted at its original handoff and does not
close the overall goal or any of the 38 open issues. The subsequent local
checkpoint and fresh regression are recorded in the
[batch63 report](Priority_Sixty_Third_Batch_Implementation_2026-09-13.md).

## Evidence boundaries and remaining work

The native capture proves compatibility with guarded synthetic SQL/HTTP. The
component/browser adapter reseals browser-selected request keys and exact
synthetic handoff references; it is not new SQL evidence, an actual-worker
baseline evaluation or independent scientific/legal review. The separately
verified actual-worker pipeline remains documented in the
[batch61 report](Priority_Sixty_First_Batch_Implementation_2026-09-13.md).

The retained 0074 migration receipt is unchanged batch61 evidence. Its selected
677-file inventory is not relabeled to cover the new browser work, and the
migration itself is not rerun because no schema or production API source was
changed. Historical ML-rights and Discovery wire archives remain intact.

Actual execution remains disabled. No fitting endpoint/button, production
deployment/migration, real membership/review, source redistribution, paid job,
push or issue closure was performed. Remaining dependencies include:

1. Resolvable controlled review-evidence documents and actual independent
   human source/scientific review, including an accepted or honestly
   inconclusive ML08 pilot.
2. Guarded one-shot execution consumption, actual isolated release-runtime
   admission and enforced resource budgets, followed by authorized reproducible
   baselines with auditable failures and data/model cards.
3. Issue-specific exact-revision PR, CI/runtime evidence and acceptance mapping;
   a local browser test or successful hash check does not close these gates.

## Reproduction

From `frontend`, using installed dependencies and the isolated browser server:

```bash
pnpm exec vitest run --maxWorkers=2
pnpm test:source
pnpm exec tsc --noEmit --incremental false
pnpm exec playwright test --config tests/e2e/ml-use-runs.config.ts --max-failures=1
```

From the repository root, use only the disposable runner for database tests:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/bin/redis-server --suite api -- -q \
  tests/test_ml_use_runs_wire.py --maxfail=1
```

The browser harness copies source to an owned temporary workspace, links
already-installed dependencies, uses mocked fonts and blocks unexpected
external traffic. It does not reuse the normal `.next` output or an existing
server on port 32062. Diagnostic screenshots remain temporary local artifacts,
not a portable production-release attestation.
