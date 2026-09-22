# Batch65 — private run-review evidence integration

Base: `60e370d` on `codex/sclib-research-v2`. The preceding user-requested local
commit was progress. This turn resumes the
[unfinished checkpoint](Run_Review_Evidence_Checkpoint_2026-09-13.md), not a
redefinition of the repository-wide upgrade goal. New integration changes remain
uncommitted.

## Priority and implementation

Fresh GitHub reads found 38 open issues and confirmed ML09 #76 depends on ML06,
ML07 and ML08. The concrete unfinished dependency was that the API required
retained review text for new approvals while the workbench still sent only a
hash. This increment connects that workflow and adds private read/purge controls.

- The approval form accepts bounded plain text, computes SHA-256 of its exact
  UTF-8 bytes and invalidates preview/consent on edit. Unknown writes retain the
  original input for explicit recovery. Denial/revocation do not require text.
- Private read replies include the full immutable decision. Client verification
  binds the document to that decision, not merely to a self-supplied text hash;
  conflicting IDs, hashes, plans, byte counts, flags and unknown fields fail.
- Only the original author with exact current review grants can read. That
  author can request purge after review-role revocation while still an active,
  verified administrator. Purge deletes live text and appends immutable history.
- Lost purge replies remain unknown until explicit identical retry verifies the
  receipt. Approval replay cannot resurrect purged text. The UI clears private
  displays on close/auth change, rejects late stale replies, renders text inertly
  and uses no browser-storage persistence or automatic writes.
- `evidence_unavailable` propagates through inspection, readiness and UI without
  changing historical decision hashes. SQL now uses an explicit Unicode
  whitespace set instead of space-only trimming; invalid UTF-8/surrogates, NUL,
  whitespace-only text and byte-limit violations are refused.

This is run/budget review evidence, **not** a paper licence, independent scientific
pilot signoff or execution permission. Model execution remains disabled. The
[operator/API guide](../../ML_RUN_EVIDENCE.md) documents coordinated API/client
rollout, exact references, retention, irreversible live purge and backup limits.

## Verification and corrections

New owned-native tests cover exact UTF-8/8,192-byte boundaries, rollback-only
preview, missing text, literal HTTP read and decision binding, independent
accounts, revoked roles, stale sessions, lost-commit recovery, no resurrection,
immutable rows, direct-SQL missing-document/invalid-text rejection, 16 KiB JSON
bodies and 20-record expired-purge batches.

The initial shape tests expected the wrong exception class; they now assert the
existing `ValueError` contract. The next run had 23 passed / 2 failed: malformed
private bodies correctly return 400, not 422, and the purge count must be scoped
to the test's own 21 decisions rather than earlier retained audit records.
Neither correction relaxed a permission or history-preservation guard.

Expanded native scope, including the genuine request/reconstruction pipeline:
**28 passed / 1 failed**, 332.34s. The failure was the capture's source-stability
assertion: the migration harness changed during capture. That attempt produced
no accepted archive. After source stabilization, all **3 native capture tests
passed**, 62.15s, including the failed run capture plus rights and Discovery
captures. This is not described as a fully green combined invocation. The only
warning is the pre-existing FastAPI `regex` deprecation in `routers/admin.py`.

The first migration rehearsal rejected a harness call to schema admission after
the connection had already been used. Reordered it to require a fresh connection
and made the old-schema assertion require an actual exact-revision mismatch.
The final rehearsal passed in **80,897 ms** with verified cleanup. It exercised:

- Empty downgrade/re-upgrade and the existing earlier scientific/history tests.
- A synthetic approval inserted into the actual 0074 schema, followed by real
  0075 upgrade, byte-exact history preservation and `evidence_unavailable`.
- Original-key recovery without invented documents, new text read/purge/no-op,
  and refusal to downgrade nonempty evidence/purge history.

Full scripts: **2,038 passed / 36 subtests**, 83.27s. The scoped new frontend tests
first passed 72 cases plus nonincremental TypeScript checking. The first full
frontend run had 1,586 passed / 1 failed because a newly inserted hash assertion
preceded its local helper declaration; moving that assertion fixed it.

