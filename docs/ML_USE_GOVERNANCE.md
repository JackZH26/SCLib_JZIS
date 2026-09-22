# Independent ML workflow membership

Implemented in batch54, 2026-09-12. Schema: `0071_ml_use_roles`.
Contracts: `ml-use-role-ledger/1.0.0`, `ml-use-role-intent/1.0.0`.
Related work: ML07 #68, ML06 #70 and ML09 #76. This foundation does not close
those issues or enable an actual research run.
Batch55 adds a separate [exact intake/preflight workflow](ML_USE_PREFLIGHT.md)
using these memberships. It does not add persisted requests or source/run grants.
Subsequent [private submissions](ML_USE_SUBMISSIONS.md) and the
[purpose-specific rights registry](ML_USE_RIGHTS.md) use these memberships with
their own exact admission and independence requirements. The membership-only
responses described here still never grant source access or execution.

## What a role means

This is an authenticated, append-only **membership registry**, not a training
license. Existing `curator`, `reviewer`, `publisher`, administrator or legacy
reviewer flags do not create ML memberships. Migration provisions no roles.

| Role | Intended future responsibility | Authority supplied by this implementation |
| --- | --- | --- |
| `requester` | Submit an exact dataset/task/run request | Membership only; no request/run execution route is introduced |
| `rights_reviewer` | Review purpose-specific source permissions | Membership only; no source-use decision is issued |
| `run_approver` | Approve a separately scoped execution request | Membership only; no execution grant is issued |

An active, email-verified site administrator can explicitly grant or revoke
these memberships. The administrator can also be a target; overlapping roles
are currently allowed. This does **not** prove separate independent reviewers,
human identity, competence, legal permission or separation of duties. Future
source/run decisions must enforce their own distinct-actor requirements.

Every response carries `scope: ml_workflow_membership_only`,
`training_execution: disabled`, false `data_access_granted`,
`source_permission_granted` and `run_authorization_granted`, plus the six
existing false scientific/release/training/reviewer/live-rights/external-
completeness authority flags. Membership does not unlock the raw research
routes. `run_baseline_dataset` continues to reject supplied datasets before
parsing or fitting with `ml_use_authorization_unavailable`.

## Deployment boundary

`ML_USE_GOVERNANCE_ENABLED` defaults to **false**. Disabled routes return private
404 responses. The flag is separate from `ML_FOUNDATION_PUBLIC_ENABLED` and
cannot enable model execution. This batch does not change any environment flag,
grant any real account a role, migrate production or expose a new admin UI.

Any later authorized rollout must apply the exact migration using the separate
migration credential before starting the matching application. Startup remains
read-only exact-head admission. Version 0071 is required even when this feature
is disabled; switching off a feature does not downgrade the schema.

## Authenticated API

All paths below are under `/v1/ml/use`. JWT or the existing browser session is
required. Browser-session writes retain the existing Origin/CSRF rules; an API
key alone cannot substitute for user authentication. Caller-supplied actor IDs,
approval flags, unknown fields and duplicate JSON keys are rejected.

| Method and path | Admission | Meaning |
| --- | --- | --- |
| `GET /access` | Current active, verified user | Own current roles and up to three chain heads; an empty role list is valid |
| `GET /roles/users/{user_id}` | Current active, verified administrator | One exact account's current membership, including inactive-account status |
| `POST /roles` | Current active, verified administrator | Rollback-only preview or exact pinned commit/replay |
| `GET /roles/outcome` | Current active, verified administrator | Recover only that actor's exact historical request using `request_key` and `expected_intent_sha256` |

Admin admission precedes mutation-body processing or another account's lookup.
Session version, activity, verification and admin status are rechecked inside
the database operation after body receipt. The mutation holds a shared actor
row lock until its transaction completes. There are no public role listings,
profile/email responses, bulk grants or account-search endpoints here.

### Preview and commit

First inspect the target's current head for the requested role. Supply both
its `id` and `record_sha256`; both must be null for the first grant. For example,
this illustrative preview uses a placeholder account UUID, not a real account:

```json
{
  "user_id": "00000000-0000-4000-8000-000000000001",
  "role": "requester",
  "action": "grant",
  "request_key": "study-a-requester-001",
  "reason_code": "assigned_study_requester",
  "expected_head_id": null,
  "expected_head_sha256": null,
  "dry_run": true
}
```

The preview executes the guarded insert and then rolls it back, including its
fence effects. It returns `result.intent` and `result.intent_sha256`, but no
durable decision ID. Review and independently retain that exact intent/hash.
Commit the **same** request with `dry_run: false` and
`expected_intent_sha256` set to the retained preview hash. The hash is not a
signature, proof of human inspection, or a server-retained preview receipt.

