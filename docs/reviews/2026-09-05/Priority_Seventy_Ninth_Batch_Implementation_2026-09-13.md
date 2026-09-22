# Batch 79 — integration evidence and research-browser CI

Base HEAD: `02949468802db042e56645e2932b08863a174074`, branch
`codex/sclib-research-v2`. Preserves uncommitted batches 74–78. The previous
goal turn made implementation and verification progress. This checkpoint adds
missing browser/migration CI evidence and records actual local integration
checks. **The full ordinary API run was subsequently interrupted deliberately;
its terminal outcome and batch80 continuation are recorded below.** Do not
describe this as a fully passing API suite or a completed remote release.

## Delivered integration changes

The default Playwright command only selected the public `.spec.ts` tests. Nine
private research-workbench `.visual.ts` suites had individual local configs but
were not executed by that CI command. The existing `frontend-e2e` job now runs
both the original public production-mode assertions and a unified private-workbench
suite. The public runtime was subsequently isolated as documented below; all
six existing CI jobs remain present.

The new launcher creates one exclusive output root before Playwright starts.
It rejects existing paths/symlinks and supports only the optional `--list`
argument; CI cannot silently select a smaller group through this command.
The config collects all `.visual.ts` files with one worker, no retries,
`forbidOnly`, blocked service workers and no reuse of an existing server.
The required attempt-qualified artifact retains JSON/HTML results, synthetic
screenshots and failure traces. The shared isolated server copies application
source, links already installed dependencies and uses synthetic browser HTTP,
inert server-side API configuration and the existing offline font hook.

The migration CI command now also requests the existing runner's source-pinned
report and uploads it as required `schema-rehearsal-attempt-N` evidence. A
report is published only after verification, owned-service cleanup and source
rechecking. Merely configuring these jobs does not mean Linux CI has run.

No application, ingestion or API/script source, schema, lockfile, scientific
field, feature flag or production configuration was changed in this batch.
The complete browser operator contract is
[RESEARCH_BROWSER_TESTING.md](../../RESEARCH_BROWSER_TESTING.md).

## Actual browser verification

Actual Playwright collection found **42 tests in nine files**. The first run
failed before executing interactions: config loading in each worker attempted
to create the already-created output root. The result was **9 startup failures,
33 not run, zero passes**. This was a harness lifecycle error, not evidence of
nine website defects. Output creation was moved into the one-shot launcher;
the workers only validate/read its inherited path. Existing-output protection
was retained, with a direct create/reopen/symlink regression test.

The complete second run passed **42/42, zero skipped, zero unexpected and zero
flaky, 144.074 s**. It exercised saved history, distributions, pilot participation,
pilot reviews, ML rights, ML runs, scientific imports, scientific review and
source tasks on desktop/mobile. No test assertion or application behavior was
weakened to make the unified run pass. Four new source/launcher tests passed.

The native browser used Node 25.5.0, pnpm 9.12.0, Playwright 1.61.1 and Next.js
15.5.21. The synthetic server no longer listened on its owned port 32078 after
completion. The desktop atomic-field availability and mobile field-report
screenshots were inspected: English labels, explicit empty atomic denominator,
private-report warnings and readable narrow-screen layout. This is not production
font/base-path/CSP or backend authentication evidence.

Both actual result documents are retained unchanged:

| Observation | Artifact SHA-256 |
| --- | --- |
| [First failed startup](Research_Browser_Batch79_First_Failed.json) | `f5a5dc53456e4edbdb69a48fe1f5db7f2b3f93a6d8ab2f7b1393a8f852d59972` |
| [Final complete browser run](Research_Browser_Batch79_Final.json) | `ae434bfe7734226a3c1f449e7de083432e3a08cdcb8a82f90084456b8fb6f994` |

Local complete screenshots/HTML are under
`/private/tmp/sclib-batch79-browser-dzi7si/second/`; the first failed directory
and isolated source copies are preserved for diagnosis. These are synthetic
test artifacts, not actual permitted scientific source evidence.

## Production-mode public browser isolation

