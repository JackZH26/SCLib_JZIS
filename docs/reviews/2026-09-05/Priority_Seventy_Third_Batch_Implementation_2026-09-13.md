# Batch73 — English own-review declaration workbench

Date: 2026-09-13. Base commit: `dc716fba4ce14b26623cc70cdd3f5b0c49b0a2f7`.
Branch: `codex/sclib-research-v2`. The previous goal turn completed and committed
batch72; this turn implements its next UI dependency, not overall ML08 closure.

The live [ML08 #54](https://github.com/JackZH26/SCLib_JZIS/issues/54) was re-read
and remains open. Its actual fixed 60-event pilot, independent comparison,
permitted source/state evidence, missingness/effort report and justified
go/narrow/stop outcome cannot be replaced by synthetic UI tests. A manual/offline
pilot remains permitted; this work does not forbid starting actual research.

## Delivered interaction

`/dashboard/research/ml-pilot-reviews` is a private English dashboard page,
linked as **ML review declarations**. It implements:

- Exact own-participant reference input and historical head inspection, with
  authenticated account/wording refresh. No foreign-reviewer directory or
  registrar acting on someone else's behalf is provided.
- Four unchanged original byte streams, individually bounded to 8 MiB, with
  raw hashes and base64 transport. The browser reads existing logical-hash
  fields; it does not claim local scientific-kernel equivalence.
- Read-only scope checking: fixed candidate count, full log including revisions,
  own contribution count, conclusion authorship, declared recommendation and
  exact original/contribution hashes. The displayed basis must hash to the basis
  bound by the following declaration preview.
- Complete, versioned English wording checked against its fixed UTF-8 digest.
  An initially unselected acknowledgement is required before preview and a
  second initially unselected confirmation before explicit commit.
- Fresh account/predecessor checks. File, reference, action, reason and consent
  changes invalidate old previews. The server independently rechecks originals,
  participation and grants on write; a cached preflight is not an approval token.
- Protective withdrawal with the exact stored basis and action-specific consent,
  without new files or source-intake permission. Role-revocation behavior remains
  guarded and covered by backend tests.
- Original-account/key/hash uncertain-outcome recovery. Missing receipts do not
  prove rollback or unlock replacement writes. Manual recovery needs no invitation
  or source upload; recovered receipts remain historical after withdrawal.
- Session-change cancellation, epoch checks, cleared visible private state,
  original-account-only recovery references in memory, no browser persistence,
  no background polling and no automatic replay of writes.

The existing participation deadline helper and base64 encoder are exported for
reuse without behavioral change. Transport remains credentialed, no-store,
redirect-refusing and bounded, with strict response shapes/canonical hashes and
no private error-body disclosure. Source originals are read through the user's
approved workflow, not a truncated substitute rendered by this page. The
[operator guide](../../ML_PILOT_ATTESTATIONS.md) documents all human steps.

## Scientific and deployment boundaries

Own review contributions and conclusion endorsement are distinct. The three
native accounts cover a zero-review conclusion author, a one-record reviewer
and a sixty-record reviewer. These are synthetic roles/counts, not actual
reviewers or proof of independence. Sixty candidate events and sixty-one
revision-bearing log records are not sixty-one independent materials. The
all-failure `stop` case remains valid without fabricated negative labels.

Scientific acceptance, current collective signoff, source permission, context/
canary verification, external digital signature and execution authority remain
false. This is authenticated account declaration, not reviewed pilot release or
ML permission. All feature flags remain default-off.

There are **no application API, model, migration or pure-worker changes** in
this batch. The backend edit only expands the native capture test to retain
initial inspection, matching preflight and full withdrawal/history replies.
Schema stays 0077. Comparing batch72's 720 rehearsal inputs finds exactly that
one test-file difference. Its original migration and installed-worker receipts
remain unchanged at their original scope, not a fresh whole-source rehearsal.

## Actual verification

| Check | Result |
| --- | --- |
| Related owned PostgreSQL/Redis API integration | 104 passed, 152.27 s; owned services cleaned up |
| New protocol, transport and interaction checks | 95 passed, 4.40 s |
| Full frontend default-English/source checks | 38 passed, 1.64 s |
| Full frontend component regression | 1,787 passed in 51 files, 42.35 s |
| Nonincremental TypeScript | Passed after UI/browser sources were added |
| New desktop/mobile browser workflows | 6 passed, 27.1 s; no retries |
| Changed Python test Ruff/format | Passed |

The 95 new tests are included in the full suite, not additional independent
coverage. They exercise all three original account flows; altered versions,
authority, consent, input, scope, predecessor and hashes; malformed originals,
response/chunk limits, UTF-8, stalled fetch/read/file preparation, cancellation,
no retries; edited previews, changed accounts during pending work, unknown
commits, 404/manual recovery, StrictMode and unavailable feature handling.

The existing FastAPI `regex` deprecation warning remains. An ESLint invocation
was attempted, but `eslint` is not installed; no lint-pass claim or dependency
installation is substituted. TypeScript, source, component and browser checks
passed. Native Darwin tests are not Linux CI/image parity or deployment proof.

Browser QA uses copied source, existing dependencies, offline fonts and explicit
synthetic adapters, blocking nonlocal requests. Desktop and 390-pixel mobile
checks verify confirmations, original payloads, key-preserving recovery,
no-source withdrawal, session invalidation, keyboard focus and no horizontal
overflow. No page errors or unexpected/external requests were observed. Desktop
recovered scope and mobile preview screenshots were visually inspected; long
hashes wrap and the preview/commit distinction is readable. Owned port 32066 is
absent afterwards. Local screenshots remain in
`sclib-ml-review-browser-artifacts-fpD7Ob` under the OS temporary directory.

## Fresh native interface evidence

Six new archives were copied byte-for-byte from the successful owned API run.
Committed batch72/older archives and digest assertions remain unchanged. Current
frontend consumers use batch73, not resealed historical fixtures.

| Fixture in `frontend/tests/fixtures` | Bytes | Source pins | Raw SHA-256 |
| --- | ---: | ---: | --- |
| `ml-pilot-attestations-native.batch73.wire.json` | 425,827 | 586 | `9efd63d963bd8a4c0a2ecb8c2294ea4cd615833a35a9f8d49acd49e560c90bb0` |
| `ml-pilot-participant-native.batch73.wire.json` | 154,622 | 586 | `e246bca6fc8654c852885137e96980706ae84b46ffc19eb4020e84d9dc8b12dd` |
| `ml-pilot-review-native.batch73.wire.json` | 82,711 | 586 | `bc1d60ecd7a7e30b93a91a3cfab34ab322284bf838671e410127e4f862644f02` |
| `ml-use-runs-native.batch73.wire.json` | 197,297 | 586 | `f0aff113f905cf23b81a2b42b436352391f0e71e7d3b449aec9e053f6e287f4f` |
| `ml-use-rights-native.batch73.wire.json` | 224,554 | 586 | `f8e7ac8010645f46c926a7e3459954566e419e4dc8fa9446ffca9c7694345a96` |
| `discovery-main-barrier-native.batch73.wire.json` | 199,291 | 290 | `dc88cea1acb6ffaaac0df1504aae279f1ea9b61936940c6bffe596e5867afe4c` |

All 3,220 overlapping pins match current bytes. The declaration archive contains
36 original responses (12 per account), including matching preflight/inspection
and withdrawal history, plus three explicitly synthetic original uploads.
Browser adapters alter test operation metadata for randomly generated keys;
they are not new SQL evidence or actual scientific declarations.

## Remaining work

1. Reconcile the latest exact document basis across required reviewers and the
   conclusion author with current account/participation validity. Complete
   account assertions alone must not imply human independence or scientific
   acceptance.
2. Bind actual permitted context bytes and canary reconstruction/replay to the
   authenticated boundary, with an approved retention policy.
3. Complete the actual stratified 60-event pilot, independent comparisons,
   unresolved arbitration, missingness/time accounting and field-specific
   go/narrow/stop recommendations. UI fixtures do not meet this requirement.
4. Supply authorized PRs, exact-revision Linux CI, reviewed migration/release
   evidence and empirical downstream ML/RPS evaluation before closing issues
   or enabling production capabilities.

No remote push, PR, issue closure, shared migration, real reviewer grant,
deployment, paid provider call or model execution is performed by this batch.

Final local checks: all 3,220 interface source pins match; 125 local Markdown
links resolve; `git diff --check` passes. A limited common-credential-pattern
scan of the 31 changed/new files found no matching key/token patterns, not a
comprehensive security audit. At the end of the implementation continuation,
changes remained in the local worktree; no additional commit had been created.

## Network-resumption commit preflight — 2026-09-13

The user requested that the saved changes be committed locally before further
development. Resumption confirmed the same 31-file batch on base `dc716fb`,
without partial batch74 application changes or lost source files.

Fresh verification retained the following distinction between attempts:

- Running the default frontend suite alongside TypeScript and browser startup
  produced 21 component failures, four worker-start errors and a 90-second
  browser-server startup timeout. Most failures reported timeouts or delayed UI
  readiness. This attempt failed and is not counted as passing evidence.
- With no application or test assertions changed, running
  `pnpm exec vitest run --maxWorkers=2 --reporter=dot` passed all 1,787 tests in
  51 files (47.46 seconds). The 38 source checks had already passed (2.20 seconds).
  This supports resource contention as an explanation for the initial attempt,
  but does not establish that unrestricted parallel runs are reliable.
- Nonincremental TypeScript and the changed Python test's Ruff check/format
  passed. Existing React `act` warnings remain in unrelated component tests.
- Running the browser suite separately passed all six desktop/mobile workflows
  in 20.2 seconds with unchanged assertions and timeouts. Its new local artifacts
  are under `sclib-ml-review-browser-artifacts-Oe00oP` in the OS temporary directory.
- All six retained native archives still have the exact hashes above, and all
  3,220 source pins match current files. The limited common-credential-pattern
  scan of the 31 files found no matches.

The earlier 104-test owned API result remains historical evidence; it was not
rerun or replaced during this commit-only preflight. No production API, schema,
feature flag or scientific-acceptance boundary changed. This checkpoint is a
local commit only, not a remote push, deployment or issue closure.
