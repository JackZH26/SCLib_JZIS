# Private run-review evidence — development checkpoint

Status: unfinished batch65, saved locally at the user's request. This is not a
release, migration approval, scientific signoff or authorization to execute ML.
The preceding batch64 offline report is recorded separately in the
[batch64 report](Priority_Sixty_Fourth_Batch_Implementation_2026-09-13.md).

## Implemented so far

- Draft migration `0075_ml_run_evidence`, metadata and database guards for
  bounded private review text and immutable purge receipts.
- New run approvals require retained UTF-8 text matching their evidence hash.
  Historical approval rows are not rewritten; missing retained evidence is
  reported as `evidence_unavailable` in the current approval status.
- Private API operations for the original review author to read or purge the
  document, and an administrator to purge expired documents in bounded batches.
- Exact-grant checks, retention tied to the parent submission, anti-resurrection
  replay behavior, and account-erasure audit references.

The retained text concerns a run/budget review only. It is not original-paper
evidence, a source licence, independent pilot acceptance or execution authority.
No actual pilot, human approval, production migration or model run was performed.

## Checkpoint verification

The already-started owned disposable PostgreSQL/Redis API run completed with
**13 passed**, one existing FastAPI deprecation warning, in 73.77 seconds:
`tests/test_ml_use_runs.py`. The runner reported cleanup of only its owned test
services and temporary data. This tests the targeted run service through the
test schema; it does not establish an Alembic migration rehearsal or full
evidence-endpoint/privacy coverage.

## Required before this increment can be accepted

1. Update the frontend input, approval-status parser, request limits and review
   workbench for the new text requirement; add controlled read/purge interaction.
   The existing workbench does not yet send the required text for a new approval.
2. Add dedicated HTTP and direct-database tests for text/hash boundaries,
   independent access, expiry, purge, replay, storage limits and audit retention.
3. Update the migration lifecycle/rehearsal tests and execute an owned 0075
   upgrade/downgrade rehearsal, including preservation of legacy approvals.
4. Recapture native wire fixtures from the changed API and verify the frontend
   contract. Existing source-pinned fixtures and the 0074 receipt are historical
   evidence; do not reseal them to imply coverage of the current API sources.
5. Complete the operator/protocol documentation, broader regression tests and
   desktop/mobile interaction checks. Execution must remain disabled until its
   separate authorization and scientific gates are genuinely satisfied.

No push, pull request, merge, deployment or issue closure is included in this
checkpoint. The repository-wide upgrade goal remains unfinished.
