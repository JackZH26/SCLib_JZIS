# Batch 82 — correct recovery-test identity and truthful regression failures

**Terminal update:** handle 3224 ended with exit 1 after four complete passing
batches: 3,919 passes and 3 skips over 112 modules. Batch5 was refused by the
pre-client capability identity/lifetime guard before test collection; it has no
JUnit, and batches6–8 did not start. The final result is incomplete, not full
acceptance. The following live checkpoints are historical. See the
[batch83 diagnosis and bounded follow-up](Priority_Eighty_Third_Batch_Implementation_2026-09-13.md)
and the [unchanged terminal report](measurements/api-regression-batch82-2026-09-13/result.json).

Base HEAD: `02949468802db042e56645e2932b08863a174074`, branch
`codex/sclib-research-v2`. Preserves the accumulated uncommitted upgrades.
This batch changes one recovery integration test, the test-only API coordinator,
its offline tests and CI time allocations. It does not change production API
behavior, scientific schemas, restore limits or scientific admission authority.

## Actual failure and reproduction

The original batch80 handle **10177** ended with **exit 1** after **2,697.675 s**.
Owned cleanup was confirmed, and the observed pytest/runner PIDs were absent.
The coordinator did not start batches 5–8. Its four independently read JUnit
files cover 112 modules and report **3,917 passed, 1 failed, 3 skipped**.
Version 1.0's partial aggregate only counts the first three zero-exit batches:
2,950 passes and three skips. Its zero aggregate failures must not be mistaken
for a successful run. All original files are retained in
[the original evidence directory](measurements/api-regression-batch80-2026-09-13/plan.json).

The failure was
`test_research_restore_worker.py::test_actual_typed_source_capsule_access_and_readonly_index_rebuild`.
It queried every run with `code_version='synthetic-not-executed/1'` and asserted
all were `planned`. Other valid synthetic fixtures use that same version label
with `completed` status. A version string is not a capsule/run identity.

A separately owned minimal reproduction added one unrelated completed run with
the same version and a complete retained row snapshot. Before changing the
query, the ordinary case passed and the interference case failed at the original
assertion: **13 passed, 1 failed, 4.63 s**. After the correction, the identical
module passed **14 tests in 5.72 s**, with owned cleanup on both invocations.
The existing FastAPI regex deprecation warning remains.

The test now derives exact run IDs from its independently inspected release
manifest, requires its expected one run, verifies exact SQL ID coverage and
retains the original planned/not-executed assertions. The unrelated run must
remain equal as a complete JSON row. Existing complete-database
snapshot equality, index replay, access checks and the snapshot's 32 MiB /
20,000-row bounds are unchanged. No run status is rewritten, retained history
deleted, test omitted or production limit raised to hide the interference.

| Retained file | SHA-256 |
| --- | --- |
| [Original batch-4 failure](measurements/api-regression-batch80-2026-09-13/batch-04.xml) | `b98b5b3ccde379646a0afd214de34b1899612a165762da76be08fbefd720d577` |
| [Original coordinator result](measurements/api-regression-batch80-2026-09-13/result.json) | `40b20cabf55f3b57c5b2c892b8974d61dbe995d3d37aaef1c4f49dbb429c5b67` |
| [Minimal red reproduction](measurements/restore-isolation-batch82-red.xml) | `6bbc7d1461779c2ff7e68584c0fc3358bcbce6935a6cfb75ca212f7d6014e026` |
| [Corrected green reproduction](measurements/restore-isolation-batch82-green.xml) | `d74667a61672d07341260736f8b27291a99d4eb9779f187d6adec1c4dd8a9b6b` |

## Failure accounting and CI budget

Coordinator **1.1.0** retains complete validated JUnit counts even when the
owned runner exits nonzero. It exposes counted and unreported batch numbers,
the count scope and per-batch JUnit status. Missing or interrupted evidence
cannot become a passing result. A nonzero runner exit remains an incomplete
failure even when a valid XML lists only passes, protecting cleanup-failure
handling. A false zero exit with JUnit failures is also rejected. No subsequent
batch starts after these failure conditions.

New offline regressions exercise actual-failure XML, interrupted/no-XML output,
false-success XML and nonzero-runner/otherwise-passing XML, as well as complete
success. Earlier reports are not resealed under the new interpretation.

The previous 30-minute API CI job allocation is insufficient to accommodate
the observed local partial regression. The job now has a **180-minute upper
bound**, with **150 minutes** for ordinary regression. This is a conservative
allocation, not a claim that native and Linux timings match or that complete CI
fits. Locked installs, image parity, all ordinary modules, separate capacity,
required artifacts and each fresh service's **one-hour** expiry remain intact.

