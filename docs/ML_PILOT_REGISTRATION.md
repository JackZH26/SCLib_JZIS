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

Readiness is computed from every current participant decision and the current
account/grant state. It never sets scientific-pilot acceptance, validates source
rights, approves public release, clears ML09 blockers or starts training.
Server timestamps establish when this service recorded the commitment/decision,
not when any external reading, selection or scientific work actually occurred.

## Planned implementation and verification

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

This document records the implementation contract, not a claim that its planned
checks have passed. Batch68 will record actual verification and remaining gates.