Follow-up inspection found that the older public Playwright config built in the
development checkout, allowed local server reuse and used the live API as both
browser and server base. It now starts a separately owned production build,
including the actual Plotly `types/` declarations, on loopback port 3102. No env
file is copied, the child receives only explicitly allowed environment settings,
and the server API is unavailable loopback port 1. The real `/sclib` prefix,
production CSP, public OAuth href and ordinary downloaded Google fonts remain.
No application authentication or frontend UI behavior was changed.

Every public suite uses a browser transport fixture that answers only the exact
session-state GET with a synthetic anonymous 401 in memory. All other external
HTTP attempts are aborted and fail the case; WebSockets and service workers
cannot bypass this fixture. An actual negative-control test checks the 401 and
denial of both an unknown API GET and a POST to the session path. No real
login, email or API request is performed by these browser cases. Build-time
public font downloads are separate from browser-time request interception.

Two setup defects were observed and retained: the first build omitted the
Plotly declarations and failed before collection; the next run correctly
blocked the previously unaccounted-for session checks and failed all 13 cases.
The fixes copy the real declarations and explicitly simulate anonymous session
state; they do not waive type checks, forward API calls or remove UI assertions.
The final production-mode run passed **13/13, zero skipped/flaky, 68.452 s**,
with local retries disabled. The original 11 public cases remain, with two
new isolation/header cases. Port 3102 had no listener after owned cleanup.
The existing `next start`/standalone-output warning remains: this is a real
production-mode Next server test, not execution of a shipped standalone image.

| Observation | Artifact SHA-256 |
| --- | --- |
| [Initial build failure](Public_Browser_Batch79_Build_Failed.json) | `91d8bd1e9d32bdc051b55c237a266c5c16119f0c7a2bd5987aae16c98e5c6d74` |
| [Detected session egress](Public_Browser_Batch79_Egress_Failed.json) | `079ab95090dab74f7fc21f487a5c42a13aaf4537d38d75afd3f62a542db9960f` |
| [Complete public run](Public_Browser_Batch79_Final.json) | `02dba4df39f2fdc1a067905682b6b3208e256522e66ce180ec3fff8f3aea9d8e` |

Complete local artifacts are retained in
`/private/tmp/sclib-batch79-public-7e44YJ/` and both failed-attempt directories.
CI now retains the public JSON result alongside its HTML report; the normal
generated JSON path is ignored by Git. Final frontend source checks passed
**45/45, 1.942 s** after the last fixture edit; the focused seven browser-harness
checks also passed (**7/7, 0.382 s**). TypeScript passed with seven public/private
E2E config/fixture/suite files explicitly added to the compiler input because
the normal project config excludes E2E files. This is not Linux CI evidence.

## Fresh native schema rehearsal

The [new 0077 report](measurements/schema-rehearsal-0077-native-batch79-2026-09-13.json)
completed in **113,938 ms** using Python 3.12.14, PostgreSQL 16.13 and Darwin
arm64. It binds **732 API/script source inputs**, including the current
uncommitted kernel and test tooling. The report's strict reader and fresh
source comparison passed after completion. Older receipts remain unchanged.

- Artifact SHA-256: `492d223e6063ab404b160c414f27085fd39b5851bb96404d067d25fc29e1fc97`.
- Internal report hash: `b40d320769ec7ed9cffc971817a11291bcd05ae14816c52c6358687af7270cbf`.
- Input-inventory hash: `696c92a2a103e7fce0e598013230bba08eb613b5a6c7717efe9267932901af6b`.

The harness performs empty-database upgrades and historical round trips, then
checks the explicitly seeded 0050-era synthetic history through target
`0077_ml_pilot_attestations`. All 23 declared fixture outcomes were observed.
Retained comparisons matched for two seeded material rows, one source revision
and 20 frozen release/pin rows. Read-model rollback and history-preserving refusal
checks passed. The synthetic scientific-import ledger had two terminal outcomes
for two attempts, one quarantined and one pending, with no unfinished attempt.

Owned PostgreSQL/Redis processes and temporary database data were cleaned up
before report publication. Scientific acceptance, training, source distribution
and deployment approval remain false. Production backup restoration, real source
exclusions, human review and corpus-scale parity remain unmeasured, not zero.
This does not prove arbitrary production history preservation or Linux parity.

## Other completed regressions

