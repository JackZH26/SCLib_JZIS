# Engineering delivery readiness — 2026-09-12

**Current status:** [September 15 delivery](Delivery_2026-09-15.md). Historical run handles and counts below keep their original scope.

Base revision: `00718749b6eb15926ae8cbfc58e02a9432488815`, with the
batch52 main-barrier worktree changes. This refresh separates local executable
acceptance from remote delivery. It does not close an issue or authorize a
production rollout.

Evidence scope: the source inventory below is the **batch52** snapshot. Batch53
adds an offline ML preparation command and tests, with no API, database-schema
or frontend implementation changes. Its additions change the repository-wide
source inventory; the retained 0070 receipt must not be presented as a fresh
whole-tree rehearsal of batch53. The original receipt is retained unchanged.
Batch54 subsequently adds the independent ML membership ledger and 0071 schema;
the 0070 claims below remain historical batch52 evidence. Current batch54
verification and its separate source-pinned receipt are recorded in the
[batch54 report](Priority_Fifty_Fourth_Batch_Implementation_2026-09-12.md).
Batch55 adds intake/preflight API and offline CLI sources without changing
schema 0071. It does not rerun or relabel batch54's whole-source migration receipt;
its own targeted API/source/frontend results are in the
[batch55 report](Priority_Fifty_Fifth_Batch_Implementation_2026-09-12.md).
Batch56 adds the private input-reconstruction worker/endpoint and shared receipt
content helper, still without a schema change. Its new source state and checks
are recorded separately in the [batch56 report](Priority_Fifty_Sixth_Batch_Implementation_2026-09-12.md);
the retained 0070/0071 migration receipts remain historical.
Batch57 adds complete ML companion currentness and audit-dependency inspection
without a schema change. Its separate verification is recorded in the
[batch57 report](Priority_Fifty_Seventh_Batch_Implementation_2026-09-12.md).
Batch58 adds schema 0072 for private ML requests and input retention. Its
source-specific migration and compatibility status is tracked separately in the
[batch58 report](Priority_Fifty_Eighth_Batch_Implementation_2026-09-13.md); earlier
0070/0071 receipts do not attest this new schema or later source files.
Batch59 adds schema 0073 for independent purpose-specific ML rights decisions.
Its verification is tracked in the
[batch59 report](Priority_Fifty_Ninth_Batch_Implementation_2026-09-13.md);
the 0072 receipt is retained as historical evidence, not relabeled as 0073.
Batch60 adds the private ML rights workbench and a native HTTP compatibility
test, without changing production API code or schema. Its own verification is
in the [batch60 report](Priority_Sixtieth_Batch_Implementation_2026-09-13.md);
the 0073 whole-source rehearsal remains the historical batch59 checkpoint.
Batch61 extends schema 0074 with exact run contracts and independent conditional
review. Its current verification and remaining execution gates are tracked in
the [batch61 report](Priority_Sixty_First_Batch_Implementation_2026-09-13.md);
no earlier receipt is relabeled as attesting the new source.
Batch62 completes targeted owner/independent-approver browser verification and
hardens seven inconsistent-response cases without production API/schema changes.
Its own tests and remaining gates are in the
[batch62 report](Priority_Sixty_Second_Batch_Implementation_2026-09-13.md);
the 0074 migration receipt remains historical batch61 evidence.
Batch63 adds a private offline ML08 canary constructor/replayer and its tests,
without production API/schema or frontend changes. Its new repository-wide
source inventory and documentary/byte-integrity evidence are tracked in the
[batch63 report](Priority_Sixty_Third_Batch_Implementation_2026-09-13.md);
neither old fixtures nor canary hashes establish real independent pilot approval.
Batch64 adds the private canary-derived human-review report and its offline/
browser tests, without changing application or database schema sources. Its
own source and verification scope is in the
[batch64 report](Priority_Sixty_Fourth_Batch_Implementation_2026-09-13.md);
rendered private declarations are not authenticated scientific acceptance.
Batch65 extends the private run API/client and advances schema to 0075. Its
new native migration receipt, raw HTTP captures, historical compatibility and
private evidence boundaries are tracked in the
[batch65 report](Priority_Sixty_Fifth_Batch_Implementation_2026-09-13.md).
Earlier 0074/API receipts retain their historical source scope, not current-head
acceptance. No remote delivery or execution authority is inferred.
Batch66 verifies actual 32 MiB capacity/concurrent admission and sole-purge audit
retention, and fixes the cold tokenizer-cache installation dependency in CI and
both Python image builds. Its final native 0075 receipt and separate current
regression results are in the
[batch66 report](Priority_Sixty_Sixth_Batch_Implementation_2026-09-13.md).
The non-root offline Dockerfile check is implemented but actual Linux builds,
image/test parity and remote delivery are not inferred from native/source tests.
Batch67 packages the shared ML08 accounting kernel/schema and private bounded
byte intake, with actual isolated wheel installation proof and canary 1.1.0
compatibility. Its new selected source inventories and verification are in the
[batch67 report](Priority_Sixty_Seventh_Batch_Implementation_2026-09-13.md).
Earlier receipts remain historical. Installation and documentary consistency
do not authenticate pilot registration, human review or scientific acceptance.
The subsequent batch68 checkpoint adds schema 0076 and private pilot
registration/participant APIs. Its [local checkpoint](Pilot_Registration_Checkpoint_2026-09-13.md)
records targeted verification and remaining gates. Neither batch67's native
captures nor its 0075 rehearsal attests this changed source state. This combined
checkpoint had not yet completed the 0076 migration rehearsal and was not
deployable. The subsequent actual 0076 native rehearsal passed, including empty
roundtrip, incomplete-roster refusal, account participation and retained-history
rollback protection. Its new source-pinned receipt and refreshed interface
captures are tracked in the
[batch68 report](Priority_Sixty_Eighth_Batch_Implementation_2026-09-13.md), not
inferred from the preceding commit-time checkpoint or older receipts. This
resolves that local migration-verification gap, not the remaining worker,
participant UI, real pilot, Linux CI or production delivery gates.
Batch69 adds database-clock chronology, explicit verifier-policy compatibility,
actual worker/installed-wheel checks and deterministic PostgreSQL collisions.
Its changed sources and independent terminal evidence are recorded in the
[batch69 report](Priority_Sixty_Ninth_Batch_Implementation_2026-09-13.md); the
batch68 receipt is retained unchanged and does not attest those later inputs.
Batch70 completes the English participant-only workbench and adds a private
read-only account-admission endpoint so revoked reviewer roles do not prevent
protective participation decisions. Its fresh native/interface and browser
evidence is recorded in the
[batch70 report](Priority_Seventieth_Batch_Implementation_2026-09-13.md).
No migration or worker source changes are introduced in that batch. The batch69
schema/installed-worker artifacts retain their original scope and bytes; they
must not be relabeled as batch70 whole-source or Linux-delivery evidence.

