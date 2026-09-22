# Remote release execution — 2026-09-21

PR [#80](https://github.com/JackZH26/SCLib_JZIS/pull/80) is submitted. The user
has authorized technical delivery, PR submission, production deployment and
acceptance, excluding human scientific review. GitHub CLI workflow permission
and account verification are complete. The September 21 native baseline remains
historical evidence; its 7,460 passing API tests are not a claim that the latest
Linux/image release has passed.

## Remote findings and remediation

The first Linux Test run, 35592860042, passed ingestion, frontend build, public
and private browser checks, monitoring configuration and empty-database
migration. Its API job failed before database tests: offline scripts were
collected from the API working directory, so three imports could not resolve.
Commit c919e7a runs that gate from the repository root. The next Linux run,
35593356011, reached all offline tests (2,303 passed, two failed): checkout lacked
the historical chunker commit needed for byte-level provenance, and an existing
workflow assertion still expected the old working directory. The API checkout
now fetches history and that assertion matches the corrected command. No
provenance comparison or service-ownership guard was removed.

CodeQL identified two taint paths to one real administration logging sink.
Application logs now contain only the reviewer UUID and a material-ID digest.
The original review note remains in the structured database audit record. An
actual authenticated SQL/HTTP regression verifies that CR/LF and Unicode line
separators in a note cannot forge log entries and are retained verbatim in the
audit row. OAuth redirect testing now compares the parsed HTTPS origin exactly.
The focused API run passed 59 tests. Separately, eleven findings were reviewed
as negative test inputs, ephemeral owned-test credentials, high-entropy token
hashes, validated enums or an intended explicit file upload. The exact alert
numbers, reasons and GitHub dispositions are retained in
[codeql-triage.json](delivery-2026-09-21/remote-release/codeql-triage.json).
No scanner, rule or source directory was disabled.

Seven fresh native SQL/HTTP captures are archived as `delivery20260921r4`, from
10 passing tests. Every recorded source digest matched its actual source bytes.
Earlier archives remain unchanged. The complete offline suite passed 2,305
cases plus 91 subtests. Frontend source checks passed 46 tests and TypeScript
passed. The first component run passed 1,889 tests but one unchanged layout test
exceeded its five-second timeout while other local checks were concurrent. A
complete rerun with two workers passed all 1,890 tests; no timeout was increased.
Both results are retained. The three new exact scanner fingerprints correspond
only to values independently verified as synthetic fixture request keys; the
two-commit incremental secret scan then passed with zero findings, as did all
14 scanner-policy checks. Retained results live in
[remote-release](delivery-2026-09-21/remote-release/).

## Production backup and rehearsal

The live checkout remains d26fc098565492b78b416fb30b6b1ec7087b24c7 at schema
0043_chunks_fts. Before any application replacement, host-local configuration
and changes were preserved privately under
`/var/lib/sclib/maintenance/upgrade-20260921-ae19bcd`; no secrets were added to
Git. The production ingestion pause was preserved.

A fresh 574,029,697-byte database backup was uploaded with a verified manifest;
retention pruning was disabled for this operation. SHA-256:
`05e0b47d5d3eeaa1c444095a38eec2fa2897554ed3847a9272656cc33940f399`.
Downloading and restoring that actual backup into an unexposed PostgreSQL
container succeeded in 523 seconds: 75,202 papers, 18,931 materials, 20 public
tables, zero invalid indexes and zero unvalidated constraints. The owned
restore container was removed. See the
[actual restore receipt](delivery-2026-09-21/remote-release/production-backup-restore.json).
This first receipt proves backup recovery at 0043. The subsequent full-data
0043-to-0078 rehearsal and distinct-role admission passed as recorded below.
Neither operation is a production application cutover.

## Still required before production completion

- Successful Linux Test/Security on the final PR and main revision, followed by
  exact release-image parity, vulnerability checks, SBOMs and signatures.
- Switch the application to the verified runtime credential at the eventual
  cutover; the full-data upgrade rehearsal and production role provisioning
  have passed. Reconcile preserved host-local changes before deployment.
- Actual SLO and monitoring admission. Current public API availability passes;
  AI routes have insufficient observations (0 of 20 minimum requests), and the
  ingestion pause leaves pipeline age above 24 hours. Neither data nor metrics
  may be fabricated to pass. The prior explicit pause requires clarification
  before resuming collection. The default private alert console also needs an
  approved external notification destination and a real delivery check.
- Merge, signed-image rollout, public version/functional acceptance, and a
  retained deployment/rollback record. These have not happened yet.

Human source-rights review, ML08 independent pilot review, RG04 gold evidence,
ML09 real-dataset admission/fitting, empirical calibration and reviewed public
Discovery rows remain explicitly open. Technical receipts confer none of
those scientific approvals.


## Subsequent production and Docker findings

The real backup clone upgraded from 0043 to 0078 in 6.5 seconds using a
non-superuser migration role. Fingerprints of all retained columns remained
identical across 18 original tables and two original views (20 relations;
the receipt field is named `unchanged_original_tables`). Alembic version and
the intentionally invalidated timeline projection-state table were excluded
from that byte comparison. Index/constraint checks passed. A distinct runtime
role had no public-schema CREATE permission and passed the actual image's
read-only schema admission. This used the locally built Linux rehearsal image
for 9f529dd, not a signed production release; it did not alter live data.

A live Similar preflight found a pre-existing 500: the host identity agent was
rotating valid tokens, while the July-started API container retained an old
bind-mounted directory inode and could not find its subject token. Restarting
that existing API container restored its mount, health and unchanged d26fc09
version. Scoped credential exchange succeeded, and the original public Similar
request then returned 200 with three non-self results in 20.595 seconds. A
systemd runtime-preservation drop-in was applied; restarting the identity agent
preserved all three directory inodes and continued container token visibility.
The repository unit now also declares RuntimeDirectoryPreserve=yes. Five-minute
token expiry and access restrictions are unchanged.

The third Linux run passed CodeQL findings and all Security jobs, as well as
frontend/source/browser and ingestion checks, but its migration job encountered
a disposable-service startup failure. A controlled, owned Docker experiment
with a two-second initialization delay proved that the old Unix-socket probe
can return while the temporary initialization server is still running. The
runner now checks the final TCP server before database bootstrap. Static setup
phase names aid diagnosis without exposing commands, DSNs or SQL. The regression
failed before the fix and passed afterwards; all 2,306 offline cases plus 91
subtests pass. Ten native cases regenerated seven r5 compatibility archives;
all 1,890 frontend component tests pass with those archives. No historical
fixture was overwritten. Final Linux validation is still required.

Production alert configuration has been prepared and validated with the running
Alertmanager image, with networking disabled during configuration validation.
The existing Resend SMTP identity authenticated successfully without sending a
message. Activating the proposed info@jzis.org destination and sending its
verification alert await explicit recipient authorization. The production
Compose override now loads the private host config and separate SMTP secret;
the deploy preflight requires those files before any production migration.

Runtime HTTP checks on the upgraded full-data clone found two open cutover
blockers: the material-list scan is too slow and Similar returns 503. In particular, 0062 does not import or activate the legacy million-chunk ANN index:
`INDEX_GENERATIONS.md` specifies lexical-only Search/Ask and a 503 for Similar
until a reviewed immutable generation exists. Its 1,000-member pilot limit is
not a full-corpus replacement. Migration success alone therefore does not
justify an unattended public retrieval cutover or a full-upgrade claim.


## Full-data HTTP findings and follow-up delivery

The four infrastructure/readiness/statistics probes returned 200 on the actual
upgraded backup clone. The material-list route exceeded the initial 25-second
client deadline; a later diagnostic probe with a 120-second client allowance
returned 200 in 80.023 seconds. This allowance is confined to the benchmark,
not application or production timeout settings. The first optimization builds
complete scientific response envelopes only for the returned page; all
candidates still use the same live visibility, scientific-filter and atomic
property-selection policies. It never sorts by the old aggregate or trusts a
stored evidence envelope. Ninety-nine targeted API tests pass, including
source holds, all sort fields, ties, offsets and the new regression proving
that complete DTO construction is bounded to the returned rows. An initial
full-data candidate probe returned 200 in 33.498 seconds, which remains too
slow for production acceptance. A second candidate probe took 33.468 seconds, 58.2% less than the 80.023-second
baseline; the complete canonical material response digest matched exactly
(total 10,507 eligible materials, three returned). These are two isolated
full-data probes, not a production load test. Similar still requires the reviewed, appropriately
scoped immutable-index migration; no legacy fallback or pilot-as-full-corpus
workaround was introduced.

The fourth Linux run, 35596346121, passed ingestion, both frontend jobs,
migration and operations; its Security counterpart, 35596346027, passed every
job including both CodeQL languages and full secret history. The API batch
failed with 980 passes and one setup error because an oversized request body
was used as a pytest parameter ID. Linux could not spawn Docker with the
resulting over-128-KiB PYTEST_CURRENT_TEST environment entry. A separate
network-disabled Linux process reproduced errno 7; a short ID succeeded.
The request bodies and all ownership guards are unchanged. Thirty focused
adjudication API cases pass. A whole-suite collection audit also identified
the other two long-body parameter groups, which now have explicit short IDs.
Final Linux testing must run against the newly published revision; older
passes do not establish its acceptance.

Production SCLib-only database ownership and distinct migration/runtime roles
were first applied in a transaction and rolled back. The inventory matched its
original state, after which the same operation committed. The runtime role has
CRUD access to application tables, no public-schema CREATE, no version-table
write and no membership in the bootstrap superuser. The migration role owns
only the SCLib database/schema/application objects and has no superuser,
CREATEDB, CREATEROLE, replication or BYPASSRLS attributes. Extension ownership
and every other database owner are unchanged. Both credentials authenticated
through the real API image under UID 1001 with read-only SQL. The migration
secret is root:1001 mode 0640 outside Git; the runtime credential is staged
privately for cutover. Application .env has not switched, schema remains 0043,
row counts are unchanged, and live health/version checks pass. This completes
credential provisioning, not migration or runtime privilege activation.

No alert email has been sent and the explicit ingestion pause remains in force.
The pending recipient and pause-resumption questions are still unanswered.
Human scientific review remains outside this technical delivery authorization.

The other two bounded-request modules pass all 87 tests. All 7,465 API cases
collect successfully, with the largest remaining ID 16,461 UTF-8 bytes. Seven
new r7 native archives come from 10 passing real SQL/HTTP cases and match every
current source pin. The intermediate r6 archives are retained without edits.

With r7 imports, all 1,890 frontend component tests and TypeScript pass.


## Catalogue cache and Linux cancellation follow-up

The complete Linux Test run 35598045347 on 1af6d62 failed in the API job:
`test_catalog_capacity_503_cancels_siblings_before_traversing_later_releases`
waited for two admitted catalogue jobs while six page readers occupied the
default worker pool. A two-core Python runner has six default workers. Its
thread-based test synchronization also needed that saturated pool. The test now
uses event-loop synchronization and explicitly exercises six-worker queued
jobs and eight-worker running jobs. Both cancellation scenarios pass for both
widths (four tests); production admission and cancellation code is unchanged.
The initial fixture bound the fixture loop instead of the test loop, and its
failed result is retained alongside the corrected passing run.

Material pages now have a bounded in-process cache of validated response bytes
(128 entries and 32 MiB of serialized keys/payloads). Each request reads the
existing transactional catalogue/source epochs. All validated query parameters,
database binding, epoch row versions and UTC policy year enter the key. Writes
to materials, papers, works and accepted source mappings invalidate through the
existing 0067 statement triggers; parent changes are covered by the same fence.
Writing transactions and old repeatable-read snapshots cannot publish pages.
A concurrent source change during a cold read produces a retryable 503 rather
than publishing a page assembled across revisions. Authentication and quota
middleware run independently for every hit.

The first test run correctly exposed that deserializing a scientific DTO through
its raw-material validators changes its semantics. Cached hits now return the
exact bytes serialized from the validated response instead of reclassifying
them. The corrected focused suite passed 248 tests, including real SQL/HTTP
mutations of raw records, display fields without updated_at changes, material
and parent holds, paper and Work lifecycle holds, accepted Work mappings,
insertion, deletion, concurrent source edits and policy-year changes.

On the upgraded complete-data clone, a three-row page took 33.444 seconds cold
and 0.007/0.005 seconds on two subsequent reads. The complete canonical response
hash remains `3dc509d9acc8e10247930101534359a1de66ea9c186863031e54e29aba472931`.
A 50-row page took 34.542 seconds cold and 0.019 seconds warm, also with identical
response hashes. These are diagnostic samples, not p95/SLO proof. **Cold reads
and reads after invalidation remain a cutover performance blocker.** Probe
containers were removed; no production data was modified.

Read-only metadata from the actual configured Vertex index reports 1,102,125
vectors, one shard, 768 dimensions, COSINE_DISTANCE and STREAM_UPDATE; the
deployment has one configured replica. SQL retains 1,117,982 chunks. These two
counts do not establish which IDs are missing or orphaned, nor per-item parity.
No model calls, index writes, replica changes or new cloud resources occurred.
The large-corpus generation/staging/readback design remains unfinished.

Seven new exact native captures (10 passing tests) retain 598 source pins for
each ML archive and 297 for Discovery. Historical archives are unchanged. A
local Docker-backed focused run stopped at service initialization before tests;
it is not counted as a Linux pass. Final GitHub Linux validation is required.

The complete offline suite passed 2,306 cases plus 91 subtests. Frontend checks
passed 1,890 component tests, 46 source tests and TypeScript. These local results
do not replace final Linux/image validation.


## Cold-read refinement and complete catalogue concurrency coverage

A second catalogue delivery test also assumed all eight admitted jobs could
start simultaneously. Both catalogue test modules now share explicit six/eight
worker fixtures; event synchronization never occupies the blocked executor.
The cancellation-capacity test waits for all eight submissions and the actual
worker width, then confirms that cancelled running/queued work retains capacity
until completion. The complete two-module run passes all 49 cases. No production
worker limit, cancellation behavior, test deadline or source gate was loosened.

Anomaly evaluation now avoids parsing quantities with no raw declaration. It
retains all explicit typed, alias, unit-only and nested-lattice channels, even
malformed ones; absent quantities cannot erase malformed compound-review
context. Tc is still parsed to validate shared source context/locators in empty
records. API and ingestion copies are byte-identical. A read-only comparison of
all 18,931 restored materials / 75,273 records found zero differing assessments
or exception types; measured anomaly CPU time fell from 23.350 to 8.252 seconds.
Another 42,288 deterministic synthetic input/context combinations also had
zero differences. Neither comparison created scientific approvals or DB writes.

The full-data HTTP experiment preserves both earlier complete response hashes:
three-row cold read 19.490 s, warm 0.032/0.005 s; 50-row cold read 19.539 s, warm
0.018 s. The measured private prototype and committed source have the same AST
and differ only in comments/whitespace; exact file/AST hashes are retained in
`anomaly-sparse-source-comparison.json`. This is not release-image parity proof.
**Cold reads remain too slow; these measurements do not close the performance
gate or justify production cutover.**

Current focused API policy/surface tests pass 257 cases; the full ingestion unit
suite passes 1,290. Initial ingestion runs exposed a missing unit-test-only
DATABASE_URL and four incorrect newly written test expectations (an unsupported
field name and a locator value that the parser deliberately sanitizes). Those
raw failures are retained; the corrected run uses the same unavailable loopback
DSN as CI and performs no production ingestion. Seven refreshed r9 native
captures pass 10 tests with all source pins verified.

The r9 captures also pass all 1,890 frontend component tests, 46 source checks
and TypeScript. The complete offline suite passes 2,306 cases and 91 subtests.
