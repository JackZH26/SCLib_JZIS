# Private ML08 preregistration and participant confirmation

Implementation target: a prospective, immutable document commitment followed by
each bound account's own exact-document confirmation. This is not a completed
pilot, proof that people had not reviewed sources earlier, verification of a
source licence, or permission to train a model.

## Scientific and privacy contract

The registrar supplies the exact frozen selection and protocol bytes, their
independently retained raw SHA-256 values, the logical selection hash and a
complete mapping from every declared reviewer alias to a distinct SCLib account
and its explicit research-reviewer grant. The existing ML08 accounting kernel
must accept the full 60-candidate documentary selection with an empty review
log. Failures, families, evidence strata and the second-review subset are bound
through that exact selection; no candidate is silently substituted.

An administrator with an explicit curator grant may propose registration.
Every participant needs an active, verified account and a current explicit
reviewer grant, not an inferred legacy role. Different aliases must bind to
different accounts. This proves account separation, not that two accounts belong
to different people or that their assessments are scientifically independent.

The registry retains opaque document/alias hashes, role/account bindings,
implementation pins, idempotency keys and server timestamps. It does not retain
the source-bearing selection/protocol bytes, reviewer names or evidence text.
The operator must retain original files in approved storage. A missing original
cannot be reconstructed from its hash or replaced with a self-consistent new file.
The registry grants no new access to those files.

Each participant confirms the same original bytes using their own authenticated
session. The registrar cannot confirm for another account. Acceptance records
agreement to the exact protocol and role, not completion or correctness of any
review. Decline and withdrawal remain possible without an active reviewer grant;
new acceptance requires the originally bound grant still to be current. A later
grant cannot silently rewrite the immutable roster. New registration is needed
for a revised cohort/roster and must not erase the earlier commitment.

Readiness is computed from every current participant decision, the current
account/grant state and the registration's document-check policy version. It never sets scientific-pilot acceptance, validates source
rights, approves public release, clears ML09 blockers or starts training.
Server timestamps establish when this service recorded the commitment/decision,
not when any external reading, selection or scientific work actually occurred.

## Declared chronology and verifier compatibility

Document checks now use `ml08-registration-documents/1.1.0`. The upload envelope
and immutable ledger versions remain 1.0.0; the database schema stays 0076.
The verifier derives normalized UTC `selected_at` and `frozen_at` instants from
the exact hashed selection. Before either preview or new registration writes,
the service requires `selected_at <= frozen_at <= clock_timestamp()` in its
actual database transaction. It does not substitute the browser clock or the
transaction-start timestamp. New acceptance rechecks those same document
instants against both the original database registration timestamp and the
current database clock. An equivalent timezone representation is allowed in
the source file; the original file bytes and hash are still preserved exactly.

These are consistency checks of **declared** times. They cannot prove that the
researchers had not already read sources, that the 60 events actually exist, or
that the reported selection/freeze dates are truthful. Direct privileged SQL
still cannot verify unseen source documents; the trusted authenticated service
is the document-check boundary, not the append-only SQL trigger by itself.

Inspection exposes `registration_document_check_version` and
`current_registration_document_policy`. Historical 1.0.0 registrations remain
readable/recoverable but do not become current or review-ready merely because
the application was upgraded. New acceptance under an obsolete registration
policy is refused; protective decline/withdrawal is retained. Do not edit a
historical record, reseal an old receipt, or replace candidates to circumvent
this restriction. Any future legacy-registration transition needs an explicit
reviewed compatibility path; no automatic transition is implemented here.

The selected implementation inventory now includes the actual shared child
I/O/cleanup helper. It is still an installed-source subset, not an OS sandbox
or complete runtime attestation. The separately installed-wheel probe runs both
real worker operations without API/ORM dependencies; it does not register
accounts or check a database clock.

## Private API workflow

The implementation is separately default-off under
`ML_PILOT_REGISTRATION_ENABLED`. All routes below start with `/v1/ml/pilots`,
require JWT authentication, and return private/no-store responses. The feature
flag does not waive exact-head schema admission. An English participant
workbench is available at `/dashboard/research/ml-pilots`; the registrar's
creation workflow remains API-only. This contract is not permission to enable
the feature in production.

| Route | Purpose |
| --- | --- |
| `GET /participant-access` | Check the active authenticated account without granting or requiring a reviewer role; exact invitation ownership is checked separately |
| `GET /registrar-access` | Check the current administrator and explicit curator admission |
| `POST /registrations` | Validate exact uploaded files, preview and explicitly commit the complete account roster |
| `POST /participation/accept` | The bound account validates the same files and records its own protocol/role acceptance |
| `POST /participation/decisions` | The bound account previews/records a decline or withdraws its current acceptance |
| `POST /review-preflight` | API-only full review-document/account check; also requires default-off `ML_PILOT_REVIEW_INTAKE_ENABLED`; no signature or write |
| `POST /inspect` | Owner or participant inspects the committed registration and current account-participation readiness |
| `POST /registrations/outcome` | Registrar recovers an exact historical registration by original key and intent hash |
| `POST /participation/outcome` | Participant recovers its own exact historical decision, without re-uploading source files |

Registration uploads use `ml08-registration-upload/1.0.0`, operation `register`,
canonical base64 `selection_base64`/`protocol_base64`, independently retained
`selection_file_sha256`/`protocol_file_sha256` and logical `selection_sha256`.
`bindings` maps each exact `reviewer_alias` to `user_id` and
`reviewer_grant_id`. `parameters` contains `curator_grant_id`, a caller-retained
`request_key`, and defaults to `dry_run: true`. A successful preview supplies
the `intent_sha256`; committing requires that exact value in
`expected_intent_sha256` and an explicit `dry_run: false`. Do not create a new
key to recover an uncertain commit.

