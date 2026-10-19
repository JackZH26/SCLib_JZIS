# API regression selection and release evidence

PR and main both execute their own checked-out revision. The PR run tests GitHub's
merge checkout; main tests the resulting main commit. Results are not reused
between those different commits.

`scripts/api_test_policy.json` defines the always-run core and reviewed code-to-test
mapping. Core covers health, authentication/session boundaries, privacy/access,
API contracts including quota rejection, and scientific HTTP search. A change to
`api/services/scientific_query.py` additionally selects its query, search, Ask,
retrieval and answer-evidence consumers. Changed existing test modules are included.

Only explicitly listed Wiki UI/content and documentation paths use core alone.
Unknown paths, deleted test modules, authentication/database/shared infrastructure,
lockfiles, workflows and selection tooling cause a full API run. Renames classify
both names. Missing mapped tests or unsupported discovery configuration fail rather
than silently narrowing coverage. New mappings must include transitive consumers
and add selector regression tests. This conservative initial map can be extended
only with evidence about the affected endpoints.

## Four independent jobs

The plan records the base SHA, exact checkout SHA, changed files, complete module
inventory, selected modules and policy hash. Historical JUnit timings determine
eight deterministic, disjoint batches, paired into four jobs. Each job runs two
batches sequentially; each batch gets new PostgreSQL and Redis instances through
`run_disposable_tests.py`. No production DSN is accepted or passed through. The
existing capability/identity and connection-before-import guards remain intact.

Each batch uploads actual JUnit, elapsed time and the installed runtime inventory
immediately, including failure receipts. The aggregate requires all batch runtimes
to agree; the release gate also compares them with the image-parity test runtime. Four jobs can run concurrently (`max-parallel: 4`, `fail-fast: false`).
Each service lifetime is bounded to 28 minutes; the job allows 65 minutes including
setup. Failure prevents the second batch in that job, but other jobs report their
results. The final job recomputes the selection at the exact checkout and verifies
every expected batch and module against actual JUnit, rejects missing/duplicate or
wrong-revision evidence, and requires all jobs to pass. Skips remain visible.

Historical run 38049173131 spent about 130 minutes in sequential API batches;
its 7,706 seconds of testcase durations predict about 32 minutes of test work per
parallel job for full coverage, plus setup. These are estimates, not measured new
workflow times. Ordinary Wiki changes should be much shorter. This first change
to the selection rules is itself critical, so both PR and main retain full coverage
in parallel during bootstrap. The old full-suite coordinator remains available.

## Independent full suite and release latch

`API full regression` runs daily at 18:17 UTC (02:17 UTC+8) or manually on main.
It uses the same four isolated jobs with forced full coverage and does not publish.
All full-suite failures are conservatively treated as release-blocking, not just a
manually selected severity subset.

Before building release images, `check_api_full_gate.py` requires the successful
exact main Test run and its matching-attempt API summary. A targeted release also
requires a successful independent full run on an ancestor within seven days. An
unfinished, failed, cancelled, stale, unrelated or unavailable full run blocks it.
A full passing Test on the exact target can bootstrap the first baseline or clear
an older ancestor's failure; a newer full failure still blocks. GitHub/API and
artifact errors fail closed. The check reads the latest updated independent run,
including reruns. It does not reuse a PR badge as main evidence.

Installed-wheel probes, complete offline safety contracts, image/runtime parity,
capacity tests, migration tests, security scans, signatures, production backup and
health checks remain required. Passing engineering tests does not certify the
scientific contents of SCWiki. Full scientific review and release observation are
tracked separately.
