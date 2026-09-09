# Exact RPS dependency rights preparation

Issue: [ML07 / #68](https://github.com/JackZH26/SCLib_JZIS/issues/68).
Contract: `rps-rights-preparation/1.0.0`.
Related: [existing RPS distribution governance](RPS_DISTRIBUTION_GOVERNANCE.md).

## Purpose and authority

The private operator can now prepare the existing fixed-schema rights document
and its permission record for one dependency of an already registered RPS
package. The operator no longer has to insert that rights artifact directly in
SQL before recording the decision. This does not create source captures,
descriptors, a package or its complete dependency closure.

An authenticated, verified account with an explicit active **reviewer** grant
is required. A legacy administrator/reviewer flag, client actor ID or approval
boolean does not provide that grant. Account/session and role checks are repeated
inside the dedicated transaction. Existing cookie/CSRF policy remains unchanged.
Roles are not granted by the workbench. The current role schema has revocation,
not a grant-expiry field; no nonexistent expiry feature is claimed.

The only purpose is `rps_structured_bundle` disclosure. A reviewer records a
rights statement based on their approved external review process; the software
does not determine licensing law or prove that permission is valid. Scientific
acceptance, ML training approval and current publication authorization remain
false. Package review and a separate third-account publisher remain necessary.
No permission operation automatically publishes a package or fits a model.

## Routes and small read surfaces

All routes below have the `/v1/ml/distributions` prefix and are disabled under
the existing ML foundation feature flag. Responses are private/no-store.

| Method and suffix | Purpose |
| --- | --- |
| `GET /operator/capabilities` | Check the current explicit reviewer account/grant |
| `GET /{package_id}/rights` | Inspect at most 25 compact dependency headers |
| `GET /{package_id}/rights/{dependency_id}` | Inspect exact package/dependency pins and current permission head |
| `POST /{package_id}/rights/{dependency_id}` | Preview or explicitly commit one decision |
| `GET /{package_id}/rights/{dependency_id}/outcome` | Recover one exact historical receipt without writing |

The dependency list exposes identifiers/hashes, not raw source projections or
the entire private registered inventory. `after` is an ordered dependency-hash
cursor; subsequent pages require `expected_inventory_sha256`. It replaces the
displayed page rather than accumulating an unbounded browser inventory.
The selected dependency response adds the current permission head's ID/hash,
decision and opaque license/basis/reason codes.

All reads use bounded read-only repeatable-read transactions and fresh current
account/role admission. They do not certify that an old dependency remains
eligible for publication. The full existing public admission gate remains
responsible for complete current sources, permissions and publication state.

## Preview, commit and exact intent

The closed POST body contains `request_key`, `decision`, `license_code`,
`basis_code`, `reason_code`, `expected_package_sha256`,
`expected_inventory_sha256`, `expected_dependency_row_sha256`,
`expected_head_id`, `expected_head_sha256`, optional `expected_intent_sha256`
and `dry_run` (default true). Both head fields must be explicitly null when
expecting no predecessor, or must identify the exact predecessor together.

Allowed license codes remain the existing `CC0-1.0`, `CC-BY-4.0`,
`CC-BY-SA-4.0`, and `permission-on-file` vocabulary. A code is a recorded
decision, not automatic evidence that a source carries that license. Basis and
reason are bounded lowercase opaque codes; arbitrary source text, credentials,
URLs, paths, actor IDs, metadata or rights-file uploads are not accepted.

The preview hash binds the fixed purpose, exact package record/inventory/public
bundle, dependency row, authenticated reviewer and grant, predecessor, request
key, complete decision fields and canonical rights-document hash. It deliberately
does not bind a random artifact ID or transaction timestamp from a rolled-back
preview. A checksum is not a signature or proof that a human read the document.

Preview runs the actual artifact/permission insert and database constraints
inside the transaction, then rolls back all changes and guard epochs. It returns
the fixed document and intent pin, not a durable new artifact or permission ID.
An exact already-existing replay may return its historical identifiers, but
the preview envelope still has `committed=false`.

Commit requires `dry_run=false` and the exact preview intent hash. A new allow
first checks the target's current projection; the unchanged permission SQL
trigger independently checks it again. It creates a restricted review artifact
and calls the unchanged permission validator in the same outer transaction.
Partial service/savepoint success is not durable success. HTTP serialization
precedes the outer commit, and the HTTP success envelope follows that commit.

The new artifact has kind `review`, the unchanged
`rps-distribution-rights/1.0.0` schema, fixed source/version metadata, restricted
access, no URI and no license assigned to the artifact itself. Its metadata
contains only the canonical rights object. Record/byte hashes are computed from
the actual canonical object bytes. `hash_status=verified` describes those bytes,
not the legal truth of the review.

## Historical bytes, revocation and recovery

Canonical rights bytes can be reconstructed from the exact object in the
permission's retained `rights_projection_json`, then checked against its
record/byte hashes. **The immutable record is the permission history and its
stored projection, not the live EvidenceArtifact row.** The latter can later
change under existing governance; current public admission must recheck it.
No uploaded original legal document or restricted source text is claimed to be
stored by this preparation operation.

A new decision checks the current head. An identical actor/key/intent retry
resolves its existing permission before creating any artifact or checking the
now-advanced head. It returns the same identifiers and does not persist new
records or epoch changes. Changed intent under the same key, changed pins or
stale predecessor for a new decision reject. A fresh write/replay still requires
the exact active reviewer grant bound to the intent.

Revocation requires an exact predecessor and inherits its rights document and
license. It does not read obsolete source bytes or require renewed positive
source eligibility. It can inherit an artifact made by the older governed
workflow. Conversely, an old externally prepared allow artifact cannot be
misrepresented as an allow created by this new preparation path; POST replay
and GET outcome apply the same origin check.

GET outcome takes `request_key` and `expected_intent_sha256`. It is scoped to
the current authenticated reviewer account and returns the original historical
grant, predecessor, intent and receipt. A replacement active grant for that
same account may read the old history; it does not reauthorize the old decision
or permit a fresh write under the old grant. Later permission heads, source holds
or live-artifact changes do not erase the retained historical receipt.

A missing outcome is HTTP 404 for this snapshot, **not proof that a commit rolled
back**. Network/commit/response ambiguity must not be converted to invented
success or automatic retry. Preserve the original key and pin. A subsequent
explicit retry must use that identical intent and may execute it if it was not
already committed; it must never silently create a new request key.

## Workbench behavior

`/dashboard/research/distributions` uses the existing English dashboard. Load a
package UUID, inspect a dependency, choose a decision and reviewed license/basis,
enter opaque codes, preview, then explicitly commit the exact preview. Neither
the favorable decision nor a license is selected by default. Editing any
decision field invalidates the preview. No full source projection is hydrated
or displayed in this workflow.

Every response is checked against a closed display contract and its expected
actor/package/dependency/head bindings. Intent and document hashes are recomputed
before a preview or receipt is displayed. These client checks prevent accidental
wire/binding confusion; they do not replace authenticated server admission.

An uncertain commit locks preparation of a new decision. **Check original
outcome** issues only a GET. **Retry exact original commit**, when the complete
original draft remains in memory, is a separate explicit write-capable action
with that same key/body/pin. Neither action runs automatically. Authentication
changes clear private evidence/drafts; only opaque original-account recovery
references remain in memory. No browser persistent storage is used. Full-page
navigation/reload uses a browser unload warning; client-side route changes may
not trigger it. The unresolved panel explicitly says to keep the page open and
exposes the opaque recovery references for the approved private operation record.
Leaving discards the in-memory retry context; it does not roll back a server write.

## Limits and acceptance

POST bodies are bounded to 8 KiB, 4,096 stream chunks and 10 seconds for body
reading. The existing 30-second request bound and two-slot nonwaiting process
capacity gate cover the full authenticated operation. SQL statements and read
snapshots retain their smaller explicit timeouts. Browser response-byte bounds
are 4 KiB for capabilities, 16 KiB for selected context and 32 KiB for pages or
receipts. These are engineering bounds, not measured production throughput.

Native SQL/HTTP tests and an actual-HTTP-derived synthetic browser fixture are
documented in the implementation report. They establish implementation behavior,
not a real rights review, operational rollout or scientific acceptance. Real
source-use decisions, exact research releases, the ML08 pilot, actual ML-use
authorization and remote delivery remain separate requirements.
