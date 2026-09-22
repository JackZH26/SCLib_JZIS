# Private review integration and capacity tests — local checkpoint

Saved at the user's request to commit current changes. Base: `60e370d` on
`codex/sclib-research-v2`. This is a work-in-progress checkpoint, not a release
or a claim that the current tree passes every acceptance check.

## Included work

- The completed batch65 private review workbench, literal read/purge UI,
  protocol verification, API hardening, migration rehearsal support and guides.
  Historical verification is recorded in the
  [batch65 report](Priority_Sixty_Fifth_Batch_Implementation_2026-09-13.md).
- The subsequent, unfinished batch66 regression work: a separate owned-service
  capacity suite using the actual 32 MiB quota, concurrent last-slot admission,
  quota reclamation and replay; a corresponding CI step; and a sole-purge-
  reference account-retention test.

## Verification at this checkpoint

The recovered terminal result for the latest owned-native invocation of
`tests/test_ml_run_evidence.py` and `tests/test_research_audit_retention.py` is
**43 passed / 1 failed**, 56.65 seconds, with one existing FastAPI deprecation
warning. The runner reported removal of only its owned services and temporary
data.

The failing test is
`test_expired_text_cannot_be_read_and_cleanup_is_bounded_with_audit_hold`.
Its direct database account-deletion assertion passed, but its later HTTP
assertion expected the audit-retention response (409). The target is still an
administrator, so the existing administrator-deletion guard rejects it first
with 400. The next step is to correct the test setup to reach the audit guard
through a permitted deletion workflow, not relax either production safeguard.
This failure remains intentionally preserved in this requested checkpoint.

The earlier capacity-test process handle is no longer available, and its terminal
result was not recovered. No corresponding test runner was live at the process
inspection. Its outcome is **unverified**, not a passing capacity measurement;
repeat the separate owned-service invocation before acceptance.

Scoped Ruff checks passed for the changed evidence model/service, evidence and
native run tests, and the new capacity suite. Whitespace checks passed before
staging. No new full frontend, browser, migration or Linux CI run was performed
for this commit; the batch65 report describes the earlier verified scope.

## Resume requirements and evidence limits

1. Correct and rerun the sole-purge-reference HTTP test in owned services.
2. Obtain a terminal result for the real-quota capacity suite, and finish its
   safety-bootstrap regression/documentation review.
3. Once API/scripts inputs are stable, capture fresh native wire fixtures and a
   fresh migration receipt. The retained batch65 archives must remain byte-exact:
   later API test changes mean their source pins are historical, not proof of
   the current checkpoint. Do not reseal them to imply current verification.
4. Rerun the relevant integrated regressions before describing this as ready
   for review or release.

No push, PR, merge, deployment, production migration, scientific acceptance,
source-permission grant, model execution or issue closure is included. The
repository-wide upgrade remains unfinished; execution stays disabled.
