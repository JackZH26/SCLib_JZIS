# ML08 own-account review declarations

Schema: `0077_ml_pilot_attestations`. Record version:
`ml08-review-attestation/1.0.0`. This private API records a participant's
explicit, versioned declaration about their own complete review contributions
and, only for the recorded conclusion author, that exact conclusion. It is not
an external cryptographic signature, proof of independent human identity, final
collective pilot acceptance, a source licence or permission to execute ML.

The complete 60-event pilot in [ML08 #54](https://github.com/JackZH26/SCLib_JZIS/issues/54)
still requires actual source events, independent human comparison/arbitration,
permitted evidence, reviewed missingness/effort and a justified go/narrow/stop
recommendation. Synthetic declarations do not satisfy those requirements.

## Prerequisites and exact declaration

New declarations require all three default-off flags:
`ML_PILOT_REGISTRATION_ENABLED`, `ML_PILOT_REVIEW_INTAKE_ENABLED` and
`ML_PILOT_ATTESTATIONS_ENABLED`. This document does not authorize enabling them
or migrating a shared database. The English own-review workbench is available
at `/dashboard/research/ml-pilot-reviews`, separate from protocol participation
at `/dashboard/research/ml-pilots`. Neither page grants scientific acceptance.

An active authenticated account can read
`GET /v1/ml/pilots/review-attestations/declaration`. It returns the exact English
`declaration_text`, its UTF-8 SHA-256 and version, plus explicit non-authority
flags. A client must show that complete wording and the exact document/own
contribution preview before asking for consent. No checkbox may be preselected.
The declaration contains different explicit meanings for attest and withdraw;
the selected action must also be clear. The version, text and hash are frozen
in `api/services/ml_pilot_attestation_contract.py`; future wording changes need
a deliberate new contract/version, not a silent reinterpretation of old rows.

The submitted `declaration_sha256` and version must exactly match this wording.
The durable record and intent retain both. An acknowledgement without the exact
contract, a supplied foreign actor or a preflight-result shortcut is refused.

## New declaration: originals, preview, explicit commit

`POST /v1/ml/pilots/review-attestations` requires the intended participant's
authenticated session and exactly one of each
`X-SCLib-Participant-Id` / `X-SCLib-Participant-Sha256` header. Ownership/current
admission is checked before upload, after upload, and in the final serializable
write transaction after complete document verification.

The body has the same four canonical base64 original-file fields, four raw file
hashes and two logical hashes as [review preflight](ML_PILOT_REVIEW_PREFLIGHT.md),
but version `ml08-review-attestation-upload/1.0.0`. Each file remains at most
8 MiB; the envelope limit remains 44,804,784 bytes. The worker mode is fixed by
the route, not a caller-supplied operation switch. Old/new envelopes cannot be
interchanged between preflight and attestation routes.

Supply every field in `parameters` explicitly:

| Field | Meaning |
| --- | --- |
| `participant_id`, `participant_sha256`, `registration_sha256` | Exact original account/registration references; participant references must match the headers |
| `request_key` | Retained nonsensitive idempotency key for this logical operation |
| `reason_code` | Nonsensitive lowercase machine code, not evidence text |
| `supersedes_id`, `supersedes_sha256` | Exact current declaration predecessor, or both null for the first declaration |
| `declaration_version`, `declaration_sha256` | Exact displayed declaration contract |
| `declaration_acknowledged` | Explicit true only after the participant has reviewed the action, wording and evidence |
| `expected_intent_sha256` | Null for initial preview; exact returned intent hash for commit |
| `dry_run` | True for preview, explicitly false for commit |

1. Read the exact declaration wording and inspect the account's current head.
2. Upload all four originals and request a preview. The shared kernel validates
   the full fixed candidate denominator, every review revision and conclusion.
   The service rechecks original registration pins, roles, current participation
   and declared review times against recorded acceptance intervals.
3. Review the returned intent and document/contribution identifiers. Preview
   runs the real insertion constraints inside a rolled-back transaction; it
   does not persist a declaration or prove that a later commit will succeed.
4. Explicitly commit the same input, original key, predecessor and returned
   intent hash. The server repeats all checks; stale heads or changed state fail.
   There is no automatic new key, rebase, retry or adoption of another version.

Each new attestation binds the current accepted participation decision ID/hash.
A changed document set requires a new explicit declaration, retaining earlier
versions. A repeated unchanged attestation under a new key is refused rather
than counted as another independent review. A participant with no review rows
and who is not the conclusion author has nothing to attest and is refused.
The complete all-failure `stop` conclusion remains a valid documentary outcome;
no missing negative Tc values or structures are fabricated.

## Withdrawal, inspection and uncertain outcomes

`POST /review-attestations/withdraw` under the same `/v1/ml/pilots` prefix takes
the control fields above only, with an exact previous attestation. It derives
the original document basis from that record; no files or substitute basis can
be uploaded. Withdrawal remains available to the active bound account after
reviewer-role revocation or withdrawal from participation. It needs registration
and attestation flags, but not the source-intake flag. It still uses preview,
explicit consent/commit and exact-key recovery; it never deletes history.

`POST /review-attestations/inspect` takes exact participant and registration
references and returns only that account's head. It is explicitly historical
record inspection, not fresh collective readiness or document/rights validation.
The registrar and other participants cannot inspect or act as that account.

`POST /review-attestations/outcome` takes the original `request_key` and
`expected_intent_sha256`, under the original active account. It returns the exact
historical record without re-uploading documents or requiring a current reviewer
grant. A recovered attestation remains historical even after its withdrawal.
A missing receipt is not proof of rollback. If a response is lost or carries
`X-Operation-State: unknown`, perform read-only exact-key recovery; do not invent
a new key or automatically repeat a write.

## Storage and safety boundaries

`ml_pilot_review_attestations` retains opaque document and own-contribution
hashes, complete-log aggregate counts, the declared recommendation, original
participation binding, fixed declaration contract, exact predecessor/intent/key,
actor and server timestamp. It retains neither source-bearing originals nor
private review prose. Account references and hashes remain private audit data,
not anonymization. Preserve originals through separately approved storage.

SQL enforces append-only records, exact intent/basis hashes, restrictive account
and parent FKs, one unbranched predecessor chain per participant, current own
participation for new attestations, bounded shape/counts and at most 100 positive
attestations per participant. Protective withdrawal is not blocked by that
positive-write cap. Existing audit history blocks account erasure. Empty schema
downgrade is possible; any declaration history blocks destructive downgrade.
These database checks do not authenticate a privileged direct-SQL caller or
verify source text. The trusted HTTP session and complete verifier are required.

All responses remain private/no-store. `scientific_acceptance`,
`scientific_pilot_accepted`, `current_collective_signoff_verified`,
`source_permissions_verified`, `context_bytes_checked`, `canary_replay_verified`,
public release and run authorization remain false; training stays disabled.
`declaration_recorded` means the account's act is recorded, not that all of those
separate gates passed. The read-only joint coverage endpoint below reconciles
account declarations against one complete document basis. Scientific acceptance
still requires independent evidence/canary replay, human review and current
source permissions; no automatic approval consumer is added.

## English workbench workflow

1. Open **ML review declarations** in the private dashboard. Refreshing access
   reads the active account and exact versioned English wording, but grants no
   reviewer role. An unavailable feature/account is not an empty history.
2. Enter your participant UUID, participant record hash and registration record
   hash from approved private handoff or your participation binding. Inspect
   your own declaration history; its head is historical, not scientific approval
   or proof that a new declaration will be allowed.
3. For a new declaration, select **Declare my complete reviews**, enter a
   nonsensitive reason code and supply four complete originals (8 MiB each).
   Read them in your approved private review workflow; this page does not render
   or substitute a truncated source-text preview. **Check original review
   documents** uploads them for read-only preflight, not a recorded declaration.
4. Inspect the fixed candidate denominator, full-log record count, own count,
   conclusion-author status and exact file/contribution hashes. Counts include
   revisions and failures; they are not independent materials or scientific
   quality metrics. A zero-review conclusion author endorses the conclusion,
   without invented review contributions.
5. Read the entire pinned declaration text and explicitly check the initially
   unselected acknowledgement. Previewing rechecks the own predecessor and
   invokes the rollback-only declaration path. The displayed preflight basis
   must hash to the returned intent's basis. Changes invalidate the operation
   rather than silently rebasing it.
6. Review the complete intent and recovery references. A second, initially
   unselected confirmation unlocks **Commit exact review declaration**. Only
   explicit commit writes; the server re-verifies files, grants, participation
   and predecessor. Editing a file, reference, action, reason or consent
   invalidates the old preview.
7. For withdrawal, select **Withdraw my prior declaration** after inspecting its
   exact head. The stored basis is shown with action-specific consent. No source
   file or current reviewer grant is required for this protective operation.
8. For uncertain delivery, privately retain the original account/key/intent hash
   and use **Check original review outcome**. A missing receipt does not unlock
   a replacement write. After reloading, use manual recovery under the original
   account. A recovered record remains historical after later withdrawal.

Requests use the credentialed session, no-store and redirect refusal. Network
operations and original-file preparation are bounded and cancelable. There is
no automatic retry, source download, browser storage, background polling or
model call. Session changes discard visible private details and stale in-flight
results. An unresolved operation retains only opaque recovery references in
memory, hidden from a different account; navigating away warns while unresolved.

The browser hashes original bytes and reads existing logical-hash fields from
selection/conclusion files without reserializing the uploads. It does not claim
to reproduce the scientific accounting kernel. The server checks the complete
original log and documents independently for preflight, preview and commit.
Preflight explains scope; it is not an admission token or fresh-write substitute.

## Joint declaration coverage: one historical database snapshot

`POST /v1/ml/pilots/review-attestations/coverage` uses the same strict
`ml08-review-upload/1.0.0` four-original-file envelope and own-participant headers
as review preflight. All three default-off flags are required. It accepts no
declaration controls, acknowledgement, request key, cached preflight or recovered
receipt. The fixed route invokes the original-file worker; it does not let the
caller choose a write operation. It performs no database write or source storage.

The endpoint authenticates the exact own binding before reading private bytes
and after intake. After the worker finishes it checks a fresh read-only,
repeatable-read database snapshot, including session, registrar/reviewer grants,
the complete registered cohort, role bindings, declared review chronology and
participation intervals. All cohort participants must still have accepted
participation. If those checks fail, coverage is unavailable, not zero or complete.

Required declarations are precisely the union of accounts with review records
(including revisions/failures) and the actual conclusion author. A zero-review
conclusion author is required; a registered backup arbitrator with no reviews
and no conclusion authorship is not required to attest nonexistent work.

For each required account, the latest append-only declaration head is classified
into exactly one category:

- **Matching:** an attest action binds the exact current member and participation
  head, fixed declaration contract, all four raw file hashes, full-log/selection
  hashes, documentary projection, selected implementation, own contribution and
  conclusion-author basis.
- **Missing:** no declaration head exists.
- **Withdrawn:** the latest head withdraws the declaration. Recovering an older
  historical receipt cannot restore it.
- **Stale:** a valid recorded attest action no longer matches this exact basis,
  declaration contract/version or accepted participation head. A withdrawal and
  reacceptance of participation does not silently revive earlier declarations.

No other accounts, aliases, individual declaration IDs or private source prose
are returned. The response gives aggregate counts, the caller's own status,
whether the conclusion author's declaration matches, exact common document
hashes and the server transaction start time. Counts are disjoint and sum to the
required count. A coherent snapshot can immediately become outdated; it is not
a live subscription, write-admission token or lock on other reviewers.

In the English workbench, after checking the originals, use **Check joint
declaration coverage**. It reuploads the same originals for server verification,
clears old consent/preview and displays the snapshot separately from the signed
wording. It never checks either confirmation box. Editing inputs, changing
accounts, writing a declaration or a failed recheck removes the previous snapshot.
After committing or recovering a declaration, inspect and check the originals
again before requesting new coverage. No browser polling or persistence is used.

Even when `account_declarations_complete` is true,
`current_collective_signoff_verified`, `scientific_pilot_accepted`, source rights,
human independence, canary verification and ML/run authorization remain false.
The check does not prove that the pilot occurred or that scientific findings are
correct. The actual 60-event study and downstream acceptance gates remain open.

## Separate canary and context byte replay

The optional [evidence intake](ML_PILOT_EVIDENCE.md) uploads the four originals,
the exact canary v1.2 and the complete permitted-context inventory. It performs
actual bounded byte hashing and full reconstruction before requesting a fresh
joint account snapshot. Its separate default-off feature switch, binary wire
format and scoped proxy configuration are documented in that contract.

Only the outer byte-integrity scope reports canary/context checks as true. The
nested account-only coverage retains its original false byte-verification flags.
Neither scope verifies source rights, independent human review, scientific
findings or run authorization. It never creates a declaration or final approval.

A successful byte proof can also open the optional
[private field report](ML_PILOT_QUALITY_REPORT.md) from the same local canary and
conclusion. It preserves the original snapshot time, does not refresh collective
coverage, and does not select consent or apply recorded field recommendations.