Final frontend: **45 files / 1,587 tests passed**, 34.74s; **38 source checks** and
nonincremental TypeScript checking also passed. Current native protocol tests
verify evidence bytes, immutable binding, purge/no-op and missing-evidence
inspection/readiness. Historical fixture hash checks remain intact.

Initial browser tests rejected the deliberately multilingual user text under an
old whole-page English assertion. The corrected check exempts only the exact
verified synthetic review string, not arbitrary preformatted/application text.
All application-owned UI remains English. The browser also verifies literal
script-like text without execution. Action-button spacing was improved.

Final isolated browser run: **4 passed**, 41.2s, at desktop 1440×1000 and mobile
390×844. Separate requester/reviewer contexts cover approval/revoke/deny,
private read, lost purge reply and identical retry, missing-evidence readiness,
lost approval commit recovery and admission clearing. No unexpected/external
API requests or page errors were observed in the handoff tests. The private
evidence desktop/mobile screenshots were visually inspected. Temporary evidence:
`/var/folders/m0/ztnj2ywn613cqhtb3_ym0xyc0000gn/T/sclib-ml-runs-browser-artifacts-5ATOIB`.
This browser double is not SQL, real human approval or execution evidence.

All these processes have terminal results; none is being treated as successful
while still running. Changed API files pass Ruff. Scoped migration checks exclude
four pre-existing C408 findings in the harness and two pre-existing PLW1510
findings in its source tests; the latter were also reproduced against `HEAD`.
These exclusions are not a claim that repository-wide lint is clean.
All 134 relative Markdown links in changed/new documents resolve, and
`git diff --check` passes.

## Retained provenance

[0075 native receipt](measurements/schema-rehearsal-0075-native-2026-09-13.json):
raw SHA-256 `3ad7c1e105b81f99b9e1c9cad35c48d3bb35befbb9200a66d8c4782ab813a512`,
686 source inputs; inventory digest
`977d424cb6f1a40b5a9b99f8605e8b3ee9c79a24b1f6f936919e61356aecdfcf`.
Runtime: native PostgreSQL 16.13, CPython 3.12.14, Darwin arm64. The copied
receipt was revalidated against current selected sources. It is not a Linux
image or production migration claim; the old 0074 receipt remains unchanged.

New `frontend/tests/fixtures/*batch65.wire.json` archives are byte-exact copies
of successful owned SQL/HTTP output. All selected source pins were rechecked
with zero mismatches; previous files were not overwritten or resealed.

| Archive | Bytes | Pins | Original JSON replies | Raw SHA-256 |
| --- | ---: | ---: | ---: | --- |
| Run governance | 193,995 | 561 | 28 | `66ae36119f0023616a3de987bc287fecf6e10058dbad53920e0f50b62d130002` |
| ML rights | 214,549 | 561 | 15 | `c6431f457ed7de687a48fe9bef413452e57d243310ffdf75dfeef06daae697aa` |
| Discovery barrier | 197,457 | 276 | 7 | `83c65fb4120d796d8f5116269cc146198aefe6cd7da104565a186a2fc13387ed` |

## Remaining work and acceptance limits

The 8 KiB payload tests and code-enforced 32 MiB aggregate quota are not aggregate
quota/concurrency stress or production capacity measurements. The purge audit
test checks an administrator who also has other audit references; a sole-purge-
reference account-erasure case remains useful hardening. No automatic expiry
scheduler or backup-erasure workflow is claimed: expiry blocks read access, and
an authorized operator must explicitly run bounded expired-document maintenance.

Independent scientific pilot acceptance and one-shot isolated execution admission
still require their own implementation/evidence. Real ML08 selection, independent
human review, source permissions and protocol acceptance are not manufactured.
ML09 still requires its authorized, leakage-safe evaluation and reproducible
release. Remote PR/Linux CI delivery remains pending the previously requested
direction. No push, PR, merge, deployment, real role grant, source redistribution,
model execution or issue closure was performed. The full upgrade goal remains
active with the open backlog intact.
