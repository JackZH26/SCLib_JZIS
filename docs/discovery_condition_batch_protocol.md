# Private condition batch ledger

Implementation contract for the next Discovery vertical. This document describes
the intended server/client contract; completion requires native SQL/HTTP and
rendered interface evidence. Existing 0087 design and local sweep contracts stay
unchanged. Requested conditions are proposals, not scientific results.

## Versions and limits

- API version: `discovery-condition-batch/1.0.0`.
- Request version: `discovery-condition-batch-operation/1.0.0`.
- Generation artifact: unchanged `discovery-condition-sweep/1.0.0`.
- Owner-only explicit curator, live session/grant, independent default-off flag.
- At most eight choices per axis, 64 scenarios; request 16 KiB, pages eight items,
  generation body four MiB, raw manifest export four MiB plus 128 bytes for its SHA.
- Authority fields: `scientific_acceptance:false`, `canonical_promotions:0`,
  `ml_training_approved:false`, `public_release:false`, `calculation_executed:false`,
  `scope:private_owner_condition_batch`.

## Closed requests

Every request has exactly `version`, `request_key`, `operation`, `payload`.
`request_key` uses the existing design key syntax and 160-character limit.

`retain_batch` payload has exactly:

```text
parent: {design_id, revision_id, revision, record_sha256}
axes: {pressures: [{kind, raw_gpa}], temperatures_k: [raw decimal or null]}
expected_input_sha256
expected_manifest_sha256
```

`propose_candidate_child` payload has exactly:

```text
batch: {id, record_sha256, manifest_sha256}
candidate_sha256
```

Decimals use the local sweep's exact coefficient/exponent identities, first raw
alias display and representation/finite/underflow admission. The server rebuilds
the complete original local manifest from the native owner parent, current actor
pins and raw axes. The parent must be the live proposed head, anchored and
currently eligible, with unchanged context/projection. Its receipt, baseline,
source state/run pins, proposal and next action stay separate from science facts.
Client input/manifest digests must match reconstruction. No uploaded proposal,
source pins, candidate list or authority fields are accepted.

## Append-only records and previews

0088 adds `discovery_condition_batches_v1` and
`discovery_condition_child_links_v1`. Both have UUID id, actor_user_id,
actor_grant_id, actor_session_version, operation, request_key, request_json,
payload, request_sha256, preview_json, preview_sha256, five authority columns,
record_sha256 and created_at. Original request/preview text is canonical UTF-8.

Batch adds `parent` (JSON), `source_pins` (JSON), `input_json`, `input_sha256`,
`manifest_json`, `manifest_sha256`, `scenario_total`. Input/manifest text is the
original local artifact, including its `batch_saved:false` and other generation
flags. Retention is attested separately; changing an artifact flag changes its SHA.

Child link adds `batch_id`, `batch_record_sha256`, `manifest_sha256`,
`candidate_sha256`, `child_revision_id`, `child_design_id`, `child_record_sha256`.
Batch/child references are RESTRICT FKs. Each candidate within one batch has one
initial child link (`batch_id,candidate_sha256` unique);
each child revision has at most one batch link. Later changes use ordinary design
revisions. Owner/request_key conflicts must be checked across both tables.

Record digest seals all stored columns except created_at and record_sha256;
batch record additionally omits manifest_json, sealed separately by manifest SHA.
Original input_json remains in its bounded receipt. Raw scientific context is not
included in either receipt; the native immutable parent already retains it.

Batch preview has exactly `version`, `actor` (the three actor fields),
`request_sha256`, `receipt_id`, `batch_id`, `parent`, `input_sha256`,
`manifest_sha256`, `scenario_total`.

Child preview has exactly `version`, `actor`, `request_sha256`, `receipt_id`,
`batch_id`, `batch_record_sha256`, `manifest_sha256`, `candidate_sha256`,
`child:{design_id,revision_id,record_sha256}`.

Preview rehearses actual guarded writes and rolls back. Child creation invokes
the existing native 0087 propose path with exactly the candidate proposal,
baseline and parent, and inserts the link within the same outer serializable
savepoint. Any failed link rolls back its child. Original parent remains unchanged.
The native child receipt's operational dry_run/pending flags reflect the outer
rehearsal, while its immutable canonical proof remains unchanged.

