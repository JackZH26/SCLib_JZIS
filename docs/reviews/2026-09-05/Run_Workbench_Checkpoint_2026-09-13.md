# Local checkpoint — batch61 and unfinished batch62

Historical checkpoint. The subsequent targeted verification and client fixes
are recorded in the [batch62 report](Priority_Sixty_Second_Batch_Implementation_2026-09-13.md);
the commit-time results below retain their original scope.

Saved at the user's request on `codex/sclib-research-v2`, based on
`85dff80ba2ec2f9bfbfc5f3f291f7a64e1c51f4f`. This preserves current development;
it is not release acceptance or authorization to deploy, migrate production,
grant real roles, execute a model or close the upgrade issues.

## Included scope

- Completed batch61: exact owner run plans, independent conditional decisions,
  original-key recovery, fresh readiness checks, the approval-expiry NULL
  guard, and migration 0074 lifecycle verification. The
  [batch61 report](Priority_Sixty_First_Batch_Implementation_2026-09-13.md)
  retains its historical API, migration, script and frontend test evidence.
- Unfinished batch62: English owner/approver workbench at
  `/dashboard/research/ml-runs`, navigation entry, strict client protocol and
  transport implementation, plus a new native HTTP capture test and fixture.
  These are initial implementations, not verified browser workflow delivery.
- Preserved old native fixtures under archive names and added fresh captures;
  no historical response was resealed to imply a new successful capture.

The batch62 native fixture is 173,875 bytes, SHA-256
`1cabdf1fc608c169a82b3b9942a6e672595c860a00b264b339f54e867dd9419f`.
Its 23 raw responses and 556 source pins came from guarded native SQL/HTTP
with synthetic identities and an explicit intake-compiler double. The earlier
capture test passed once; it is not human review or real execution evidence.

## Commit-time checks

- Nonincremental frontend TypeScript: passed.
- Existing frontend regression suite: 41 files / 1,436 tests passed in 42.16s.
  All 38 source checks also passed, including the global English-default rules.
- Scoped Ruff for the changed run model, services, router and API tests: passed.
- All 556 run-workbench, 555 ML-rights and 274 Discovery active fixture source
  pins match their current files. Both historical archives match the previous
  committed active fixture bytes exactly.
- The frozen 0074 migration report hash remains
  `9faab27a9890a83da206755c402b355061d4d3062cc51be79e42dbb176faff28`.
  It is historical batch61 evidence and does not include the new batch62 test
  or browser implementation. Database tests and migrations are not repeated
  during this commit-only request.
- Git whitespace validation passed before staging.

## Required follow-up

1. Test the new client parsers against all native run responses and hostile
   payloads, including raw host-document floating-point values and hashes.
2. Add workbench component coverage for exact preview/commit, identity changes,
   independent decisions, readiness boundaries and unknown-outcome recovery.
3. Run isolated desktop/mobile browser and English-default checks for the new
   workflow, inspect its layout, and update its operator instructions.
4. Keep actual execution disabled until the separate scientific, source-rights,
   runtime and execution-consumer gates have been satisfied and verified.

Existing frontend suites do not substitute for the missing batch62-specific
component, protocol, accessibility and browser verification.
