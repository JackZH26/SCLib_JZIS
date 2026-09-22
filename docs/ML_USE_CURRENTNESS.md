# Current ML input and audit-dependency inspection

Batch57. Response `ml-use-current-reconstruction/1.0.0`; dependency inventory
`ml-use-captured-dependency-inventory/1.0.0`. Schema remains 0071.

Historical scope: this document describes the read-only inspection contract.
Batch58's separate [submission workflow](ML_USE_SUBMISSIONS.md) adds schema 0072
and private retention without changing this endpoint's response or authority.

## Operator entry point

Submit the unchanged canonical upload produced by
[the private reconstruction workflow](ML_USE_RECONSTRUCTION.md) to:

`POST /v1/ml/use/preflight/reconstruct/current`

The input remains `ml-use-reconstruction/1.0.0`. There is no extra client
`reconstruction`, `approved`, actor override or source-list field. The server
always launches its actual bounded reconstruction worker; a client cannot
replace it with a previously saved successful report. Both reconstruction
endpoints now expose the closed upload fields in OpenAPI.

This endpoint is separate from the existing `/preflight` and `/reconstruct`
operations, whose response versions and limited scopes remain unchanged.
The same default-off feature flag, active verified admin + exact curator +
exact ML requester admission, session/Origin checks and private/no-store
English errors apply. No flag is enabled or real role provisioned here.

The upload contains private source/ML/audit data; base64 is not encryption.
Only submit inputs whose transfer and local processing are already permitted.
Do not attach the upload or raw companion content to public issues or logs.

## What the current inspection adds

After full dataset/preparation reconstruction, the handler starts one **new**
UTC read-only REPEATABLE READ transaction with five-second SQL statement bounds.
It rechecks session, account and exact requester/curator grants before processing
the private inputs in that snapshot. Registered capsule, feature bindings and
the conservative current source closure are inspected in that same transaction.

The existing complete label-capture service then:

1. Revalidates the exact frozen manifest, source companion and review companion.
2. Recaptures the complete feature-review observation, including latest decision
   heads, full multi-item request siblings, current scientific subjects, reviewer
   identities/grants/revocations, source dependencies and lifecycle histories.
3. Requires that observation to match the independently pinned review companion.
4. Recaptures every frozen root label and its current dependency/owned-child
   graph, including excluded examples and newly added source occurrences or
   capture siblings; then requires the exact label observation to match.

No smaller selected-feature-only inventory is substituted for these complete
captures. New decisions, relevant actor/role changes, retractions, material
holds or added owned source rows cannot be omitted by retaining an old checksum.
Observation mismatch is a conflict; unavailable/timed-out inspection is not
an empty successful observation. No original input or SQL row is rewritten.

The requester may differ from the companion's declared original capturer. The
requester is independently authenticated at the current API boundary. The
capture service additionally checks the declared capturer's current full-audit
eligibility when reproducing that observation. This is read-only evidence
comparison, **not impersonation of an authenticated historical session** or a
write operation by the declared person. Accordingly,
`historical_capture_session_authenticated` remains false. The declared identity
is reported separately from the actual requester admission.

## Versioned dependency inventory

The new `dependency_inventory` combines the registered closure with all rows
in the exactly recaptured review/label observations and the source companion,
including audit-only dependencies absent from the original frozen manifest.
It also enumerates members and artifact references inside both historical
stored review subjects and current subjects. It returns only IDs, hashes,
encoding/scope tags, sizes and origin references, not raw rows or source text.
Native import package/outcome/file references carried beside the subject's row
snapshots are included as container-bound membership references as well. This
does not claim that every underlying private import-ledger row was exported or
independently recaptured as a full row.

Each logical `(table, row_id)` has independently tagged representations:

These are the new inventory's explicit encoding tags; they name existing byte
formats without changing the underlying frozen/review protocol versions.

| Encoding | What its hash covers |
| --- | --- |
| `research-release-canonical/1.0.0` | Existing canonical research-release row projection |
| `scientific-adjudication-canonical/1.0.0` | Exact existing SQL audit row text, including the restricted four-field user projection |
| `source-lifecycle-jsonb-text/1.0.0` | Existing paper/Work lifecycle snapshot text |
| `ml-feature-binding-record/1.0.0` | Existing immutable feature-binding record body |
| `scientific-subject-membership/1.0.0` | Canonical `{subject_sha256, table, row_id}` membership tuple; the separately supplied `container_sha256` pins the full subject |

The last row is intentionally **not a standalone row-content hash**. Decimal
scale, timestamp spelling or another wire format must not be normalized into
invented equality between protocols. `historical_input`, `historical_subject`
and `current_observation` tags remain separate even when their hashes happen
to match. Sorted `origins` preserve which observation supplied each occurrence.

Artifact digests record uploaded byte sizes where bytes actually occur in the
verified capsule/source companion. A digest referenced only by a review subject
may instead have `uploaded_size_bytes: null`; it is not described as uploaded,
accessible or licensed. The eight original input pins remain explicit. The
complete inventory is canonically hashed as `dependency_inventory_sha256`.

`row_count`, `representation_count` and `artifact_digest_count` are inventory
counts, not independent experiments or scientific support. The output sets
`independent_support_count: null`, `external_dependency_completeness_proven:
false` and `source_permission_granted: false`. Sources missing from SCLib cannot
be discovered or licensed merely by enumerating SCLib's captured graph.

The older `requirements` list retains its original registered-closure scope;
consumers must not mistake it for the new broader `dependency_inventory`.
Neither list is a purpose-specific permission decision.

## Bounds and response meaning

The upload/worker retain all batch56 byte, CPU, memory, output and cancellation
bounds. This complete operation has a 90-second whole-handler ceiling; its
current-inspection phase has a 30-second budget and retains the existing
20-second cumulative label-capture and row/byte guards. It shares the two
nonblocking per-process inspection slots. Inventory limits are 4,000 distinct
rows, 16,000 representations, and 4,000 artifact digests; the final response is
at most 1 MiB. Failure returns no partial successful inventory. These bounds
are not measured production throughput or a distributed execution quota.

A successful response reports both input reconstruction and companion
observation comparison as verified. This proves consistency **within one
database snapshot**, not that later commits cannot invalidate it. An existing
REPEATABLE READ snapshot correctly remains historical after another transaction
commits a retraction. A subsequent new inspection rejects that stale input.
Future submission, permission decisions and run consumption must perform their
own currentness checks; this response is not a durable lease.

All publication/scientific/ML/rights authority flags and `request_persisted`
remain false. The decision is still `not_authorized`: purpose-specific source
permissions, independent exact run approval and actual ML08 pilot acceptance
remain separate blockers. Captured acceptance or lack of a hold is not an ML
licence, proof of physical validity, or evidence that a calculation ran.

## Next dependent implementation

Persist the exact request and this versioned inventory with recoverable
submission, explicit private-input retention/access policy and currentness
rechecks. Then add independent purpose-specific source decisions with exact
evidence, expiry/revocation, followed by exact run approval/consumption and an
actually reviewed pilot. This increment performs no request submission, real
review, model fit, paid calculation, publication, backfill or deployment.
