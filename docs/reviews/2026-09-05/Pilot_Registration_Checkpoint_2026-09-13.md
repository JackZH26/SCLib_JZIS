# Pilot registration checkpoint — batch66/67 and unfinished batch68

Historical commit-time status. Subsequent migration work and verification are
tracked in the [batch68 report](Priority_Sixty_Eighth_Batch_Implementation_2026-09-13.md);
this checkpoint's original results and unfinished-work record are retained.

Local checkpoint requested before further development, recovered after the
connection interruption. Base: `d85b106` on `codex/sclib-research-v2`.
**This is work in progress, not a release candidate. Do not deploy this
checkpoint or apply migration 0076 to a live database.**

## Preserved implementation

- Batch66: real private-payload capacity and audit-retention checks, plus
  tokenizer-cache preparation in CI and both Python images. Its earlier
  verification remains in the [batch66 report](Priority_Sixty_Sixth_Batch_Implementation_2026-09-13.md).
- Batch67: installable ML08 accounting/schema, bounded exact-document intake,
  canary compatibility, installation probe and historical native/UI evidence.
  See the [batch67 report](Priority_Sixty_Seventh_Batch_Implementation_2026-09-13.md).
- Unfinished batch68: three append-only registration/participant/decision
  ledgers, draft migration 0076, account-retention references, isolated upload
  checking and private authenticated preview/commit/inspection/recovery APIs.
  The independent `ML_PILOT_REGISTRATION_ENABLED` flag defaults to false.
  No participant workbench has been implemented.

Registration commits to exact selection/protocol hashes and reviewer-account
bindings; source-bearing files are not retained by these ledgers. Each account
must confirm for itself. Account separation is not human identity verification
or scientific independence. Participation readiness never grants scientific
pilot acceptance, source rights, public release or ML execution authority.
The [implementation contract](../../ML_PILOT_REGISTRATION.md) records the boundary.

## Checks repeated after recovery

No prior test process was still running when recovery began. The interrupted
run had no recoverable terminal result, so it was not counted as passing.

- The actual owned-native registration and HTTP suites passed **15 tests**,
  23.01s, with one existing FastAPI `regex` deprecation warning. They exercise
  actual PostgreSQL, authenticated HTTP and the child document checker using
  synthetic study/account data. The runner confirmed cleanup of its own
  PostgreSQL/Redis services and temporary test data.
- A new import-format issue in `api/models/db.py` was corrected. All other
  changed/new Python files pass scoped Ruff. That existing model file retains
  exactly the same eight lint findings as `HEAD` (four UP037 and four E402);
  this is not a claim of a lint-clean repository. Eight new registration
  Python files pass formatting checks.
- `git diff --check` passes. A limited private-key/common-provider-token
  pattern scan found no matches in the changed/new files; this is not a
  comprehensive secret audit.

After the import-format correction, the final combined
registration/HTTP/audit-retention run passed **47 tests**, 56.09s, with the same
one pre-existing warning and verified owned-service cleanup. Its 15 registration
cases overlap the earlier run; these counts must not be added as unique tests.
No reported test process remains running. The final command was:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py \
  --backend native --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/bin/redis-server --suite api -- -q \
  tests/test_ml_pilot_registration.py tests/test_ml_pilot_registration_http.py \
  tests/test_research_audit_retention.py --maxfail=1 --tb=short
```

## Required follow-up before release

1. Complete the new migration lifecycle coverage. The existing rehearsal still
   asserts head `0075_ml_run_evidence`; it has not been updated or executed for
   0076. Test empty upgrade/downgrade, populated downgrade refusal, old-row
   preservation and startup admission through the disposable runner. API
   metadata-created tests are not an Alembic migration rehearsal.
2. Extend adversarial coverage for malformed/oversized uploads, worker
   cancellation, competing writers, partial rosters, stale decisions, original
   grant replacement and declared-versus-server chronology. Perform the new
   worker's installed-wheel verification rather than inheriting batch67's
   narrower installation proof.
3. After backend sources stabilize, generate new native run/rights/Discovery
   captures and update consumers from those actual bytes. The batch67 archives
   and 0075 receipts are historical and no longer prove current-source parity.
   Preserve their original hashes; do not reseal or relabel them. Repeat the
   full script/frontend/browser checks and source-pin validation.
4. Add and verify the English participant workflow and independent scientific
   signoff as separately scoped development. Real participants, approved
   sources and the actual 60-event study remain required for ML08 #54.
5. Obtain the separate remote delivery direction and actual Linux/image
   evidence before claiming delivery or closing the corresponding issues.

The feature flag does not exempt a deployed API from exact-head schema checks;
default-off is not a reason to deploy this unverified migration. Historical
batch66/67 pass counts describe those source states, not a full green build of
this checkpoint. No push, PR, deployment, production migration, real role grant,
real-data review, model execution or issue closure is performed by this save.
