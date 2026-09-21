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
This proves backup recovery at 0043; it does not yet prove 0043-to-0078 upgrade
or a production cutover. A separate internal-network clone is being prepared
with non-superuser migration/runtime roles for that next check.

## Still required before production completion

- Successful Linux Test/Security on the final PR and main revision, followed by
  exact release-image parity, vulnerability checks, SBOMs and signatures.
- Successful real-data 0043-to-0078 rehearsal and production migration/runtime
  role provisioning; reconciliation of preserved host-local changes.
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