The intent binds the authenticated actor, target account, role, action, request
key, reason code and exact predecessor ID/hash. A stale head or edited pinned
intent returns 409. Changing the requested action needs a new preview and new
request key; silently accepting a freshly calculated replacement hash defeats
the intended human review step.

To revoke, reference the exact current grant. To regrant, reference the exact
current revocation. Consecutive grants or revocations are rejected. A revoked,
inactive or unverified target can still have its existing membership revoked;
new grants require the target to be active and verified.

`reason_code` is a bounded machine identifier, not a place for names, source
text or private narratives. Client request keys should not encode secrets.

### Durable outcome versus current membership

The outer HTTP response's `committed: true` means the decision is durably
recorded or an identical durable decision was recovered. Nested service
`result.committed` remains false because services never commit their caller's
transaction. `result.replayed` identifies a recovered existing operation.

On POST timeout or database/runtime failure, 503 may carry
`X-Operation-State: unknown`. A committed transaction can outlive its lost
response. Do not create a replacement request or assume failure. Query
`/roles/outcome` with the original request key and independently retained intent
hash, or retry the identical POST. A missing outcome means **not observed in
this snapshot**, not proven rollback. Recovery cannot cross actor ownership.

An old grant remains recoverable after revocation or regrant, but its replay
does not reactivate it or append another row. Use a fresh `/access` or exact
target inspection to learn current membership. Historical receipt hashes and
previously returned role lists must never authorize a later data operation.

Current membership requires an active, verified target and the latest matching
grant; an optional exact grant ID must match that head. Disabling or unverifying
an account suppresses its roles without deleting history. Re-enabling it makes
an unretracted grant effective again; use an explicit revocation for permanent
withdrawal. The original issuing administrator's later status does not itself
revoke membership. Future grant consumption must perform its own fresh checks
in the same appropriately isolated operation, not trust a cached HTTP read.

## Storage and transaction guarantees

`ml_use_role_decisions` contains `id`, `version`, `user_id`, `actor_user_id`,
`role`, `action`, `request_key`, `reason_code`, `supersedes_id`,
`record_sha256` and server-defaulted `created_at`.

There is one root per account/role, one successor per decision, and one request
key per actor. Each successor must match its predecessor's account/role, refer
to the current head and alternate grant/revoke. SQL checks independently
enforce the closed vocabulary, bounded ASCII keys, hashes, current declared
admin/target eligibility and finite timestamps. Python and PostgreSQL recompute
the same hash, including the decision ID and excluding only the hash/timestamp.
The timestamp is display metadata, not the hash's chronological authority.
Chain references, rather than timestamp sorting, determine currentness.

Mutation uses SERIALIZABLE isolation and the existing nonblocking publication
writer fence/epoch. Conflicting writers fail for fresh retry; identical request
replay is a SQL no-op. Reads use read-only REPEATABLE READ snapshots. SQL actor
checks validate a declared account, **not** the identity of an arbitrary SQL
caller; application authentication and a restricted runtime DB credential are
still essential. Database owners can alter triggers and are outside this
application threat model.

Update, delete and truncate are refused. Restrictive actor/target foreign keys
and account-deletion preflight preserve audit history even after revocation.
Account disablement remains possible; deleting an account that owns this history
requires a separately designed retention/anonymization process, not cascading
away the ledger.

The 0071 downgrade takes an exclusive table lock and refuses **any** retained
membership history. With an empty table it removes only its own table/functions;
previous data and frozen Discovery contracts are preserved. Do not bypass this
guard to roll back a populated production installation.

## Limits and remaining steps

Routes use private/no-store and nosniff responses with fixed English errors.
Per process there are two nonblocking request slots, a 15-second request
deadline, 5-second body deadline, 8 KiB body limit, 4,096 stream-part limit,
32 KiB response limit, and 3/5-second read/write SQL statement limits. Multiple
workers multiply the slot count; this is not a distributed quota or rate limit.
There is no provider, queue, training or source-body I/O in these endpoints.

The next implementation needs a separately versioned request/authorization
ledger binding the exact dataset, task, feature/label inputs, permitted purpose,
source dependency graph and reviewed rights scope. It must recheck current
recursive source permissions and exact active memberships at approval and use,
enforce separation of duties, support revocation/expiry and recover uncertain
outcomes without issuing new authority. An RPS metadata publication grant must
not be silently reused as a model-training license.

Only after those controls and an actually reviewed ML08 pilot exist can a
separately approved real-data baseline runner be considered. Prediction release,
active learning, external calculation and production rollout remain distinct
decisions. See [baseline preparation](ML_BASELINE_PREPARATION.md) for what
researchers can already prepare privately without fitting a prediction model.
