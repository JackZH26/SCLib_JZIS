# Batch67 — installable ML08 accounting and bounded document intake

Base: `d85b106` on `codex/sclib-research-v2`, preserving the uncommitted batch66
changes. This increment advances the ML08 technical prerequisite identified in
batch66: the API must not depend on repository-only scripts to check pilot
documents. A fresh GitHub read still found 38 open issues, including ML08 #54.
No issue is closed by synthetic accounting or installation tests.

## Delivered scope

- Moved the existing scientific validator into
  `api/services/ml_pilot_accounting.py`; the compatible repository CLI delegates
  to that single kernel. Scientific accounting remains `ml08-accounting/1.0.0`.
  Returned warning lists no longer share mutable state across requests.
- Packaged the exact schema beside that module. A test requires byte identity
  with the retained public schema; installed execution does not locate `docs/`
  through a guessed repository parent.
- Added `services.ml_pilot_documents` with independently supplied raw-file and
  logical anchors, protocol binding, optional paired conclusion, 8 MiB per input,
  cumulative 400,000-node/depth-64 guards and 2,000 review revisions. Physical LF
  JSONL parsing preserves quoted U+2028/U+2029; duplicate keys, invalid Unicode,
  nonfinite values and over-limit documents fail without truncation.
- Kept every authority flag false. This service neither stores documents nor
  registers a pilot, authenticates a person, opens evidence, verifies permission,
  replays the canary or grants a training run.
- Updated canary construction to `ml08-canary/1.1.0`, with the two installed
  modules and schema added to its selected-source inventory. Existing input
  schemas remain 1.0.0; historical canaries/reports retain their original bytes
  and pinned implementations, not edited versions or resealed hashes.
- Included the new schema resource in native interface and migration source
  provenance. The database head remains 0075; this batch adds no migration.

The [intake contract](../../ML_PILOT_DOCUMENT_INTAKE.md) documents the exact API
of the internal service and unfinished authentication gates. The
[canary guide](../../ML_PILOT_CANARY.md) records version compatibility.

## Actual installation, including the defect it exposed

An initial real-wheel probe failed: reusing the audited-dataset JSON helpers
indirectly imports `models.ml_task`, whose package initializer loads `models.db`.
A second diagnostic attempt confirmed that initializer dependency. The final
probe does not whitelist ORM imports or install application dependencies to
hide this failure. Instead, the new pilot transport module owns its bounded
JSON scanner and uses only the standard library plus the shared accounting
kernel. Existing larger dataset codec behavior was not changed.

Locally, the actual API wheel was built using the declared Hatchling backend
(cached Hatchling 1.31.0; no local `uv` command was available). A new standard-
library venv installed that wheel with `pip --no-index --no-deps`. Its Python
3.12.14 ran the probe with `-I`. The probe blocks repository script, server/ORM
imports, sockets and subprocesses; both modules and schema resolved inside the
new installation. All 60 synthetic candidates remained unreviewed, unregistered
and non-authorizing. These are software fixtures, not actual source events.

The successful [installed-wheel receipt](measurements/ml08-installed-wheel-native-2026-09-13.json)
has raw SHA-256 `c76cfd82e7309c90b870fd542529d4a1350dbd9f3b68df5859c93bd6e650d71a`.
The tested wheel has SHA-256
`d4d8b2315e75be84737e789fbe7733733ec5a0c3341a1404ebe19127a7efedbf` and remains
under `/private/tmp/sclib-ml08-package-final-QM1wDK/wheel/`. The receipt pins
the two installed source files and schema; it is not a full runtime/image or
reproducible-build attestation. A repeat probe matched the retained receipt.

The API CI job now builds a wheel with `uv build`, installs it in a separate
dependency-free venv and runs the same isolated probe before the scripts suite.
This is an implemented CI gate, not evidence that Linux CI or a Docker build
has executed. The existing locked test environment is not modified by that
separate installation.

## Verification

The first complete scripts run passed **2,073 tests / 39 subtests**, 185.87s.
The real migration invocation then exposed an integration omission: collection
included the new schema but receipt validation still rejected its path. It
exited 2 with `invalid_report_input_path`, cleaned up its owned services and
published no report. This is a failed rehearsal, not acceptance evidence.

The receipt validator now narrowly permits direct `api/services/*.schema.json`
resources, without admitting arbitrary JSON, nested paths or traversal. Eight
path cases and a real-inventory-to-receipt round trip cover the previously missed
consumer boundary. Targeted intake/report checks passed **113 tests**, 3.90s.
Final full scripts: **2,081 passed / 39 subtests**, 218.53s. Targeted/earlier
passes overlap this suite and must not be added as unique coverage.
The fresh [final 0075 native migration receipt](measurements/schema-rehearsal-0075-native-batch67-2026-09-13.json)
passed the complete migration/read-model rehearsal with verified owned cleanup,
**226,151 ms** and **694 source inputs**. Runtime: PostgreSQL 16.13, CPython
3.12.14, Darwin arm64. The archived 107,914-byte file has raw SHA-256
`c7557d037d123f36c48d0137531cf54816e32de7b843ba0e833de597b3782deb`;
its input inventory hash is
`9f2b753d9a3b406ff7778a9ae60f3a0ae73121a8856f75e412e95571c27ec033`.
The copied receipt passed strict parsing and comparison with current source
provenance. The earlier failed run has no archived passing receipt; old batch66
and earlier evidence remains unchanged and historical.

