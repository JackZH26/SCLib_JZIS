# Private ML08 review-document preflight

This read-only prerequisite binds four complete original documents to an
existing prospective registration and its authenticated account roster. It
does not record an attestation, endorse a conclusion, verify source licences,
replay a canary, release data or authorize training. No schema migration or
new signature ledger is introduced.

## Admission and transport

`POST /v1/ml/pilots/review-preflight` requires **both**
`ML_PILOT_REGISTRATION_ENABLED` and `ML_PILOT_REVIEW_INTAKE_ENABLED`.
Both default to false. This contract does not authorize enabling either flag.
The English [own-review workbench](ML_PILOT_ATTESTATIONS.md) at
`/dashboard/research/ml-pilot-reviews` uses this endpoint to display exact
account/document scope before declaration consent. The separate participation
workbench handles protocol participation. Preflight remains read-only and is
never accepted by the declaration write endpoint as a reusable approval token.
The separate `/review-attestations/coverage` endpoint reruns the original-file
worker and checks the latest required account declarations in one read-only
snapshot; it does not accept this preflight response as a substitute for originals.

Use the intended participant's authenticated session and exactly one of each
`X-SCLib-Participant-Id` and `X-SCLib-Participant-Sha256` header. The server
checks ownership and current account/role admission before reading source
bytes, after receiving the upload, and again after document verification.
The registrar cannot substitute its own session for a participant's.

The JSON body is a closed object with these fields:

| Fields | Meaning |
| --- | --- |
| `version` | Exactly `ml08-review-upload/1.0.0` |
| `parameters` | Exactly `participant_id`, `participant_sha256`, `registration_sha256`; participant references must match the headers |
| `selection_base64`, `protocol_base64`, `reviews_base64`, `conclusion_base64` | Canonical base64 of the four original byte streams, not reserialized substitutes |
| `selection_file_sha256`, `protocol_file_sha256`, `reviews_file_sha256`, `conclusion_file_sha256` | Independently retained SHA-256 of each complete original file |
| `selection_sha256`, `review_log_sha256` | Existing scientific accounting kernel's logical hashes |

All four files are required and each is bounded to 8 MiB. The envelope limit
is 44,804,784 bytes (four maximum-sized base64 strings plus 65,536 bytes of
metadata allowance); it is not a scientific sample-size limit. Uploads have a
10-second stream deadline and a 4,096-chunk cap. Unsupported content types,
invalid UTF-8/JSON/base64, duplicate keys, extra fields, mismatched hashes and
oversized inputs fail closed. No input is truncated. Responses are private,
no-store and bounded to 128 KiB; errors do not echo private document content.

There is no `dry_run`, request key or commit operation. This endpoint performs
only reads, so it does not issue an unknown-commit marker or a recovery token.
Repeating a preflight obtains a new current observation, not a signature.

## Full scientific document accounting

The installed shared accounting kernel checks the fixed 60-candidate selection,
all review revisions and the submitted conclusion. It preserves inaccessible,
unresolved and failed cases in the denominator. The declared second-review
subset, comparisons and required arbitration cannot be removed to obtain a
passing preflight. Unknown pressure is not ambient pressure; failed extraction
does not create a negative superconductivity label or `Tc = 0`.

A complete documentary `stop` conclusion is valid. Passing this check means
the documents satisfy the existing accounting rules, not that a `go` decision
is correct or that these 60 events suffice for a model. The response's
`recorded_recommendation` is the uploaded declaration, not a server endorsement.

The document worker runs as one owned isolated-interpreter child with no
inherited application credentials. It has bounded input/output, a 35-second
wall deadline and a 25-second CPU limit; cancellation and failure reap the
child. Linux also applies an address-space bound. Its selected-source inventory
is not an OS sandbox or complete runtime/image attestation.

## Database binding and time semantics

The server independently checks all of the following in a fresh read-only
database snapshot:

1. Exact selection/protocol byte pins and logical selection match the immutable
   registration, using the current registration document policy.
2. Every declared alias and role maps to the original registered account;
   the registrar and all bound account grants remain current. A new grant
   does not silently replace an original roster binding.
3. Every participant's decision chain is intact and its current head accepts
   participation. The bounded combined history retains intermediate withdrawals
   and reacceptances rather than looking only at today's head.
4. Every **declared** review completion time is no earlier than registration,
   no later than the database clock, and inside that reviewer's recorded
   accepted-participation interval. The conclusion author must also have been
   participating at the declared conclusion time.

An old review declared inside an earlier valid acceptance interval remains
eligible after later withdrawal and reacceptance. A review declared during a
withdrawal gap is refused even if the participant currently accepts. These
checks do not prove that external reading actually occurred at the supplied
time, or that distinct accounts correspond to independent humans.

## Privacy, non-authority and remaining gates

Each caller receives only its own participant/account references and opaque
contribution count/hash, plus document, projection and implementation hashes
and aggregate counts. Other accounts, reviewer aliases, individual review
timestamps and source prose are not returned. Hashes remain private audit data,
not anonymization or external signatures. Original source-bearing files are
not retained by this endpoint; retain them only in separately approved storage.

The response explicitly keeps `attestation_recorded`, `context_bytes_checked`,
`canary_replay_verified`, `conclusion_endorsed`, scientific acceptance, source
permission, public release and run authorization false; training stays disabled.
The supplied canary hash is a declaration only. A successful preflight is not
a reusable admission token: future signed writes must recheck exact documents,
current accounts, predecessor state, rights and implementation policy.

The subsequent [own-account declaration API](ML_PILOT_ATTESTATIONS.md) now
records exact original-document declarations and withdrawals in schema 0077.
It does not turn this preflight result into a reusable token. Still required:
the human signoff interface and current collective acceptance; binding and
replay of actual evidence/canary bytes;
current source-access decisions; and the real 60-event pilot with retained
failures, missingness, curation effort and a reviewed go/narrow/stop conclusion.
ML09 execution and AL01 validation remain separate gates. Synthetic tests do
not satisfy those research requirements.

See [registration](ML_PILOT_REGISTRATION.md),
[document intake](ML_PILOT_DOCUMENT_INTAKE.md),
[canary replay](ML_PILOT_CANARY.md) and
[batch71 verification](reviews/2026-09-05/Priority_Seventy_First_Batch_Implementation_2026-09-13.md).
