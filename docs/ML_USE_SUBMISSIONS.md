# Private ML submission and input retention

Batch58; `ml-use-submission/1.0.0`, schema `0072_ml_use_submissions`.
This workflow retains an exact research request for later independent review.
It does not grant source-use permission, authenticate historical capture acts,
approve science, authorize fitting, publish predictions or start a calculation.
The existing `ML_USE_GOVERNANCE_ENABLED` flag remains **off by default**.

## What is stored

| Table | Contents | Lifecycle |
| --- | --- | --- |
| `ml_use_submissions` | Exact declaration, typed dependency inventory inside the original inspection, input hashes, authenticated requester/grant identities, idempotency intent, record hash and server timestamps | Immutable private audit metadata; no public collection or download |
| `ml_use_private_inputs` | The original canonical upload, including all eight pinned files and capsule artifacts | At most seven days of application access; separately purgeable |
| `ml_use_input_purges` | Request identity, authenticated administrator, owner-request/expiry reason and timestamp | Immutable receipt; insertion atomically removes that request's input row |

Metadata includes scientific identifiers, reviewer identifiers and hashes and
must remain private. It excludes source text and feature/label matrices, but
is not anonymous. The input blob does contain private scientific/audit bytes;
base64 and content hashes are **not encryption**. There is no raw-input HTTP
download and no anonymous or cross-owner submission lookup.

`private-ml-input-seven-days/1.0.0` is a concrete technical policy: acknowledge
seven-day input access, owner-requested earlier removal, and retained private
audit metadata with no automatic metadata-erasure endpoint. A deployment owner
must approve the applicable retention/access policy and permitted transfers
before enabling this feature. Sending the policy token does not prove legal
permission to upload, retain or train on the underlying material.

Production operators must separately control PostgreSQL access, encryption,
WAL/backups, logs, replicas and backup expiry. Deleting a payload row does not
prove secure media erasure or deletion from backups. The account-erasure guard
preserves referenced audit identities pending a reviewed retention or
de-identification workflow; it is not a legal retention determination.

## Exact preview and submission

First obtain the actual upload from [input reconstruction](ML_USE_RECONSTRUCTION.md)
and the dependency inventory hash from [current inspection](ML_USE_CURRENTNESS.md).
Keep the original upload bytes unchanged. For both operations below supply:

- `Idempotency-Key`: one new owner-scoped key, retained for recovery.
- `X-SCLib-Envelope-Sha256`: independently retained SHA-256 of the upload bytes.
- `X-SCLib-Inventory-Sha256`: exact inventory hash from the full current inspection.
- `X-SCLib-Retention-Policy`: `private-ml-input-seven-days/1.0.0`.
- `Content-Type: application/json`: the body is the original reconstruction upload.

1. `POST /v1/ml/use/requests/preview` actually reconstructs and rechecks all inputs,
   compares the expected inventory, and returns the exact intent plus its hash.
   It persists nothing. Review the requested retention policy and exact pins.
2. `POST /v1/ml/use/requests` uses the same body/headers and additionally requires
   `X-SCLib-Intent-Sha256` from that preview. The first submission runs the actual
   server worker and full SQL inspection again, then writes the private request
   and input atomically. Do not construct or upload a replacement worker report.

The closed intent binds its version, owner-scoped request key, envelope hash,
inventory hash and retention policy. Account identity comes from authentication,
not from the intent. Reusing a key with different pins is a conflict. Concurrent
writers use SERIALIZABLE transactions and the shared publication writer guard;
conflicts fail rather than generating a second durable request.

All operations require current verified active admin + explicit curator + ML
requester admission, and submission additionally rechecks both exact input grant
IDs. Browser sessions retain Origin/CSRF checks; API keys do not substitute for
authenticated users. Role checks precede upload processing and are repeated
after CPU work. The write transaction rechecks and locks the authenticated
account/session before committing. Membership is still not data-use permission.

## Recovery, history and reinspection

The following owner-scoped endpoints take only this closed JSON body:

```json
{
  "request_key": "your-original-owner-scoped-key",
  "expected_intent_sha256": "your-independently-retained-intent-hash"
}
```

The hash above is a placeholder, not an executable request.

