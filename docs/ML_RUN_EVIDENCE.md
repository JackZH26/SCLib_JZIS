# Private run-review evidence

Schema: `0075_ml_run_evidence`. Private evidence API:
`ml-run-review-evidence/1.0.0`. This extends
[conditional run governance](ML_USE_RUNS.md), not scientific pilot acceptance.

## Meaning and content

A new conditional approval must retain the reviewer's short plain-text account
of the exact proposed run and budget. `evidence_text` contains the literal text;
`evidence_sha256` is SHA-256 of its UTF-8 bytes, including spaces and newlines.
The browser calculates this hash. It must not trim, normalize or render the text
as HTML or Markdown. The text is not returned in plan/approval receipts, source
coverage, public pages or ML dataset exports.

Record the review rationale and relevant opaque private references, not paper
contents, credentials or unnecessary personal information. This document does
not establish a source licence, independent scientific acceptance, data quality,
model accuracy or permission to execute. All execution-authority flags remain
false; model execution is disabled.

Text must be non-whitespace, valid UTF-8 without NUL, and at most 8,192 bytes.
The total live payload storage cap is 32 MiB, enforced in the serialized writer
transaction. New approval requests have a 16 KiB JSON-body ceiling; escaping
can reach that ceiling before the text's byte limit. Other run/rights request
limits remain 8 KiB. No content is silently truncated.

## Atomic storage and compatibility

`ml_run_review_evidence` stores one payload per immutable approval decision.
A deferred database constraint requires every newly inserted approval to have
its matching document in the same transaction. Preview exercises the constraint
and rolls back both rows. Denial and revocation do not store text. A committed
original-key retry returns its historical receipt and never recreates purged
bytes, even when the caller supplies the original text again.

The 0075 migration creates no grants, approvals, source permissions or documents
for old decisions. Old decision/intent hashes remain byte-exact. An old approval
without a retained document is `evidence_unavailable` in a current inspection or
readiness check; this is not a rewrite of its historical decision. A newly
reviewed approval requires an explicit new decision and predecessor binding.

The immutable run record codec remains version 1. The new input requirement and
`evidence_unavailable` status are an API/client contract extension: deploy the
matching frontend and API together after release approval. An old hash-only
client cannot create a new approval. Do not treat historical 0074 native fixtures
or migration receipts as proof for the changed API.

## Private API and author workflow

All endpoints are under `/v1/ml/use/runs`, use session authentication, return
`Cache-Control: private, no-store`, and retain the governance feature gate.
Unknown/malformed errors do not echo submitted text. Except the expired batch
operation, use exactly `{decision_id, decision_sha256}` from the immutable
historical decision receipt; knowing those references is not authorization.

| Operation | Admission and result |
| --- | --- |
| `POST /evidence/read` | Original author, active verified administrator and the exact still-current curator/run-approver grants from that decision. Returns literal text, byte count, content hash, full hash-verified decision and original parent retention expiry. |
| `POST /evidence/purge` | Original author who is still an active verified administrator. Review-role revocation does not prevent withdrawal. Deletes live text and appends an immutable purge receipt atomically. An identical retry returns the existing receipt. |
| `POST /evidence/purge-expired` | Active verified administrator; requires an explicit empty JSON object `{}`. Removes at most 20 expired documents in one transaction; returns count, batch limit and `more_may_remain`. It cannot purge unexpired documents belonging to others. |

The independent-approver workbench provides **Private run-review text** on the
approval form. Editing text invalidates its preview and consent. Commit uses
the exact retained preview body. An unknown commit still requires original-key
recovery; no new approval is inferred from a missing reply.

**Manage private review evidence** opens a separate panel. Enter your decision
UUID/hash and explicitly read or confirm purge. The client verifies the document
against the immutable decision and displays source-like markup as inert text.
Clear the display or close the panel when finished. No drafts or documents are
saved in browser storage. Session changes abort pending reads and clear private
display; stale responses cannot repopulate it.

Purge is irreversible for the live document and requires explicit confirmation.
If its reply is lost or unverifiable, the panel locks that operation and offers
only an explicit identical retry. A verified receipt proves live-text purge,
not deletion of backups or independent copies. Keep the original references in
an approved private log; navigating/reloading loses in-memory recovery state.
Reload plan/readiness after purge rather than relying on a prior snapshot.

## Retention and operator responsibility

Read access ends at the original submission's seven-day expiry; it never slides
on read, retry, a new role grant or a replacement approval. Purging a document
preserves the decision, immutable purge actor/time/reason and audit references.
Account erasure cannot silently delete those references.

Expiry blocks reads but is not itself byte deletion. No automatic scheduler or
backup-erasure workflow is introduced in this increment. An authorized operator
must explicitly run the bounded expired-document maintenance operation until a
batch reports fewer than 20 removals. New expirations can occur afterward.
Backups, browser-held copies and downloaded reports have their own approved
retention obligations; this endpoint makes no claim to erase them.

Downgrade locks the parent decisions and both new tables. It refuses if either
live documents or purge history exists. Do not remove audit history to force a
rollback. Rehearsal and API tests use only owned disposable services; see
[the testing guide](TESTING_SAFELY.md).