A five-second read-only OS sample of the exact owned pytest process observed
225 of 413 main-thread sample stacks passing through `builtin_sorted`, with
JSON encoding/decoding in the stack tree. The local diagnostic is retained at
`/private/tmp/sclib-api-profile-80Nx9O/cpu.txt`. This supports further inspection
of snapshot cost but does not attribute the full suite's runtime, establish a
speedup or justify weakening complete-row equality. No snapshot algorithm was
changed in this batch.

## Completed verification

- Focused coordinator/runtime/security checks: **54 tests and 7 subtests passed,
  0.20 s**. The initial command used a nonexistent singular test filename and
  collected nothing; the recorded successful invocation uses the actual
  `test_security_workflows.py`. No passing result is inferred from collection failure.
- Complete offline scripts: **2,288 tests and 82 subtests passed, 186.99 s**,
  in the minimal environment with the preverified tokenizer cache.
- Frontend source checks after the CI budget edit: **45 passed, 2.399 s**.
- Ruff passed using the API's normal working-directory/config discovery and
  the declared Python 3.11 target for the scripts. Two coordinator files pass
  formatting checks; no unrelated API whole-file formatting was performed.
- Actual YAML parsing confirms all six CI jobs remain, the API job/ordinary
  regression limits are 180/150 minutes, and no step ignores failure.
- [Fresh native 0077 rehearsal](measurements/schema-rehearsal-0077-native-batch82-2026-09-13.json):
  **23 fixture checks, 734 source inputs, 145,885 ms**, owned cleanup verified,
  strict receipt reading and current source comparison passed. CPython 3.12.14,
  PostgreSQL 16.13, Darwin arm64; all four authority flags false. This is bounded
  synthetic migration/history evidence, not a production restore.
  File SHA-256: `e66e8c2e163ca756ae66e75d7ec29ca83ea7bc91d35d24260b85cd32eea11b26`;
  internal report SHA-256: `03d9e5ac823576cac052a563ce2f298cf381613676118493bd7dbe7e97ae9098`;
  input inventory SHA-256: `447d7d837b6ca378180ccc32908e8dc32bdf4347cb3f2c37dfc1e7280608b884`.

## Original-batch replay passed; full regression active — 2026-09-13 14:04:36 UTC

The original fourth batch's **same 28 whole modules** completed after the focused
fix: **969 passed, zero failed/errors/skips, 1,150.40 s**, with one existing
FastAPI warning and owned-service cleanup. Handle **95172 is terminal**, exit 0.
The actual JUnit was independently checked against all 28 assigned modules and
retained as [the corrected batch-4 replay](measurements/api-batch4-replay-batch82.xml),
SHA-256 `2a0d35ee4a2c1e0e6d5dcdd3752c9e54899aafc396039809d9ecdfcd90903f50`.
All 734 API/script inputs still matched the current migration receipt. This
resolves the observed failure in its original complete module workload, without
claiming that the remaining API modules or Linux CI have passed.

A **new complete eight-batch run** using coordinator 1.1.0 is now live under
handle **3224**, with artifacts at
`/private/tmp/sclib-batch82-full-api-at5uXx/run`. It includes all **223 ordinary
modules**; the successful focused replay is not substituted for a batch in this
new run, and no old partial results are stitched into it. Keep API/script inputs
and HEAD unchanged until it terminates. Observe this same handle after output
timeouts; do not launch a duplicate merely because a poll has no output. Final
full-module coverage, all JUnit counts and terminal source comparison remain
pending. The separately owned capacity and genuine-reference results keep their
own documented scopes.

The new run's **first batch** completed **993 passes across 28 modules
in 471.66 s**, with zero failures/errors/skips and one existing FastAPI warning.
Its actual JUnit was independently matched to the assigned module list; owned
cleanup was reported and all source pins still match. The same live coordinator
subsequently completed **batch 2 with 897 passes across 28 modules in 849.20 s**,
also with zero failures/errors/skips, one existing warning and owned cleanup.
The **third batch** then completed **1,060 passes and three explicit-reference
skips across 28 modules in 476.23 s**, with zero failures/errors, the same
existing warning and owned cleanup. All three actual JUnit files have been
independently checked against their assigned module lists: **2,950 passes and
3 skips across 84 modules**, with all 734 source pins and HEAD unchanged.
The skipped cases are exactly `al-example14`, `alas-grid-recover` and
`bn-example17-2d`: this ordinary invocation did not supply the pinned local
reference paths and attempted no download. Their separate batch81 actual
three-pass result remains separate and is not substituted into these totals.
The same handle **3224** has advanced to batch 4. These are
partial checkpoints, not full API acceptance,
an overall performance improvement or a measured Linux CI result.