Both direct SQL guards reconstruct/check exact manifest/candidate/proposal pins,
live curator/session, current proposed parent and current source closure under
existing integrity/publication/lifecycle/design locks. UPDATE/DELETE/TRUNCATE
are refused. Downgrade refuses either nonempty ledger.

SQL guards also check explicit material/retained-record governance and a bounded
32-edge material ancestor walk (missing, cycle, depth and negative holds). They
do not reproduce the complete catalogue parser/anomaly policy. The HTTP service
independently executes the existing current catalogue eligibility policy before
retaining a batch or creating a child; direct SQL proof is not full policy parity.
Operational eligibility never confers scientific acceptance.

## HTTP and closed response shapes

Prefix `/v1/research/discovery-condition-batches`:

- `GET /capabilities`: version, request_version, actor_user_id, session_version,
  curator_grant_id, can_write:true, operations (in above order), max_page_size:8,
  max_operation_bytes:16384, max_manifest_bytes:4194304, and authority.
- `POST /operations/preview`: body exactly `{request}`.
- `POST /operations/commit`: body exactly `{request,expected_preview_sha256}`.
- `GET /operations/outcome`: original request_key and expected_request_sha256.
- `GET /batches`: offset 0–1000, limit 1–8.
- `GET /batches/{id}`: candidate offset 0–63, limit 1–8.
- `GET /batches/{id}/manifest`: raw canonical local generation JSON, custom export
  byte limit; shared private body/response limits remain unchanged.

Receipt has exactly version, receipt_id, receipt_sha256, operation, actor_user_id,
actor_grant_id, actor_session_version, request_key, request_sha256, preview_sha256,
request_canonical_json, preview_canonical_json, receipt_canonical_json, batch_id,
batch_record_sha256, input_sha256, manifest_sha256, candidate_sha256 (null on
retain), child (native DesignReceipt or null), replayed, dry_run,
pending_ledger_written and authority. An uncertain save is recovered with its
original request key/SHA through GET only; no automatic commit retry.

Batch entry has exactly id, record_sha256, parent, source_pins, input_sha256,
manifest_sha256, scenario_total, eligibility, receipt and authority. Eligibility
is `{eligible,reason_codes}`; reasons are finite current-source/head holds.
Page has version, actor_user_id, session_version, offset, limit, total, entries
and authority. Detail has version, actor_user_id, session_version, entry, offset,
limit, scenario_total, scenarios and authority. Each scenario has the unchanged
local candidate_id, candidate_sha256, conditions, proposal and
child (exact `{design_id,revision_id,record_sha256}` link or null).

GET egress rechecks fresh session/grant and all three integrity/lifecycle/
publication epoch fences. History and artifact hashes survive holds and drift;
held batches cannot create new children. Source values are not batch properties.

## Interface and evidence required

Local planner continues to work without server batch capabilities. When enabled,
the private workspace can preview/retain a generated manifest, read owner history,
verify/export exact manifest bytes, preview an exact candidate child, save it and
open its native design history. Before commit dispatch, edits and leaving the page
clear prepared operations and ignore late preview results. Once a commit is
dispatched, edits and new operations are locked until its original outcome is
proved. Leaving the page clears displayed private values but retains only seven
recovery pins: actor, request key/SHA, preview SHA, receipt SHA/ID and input SHA.
The same actor can refresh session/grant and GET the original outcome; this never
reposts the commit. Identity or authentication changes clear those pins. Recovery
proofs check the sealed outer receipt and native child record before unlocking.
Retention and child commits require
separate explicit clicks. User revisions after initial child creation retain the
ordinary immutable parent chain rather than masquerading as the original candidate.

Native validation must cover TS/SQL manifest SHA parity, 15→12 and 8×8,
ambient/zero/unknown and precision boundaries, parent/source/owner holds, preview
rollback, atomic link failure, request-key replay/conflict, session/grant drift,
direct SQL forgery, bounded pages/export, immutable operations and nonempty
downgrade. Closed TS proof validators must independently replay native fixtures.

This closes condition-batch traceability only. Explicit atomic sites/occupancies,
reviewed physical state genealogy, actual pressure curves, scientific gold and
calibration, executed experiments/calculations and release verification remain
part of the full Materials/Discovery objective.