| Endpoint | Meaning |
| --- | --- |
| `POST /v1/ml/use/requests/outcome` | Recover the exact durable historical receipt; does not claim current source validity |
| `POST /v1/ml/use/requests/recheck` | Internally retrieve the unexpired owned bytes, run the actual reconstruction worker, then inspect a fresh SQL snapshot; no raw-byte download or overwrite of historical evidence |
| `POST /v1/ml/use/requests/purge` | Atomically remove the owned input blob and append a purge receipt; repeated requests preserve the original receipt |

If a commit response is lost, recover with the same key and expected intent
hash. `503` with `X-Operation-State: unknown` means the commit may have happened;
do not infer rollback or switch to a new key. A not-observed outcome is only a
statement about that lookup snapshot. Retry after the original operation has
finished. Replaying an exact stored submission returns the original receipt
without rerunning the compiler, renewing expiry, replacing its observation or
recreating purged bytes. A fresh study requires a new explicit request.

History can remain readable after a source retraction while `recheck` fails.
That is deliberate: the stored inspection describes the **pre-submission SQL
snapshot**, not necessarily source state at the later commit. Its original
`observed_at` and all original fields are retained unchanged under
`stored_observation`; top-level `currentness_checked_now` is false. Source
changes between inspection and storage do not transform this historical record
into a current authorization. Review/approval/consumption must independently
check current sources and exact permissions under their own concurrency gates.

Reinspection checks retention and admission again after the worker. Expiry or
purging during reconstruction cannot cause a successful final recheck. Its
response is the original current-inspection contract, not a persisted new review.

## Retention and bounded operation

Input expiry is assigned by PostgreSQL as server creation time plus seven days.
No update, replay or client timestamp can extend it. Reads use the current
database clock, not merely a transaction's older start time. Expired bytes are
unavailable even if a cleanup operation has not physically deleted them yet.

`POST /v1/ml/use/requests/purge-expired` is a bodyless, administrator-only
maintenance operation, removing at most 20 expired input rows per transaction.
It returns counts, not another owner's IDs or bytes. It is idempotent and never
purges an unexpired input. This increment supplies the maintenance endpoint,
**not a scheduled production cleanup job**; operators must arrange cleanup
and separately govern backup expiry before enabling retention in production.

Initial hard limits are 100 immutable requests per owner, 1,000 globally,
64 MiB of retained input per owner and 256 MiB globally. All retained blobs,
including expired-but-not-yet-purged rows, count toward storage limits. Cleanup
does not reset immutable metadata quotas. These are conservative admission
ceilings, not measurements of production capacity or permanent scale targets.

The existing upload/worker limits remain 32 MiB wire, 24 MiB decoded inputs,
16 MiB per file, 256 artifacts, 45-second worker wall time and bounded CPU/output.
Submission/recheck handlers have a 100-second outer deadline and share the two
nonblocking per-process private-inspection slots. Currentness retains its
30-second phase and existing full-audit bounds. Lookup bodies are at most 4 KiB;
responses at most 1,100 KiB. Maintenance body reads have five seconds. Database
statements have five seconds. There is no claim of a distributed rate limit or
an OS security sandbox.

## Schema and rollout boundaries

0072 is additive and provisions neither users nor roles. The normal migration
authority is separate from startup, and startup requires the new exact head.
An empty 0072 downgrade can remove only its three empty tables/functions.
Any retained request or purge audit history refuses downgrade, even after all
input blobs are gone. Back up and review retention before an approved rollout;
do not disable triggers to force a rollback.

SQL enforces declared active accounts/exact grants, immutable request and purge
rows, exact record/content pins, payload hashes, atomic input completeness,
purge authorization and storage bounds. It does not authenticate a SQL caller,
run the Python compiler or prove a legal licence. HTTP accepts no client-supplied
inspection; the trusted service receives the actual server-produced observation.
All scientific/public/source/run authority remains false.

The subsequent [independent rights registry](ML_USE_RIGHTS.md) adds per-resource,
purpose-specific decisions and fresh owner coverage under schema 0073. This
0072 submission contract itself is unchanged. Exact run approval/consumption
and a genuinely reviewed ML08 pilot remain separate required steps.
No real data submission, production migration, cleanup scheduling, model fitting,
source redistribution, remote issue closure or deployment is performed here.
