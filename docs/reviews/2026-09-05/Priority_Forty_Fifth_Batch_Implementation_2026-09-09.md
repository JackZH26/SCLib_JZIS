# Forty-fifth implementation batch — pending scientific import workbench

Date: 2026-09-09. Branch: `codex/sclib-research-v2`.
Baseline: `f90c3ee52f16cea0b4c33d65ef6048de5deb64ab` (forty-fourth batch).
Issues: [ML05 #67](https://github.com/JackZH26/SCLib_JZIS/issues/67),
[UX02 #73](https://github.com/JackZH26/SCLib_JZIS/issues/73).
Contract: [Scientific import workbench](../../SCIENTIFIC_IMPORT_WORKBENCH.md).
Original design: [retained implementation proposal](Scientific_Import_Workbench_Implementation_Design_2026-09-09.md).

## Outcome

Added an English private workbench over the actual existing pending QE matdyn
importer. Operators can inspect an exact existing material, select bounded local
source files and independent hashes, preview the real import and explicitly
commit the same byte/context package. The navigation extends the current
dashboard; no new hosting platform, dependency package or authentication scheme
was introduced.

The accompanying small backend increment adds current-curator capabilities,
read-only original actor/key/package-pin recovery, and optional preview-package
pin checking before the durable start. It preserves the old two-stage import,
schema, parser, native data formats, pending-result creation, review gates and
independent failure/recovery behavior. The previous API lacked a browser-accessible
original-key lookup when the first acknowledgement was lost before an attempt
UUID reached the client.

This does not execute QE/DFPT/phonopy, expand the scientific property registry,
create a material, approve a result, infer a superconducting label, admit training
data or calculate RPS. No actual user-source package, paid provider, production
database, production migration, remote push, PR, deployment or issue closure was
performed. Owned synthetic native-format source bytes are used only in tests.

## Exact source and preview identity

The browser rejects noncanonical manifest bytes rather than silently rewriting
them. Canonical UTF-8, closed versioned keys, supported integer sizes, no duplicate
keys/BOM/trailing newline, independently expected hashes and complete inventory
are checked. Physical source filenames may differ from their logical names;
actual selected bytes and sizes establish the match. Shared hashes are encoded
once while their distinct logical references and original inventory order remain.

Optional FC requires actual bytes, its independently supplied hash and the exact
logical `flfrc` name, not a physical `<sha>.bin` capture name. Missing FC remains
an explicit quarantine path. No structure is generated from formula text.

The complete file selection is size-checked before large reads. Metadata and
the File map are captured synchronously before asynchronous reads/hashes; a
caller cannot change the request key or context halfway through preparation.
The actual Python-generated fixture confirms browser construction of the same
augmented package key, including manifest/context UTF-8 lengths and compiler hash.

Independent review found that the old POST accepted the same files after a
compiler change without checking the preview package. The additive
`expected_request_sha256` now rejects that mismatch before parsing or durable
start. It remains optional for legacy clients and is always supplied by the
new workbench. The browser also rechecks account/grant/compiler before committing.
It does not compare whole preview/commit receipts or measured worker times.

The compiler inventory intentionally includes the service file. Its new helper
functions change the compiler hash of new packages, but do not rewrite prior
retained source/history. Read-only historical lookup uses the original package
pin, not the currently installed compiler. Different compiler versions are not
silently interchangeable execution retries.

## Durable outcomes without automatic retries

The new GET lookup authenticates a current curator, finds only that account's
original request key, and compares the independent package pin. A replacement
current grant may read the same account's historical receipt; the retained old
grant is not falsely presented as current execution authority. The legacy
attempt-ID endpoint retains its existing broader curator inspection semantics.

GET is genuinely read-only: no source insertion, parsing, worker resume, failure
write, guard-epoch change or new attempt. An absent/foreign key returns 404;
wrong pins return 409. A durable start without a terminal returns
`outcome_unknown`. None of these implies rollback or automatic retry permission.
Exact bounded query fields are enforced. Independent inspection of FastAPI's
dependency flow showed that an endpoint-only byte check would run after query
allocation, so the 1,024-byte raw limit now runs before the handler. A test spies
on query parsing itself, not just the final status code.

The UI sends a second POST only for the explicit commit action. A synchronous
guard blocks double clicks. Unknown acknowledgement locks new imports and
discards files, encoded drafts, preview, formula and material-row pins, leaving
only the original account/key/package recovery references. **Check original
outcome** is a separate GET-only action with no automatic polling or retry.

Account notifications invalidate the request generation and clear private state.
Late file reads and HTTP responses cannot repopulate it. Other accounts do not
see the retained recovery locator. A successful historical read cannot imply
fresh scientific/source/ML authority. Full-page unload warnings and explicit
private-record instructions are present; client-side navigation/reload can still
lose in-memory references. No persistent browser storage or browser execution-
resume workflow is claimed.

## Scientific display and accessibility

The workbench projects only a bounded receipt: import status, safe reason codes,
actual durable IDs, exact package pin and parser-worker CPU/wall times. Closed
envelope/authority checks reject contradictory statuses, impossible successful
coordinate/coverage shapes, unexpected fields and wrong pins. Raw native reports
are never rendered or rehashed with JavaScript's different float serialization.

`success_pending` is labeled pending scientific review, not success at producing
a superconductor. A preview may propose that status without creating rows; no
durable ID or review link is shown from it. Only actual committed property IDs
link the user toward the existing evidence inventory. The general inventory
link is not advertised as an unsupported property deep link.

Calculation CPU/wall/monetary costs remain not reported, never zero. Formula
agreement is not phase/sample identity; supplied q-point minima are not complete
zone stability. Current scientific, source-time, redistribution, execution and
ML flags all remain false. Default labels, errors, missingness, accessibility
copy and numeric formatting are English, preserving the scientific units and
unreviewed source declarations.

Desktop and 390 px mobile workflows verify real File APIs, keyboard focus and
sticky-header offset, no horizontal overflow, explicit upload/commit and recovery
states. The browser fixture transport uses captured actual disposable SQL/HTTP
responses, not a live user upload or a mocked claim of scientific validation.

## Verification

Final combined backend, frontend, browser and production-mode build checks
passed against the frozen sources. Subsequent edits finalize documentation only.

| Check | Result |
| --- | --- |
| Guarded native API, exact seven-module selection below | **311 passed**, 1 existing warning, **196.76 seconds**, exit 0 |
| Final whole frontend Vitest, one worker | **1,077 passed** across 34 files, **74.92 seconds**, exit 0 |
| New focused contract/component cases | **129 passed**, **3.90 seconds** |
| Final desktop/390 px Chromium cases | **4 passed**, **19.1 seconds** |
| Frontend source regression | **35 passed**, **1.50 seconds**, exit 0 |
| TypeScript `--noEmit --incremental false` | Passed, exit 0 |
| Isolated production-mode standalone build with `/sclib` base path | Passed after final source synchronization; 33 static pages, new import route included |
| Python Ruff `I,F` and Git whitespace | Passed |

The warning is the existing FastAPI `regex` deprecation in `routers/admin.py`.
The native runner confirmed cleanup of only its owned PostgreSQL/Redis/services
and temporary data. The run includes no skipped genuine-reference canary claim:
those external-source tests were deliberately not selected or downloaded again.

Native checks include complete SQL-state/epoch equality for preview and GET,
exact pinned commits and terminal replay, all four actual attempt outcomes,
wrong actor/key/pin, grant/session changes between authentication and read,
feature gating, sanitized unavailable reads, malformed queries, pre-parser
allocation bounds and pre-start compiler drift. Existing importer, native
coordinate/frequency parser, schema and public-admission tests are unchanged.

Earlier native checkpoints were 134 combined cases, then 32/33 focused cases,
then nine changed query-boundary cases. They overlap the final 311 and are not
additional independent coverage. The first full frontend checkpoint passed
1,076 tests before the final historical-grant test and material-binding cleanup;
the final result above supersedes it. Earlier browser/focused measurements are
likewise not added to the final totals.

The build uses an owned OS temporary source copy including the existing Plotly
type declaration directory and a local copy-on-write clone of installed
dependencies. It uses unchanged Next.js configuration, the existing offline font
fixture and inert API origins. The normal worktree `.next` and existing port
3105 were not used. A final rebuild synchronizes the last material-binding-clear
change before claiming current-source verification. This is a local production-
mode check, not actual Linux release-image CI, production-origin verification or
deployment. The isolated browser server on port 32045 was stopped after testing;
temporary screenshots/copies remain in the OS temporary area for diagnosis.

Reproduce the native selection from the repository:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server --suite api -- \
  tests/test_scientific_import_recovery.py \
  tests/test_scientific_program_import_operators.py \
  tests/test_scientific_pending_import.py tests/test_scientific_import_schema.py \
  tests/test_qe_matdyn_import.py tests/test_qe_force_constants_import.py \
  tests/test_scientific_result_public_gates.py -q --tb=short --show-capture=no
```

From `frontend`, use `pnpm exec vitest run --maxWorkers=1`,
`node --test tests/*.test.mjs`, `pnpm exec tsc --noEmit --incremental false`, and
`pnpm exec playwright test --config tests/e2e/scientific-imports.config.ts`.
No complete API or new scripts-suite regression is claimed for this increment.

## Remaining issue acceptance

A fresh read-only GitHub query found **38 review issues OPEN, 0 CLOSED**. Live
ML05 and UX02 acceptance criteria were reread; this interface increment does not
replace their full scientific, dependency and delivery requirements.

ML05 still requires its permitted genuine-package cohort and scoped context/
method review; the existing limited phonon adapter must not be relabeled as
support for all DOS, EPC, energy or stiffness conventions. UX02's independent
review/publisher flow and downstream acceptance remain separate from curator
import. Real ML08 review and authorized ML09 evaluation cannot be supplied by
synthetic test totals. Linked PR/release evidence, production acceptance and any
human scientific/source-rights decisions remain unperformed. The overall goal
remains active; no scientific or release gate was waived to close an issue.

## Next dependency-ready software increment

The next practical local gap is RPS source-binding preparation and package
registration before the already implemented rights workbench. The current
`DistributionRightsWorkbench` requires an already registered UUID. The existing
registration API requires complete bindings and actual descriptor/source bytes;
`research_distribution_contract._prepare()` does not create missing descriptor
evidence. `tests/rps_distribution_fixtures.py::distribution_inputs()` currently
illustrates preparation using direct synthetic SQL inserts, not an operator UI.

The next increment should accept independently pinned existing releases/public
bundles and explicitly selected genuine source-capture or frozen-result roots,
resolve exact material/state rows, and prepare only the existing controlled
`rps-artifact-record/1.0.0` descriptor bytes. Reuse the existing inventory and
registration validators, with rollback-only preview, exact-intent atomic
registration and original-key read-only recovery before handing off to rights
review. Missing/substituted roots must fail; no external import, fabricated
scientific evidence, rights decision, publication or general ML-use permission
may be generated by this preparation step. This is a concrete usability gap,
not a claim that ML07's literal acceptance criteria require another UI.
