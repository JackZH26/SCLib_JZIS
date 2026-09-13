# Batch69 — prospective registration chronology and worker reliability

Base: local `634265d` on `codex/sclib-research-v2`, preserving the uncommitted
batch68 work. A fresh read of ML08 #54 still requires a genuine preregistered
60-event study, independent human reviews, permitted evidence, field-specific
missingness and curation effort. This increment addresses the next concrete
software prerequisites; a fresh issue-list count remains **38 open issues**.
Synthetic declarations do not satisfy those scientific
acceptance criteria or close the issue.

## Changes and scientific boundary

- The installed document checker is now `ml08-registration-documents/1.1.0`.
  It derives canonical UTC selection/freeze instants from the exact pinned
  selection. The authenticated service checks the ordered instants against
  PostgreSQL `clock_timestamp()` inside both preview and new-write transactions.
  New acceptance also checks against the original registration timestamp.
  Browser/worker clocks and transaction-start time are not substitutes.
- Historical verifier policies are explicit in private inspection. An older
  policy cannot gain current readiness or new acceptance just because code
  changed; original-key read-only recovery and protective decisions remain.
  The upload/ledger formats remain 1.0.0 and database head remains 0076. No old
  immutable row, file or native receipt is rewritten. A future legacy transition
  requires a reviewed explicit workflow, not changed candidates or altered hashes.
- The selected installed implementation inventory additionally pins the shared
  worker I/O/cleanup helper. Its scope still does not establish a complete runtime
  attestation or an OS security sandbox.
- Added offline adversarial tests and real subprocess tests, including both
  exact 8 MiB input files in one envelope, duplicate/nonfinite/invalid/deep JSON,
  cumulative node limits, bad base64/anchors, alias/account substitution, source
  changes during verification, cancellation including in-flight spawn, timeout,
  over-limit output, owned-child reaping and the real I/O audit hook.
- Added actual owned PostgreSQL/HTTP tests for future freeze rejection in preview
  and explicit commit, timezone/subsecond comparisons, unchanged full SQL state
  on rejection, altered acceptance bytes, legacy-policy visibility and colliding
  writers. The collision tests pause one writer **after its real lock**, observe
  PostgreSQL SQLSTATE `55P03` for the other, then verify one durable history and
  exact original-key recovery. A competing stale root gets 409, not an overwrite.

Only declared-time consistency and account behavior are tested. Neither a
server timestamp nor an account hash proves external chronology, actual human
identity/independence, source permission, the existence of the claimed source
events, or scientific acceptance. The private API remains default-off, with
training disabled and no participant web workbench yet. See the
[registration contract](../../ML_PILOT_REGISTRATION.md).

## Actual installed-wheel execution

The new `scripts/probe_ml_pilot_registration_install.py` runs both installed
worker operations with isolated Python. It refuses repository fallback and
application/ORM imports. Its parent permits only the exact owned worker command
and minimal environment; the installed child uses its real I/O guard. The
event loop's local wakeup socketpair is established before denying new sockets.
This is not an OS-level network sandbox.

A new wheel was built with cached Hatchling 1.31.0 and installed with
`pip --no-index --no-deps` into a separate new venv. No local `uv` executable was
available. The existing API environment was not modified. The tested wheel is
retained under `/private/tmp/sclib-batch69-package-guNmHC/wheel/`, SHA-256
`35981663fbf0899c67c3112b76140159570e88429b7445e7aec5eb16a859109a`.

The [native installed-worker receipt](measurements/ml08-installed-registration-worker-native-batch69-2026-09-13.json)
preserves the successful probe's exact stdout bytes; a second actual invocation
matched them. Raw SHA-256:
`2397d9c56d325bc7ab4f1cb4d77407deb3140fa011abf507ce21a4a15b87d1fc`.
It reports two successful real children, six selected installed source pins,
CPython 3.12.14, synthetic input only, and no registration/participation/science/
training authority. It explicitly did not check a database clock. Native macOS
installation is not Linux image parity or remote CI execution.

The existing CI wheel-install step now runs this second probe before the full
offline scripts suite. This is an implemented gate, not proof that remote CI ran.

## Verification and honest failures

- Initial offline worker cases: **39 passed**, 11.24s. Their combined run with
  existing document tests passed **69**, 15.53s. After adding isolation/fallback
  probe checks, the worker module passed **40**, 14.86s. These overlap.
- Initial native registration/HTTP/reliability run: **22 passed / 1 failed**,
  37.23s. The new historical inspection test omitted its required read-only
  transaction. The production admission guard correctly refused it. The test
  now enters the existing read-only snapshot helper; no guard was relaxed.
