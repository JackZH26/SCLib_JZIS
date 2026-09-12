# Exact ML-use intake and online dependency preflight

Batch55, 2026-09-12. Contracts: `ml-use-request/1.0.0` and
`ml-use-preflight/1.0.0`. No new database migration; schema remains 0071.

Batch56 adds a separate [full-input reconstruction endpoint](ML_USE_RECONSTRUCTION.md)
and private upload-package CLI. The descriptor-only endpoint documented below
retains its limited scope and original response semantics.

## Delivered scope

The private [baseline preparation](ML_BASELINE_PREPARATION.md) can now be
connected to an explicit use-purpose declaration and a live registered-input
inspection. This increment deliberately separates three facts:

1. The local CLI replays the actual eight independently pinned input files
   before writing an intake declaration.
2. The authenticated API observes the registered frozen capsule and current
   dependency graph in one bounded read-only database snapshot.
3. Neither operation issues a purpose-specific source licence or execution
   approval. The request is **not persisted or submitted to an approval queue**.

The sole v1 purpose is `private_baseline_evaluation`. It describes a proposed
private predictive fitting/evaluation study, not permission to perform it.
Public predictions, source redistribution, external providers, active learning
and paid calculations require separate future contracts; there is no broad
`research` purpose that implicitly authorizes all of them.

## Private request preparation

Run `scripts/ml_use_request.py prepare` only with inputs whose local access and
processing are already authorized. It verifies the complete existing baseline
preparation against the original artifacts and inputs. It does not fit a model,
connect to a database or submit an HTTP request.

Eight canonical whole-file SHA-256 pins are required:

| Input flag | Meaning |
| --- | --- |
| `--manifest` | Exact frozen research capsule, with its closed adjacent artifact inventory |
| `--task` | v4 dataset task, including target, feature and split declarations |
| `--companion` | Exact feature-source companion |
| `--review-companion` | Scientific review observation companion |
| `--label-companion` | Label/currentness observation companion |
| `--package` | Identity-audited dataset package |
| `--config` | Exact baseline configuration |
| `--preparation` | Independently retained baseline preparation receipt |

Each flag has a required matching `--NAME-sha256`. For example, use the exact
same original files as baseline preparation, add the preparation receipt, and
choose a new private output path:

```bash
api/.venv/bin/python scripts/ml_use_request.py prepare \
  --manifest /private/study/capsule/manifest.json --manifest-sha256 MANIFEST_SHA \
  --task /private/study/task.json --task-sha256 TASK_SHA \
  --companion /private/study/source.json --companion-sha256 SOURCE_SHA \
  --review-companion /private/study/reviews.json --review-companion-sha256 REVIEWS_SHA \
  --label-companion /private/study/labels.json --label-companion-sha256 LABELS_SHA \
  --package /private/study/audited.json --package-sha256 DATASET_SHA \
  --config /private/study/config.json --config-sha256 CONFIG_SHA \
  --preparation /private/study/preparation.json --preparation-sha256 PREPARATION_SHA \
  --output /private/study/ml-use-request.json
```

These are illustrative paths and digest placeholders, not real permissions or
existing study files. For later verification, repeat all eight input/path pairs,
change the mode to `verify`, omit `--output`, and supply `--request` plus the
independently retained `--request-sha256`.

The CLI reuses the full baseline replay, checks the input bytes and identities
again, rejects aliases/substitutions, checks its own implementation stability,
and uses the existing private `0600`, no-clobber writer outside the capsule.
A failed or no-go baseline cannot emit an intake declaration. A resealed
declaration cannot replace reconstruction from the original files. The command
does not accept `--approved`, an actor ID, free-form source overrides or a
training switch.

The resulting request contains only:

- Contract version and the single explicit purpose.
- Dataset and base-release IDs.
- Eight independent input pins.
- Sorted, unique, exact registered feature-binding IDs and record hashes.

No labels, feature matrices, source text, URLs, file paths or role assertions are
copied to the request. Its IDs/hashes remain private metadata; do not publish it
without separate review. Printed verification booleans are local diagnostics,
not signatures or evidence that another party ran this exact CLI.

## Online API

The existing `ML_USE_GOVERNANCE_ENABLED=false` switch covers these routes. This
batch does not enable it in any environment or provision real roles.

| Endpoint | Operation |
| --- | --- |
| `GET /v1/ml/use/preflight/access` | Check the current private-inspection admission and return exact curator/requester grant IDs |
| `POST /v1/ml/use/preflight` | Inspect one exact independently pinned request; read-only, with no stored request or approval |

Admission requires an active, verified **administrator AND explicit curator
AND explicit ML requester**. This preserves the existing strong private ML
audit-export policy until dataset-scoped access controls exist. It is an interim
operator boundary, not a claim that all researchers should be administrators.
ML membership alone cannot reveal another account's data inventory. Future
dataset ACLs should narrow this requirement without widening source access.