## Findings and next delivery decisions

Batch71 adds the separately default-off, read-only four-document review
preflight, with registered-account and participation-interval checks. Its
[own verification](Priority_Seventy_First_Batch_Implementation_2026-09-13.md)
does not introduce a schema migration, scientific signature or execution
authority. Batch70 whole-source captures remain unchanged historical evidence;
five newly captured batch71 archives bind the changed backend and harness sources.

Batch72 advances schema to 0077 with default-off own-account review declarations,
fixed English consent and exact original-document/participation binding. Its
[source-specific verification](Priority_Seventy_Second_Batch_Implementation_2026-09-13.md)
includes a new 1.2 schema receipt, native HTTP captures and isolated installed
worker checks. Earlier 0076 receipts retain their historical source scope. This
is not collective scientific acceptance; the declaration UI, current collective
review, actual permitted 60-event pilot and Linux CI/remote delivery remain
unfinished. The table below is the historical batch52 delivery snapshot, not a
claim that its 0070 receipt covers current 0077 sources.

Batch73 implements that English own-review declaration UI, including complete
original-file scope checking, two-step consent, withdrawal and unknown outcome
recovery. Its [native/UI verification](Priority_Seventy_Third_Batch_Implementation_2026-09-13.md)
does not change application API, schema or worker code. The expanded native
capture test changes whole-source provenance; batch72 receipts remain unchanged
at their original scope. Collective currentness, actual source/canary admission,
real pilot and remote delivery remain unfinished.