The seven batch75 HTTP archives are retained unchanged. Their 3,852 selected
source pins have exactly one changed source path per archive:
`api/tests/test_research_restore_worker.py`. Consequently they are historical
compatibility evidence, not current-source captures. The separate real SQL/HTTP
capture run **62036** subsequently ended with **7 passed, 116.62 s, exit 0** and
owned cleanup. Its [actual JUnit](measurements/native-wire-batch82.xml) is retained.
The fresh private pytest root is `/private/tmp/sclib-batch82-wire-k9OT7d`.

### New source-matched interface captures

All seven files were copied from that successful capture invocation into
`frontend/tests/fixtures/`, without rewriting original response bytes or old
archives. All **3,852** selected source pins in the new files match current
sources. These remain synthetic-account/native SQL/HTTP compatibility records,
including explicitly documented test doubles; they are not real scientific
approvals, a deployed backend or completed human review.

| Archive | Bytes | SHA-256 |
| --- | ---: | --- |
| `discovery-main-barrier-native.batch82.wire.json` | 199803 | `26b45abdf9e3ac54880c068bb973e324fe72b57c48eefe7e94f1dcb0d13a3e75` |
| `ml-pilot-attestations-native.batch82.wire.json` | 450767 | `08e050531f85333e84deb71195e94653dad53f8a5ba9e19876a069db80f43db5` |
| `ml-pilot-evidence-native.batch82.wire.json` | 360282 | `4430a9b34bcfb8251a68c90d598fd319b7112efdd9bff7c3c434f3ee83277c4e` |
| `ml-pilot-participant-native.batch82.wire.json` | 155529 | `884eb7653786ac4b8136e55c887884a49242097fa33551a6a24f9a16b13c4ccb` |
| `ml-pilot-review-native.batch82.wire.json` | 83618 | `1e03c19b728fb6e732ed0b28f006a48211c91c30115f563595ddbbff4428e724` |
| `ml-use-rights-native.batch82.wire.json` | 219136 | `bfaca5370980fd46952760adf4c3ae7f4c7d47ae67455821d729d967d1eac75a` |
| `ml-use-runs-native.batch82.wire.json` | 198204 | `a8721eb35843ea698e09d7e375d318fb03b855d937617ef5966996fa13007e7a` |

Active frontend native-fixture imports now use batch82. New exact-archive hash
assertions supplement, rather than replace, all existing historical assertions.
The nonincremental TypeScript check passed. Complete component verification
**42986** ended with **1,887 passed in 53 files, 93.66 s**. The full isolated
private browser suite **96192** ended with **42 passed**, zero skipped,
unexpected or flaky cases, and **162,619.808 ms** in its actual JSON report.
The new artifact root is `/private/tmp/sclib-batch82-browser-ZZeqw5/run`.
The [unchanged copied browser report](Research_Browser_Batch82_Final.json) has
SHA-256 `a6c127b34821817ae6ec7d1348e0054a2d02c6e42ed318063ecff395650f27e9`.
Port 32078 had no listener after completion. The current mobile field-report
screenshot was inspected: English labels, explicit private/scientific limits
and zero effective atomic results are retained rather than inflated from the
60 selected synthetic events. The public production-mode browser/source implementation is unchanged;
its historical batch79 result is not relabeled as a new execution.

### Delivery secret-scan follow-up

A subsequent actual local Gitleaks 8.30.1 scan covered 128 modified/untracked
files and the 61 accumulated branch commits. It reported 38 working-file
findings and 63 historical findings, not a clean exit. Inspection classified
them as synthetic request identifiers, four verified same-commit source hashes
and one ordinary prose match. The [retained scan and triage](Secret_Scan_Triage_Batch82_2026-09-13.md)
records the exact scope, redacted original reports and bounded pending fix.
No ignore policy or source was changed while the full API regression is live.
An actual temporary-policy probe subsequently produced a clean scan for the
same historical range using only the reviewed exact fingerprints. Wrong-commit
and same-path mutable-file controls each still reported their expected finding.
This validates the proposed exception scope, not the unchanged repository
policy or a remote Security run; the original nonzero reports are retained.
The exact-fingerprint security-policy/test follow-up is now a concrete
remaining delivery item; local scientific/functional tests cannot waive it.

No commit, push, PR, issue closure, merge, deployment, production migration,
real permission decision or feature activation occurred. The user's publishing
authorization remains pending. The ML05 sample/rights/context gaps, independently
reviewed ML08 pilot and empirical downstream ML/RPS evaluations remain separate
unfinished issue requirements. Engineering regression alone cannot close them.