Acceptance uploads use operation `accept`, the same file fields, no `bindings`,
and the returned participant/registration identifiers and record hashes in
`parameters`. The request must also supply matching
`X-SCLib-Participant-Id`/`X-SCLib-Participant-Sha256` headers so ownership can be
checked before receiving source bytes. Each decision supplies a reason code
and the exact current predecessor ID/hash, or nulls for the first decision.
Decline/withdraw uses the small decision endpoint without uploaded files. It
remains possible after the original reviewer grant is revoked, provided the
account itself is still active and authenticated.

Responses marked `X-Operation-State: unknown` require read-only original-key
recovery; they are not proof of rollback. Historical acceptance recovery is not
a fresh readiness observation. The owner can inspect all pseudonymous account
bindings; a participant receives only its own binding/decision and redacted
registration metadata. Hashes and account identifiers remain private audit data,
not anonymized public data. Original files and invitation references must be
handed to the intended participants through separately approved channels.

## Participant web workflow

1. Open **Dashboard → ML pilot participation** and refresh account access.
   Paste the registration UUID and record SHA-256 received through the approved
   private handoff. References are not placed in URLs or browser storage.
2. Inspect the current snapshot. Participants see only their own binding and
   decision; the admitted registrar sees the full roster but cannot act for
   someone else. Counts describe account participation, not independent people,
   successful reviews, scientific replication or field recoverability.
3. Explicitly choose accept, decline or withdrawal and a nonsensitive reason
   code. New acceptance requires the current bound roles and document policy.
   Upload the original selection and protocol files, each no larger than 8 MiB;
   their raw hashes must match the registered pins before the browser sends
   them. The server independently checks the exact documents and logical hash.
   A file recreated from its parsed JSON is not necessarily the original file.
4. Review the exact role, predecessor and decision and request a rollback-only
   preview. The browser obtains fresh admission and re-inspects the invitation;
   a changed predecessor or role state invalidates consent and requires review
   again. Preview does not commit a new decision. Explicit commit sends the
   original preview input, key and intent hash. The server remains authoritative
   for concurrency, account/grant validity and document chronology.
5. If a commit response is lost or unverifiable, retain the original account,
   request key and intent SHA-256 privately. Use **Check original outcome**;
   no replacement key or automatic write retry is sent. A 404 snapshot is not
   proof of rollback and does not unlock another write. After reloading, manual
   historical recovery uses those same references, without documents or a
   current reviewer grant. Contact the operator if the exact outcome remains
   unresolved; do not guess a new key to bypass the uncertainty.

Session changes and explicit refresh clear the displayed invitation, consent,
files and prepared preview. Late replies cannot restore cleared state.
Unresolved recovery references survive only in page memory and are displayed
again only after admission under the original account; they do not survive a
page reload. The page warns on browser unload while an outcome is unresolved.
Decline and withdrawal do not upload files; withdrawal requires a current
acceptance. Active account admission remains mandatory after reviewer-role
revocation. Historical acceptance recovery never sets current readiness.

The browser checks closed response shapes, declared non-authority flags,
canonical hashes and visible record relationships. A participant's redacted
projection cannot independently reconstruct the hidden full registration or
other accounts' heads; these remain authenticated server observations. Hashes
are consistency checks, not third-party signatures or permission certificates.

## Implementation and verification boundaries

- Add registration, participant and participant-decision ledgers, restrictive
  identity FKs, append-only guards, exact predecessor/idempotency checks,
  bounded capacities, atomic roster completion and downgrade refusal on history.
- Provide separately default-off private preview/commit, own-participation,
  inspection and exact original-key recovery endpoints. Recheck session and
  current membership after uploads and before committing; uncertain outcomes
  require read-only recovery, never a new automatic request key.
- Authenticate before reading bounded upload bodies. Reject duplicates, invalid
  JSON/base64, mismatched anchors, roster omissions, alias/account duplication,
  cross-account decisions and unsupported positive authority declarations.
- Exercise actual PostgreSQL/HTTP preview rollback, outer rollback, commit,
  replay, stale-head and concurrent writes, role/session revocation, unknown
  outcomes, audit retention and empty/populated migration boundaries using only
  the guarded disposable runner. Synthetic fixtures never count as the real
  ML08 study.

The ledger/service/HTTP implementation is present; the bullet list above is the
full verification target, not a claim that every case has passed. Actual migration
and regression evidence, including remaining adversarial/UI gates, is tracked
in the [batch68 report](reviews/2026-09-05/Priority_Sixty_Eighth_Batch_Implementation_2026-09-13.md).
The subsequent chronology, worker, installed-wheel and actual write-collision
checks are recorded in the [batch69 report](reviews/2026-09-05/Priority_Sixty_Ninth_Batch_Implementation_2026-09-13.md).
The participant workbench, native account-only admission and browser recovery
verification are recorded in the [batch70 report](reviews/2026-09-05/Priority_Seventieth_Batch_Implementation_2026-09-13.md).

The subsequent [review-document preflight](ML_PILOT_REVIEW_PREFLIGHT.md) binds
all four originals and every declared review time to this registration and the
recorded participation history. It is separately default-off and read-only;
participation and documentary consistency still do not constitute an
authenticated scientific signoff. Its verification is recorded in the
[batch71 report](reviews/2026-09-05/Priority_Seventy_First_Batch_Implementation_2026-09-13.md).