- Separate owned capacity invocation: **1 passed, 66.41 s**. It fills the real
  32 MiB logical review-text cap, tests concurrent last-slot admission, atomic
  rejection, reclamation and original-key replay without payload resurrection.
  It was not mixed into the ordinary API database lifetime. Cleanup completed.
- Full ingestion unit suite: **1,275 passed, 19.95 s** in a minimal environment
  with an unavailable database URL and a parent-process audit hook rejecting
  DNS/socket connection attempts. This was unit/mocked pipeline execution, not
  production ingestion, a database run or a paid provider operation. Existing
  34 SQLAlchemy string-compilation deprecation warnings remain.
- The first ingestion collection failed because the minimal environment used
  an empty default tokenizer cache and the network guard refused a dependency
  download. The public tokenizer data was then prepared separately in an owned
  cache; its SHA-256 was verified as
  `223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7`.
  The successful rerun kept the same network guard. No application fix, fake
  tokenizer or live ingestion was substituted for this setup correction.
- Full frontend component regression: **1,887 passed across 53 files, 80.69 s**,
  two workers. Existing unrelated React `act(...)` warnings remain.
- Frontend source checks: **42 passed, 1.801 s**, including four new browser-CI
  checks. Nonincremental TypeScript and launcher syntax checking passed.
- Focused private-ingress/installed-probe/security workflow checks: **45 passed,
  43 subtests, 2.62 s**. Separate final schema-report/security checks: **107 passed,
  1.66 s**. These selections overlap; do not sum them as unique cases.
- A new complete offline script run after the workflow/public-browser edits
  passed **2,257 tests and 82 subtests in 204.75 s**. It used a minimal environment
  and the already prepared tokenizer cache, without an API/database invocation.
  This is separate from the still-running full API test process.
- Workflow YAML parsing and whitespace checks passed. The previous batch78
  production build and script run remain unchanged historical observations.
- All 134 local link targets in the checkpoint/operator/index/readiness docs
  resolved after the public-browser addition. Schema report validation still
  matched all 732 API/script source inputs. Scoped credential-pattern checks
  found no match in the new browser/migration artifacts and public harness;
  these are bounded checks, not a complete repository security audit.

## Ordinary API run — interrupted, not a complete passing result

One complete ordinary API invocation was started using the supported runner with
fresh native PostgreSQL/Redis, `--suite api -- -q --maxfail=1 --tb=short` and no
test-module filter. The capacity invocation and migration rehearsal used their
own separate services. API/script source inputs have remained unchanged during
this run; the runner's expiry and identity checks were not relaxed.

The former local handle **67943 is terminal with exit code 2**; do not poll or
restart it as though still live. After 42 minutes at approximately 43% progress,
the owned pytest child's exact parent/PID/user/command identity was verified and
one SIGINT was sent to that child only. This was a deliberate execution-strategy
change, not a timeout misread or an unexplained lost process. Pytest reported
**3,290 passed, one existing warning, 2,534.06 s, KeyboardInterrupt**. The parent
then confirmed removal of only its owned services and temporary test data;
the parent, pytest, PostgreSQL and Redis PIDs were absent afterward.

No complete API pass is claimed. The single native run had exceeded the CI
job's 30-minute budget, although native/Linux timing is not interchangeable.
Neither its one-hour capability nor database expiry was extended. The
[batch80 continuation](Priority_Eightieth_Batch_Implementation_2026-09-13.md)
executes all ordinary modules in separate owned-service batches, preserving
every assertion. Its new coordinator source changes the broad source inventory;
the 732-input batch79 migration receipt remains immutable historical evidence.

## Delivery and scientific status

No commit, push, PR creation, merge, deployment, production migration, permission
grant or feature activation was performed. The requested confirmation for
publishing the accumulated upgrade branch and creating a draft PR is still
pending. The earlier remote check found 38 open review issues; this checkpoint
does not close them or waive their individual criteria.

Complete the batch80 full API integration first. Then address any real failures
and complete exact-revision remote CI/PR delivery once authorized. Independent human
pilot work, permitted sources, scientific acceptance and actual empirical ML/RPS
evaluation remain separate requirements; passing synthetic integration tests
cannot replace them.
