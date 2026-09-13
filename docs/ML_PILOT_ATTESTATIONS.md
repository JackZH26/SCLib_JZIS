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
or migrating a shared database. The current implementation is API-only; the
English participation workbench does not yet provide a scientific-signoff form.

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
separate gates passed. Current scientific acceptance must eventually reconcile
every required reviewer and exact latest document version with independent
evidence/canary replay and current permissions; no automatic consumer is added.