Batch74 adds [joint account-declaration coverage](Priority_Seventy_Fourth_Batch_Implementation_2026-09-13.md)
against newly verified original files in a single read-only database snapshot.
Required contributors and the conclusion author are counted separately from
unused backup roles; withdrawn and stale declarations cannot count as matching.
The English workbench displays these privacy-safe aggregates as historical
snapshots, never collective scientific signoff. Actual source/canary evidence,
independent human pilot, downstream empirical evaluations and remote delivery
remain unfinished; schema stays 0077.

Batch75 adds [default-off authenticated byte replay](Priority_Seventy_Fifth_Batch_Implementation_2026-09-13.md)
through a shared portable canary v1.2 kernel and bounded ephemeral context
streaming. A fresh joint account snapshot follows reconstruction; the English
workbench displays both scopes without scientific approval. Source-only proxy
configuration and clean installed-wheel replay are not deployed ingress or Linux
image parity. All real-source rights, independent-human pilot, scientific
acceptance and remote delivery gates remain open; schema stays 0077. Earlier
canaries, reports and source-pinned receipts remain immutable historical evidence.

Batch76 adds the [private field-quality view](Priority_Seventy_Sixth_Batch_Implementation_2026-09-13.md)
over that same verified canary and conclusion. It distinguishes all eleven
fields/seven states, event/result denominators, recorded effort and original
human proposals; private text and frozen groups are not public summaries or
scientific acceptance. No API/compiler/schema or native source inventory changes
are introduced. The full offline report, genuine pilot, deployed ingress/privacy
verification and Linux delivery evidence remain separate requirements.

Batch77 adds [scoped private ingress and actual native transport verification](Priority_Seventy_Seventh_Batch_Implementation_2026-09-13.md):
eleven exact body ceilings, shared private location policy, chunked/full-boundary
transmission, temporary-file descriptor observation with a positive detection
control, private response checks and owned-process cleanup. The final report
pins its three current Nginx sources. Bootstrap/CI and migration-only deployment
instructions are aligned, but neither Linux CI nor production configuration was
executed. Earlier API/schema receipts remain historical; real pilot, source
permission, scientific acceptance and remote delivery gates are still open.

Batch78 closes the missing [installed-evidence CI coverage](Priority_Seventy_Eighth_Batch_Implementation_2026-09-13.md):
an explicit clean-wheel driver checks exact installation identity, actual
streaming replay for zero/revised/full-8-MiB contexts and corrupted-byte rejection.
A new native wheel execution and production-mode frontend build passed. This
adds no application/schema change and does not attest Linux images or deployed
privacy. The remote implementation PR/exact-revision CI handoff and independent
scientific gates remain open; earlier receipts are not relabeled.

The [batch79 integration checkpoint](Priority_Seventy_Ninth_Batch_Implementation_2026-09-13.md)
adds actual 42-case unified research-browser verification and CI collection,
required migration CI evidence, a fresh 0077 native receipt binding 732 source
inputs, independent capacity verification and full ingestion/frontend results.
It also isolates the public production-mode server/browser transport; all 13
public cases passed with the real prefix/CSP and synthetic anonymous session
state, without live API calls. Source checks reached 45 passing cases.
Its monolithic API run ended deliberately after 3,290 passes and owned cleanup,
not a complete passing suite. The new receipt is
synthetic native evidence; the older table below retains its batch52 scope.
Remote CI/PR delivery and independent scientific acceptance remain unfinished.

The [batch80 continuation](Priority_Eightieth_Batch_Implementation_2026-09-13.md)
assigns all 223 ordinary API test modules to eight independent owned-service
lifetimes, retaining complete module assertions and checked JUnit outcomes.
The fresh 734-input migration report and complete offline-script regression
passed at that source snapshot. The API run subsequently ended after batch 4
with 3,917 actual passes, one failure and three skips; batches 5–8 did not run.
Earlier receipts retain their original source scope; no single passing batch
establishes complete API coverage, Linux runtime fit or remote delivery.

