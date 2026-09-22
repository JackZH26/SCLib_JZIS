# Thirty-seventh implementation batch: scientific release restore rehearsal

Date: 2026-09-09. Base commit: `30a8b47`.
Issue advanced: [EN06 / #71](https://github.com/JackZH26/SCLib_JZIS/issues/71).
Related dependency: [RG03 / #69](https://github.com/JackZH26/SCLib_JZIS/issues/69).
Application schema remains `0067_scientific_adjudication`; no new migration,
backfill, source review or production operation.

## Delivered outcome

A complete **synthetic** scientific release now survives a real `pg_dump` and
`pg_restore` between two independently created, capability-guarded local
PostgreSQL instances. Verification checks the original release/pins, retained
artifact bytes, full public-table contents, permission/publication state and
source-linked vector-generation recovery. It does not infer health merely from
the server starting or a few core tables having rows.

The final full native rehearsal passed all stages and published a sanitized
[immutable measurement receipt](measurements/EN06_Research_Restore_2026-09-09-02.json).
The [first checkpoint](measurements/EN06_Research_Restore_2026-09-09-01.json) is
retained separately; it predates a subsequent legacy-test expectation correction.
The [recovery runbook](../../RESEARCH_RELEASE_RESTORE.md) documents exact commands,
failure behavior, evidence limits and remaining operational acceptance gates.

This is a local software acceptance slice. It is **not** an audited real-material
release, a production recovery demonstration, an external storage ACL test or
issue closure. No scientific, ML-training, public-release or deployment authority
is granted by the receipt.

## Complete dependency and recovery checks

The fixed fixture uses typed scientific records rather than an arbitrary table
marker: Work/paper, sample/state, pending Tc claim, measurement and synthetic
calculation events, a coordinate-bearing structure, planned/unexecuted run,
input/output manifests, property, source locator, policies, review, snapshot
membership, ML example/input, frozen release and immutable row pins.

The coordinate schema is consumed by the real coordinate feature reader during
the guarded source test. Its geometry and values are synthetic; neither the
coordinate reader nor the restore drill validates a real material prediction.
The planned run is not represented as a completed DFPT calculation. Missing
pressure is not converted to ambient pressure or zero.

The source uses the actual freeze and metadata-publication services. Separate
synthetic curator, reviewer and publisher accounts perform their respective
steps; the private source canary exists only in restricted artifact bytes, not
in a public bibliographic abstract. Real ASGI requests check denied anonymous,
ungranted/admin-only and revoked accounts, allowed current research operators,
and the metadata-only public manifest. These are application authorization
checks, not recovery of cloud IAM or production database roles.

The restored index is reconstructed in a new empty disposable adapter from
retained completion/vector bytes. It retains the exact generation, activation,
validation, member, evidence-revision, source/result and content-hash bindings.
Complete readback and source hydration are checked, then publication is replayed
with zero new upserts. SQL validation/activation history is not regenerated to
make an old generation look freshly validated. Derived Facts remain explicitly
support-ineligible; no embedding provider or ANN-quality evaluation is involved.

Before and after target verification, all public table row counts and canonical
content fingerprints match the original source snapshot. The source is checked
again independently. The schema head must match, public constraints must be
validated and indexes valid/ready; this does not claim exhaustive DDL equality,
cluster-role/secret recovery or corpus-scale completeness.

## Operational integrity

- The parent accepts only a backend, explicit native binary directories and a
  new report destination. It has no existing-dump, DSN, bucket, arbitrary-command
  or attach/reuse input. Both PostgreSQL/Redis pairs are created independently.
- Capability/runtime checks precede application clients; database and Redis
  identity checks precede actual use. Workers admit connections only to the
  exact owned loopback service ports. Inherited credentials are not passed on.
- Target verification is a fresh dedicated process, not a pytest fixture. It
  never drops/recreates or migrates the restored target. The source guard schema
  is excluded from the dump so the target keeps its own ownership identity.
- The source worker supplies the independent descriptor hash to the parent;
  copied self-descriptions cannot substitute their own trust root. The child
  stage's canonical run ID and root must match the parent's capability.
- Private capsule files are content-addressed, bounded, exclusive, non-symlinked
  and checked against held directory/file identities. Missing, extra, corrupt,
  substituted, aliased and oversized inputs fail closed, including actual
  coordinate and run input/output bytes.
- The actual open dump descriptor is fingerprinted before and after it is
  passed to `pg_restore`; path-only prechecks are insufficient. Nonblocking open
  rejects a substituted FIFO before any unbounded read. Restore is atomic with
  `--exit-on-error --single-transaction --no-owner --no-acl`.
- Success is published only after target/source checks, both owned cleanups and
  executed-source hash revalidation. Failures during construction, startup,
  stages, cleanup or publication cannot create a success receipt. Cleanup does
  not delete a replacement directory or an old colliding report.
- macOS native temporary roots use a resolved short system temporary parent to
  stay below the Unix-socket path limit. The directories remain uniquely created
  and mode `0700`; source files/logs/report are private.

The old PostgreSQL core-table restore job, backup script and retention policy
remain intact. A separate scientific-recovery workflow job uses locked Python
3.11 dependencies and uploads only a successful sanitized receipt. Static
workflow regression checks do not constitute a remote CI run.

## Small production compatibility fix

The rehearsal exposed an unrelated tokenizer initialization on UTF-8-only
embedding receipts. `stage_generation` now preflights the declared count method
using a bounded scalar query over immutable completion receipts. It prepares
the real cl100k encoder before the SQL fence **only when required**. The actual
under-fence receipt inventory, hashes and token recount remain unchanged.

Regression tests cover pure UTF-8 staging and exact replay without a tokenizer,
mixed/cl100k receipt initialization and real token recount, raw-SQL undercount
rejection, missing receipts, unavailable required tokenizer and native
UPDATE/DELETE/TRUNCATE rejection. No migration, provider contract, generation
format, source pin or scientific gate was relaxed.

## Verification

The measured parent created its own source and target services; all API tests
used the existing guarded disposable native runner. Successful runs confirmed
cleanup of only their owned services and temporary data. No inherited database
or existing local development service was reused.

| Evidence | Result |
| --- | --- |
| Final two-instance native dump/restore | Passed; **13.115 seconds** total including setup/checks/cleanup; macOS arm64, CPython 3.12.14, PostgreSQL 16.13 on both sides |
| Source/target/source-recheck inventories | **89 public tables, 116 rows**, identical SQL snapshot SHA-256 in all three measured stages |
| Retained capsule | **7 artifacts, 1,155 bytes**; exact manifest/descriptor/capsule hashes match |
| Final custom-format SQL dump | **920,498 bytes**, content fingerprinted on the exact restored file descriptor |
| Index reconstruction | **2 members, 6,144 vector bytes**; first upserts 2, replay upserts 0; no missing/mismatched/orphan members |
| Final entire scripts suite | **1,197 passed + 36 subtests**, 15.57 seconds |
| Focused new contract/orchestration | **132 passed**, 1.62 seconds; included in the full scripts suite |
| Focused index-helper source tests | **55 passed**, 0.35 seconds; included in the full scripts suite |
| Focused worker source-only tests | **21 passed**, 0.39 seconds; included in the full scripts suite |
| Guarded index/tokenizer/receipt regression | **91 passed**, 10.66 seconds; overlapping with integrated API selection |
| Guarded typed-fixture/access/index/schema regression | **13 passed**, 2.68 seconds; overlapping with integrated API selection |
| Corrected legacy release-schema regression | **89 passed**, 5.95 seconds; overlapping with integrated API selection |
| Final integrated 17-module API regression | **544 passed**, 95.06 seconds; one existing FastAPI `regex` deprecation warning |
| Scoped Python lint and whitespace | Ruff I/F and `git diff --check`, passed |

The archived receipt binds **554 executed input-file hashes**, its base revision
and dirty source state. After receipt publication these inputs were independently
rehashed and matched the captured provenance; the retained file was mode `0600`.
Its report checksum is
`682c9c13e534c5049b620b42e6833eac4d861a853abb4bfa6062729f62027199`.
This checksum is not a signed attestation. The receipt describes the measured
pre-commit state; it is not rewritten to pretend a later commit existed then.

The 13.115-second total includes setup and orchestration in addition to the
individually timed stages. It is not a production RTO, and no zero-loss/RPO claim
is made. Production loss window, RPO/RTO, full-corpus performance, external vector
service recovery, roles/secrets and scientific validity remain `null`.

No frontend files changed, so this batch does not claim a new browser/UI run.
Linux Docker/CI execution and production image equivalence remain unverified
by this native rehearsal.

### Corrections during verification

The source-only fixture tests exposed two genuine contract mismatches: the
disposable vector adapter still requires SDK-shaped resource names, and pending
legacy material records correctly block metadata-publication admission. The
fixture now supplies valid strictly local resource names and a neutral synthetic
catalogue record while preserving the actual pending claim and raw paper record.
No access or scientific-review gate was disabled. Earlier failed fixture runs
are not counted as acceptance or described as successful restores.

The final source checks also caught an expired transaction-local statement
timeout after source commit, the missing explicit Redis identity check and
schema-validity checks. Those were fixed before the retained full rehearsal.
The first full two-instance parent run passed in 14.253 seconds without retries
or an overwritten receipt. It is retained as checkpoint 01.

The initial broader 17-module API run then reported **543 passed and one failed**
in 92.97 seconds: the old 0054 concurrency test expected a catalogue edit to
succeed while a release fence was held. Schema 0067 deliberately added a
catalogue-writer integrity fence. The test now checks the exact `55P03` rejection,
rollback with unchanged current formula, a successful fresh transaction after
the capsule commit, and unchanged full release/pin records. Production guards
were not changed. Its focused module passed all 89 tests. Because this test file
is part of source provenance, the final full rehearsal was rerun as checkpoint
02; checkpoint 01 was not relabeled or overwritten. New random fixture
identities naturally produce different capsule/dump hashes between runs.

## Remaining acceptance and next priority

EN06 remains open for an authorized isolated recovery of one **real audited
release**, complete backup inventory, actual storage/role access controls,
external vector resource reconciliation, real-scale timing/loss-window
measurements, owner-approved RPO/RTO and linked delivery/CI evidence. Existing
backups must remain intact. Synthetic software tests cannot satisfy these gates.

The next safe local software slice is RG03 / #69: immutable response-level
evidence/generation pins for newly saved answers, honest unpinned legacy history,
and separate current-source warning/hold checks. Reconstructing invented pins
for past answers is not an acceptable migration strategy.

This batch does not authorize push, PR creation, live issue closure, deployment,
source redistribution, paid calculation or a real scientific review decision.
The broader goal remains active.
