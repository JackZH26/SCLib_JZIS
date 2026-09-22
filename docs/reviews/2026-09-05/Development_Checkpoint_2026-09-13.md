# Development checkpoint — batch60 and unfinished batch61

Historical checkpoint only. Subsequent implementation and verification,
including resolution of the draft expiry guard and source-pin failures, are
tracked in the [batch61 report](Priority_Sixty_First_Batch_Implementation_2026-09-13.md).

This local checkpoint was requested before further development. It preserves
the completed batch60 workbench and the initial, unfinished batch61 schema
together. **It is not a release candidate. Do not deploy this checkpoint or
apply migration 0074 on a live database.** No push, deployment, production
migration, real permission grant or model execution is performed by this save.

## Included work

- Batch60: private English ML source-rights workbench, native wire fixture,
  component/browser tests and operator documentation. Its earlier verification
  is recorded in the [batch60 report](Priority_Sixtieth_Batch_Implementation_2026-09-13.md).
- Batch61, work in progress only: `ml_use_run_plans` and
  `ml_use_run_decisions` model definitions, draft migration 0074, metadata
  registration and user-retention references. No run service, HTTP router,
  live readiness integration or execution consumer has been implemented.

## Checks repeated before this checkpoint

- Scoped Python Ruff and syntax compilation: passed for the new model,
  migration, retention service and native wire test.
- Frontend TypeScript, nonincremental: passed.
- Frontend source checks: **38 passed**.
- ML rights and Discovery main-barrier component tests: **137 passed,
  2 failed**. Both failures are exact-source-pin checks: `api/models/db.py`
  changed after the historical native fixtures were captured. This is a real
  checkpoint verification failure, not a new successful native capture.
- Whitespace checks passed. No API/database tests or migration rehearsal were
  repeated for the new 0074 schema in this commit-only turn.

The earlier batch60 result of 1,436 passing frontend tests applies to the
pre-batch61 source state, not this combined checkpoint. Historical fixtures and
rehearsal receipts are preserved unchanged; none is resealed to imply that the
unfinished schema has been tested.

## Required follow-up before release

1. Fix and test the draft approval-expiry NULL guard. SQL `CHECK` accepts an
   unknown result: the current approval condition needs an explicit
   `expires_epoch IS NOT NULL`, with matching insert-guard and native rejection
   coverage. This known draft defect is recorded, not silently repaired during
   the user's commit-only request.
2. Complete and review the run plan/independent decision services and routes,
   exact ownership/role checks, replay handling, expiry/revocation and fresh
   source-rights/readiness checks. Approval records alone must not enable runs.
3. Update migration lifecycle tooling, which still assumes head 0073, for
   both 0074 tables and history-preserving downgrade checks. Perform a guarded
   disposable-database rehearsal and native integration regressions.
4. After backend sources stabilize, archive the historical active fixtures and
   generate new native captures. Update source-pin assertions only from those
   real captures, then repeat frontend and browser verification.
5. Keep actual execution disabled until independently reviewed scientific
   inputs and guarded execution consumption satisfy their separate gates.

This checkpoint does not close any issue or mark the ongoing upgrade complete.