The initial native interface invocation passed **3 tests**, 127.89s, and removed
only its own PostgreSQL/Redis services. The pre-existing FastAPI `regex` argument
deprecation warning remains unrelated. New byte-exact synthetic HTTP archives:

| Archive | Bytes | Selected pins | Original JSON replies | Raw SHA-256 |
| --- | ---: | ---: | ---: | --- |
| `ml-use-runs-native.batch67.wire.json` | 194,500 | 565 | 28 | `c8cc16d02e1117ab6fb6c106fc2181b4b8f1009d9ff0a5b06a42e4adfc3e0b00` |
| `ml-use-rights-native.batch67.wire.json` | 211,875 | 565 | 15 | `4372be2a47ff30fab7990a58ac3d2db193d722602d6c18886b0d56b38d0f3059` |
| `discovery-main-barrier-native.batch67.wire.json` | 197,837 | 279 | 7 | `cc48f80182e16f1238a5da9480c43f10b31b6bd93d037412a6fe3400ecb830ad` |

These source inventories are explicitly selected subsets, not complete runtime
attestations. The reporter fix changes a selected script in the run/rights
captures, so those initial archives remain historical and need separate final
captures; the Discovery capture's selected inputs are unchanged. Frontend
consumers additionally require the installed schema pin. All historical
raw-archive hash checks remain intact. The second fresh native invocation passed
**2 tests**, 132.08s, with verified owned-service cleanup. Its final archives are:

| Final archive | Bytes | Selected pins | Original JSON replies | Raw SHA-256 |
| --- | ---: | ---: | ---: | --- |
| `ml-use-runs-native.batch67-final.wire.json` | 194,500 | 565 | 28 | `7f936957dfd468cb7d23ad93c04d759c798b89b6bb27218856107489327c478b` |
| `ml-use-rights-native.batch67-final.wire.json` | 221,685 | 565 | 15 | `d4d6c5d119b35eab2a1d05a474b00dc1fb77403d041ad4fe0fb34b473c45c4de` |

These are the active run/rights test inputs; the unchanged Discovery batch67
archive remains active. No historical response was reserialized or resealed.

The first frontend run passed 38 source checks, then **1,579 unit tests passed /
8 failed** (95.30s): seven layout cases exceeded the existing five-second limit
and one governance case asserted focus before React's effect ran. TypeScript
checking did not execute after that failing `&&` step. The focus test now waits
for the actual effect and restores the temporary scroll implementation even on
failure; no application focus behavior was changed. The unchanged layout tests
and corrected governance test passed together: **43 tests**, 26.20s, with two
workers. Final frontend verification uses bounded concurrency without skipping
cases or increasing their timeouts.

Final frontend command:
`pnpm test:source && pnpm exec vitest run --maxWorkers=2 && pnpm exec tsc --noEmit --incremental false`.
All **38 source checks**, **45 files / 1,587 unit tests** (103.48s), and the
subsequent nonincremental TypeScript check passed against the final fixtures.
All three active native inventories, the final migration provenance and exact
installed-wheel receipt were reverified after those source changes stabilized.

The run workbench's separate isolated browser suite passed **4 tests**, 1.6 min,
using the initial batch67 native run responses. It covers desktop/mobile
independent review, approval/revoke/deny, private text, purge, lost responses,
exact recovery and cleared admission. Its browser transport remains synthetic,
not fresh database responses or real human approval.

After switching to the final archives, the isolated run browser suite passed
again: **4 tests**, 40.3s. The rights browser suite also passed **4 tests**, 33.5s,
including inventory paging, keyboard preview, read-only lost-reply recovery and
admission refresh clearing private data at both viewport sizes. These are not
additional unique run cases beyond the earlier run suite. Final browser artifacts:

- Runs: `/var/folders/m0/ztnj2ywn613cqhtb3_ym0xyc0000gn/T/sclib-ml-runs-browser-artifacts-XjDFhQ/`.
- Rights: `/var/folders/m0/ztnj2ywn613cqhtb3_ym0xyc0000gn/T/sclib-ml-rights-browser-artifacts-7RiXgX/`.

The final mobile private-evidence screenshot was inspected: source-like text
stays literal, narrow controls remain contained, and website-owned copy stays
English. All reported test processes have terminal outcomes. Scoped Ruff,
browser-harness syntax and `git diff --check` passed; all 108 relative links in
the changed batch67 documentation resolve. No broad service cleanup was used.

The standalone private report browser check passed desktop 1440×1000 and mobile
390×844, with 60 events, 11 priority fields, zero external requests, zero page
errors and no document-width overflow. It used a freshly generated, explicitly
synthetic hostile-text fixture from the existing test (1 passed, 3.44s), not a
real private pilot. Overview, mobile field table and event-history screenshots
were inspected. Quoted markup stays inert; the field table scrolls locally on
mobile. Artifacts remain in
`/private/tmp/sclib-batch67-native-sazkAr/report-browser-artifacts/`.

## Next dependency and scope limits

Next is immutable preregistration with server chronology and authenticated
reviewer membership, followed by independent exact-artifact scientific signoff.
The uploaded protocol's approval field, candidate declarations and file hashes
cannot prove real approval, real events, independence or source permission.
Actual permitted sources and human participants remain required for ML08 #54.
The existing offline/manual pilot path is still supported; a new web workflow
is not a substitute for doing that scientific work.

After genuine pilot acceptance, ML09 still needs its separate current-rights,
runtime, budget and one-shot execution gates. No model fitting, real data import,
role grant, production operation, commit, push, PR, deployment or issue closure
was performed in this increment. Remote delivery still needs the previously
requested direction. The upgrade goal remains active.