The POST body is a closed envelope:

```json
{
  "request": {"...": "the complete unmodified ml-use-request/1.0.0 object"},
  "expected_request_sha256": "independently_retained_request_hash",
  "expected_requester_grant_id": "exact_current_ml_requester_grant_uuid",
  "expected_curator_grant_id": "exact_current_curator_grant_uuid"
}
```

The example is schematic and intentionally not executable. Use the actual
generated object and canonical hash, not an edited or automatically rehashed
replacement. Authenticate through the existing JWT/browser-session boundary;
API keys do not replace a user session. Browser-session POSTs retain Origin/CSRF
validation. Admission occurs before private body processing, then session,
account and both exact role grants are rechecked in the final SQL snapshot.

## What the online inspection actually verifies

The API checks the request hash and closed vocabulary, exact dataset/release
identity, stored capsule manifest/pin/bundle integrity and absence of a release
notice. It reads **all** current registered feature bindings for that release
and compares their IDs/hashes with the declaration. Added, omitted, stale or
foreign bindings reject the request rather than shrink the source inventory.

All frozen rows are conservative roots, including unused examples, policy and
review artifacts. Additional roots come only from actual registered feature
bindings. The server recursively follows the schema's foreign-key paths and
discovers owned children from SQL, including label source occurrences, accepted
paper/Work mappings and capture siblings. It never accepts a user-selected
source list as complete. The declared policy is deliberately a whole-capsule
superset, not a minimal selected-feature licence inventory.

The response reports sorted dependency IDs and actual current row hashes,
their frozen hashes where applicable, changed-row flags, exact feature-binding
pins and a requirement-list hash. It contains no raw row bodies or source bytes.
Current catalogue, source-lifecycle, ancestry and scientific-review holds use
the existing conservative site checks. A `held_or_unavailable` result is not a
diagnosis that every source is scientifically invalid; it means the aggregate
negative gate did not establish an absence of holds. Even `no_hold_observed`
does not mean scientifically accepted or licensed.

`registered_dependency_inventory_checked: true` has the explicitly limited
scope `registered_capsule_and_feature_binding_dependencies_only`. External
dependencies missing from SCLib and companion-only audit artifacts outside
those roots are not thereby proven complete. The private task, companions,
audited package, configuration and preparation bytes are **not uploaded or
rebuilt online**. Accordingly, `online_private_input_reconstruction_verified`
stays false, even when the preceding local CLI succeeded. Arbitrary replacement
digests cannot earn authorization merely by passing this inspection.

The purpose-permission registry and independent run decisions are not yet
implemented. Every requirement reports `purpose_permission_status:
not_available`, `permission_granted: false`; the aggregate decision is always
`not_authorized`. Existing publication permissions, open-access indicators,
licence strings, a clean lifecycle or scientific acceptance are never converted
to a model-training licence. All existing scientific/release/training/reviewer/
live-rights/external-completeness flags remain false.

## Snapshot, limits and failure semantics

The API uses read-only REPEATABLE READ, 5-second SQL statement limits, a
20-second whole-request deadline, a 5-second body deadline and two nonblocking
slots per process. Requests are bounded to 96 KiB plus a 2 KiB envelope and
4,096 stream parts; duplicates/nonfinite JSON/unknown fields fail closed.
There are at most 500 registered feature bindings and 1,000 dependency rows;
source-row hydration is preflighted using the existing 8 MiB closure byte budget,
with a separate 2 MiB binding budget and bounded catalogue-ancestry inspection.
Responses are at most 512 KiB. These are per-operation bounds, not distributed
rate limits or measured production capacity.

Responses are private/no-store and nosniff with fixed English errors. Missing or
malformed input is not an empty successful inventory. Hash/grant/registration
changes require a fresh inspection; body/DB/runtime failures grant no authority.
POST is read-only: there is no hidden mutation, idempotency ledger or uncertain
commit to recover. Repeat it after an interruption with the same request pins.

`observed_at` identifies the transaction time, not an expiry or a durable
permission. A later source change, role revocation or logout invalidates any
assumption based on an earlier result. A future approval/runner must perform
fresh checks as part of its own appropriately isolated admission.

## Next implementation boundary

Before genuine ML use, implement private artifact intake/reconstruction for all
eight exact inputs, a persisted request with a versioned complete dependency
inventory, purpose-specific reviewed source decisions and revocation/expiry,
separate authenticated rights reviewers/run approvers, then final currentness
checks when an exact run is consumed. Reuse this descriptor as intake, not as an
approved grant. The actual reviewed ML08 pilot, scientific target/protocol
approval and prediction-release decisions remain separate.

This batch changes no frozen dataset/companion versions, membership schema,
stored material fields, existing RPS scores or training entry points. There is
no new admin UI, real source review, model fit, external calculation or deployment.