The [batch81 real-byte verification](Reference_Canary_Verification_Batch81_2026-09-13.md)
separately executed all three opt-in QE reference cases using existing pinned
local files. Import/replay checks passed with one pending observation and two
explicit quarantines. This is not scientific acceptance, source redistribution
permission, a completed ordinary API run or Linux delivery evidence.

The [batch82 correction](Priority_Eighty_Second_Batch_Implementation_2026-09-13.md)
reproduces the recovery-test failure with an unrelated same-version run and
corrects the query to exact capsule run IDs, without changing business states or
snapshot limits. Its 14-case focused check, 2,288 offline tests, 45 frontend
source checks and fresh 734-input migration rehearsal passed. Coordinator 1.1
preserves failed-batch JUnit counts and CI uses explicit larger time bounds.
Seven renewed native interface captures, 1,887 current component tests and 42
private browser cases subsequently passed. The original 28-module replay then
passed all 969 cases with owned cleanup. A fresh complete 223-module/eight-batch
run is active; full corrected API acceptance remains pending. Earlier receipts
retain their original source pins.

| Issue | Local implementation | Remaining delivery work |
| --- | --- | --- |
| EN01 #42 | Pre-client disposable capability guard; owned PostgreSQL/Redis; least-privilege runtime; rechecked cleanup identity; fresh safety/API results passed | Link the authorized implementation PR and its CI evidence |
| DR03 #56 | Shared strict feed validation, atomic matched last-good cache, version-bound pagination/details and frontend invalidation; current API/UI regressions passed | Supply the PR and compatibility notes |
| EN03 #59 | Session-locked durable cycles, independent-process crash/replay checks, transactional Stats/Timeline preservation; current real two-process/SIGKILL regressions passed | Deliver the implementation with writer compatibility notes and CI evidence |
| EN02 #58 | Separate migration authority, read-only exact-head admission; new0070 native rehearsal passed and637 current source pins verified | Deliver the source-pinned report with the PR; prior0068 evidence remains historical |
| EN04 #52 | Locked environments, measured inventories and final published-image digest parity gate | Actual exact-revision Linux Test jobs and release-digest execution evidence; mocked local tests do not meet this gate |

The missing schema-report framework and final-image gate noted in earlier
audits were already implemented in batch33. They should not be rebuilt. The
opening pending language of the earlier DR03/EN03 audit was superseded by its
section5 source/type-check results. Subsequent code changes require this fresh
targeted verification, not retroactively treating the old results as current.

The latest retained pre-batch52 schema receipt was the0068 RG03 receipt. Its
full-file hash matched its archive index, but its source inventory differs from
the current branch. The new0070 rehearsal must bind its own source bytes,
retention checks and cleanup outcome. Local native execution is not Linux
release-image parity.

## Full EN01 acceptance mapping

The earlier engineering audit inspected #42 only as a dependency. The current
live issue has six acceptance criteria; all six have concrete implementation
and test paths:

| Criterion | Implementation and verification |
| --- | --- |
| Unapproved PostgreSQL target aborts before connection | `scripts/test_safety.py:validate_test_environment`; `scripts/tests/test_test_safety.py` patches sockets/client imports and rejects changed PostgreSQL targets before runtime inspection |
| Unapproved Redis target aborts before connection/cleanup | Same guard and instrumented changed-Redis tests; actual Redis ACL/DB identity checked in `api/tests/test_disposable_environment.py` |
| Missing/invalid sentinel fails despite a test-like database name | Private capability directory/file, run ID, expiry, process identity and exact DSN checks; missing, symlinked, public, expired and mismatched capability regressions |
| Approved ephemeral schema/Redis path and owned cleanup | `scripts/run_disposable_tests.py` creates its own services; `api/tests/conftest.py` revalidates before DDL/cleanup; PostgreSQL marker/role and Redis one-DB ACL integration cases |
| Shared CI/local guard and no secret-bearing failure output | `.github/workflows/test.yml`, `docs/TESTING_SAFELY.md`, minimal child environment, sanitized failures and no-network traceback/client-import tests |
| Never use reviewed source data for destructive tests | No attach/reuse/DSN argument; new private cluster/container and synthetic fixtures only; all database executions in this batch use the capability-owned runner |

