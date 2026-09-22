# Private ML-use input reconstruction

Contract `ml-use-reconstruction/1.0.0`, batch56. The existing descriptor-only
[preflight](ML_USE_PREFLIGHT.md) remains unchanged at its original endpoint.
The new endpoint additionally receives and reconstructs the actual private
inputs. Neither endpoint submits an approval request or enables model training.

Batch57 adds a separate [current full-audit inspection](ML_USE_CURRENTNESS.md)
at `/reconstruct/current`, using the same upload. The original endpoint below
keeps its reconstruction-only semantics and explicit currentness limitation.

## What is now verified

`POST /v1/ml/use/preflight/reconstruct` accepts eight exact, canonical JSON files
and the frozen capsule's complete content-addressed artifact inventory:
manifest, task, feature-source companion, review companion, label companion,
audited dataset package, baseline configuration and preparation receipt.

The server checks each whole-file SHA-256 against the independently pinned
request, verifies the exact capsule/artifact inventory, rebuilds the audited v4
dataset and train-only preprocessing, and reconstructs every data-derived
preparation field. This includes prepared views, configuration and input pins,
coverage/missingness/cohort diagnostics, technical gate, training blockers and
the all-false authority fields. It then independently derives the original
request from the manifest and source companion. Missing inputs, substitutions,
resealed inconsistent receipts, undeclared fields and missing/extra artifacts
fail closed. No predictive fitting, hyperparameter selection or prediction occurs.

`online_private_input_reconstruction_verified: true` means exact input-byte
integrity and matching server-rebuilt data-derived outputs, **not** authentication
of the client machine, researcher or prior computation. The client's recorded
environment/source inventory is bounded, structurally validated and pinned as
self-reported provenance. Its historical truth is not established by a checksum.
The response explicitly sets `client_runtime_provenance_authenticated: false`
and records the current server's implementation/runtime separately. The dataset
compiler's existing exact implementation checks are retained; changed derived
values or compiler pins cannot be excused as a client-platform difference.

This distinction permits checking numerically identical preparation content
without falsely attesting that a client used a particular operating system.
It does not weaken the original offline CLI's stricter same-code/runtime replay.

## Private operator workflow

1. Prepare and independently verify the original eight files and request using
   [the existing CLI](ML_USE_PREFLIGHT.md). Only process locally authorized data.
2. Inspect current admission using `GET /v1/ml/use/preflight/access`. The existing
   active verified admin **and** exact curator **and** ML requester boundary
   remains in force; this is not a reason to provision broad administrator roles.
3. Run `scripts/ml_use_reconstruction.py` with the same eight `--NAME` and
   `--NAME-sha256` pairs, plus `--request`, `--request-sha256`,
   `--requester-grant-id`, `--curator-grant-id` and a fresh `--output` path.
   `api/.venv/bin/python scripts/ml_use_reconstruction.py --help` lists the
   complete argument contract. This command performs full local request replay
   and byte/inode rechecks before creating a private, no-clobber `0600` file.
4. An authorized operator may submit that file verbatim to the reconstruction
   endpoint using the established authenticated session. Do not deserialize and
   pretty-print the envelope, infer new hashes, place credentials in the file,
   or send it to a third-party service. Browser-session POSTs retain Origin/CSRF
   checks. The CLI does not perform any HTTP submission.

Unlike the small request descriptor, this upload **contains private source and
scientific input bytes**, including companion audit data. Base64 is not
encryption. Keep the file outside the public repository and do not attach it
to an issue, application log or public artifact. HTTP upload is a separate
operator action; the local package command grants no right to transfer sources.

The closed envelope contains exactly:

| Field | Meaning |
| --- | --- |
| `version` | `ml-use-reconstruction/1.0.0` |
| `request` | Unmodified `ml-use-request/1.0.0` declaration |
| `expected_request_sha256` | Independently retained request pin |
| `expected_requester_grant_id` | Exact current ML requester membership |
| `expected_curator_grant_id` | Exact current curator membership |
| `inputs_base64` | Eight named canonical file payloads, with no paths or URLs |
| `artifacts_base64` | Exact capsule artifact SHA-256 → canonical base64 bytes |

Only canonical UTF-8 JSON and canonical base64 are accepted. Artifact keys are
digests, not filenames; the service extracts no archive and fetches no URI.
Artifacts embedded in the original companions remain part of those pinned
files and are checked by the unchanged companion/dataset verifiers.

## API and process boundaries

The feature uses the existing default-off `ML_USE_GOVERNANCE_ENABLED`. No new
flag is enabled and no real roles are provisioned by this increment.
Admission precedes body reading; the exact request and registration are checked
before starting the worker. After reconstruction, a **new** read-only REPEATABLE
READ transaction repeats session, active account, exact membership, capsule,
feature-binding and current registered-dependency checks. Logout/revocation or
registration drift during CPU work cannot reuse the earlier admission result.
Source changes are reported as existing negative gates, not repaired or ignored.

Heavy reconstruction runs in an owned child using the installed API environment,
with no inherited database/provider credentials, no shell or user-selected code,
and Python isolated mode. Audit hooks reject networking, process creation and
filesystem writes; predictive fitting entry points are denied. These hooks are
defense in depth for server-owned code, **not an OS sandbox against hostile code**.
No uploaded script, pickle or executable object is deserialized.

| Bound | Value |
| --- | --- |
| Canonical request envelope | 32 MiB |
| Combined decoded input/capsule artifact bytes | 24 MiB |
| One decoded file | 16 MiB |
| Capsule artifact count | 256 |
| Body reception | 10 seconds; 4,096 stream parts |
| Whole HTTP handler | 60 seconds |
| Worker wall time | 45 seconds |
| Worker CPU | 30-second soft / 31-second hard limit |
| Worker address space | 1.5 GiB on Linux; not claimed on macOS |
| Worker output / final private report | 128 KiB / 512 KiB |
| Concurrent inspections | Two shared nonblocking slots per API process |

Core dumps and new file writes are disabled in the child. On cancellation,
deadline, failed reconstruction or excessive output, the parent kills and reaps
its owned child before returning the slot. No upload files are persisted by the
API. Existing strict JSON tree, SQL row/byte and five-second statement bounds
also apply. These are bounded pilot operations, not benchmarked production
capacity or a distributed quota. Unix `resource` support is required.

All responses and errors remain private/no-store and nosniff, with fixed English
errors and no private input/worker traceback. No SQL writes, request IDs, approval
ledger or commit recovery are implied by a successful reconstruction response.

## Remaining gates and next implementation

The final registered-dependency inspection retains its original declared scope.
Rebuilding the submitted review/label companion bytes is **not** the same as
recapturing their entire current SQL observations. Thus
`companion_observations_rechecked_online: false` and the explicit
`companion_observations_not_rechecked_online` blocker remain. In particular,
companion-only audit dependencies and outside-SCLib sources have not become a
complete current permission inventory merely because reconstruction passed.

Next: recapture those full observations in one current snapshot, derive and
persist an exact versioned request/inventory, then implement purpose-specific
source decisions with independent rights review, expiry/revocation, and exact
independent run approval. Real reviewed ML08 pilot acceptance and final runner
admission remain separate. This result always says `not_authorized`; source
permissions, execution approval and scientific/ML authority flags remain false.

No material quantities, family semantics, RPS score, dataset format or database
schema changes. Schema remains 0071. The CLI and server now share the unchanged
deterministic preparation-content function; its new source pin means a fresh
current offline preparation must record current code. Historical receipts and
captures are retained unchanged, not rewritten to manufacture current evidence.
