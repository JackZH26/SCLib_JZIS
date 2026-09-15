# Batch 80 — complete API regression across owned service lifetimes

**Terminal update:** handle `10177` ended with exit **1** after batch 4, with
owned cleanup confirmed. It is no longer running. The raw four JUnit files
record **3,917 passed, 1 failed and 3 skipped**; batches 5–8 were not started.
The failure, focused reproduction and source correction are tracked in
[batch82](Priority_Eighty_Second_Batch_Implementation_2026-09-13.md).
The checkpoint sections below retain their historical observations, not current
running status. Original [plan](measurements/api-regression-batch80-2026-09-13/plan.json),
[result](measurements/api-regression-batch80-2026-09-13/result.json) and all four
JUnit files are retained without rewriting their version 1.0 accounting.

Base HEAD: `02949468802db042e56645e2932b08863a174074`, branch
`codex/sclib-research-v2`. Preserves uncommitted batches 74–79. The preceding
goal turn made actual implementation/verification progress. This batch addresses
the observed integration-runtime constraint without reducing test coverage,
weakening scientific assertions or extending disposable database capabilities.

## Observed constraint and honest terminal record

The monolithic batch79 API run reached approximately 43% after 42 minutes,
already beyond the configured 30-minute CI job budget. This native observation
does not prove Linux timing, but it cannot establish runtime fit. Inspection
also found that many isolation assertions call `tests.test_research_freeze.state`,
which reads, materializes and sorts complete rows from every application table.
Unrelated committed history accumulates throughout a monolithic service lifetime.
This is a plausible amplification mechanism, not a measured per-function profile.

After verifying the exact owned pytest PID, parent, UID and command, one SIGINT
was sent to that child. Pytest terminated with **3,290 passed, one existing
FastAPI warning, 2,534.06 s and KeyboardInterrupt**. The original supported
runner completed owned-service/data cleanup and returned **2**. Its former
handle **67943 is terminal**, and the four known owned process IDs were absent
afterward. No unrelated database, Redis instance or development server was
stopped. This observation is explicitly incomplete, not a passing full suite.

## Implemented execution change

`scripts/tests/run_api_regression.py` is a standard-library, test-only coordinator.
It does not replace or weaken `run_disposable_tests.py`; every batch invokes
that same owned-service entry point with a fresh private cluster/container pair.

- Enumerate the current ordinary pytest modules and assign each exactly once
  across eight deterministic batches. The present inventory is **223 modules**.
  Run complete modules, without `-k`, `-m`, ignored files or an early-pass filter.
- Retain every test assertion, full-row comparison, transaction and within-module
  history. The whole suite does not share one global database lifetime. Capacity
  and migration tests remain separate, as before.
- Refuse changed discovery conventions, symlinked modules and unreviewed nested
  Python test layouts. The existing fixtures directory is data-only; it cannot
  conceal Python files. A newly added ordinary module is assigned automatically.
- Inherit no service credentials or pytest selection variables. Use argument
  arrays, not a shell. No package/service installation or paid provider call is
  introduced by the coordinator.
- Retain each actual JUnit report. Require cases from every assigned module,
  reject unexpected/duplicate cases, and check failure/error counts independently
  of the subprocess exit code. Skips remain visible and never count as passes.
- Stop after a nonzero owned-runner result or invalid evidence/source state.
  Check API/script source provenance before every batch and at final completion.
  Never extend or recycle a capability, truncate retained audit history between
  tests, or reconnect to another run's database.
- Create an exclusive owner-only output directory and new plan/result JSON
  files, retaining earlier outputs. Missing batches or a plan alone cannot imply
  completed coverage. These observations confer no scientific or production authority.

The API CI job now uses this coordinator and requires its attempt-qualified
artifact before the separately owned capacity run. All six jobs and the
locked-install/runtime-parity gates remain. The 30-minute CI budget is unchanged;
actual Linux runtime fit and remote CI still require execution after delivery.

## Verification checkpoint

The initial planner check correctly refused the existing fixtures subdirectory.
Its policy was corrected to admit data-only fixtures while rejecting Python or
symlinks there; no test directory was silently excluded. The focused coordinator,
runtime-inventory and security workflow suite passed **50 tests and 7 subtests,
0.17 s**, including 27 coordinator tests. Ruff lint/format and whitespace checks
passed. A subsequent diagnostic output-line addition changes no execution policy.