This is a software acceptance map, not a claim that a malicious local user who
can edit the guard is sandboxed. Nor does it replace the actual Linux CI
execution required by EN04. The native runner is an explicit supported local
fallback, not an unapproved shared-database alternative.

## Compatibility boundaries to retain in a PR

- DR03: deploy the matching feed/metadata/validation/cache contracts; an outage
  is not permission to fabricate a validated empty feed. Keep scientifically
  unsupported legacy leads separate from reviewed scientific projections.
- EN03: one effective committed SQL cycle is not exactly-once callback
  invocation or external vector/provider delivery. All participating writers
  must preserve the physical PostgreSQL session and share cadence/policy;
  nonparticipating old writers require a separately approved rollout plan.
- EN02: application startup checks rather than migrates the schema. A0070
  rollback with retained v2 declarations must refuse; restore/migration and
  source-governance preservation are deployment decisions, not history deletion.
- EN04: final-image parity checks run before signing/explicit attestation and
  deployment summary, but initial image push/BuildKit provenance may already
  have occurred. Do not claim that the gate prevents every registry write.

No real scientific review, real pilot, production deployment or production
capacity metric is newly required to close these bounded engineering issues.
Those are separately tracked scientific/operational gates.

## Remote status and evidence location

Fresh read-only checks on2026-09-12 found no PR for
`codex/sclib-research-v2` and no matching remote branch. #42 and #77 were still
open. No push, PR creation, issue mutation or deployment was performed.

Current batch execution results, exact migration receipt and limitations are
recorded in [the batch52 implementation report](Priority_Fifty_Second_Batch_Implementation_2026-09-12.md).
Do not substitute this readiness map for that terminal test evidence.

The completed refresh passed538 combined guarded API tests,1,671 script tests
(36 subtests),1,353 frontend tests,38 source checks, TypeScript and the final
isolated production build. The final52 main-barrier checks are an overlapping
separate module rerun, not52 additional unique combined-run checks. No native
test services remain running. These local results do not manufacture EN04's
missing Linux/final-image evidence or close issues without delivery.

## Additional delivery gate — actual secret scan, 2026-09-13

The [batch82 local scan and triage](Secret_Scan_Triage_Batch82_2026-09-13.md)
reports 63 findings over the 61 local branch commits and 38 findings in eight
of 128 modified/untracked files. They were inspected as synthetic request IDs,
same-commit source hashes and ordinary prose, but the scanner still exits
nonzero. Exact immutable fingerprint exceptions and their security contract
tests remain pending until the active API/script source freeze ends. Newly
uncommitted fixture fingerprints require the eventual authorized commit.
Neither this classification nor the earlier functional test results establish
a clean remote Security run. No broad ignore or history rewrite was applied.

### Batch83 terminal-state and policy update

The [batch83 follow-up](Priority_Eighty_Third_Batch_Implementation_2026-09-13.md)
records the batch82 run's actual incomplete termination: four complete batches
passed 3,919 cases with three skips, then the fifth lifetime was refused before
test collection. Original artifacts are preserved; zero failed cases in the
four complete XML files is not a complete passing run. Minimal startup probes
did not reproduce the refusal. Value-free safety reason codes were refined
without changing the accepted identity/time interval or granting an expiry grace.

The 36 reviewed historical scan fingerprints and matching tests are now
implemented, and an actual scan of the same 61 commits passed under repository
policy. Uncommitted fixture fingerprints still require an authorized real commit.
Full offline verification passed 2,290 tests and 91 subtests; the exact
fifth-batch replay passed all 1,032 tests with cleanup and unchanged sources.
A new independent full 223-module regression is live as of 2026-09-14 UTC;
complete API, source-matched evidence refresh and remote Test/Security
acceptance remain pending. No root cause is inferred from a successful retry.