- Final targeted registration/HTTP/reliability plus audit-retention run:
  **56 passed**, 72.00s, with the pre-existing FastAPI `regex` deprecation warning.
  Owned services and temporary test data were cleaned up. The new reliability
  module has nine cases, including three deterministic actual write collisions.
- Scoped Ruff checks pass using the existing per-file configuration and Python
  3.11 language target; no lint exception was added. `git diff --check` passes.
- The final complete scripts suite passed **2,132 tests / 39 subtests**, 280.62s.
  Earlier targeted script checks overlap it and are not added as unique coverage.

The complete owned-native 0076 rehearsal passed in **312,909 ms** and verified
cleanup before publishing a `schema-rehearsal/1.1.0` receipt. The new
[batch69 migration receipt](measurements/schema-rehearsal-0076-native-batch69-2026-09-13.json)
is 110,360 bytes, raw SHA-256
`71adde39a4b472b18117b4ce5e55efa9c1890fba7777fdd7df27208c1e37dbc6`.
It pins **706 source inputs**, inventory SHA-256
`58730046219f3a1177d683e3a2111fde1e16d7c458d4930ea5eba28653a0a10f`.
All four pilot outcomes are separately observed: empty roundtrip preservation,
incomplete-roster refusal, account participation and nonempty-history downgrade
refusal. This is the complete existing rehearsal on current source, not only
metadata schema creation. Native runtime: PostgreSQL 16.13, CPython 3.12.14,
Darwin arm64. The archived bytes equal the original receipt and pass strict
validation and current-source comparison. This does not establish Linux image
parity, real source data acceptance or production deployment safety.

The separate native interface capture invocation passed **3 tests**, 193.39s,
with the same pre-existing warning and verified owned cleanup. The new archives
were copied byte-for-byte without overwriting the originals:

| Active archive | Bytes | Selected source pins | Original JSON replies | Raw SHA-256 |
| --- | ---: | ---: | ---: | --- |
| `ml-use-runs-native.batch69.wire.json` | 195,841 | 575 | 28 | `4d12cc266b5420f7630613501dcee172ba222c01f3ec22d858dd5a5de43b8923` |
| `ml-use-rights-native.batch69.wire.json` | 221,522 | 575 | 15 | `efefe4aef7b5112d21359128f17e662198a5e8531ca90a20a0bad007014d3222` |
| `discovery-main-barrier-native.batch69.wire.json` | 198,499 | 284 | 7 | `e74ffc908035889d4cd28424ef1e96ac8ea401f7289809f2f0ffc73d068b9b1e` |

All selected hashes matched current source files. Frontend consumers now import
these archives; earlier raw-hash assertions remain intact. Run/rights consumers
also require the new reliability test and installed-worker probe in the selected
inventory. These existing ML run/rights/Discovery captures check source/interface
compatibility; they are not pilot UI tests or new scientific reviews.

Frontend source checks passed **38**, followed by the nonincremental TypeScript
check. The final full frontend run and the two isolated browser suites were
started after the scripts and native processes completed, retaining the existing
two-worker/timeout settings. The full frontend run passed **1,587 tests in 45
files**, 135.67s, followed by the nonincremental TypeScript check. No skipped case
or increased timeout was used. Both subsequent browser suites passed: **4 run
workbench cases**, 57.7s, and **4 rights workbench cases**, 32.2s, including desktop
and mobile. These use declared browser transport doubles around the exact new
native captures; they are not another SQL execution or actual human review.

Current screenshots are retained in the private temporary artifact directories
`sclib-ml-runs-browser-artifacts-kG0UTx` and
`sclib-ml-rights-browser-artifacts-jpnnwF`. Visual inspection of the mobile private
evidence and rights preview captures confirmed readable wrapping, visible
controls, English website-owned copy and multilingual quoted evidence rendered
as text. Isolated test ports 32060/32062 have no remaining listener; the observed
owned server/worker PIDs have exited. No normal development service was stopped.
Batch68 and earlier receipts retain their historical source scope; none is
relabeled as current.

Final artifact checks compare all three raw archive hashes and their selected
source pins, the six installed-worker source pins, and the complete 706-input
new migration receipt against current files. All **115 relative links across
six touched Markdown documents** resolve. `git diff --check` passes. This batch
and the preceding batch68 increment remain uncommitted on top of `634265d`.

## Next gates

The next product increment is an English participant workbench for exact-file
preview, account-bound acceptance/decline/withdrawal, current-policy inspection
and original-key recovery. Independent exact-artifact scientific signoff remains
a separate subsequent workflow. Real reviewers, permitted source material and
the actual 60-event study are still required for ML08 closure; ML09 and AL01
remain dependent on real reviewed inputs and their own execution gates.

Remote PR/Linux CI delivery and production enablement remain separate. This
increment did not push, deploy, modify a shared database, grant real roles or
close an issue. The full upgrade goal remains active.