The complete native eight-batch run was active at the initial checkpoint:

```text
Handle: 10177
Artifacts: /private/tmp/sclib-batch80-api-zfiWZL/run
Backend: newly owned native PostgreSQL / Redis per batch
Selection: all 223 ordinary API modules, eight batches
```

At that checkpoint, the correct next action was to observe the same live handle,
not restart on an output timeout. The terminal result is now recorded above;
a passing first batch is not full acceptance.
The first actual batch completed **993 passes in 522.24 s**, with one existing
FastAPI warning and owned cleanup. Its JUnit independently matched all **28
assigned modules**, with **zero failures, errors or skips**. All 734 plan input
pins still matched, and the coordinator advanced to a fresh second batch.
At **2026-09-13 13:05:17 UTC**, batch 2 was still live, at approximately 40%.
No overall speedup or 30-minute CI fit is claimed from comparing differently
sized partial runs; the final runtime must be measured before delivery.
The independent migration and offline-script checks have now completed:

- Complete offline scripts: **2,284 passed and 82 subtests passed, 181.69 s**.
  The minimal environment used the already prepared hash-verified tokenizer
  cache; no API/database was attached by this test invocation.
- The [fresh native 0077 report](measurements/schema-rehearsal-0077-native-batch80-2026-09-13.json)
  passed **23 fixture checks in 143,611 ms**, with owned cleanup verified. Its
  strict reader passed and all **734 API/script source inputs** still matched.
  Runtime: CPython 3.12.14, PostgreSQL 16.13, Darwin arm64. All four scientific,
  training, distribution and deployment authority flags remain false. This is
  the same bounded synthetic-history rehearsal, not a production backup restore.
- Report file SHA-256:
  `9fc682bb6a604ddd324b3dcb44bb02ddeb6a40171a377f5da9c595119aafb026`.
  Internal report hash:
  `3004ad4ec70fc2f53535db9b2f150cb651e1c1224ab86e746add1ef10adeaee3`.
  Source-input inventory hash:
  `b727aa47b6fdec58df22b87b989861983997ec9ab3480ca143547777f5863daa`.
- All 136 then-present local documentation link targets resolved. Whitespace
  checks passed. The migration receipt is an actual new observation; older
  732-input receipts were not resealed or overwritten.
- Frontend source regression after the CI edit: **45 passed, 1.680 s**.
  No application UI, API implementation, schema or test assertion was changed
  in this batch; the source inventory change comes from test coordination.

The batch79 browser/ingestion/capacity results remain historical, not relabeled
as executions of this new coordinator. The earlier 732-input migration receipt
is retained unchanged; the added test-tooling files change its broad inventory.

### Resumed verification checkpoint — 2026-09-13 13:25:27 UTC

The same handle **10177** remains live; it was not restarted after the
interruption in the conversation. Actual JUnit checks now cover:

| Batch | Whole modules | Passed | Skipped | Failed / errors | Pytest elapsed |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 28 | 993 | 0 | 0 / 0 | 522.24 s |
| 2 | 28 | 897 | 0 | 0 / 0 | 777.17 s |
| 3 | 28 | 1,060 | 3 | 0 / 0 | 452.22 s |

Owned-service cleanup was reported after each completed batch. Batch 4 has
started in new owned services. The partial result is **2,950 passes across 84
modules**, not full-suite completion. The three skips are precisely the Al,
AlAs and BN explicit-reference cases, because ordinary regression receives no
external reference paths. Their separately executed
[batch81 verification](Reference_Canary_Verification_Batch81_2026-09-13.md)
records three passes; its retained XML hash was rechecked, without replacing
these skips or adding those passes to this run.

The plan's API/script source pins still match. No terminal `result.json` exists
yet, and CI runtime-budget acceptance remains unresolved. The
[local implementation PR draft](Implementation_PR_Draft_2026-09-13.md) now
separates these measured results from pending remote CI and scientific review;
it has not been submitted.

## Remaining delivery and scientific gates

No commit, push, PR, issue closure, merge, deployment, production migration,
permission grant or feature activation was performed. Authorization requested
for committing/pushing the upgrade branch and opening a draft PR remains pending.
Full local API integration is necessary, not sufficient for the exact-revision
Linux delivery gate. Real permitted-source pilot work, independent human review,
scientific acceptance and empirical ML/RPS evaluation remain separate requirements.
