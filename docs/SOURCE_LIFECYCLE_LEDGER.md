# Observed source lifecycle ledger — SC08, policy 1.0.0

Date: 2026-09-07. Migration: `0056_source_lifecycle`.
Issue: [SC08 / #66](https://github.com/JackZH26/SCLib_JZIS/issues/66).

## Outcome and scientific boundary

An observed correction, withdrawal, retraction or dispute now creates a durable
source-review hold. Updating a Paper back to `published`, or a Work to `active`,
does not restore eligibility. This is negative governance, not a determination
that a material cannot superconduct or that every result in a paper is false.
The conservative whole-material policy can still hold independent support until
the unfinished result-scoped adjudication workflow exists.

Three additive tables implement this boundary:

| Table | Purpose | Does not mean |
| --- | --- | --- |
| `source_lifecycle_epoch` | Transaction-level fence for ordered observed writes | Provider event ordering or a propagation SLA |
| `source_lifecycle_events` | Immutable per-Paper/per-Work revision chain and exact catalogue snapshot hashes | ML01 provider revision, source bytes, full old metadata archive or original publication time |
| `source_lifecycle_reviews` | Immutable exact-event/optional-exact-claim processing review, explicit role and actual artifact binding | Scientific acceptance, source reinstatement, public permission or training approval |

Neither event nor review mutates prior ML01 source-registry rows, ML03 shadow
receipts, ML04 capsules/notices, or ML07 public bodies. Their released hashing
contracts and schemas remain unchanged. File-backed RPS releases are not silently
enrolled in this SQL governance scheme.

## Capture rules

Database AFTER INSERT/UPDATE triggers observe Paper and Work changes, including
ordinary SQL writers outside the API. A source starts a chain only when its
current or immediately previous normalized status is `retracted`, `withdrawn`,
`corrected` or `disputed`. A never-held ordinary source has no fabricated baseline.
Capture normalization is `lower(btrim(status))`; it does not merge `published`
with `active`, or `withdrawn` with `retracted`.
Once tracked, every changed semantic snapshot appends a revision, including
restoration of ordinary status. A semantic no-op appends nothing.

The parent status vocabularies are not broadened: Work retains its existing
narrower `publication_status` constraint, while `disputed` is available on Paper.
The shared capture policy recognizes a status only where that parent schema
permits storing it.

An event records source identity, monotonically increasing revision, exact
predecessor, previous/current snapshot hashes, previous/current normalized
statuses, event kind, record hash and database observation time. At insertion,
the database validates the live source and chain and computes the record hash
and observation timestamp. Direct ordinary event INSERTs cannot bypass capture.

`baseline_observed` means the database first observed an already-held source.
`lifecycle_change` means normalized status changed. `catalogue_revision` means
the tracked source's semantic metadata changed without a status transition.
Migration bootstrap observes existing held rows at migration time by semantic
no-op updates. It does not invent previous status, backdate events or claim to
recover changes predating the migration. The catalogue field values are retained.

The versioned semantic hash covers bibliographic identity/content and scientific
extraction metadata, including Paper submitted/published dates and Work
availability. The exact frozen field lists are in `models/source_lifecycle_v1.py`.
Operational timestamps, citation/chunk counts and geographic enrichment are not
source-semantic changes. Claim revision hashing covers the claim SQL row except
its creation/update timestamps; it is a separate observed binding, not a
substitute for the canonical ML01 claim/source contract.

Snapshot hashes use the version-labeled PostgreSQL JSONB representation. They
are deliberately not advertised as portable provider-byte SHA-256 values.
Event/review record hashes use the closed scalar record representation, include
the record UUID, and exclude `created_at` and `record_sha256`. A database owner
disabling triggers or rewriting functions is outside the ordinary-DML guarantee.

## Read-time admission

`resolve_paper_lifecycle` and `resolve_work_lifecycle` return the original status
for an existing untracked source. Tracked sources return a separate envelope:

```json
{
  "status": "published",
  "lifecycle_review_required": true,
  "lifecycle_revision": "<64-character current revision digest>"
}
```

No fake `corrected` status is written into ORM objects, bibliographic responses
or historical Timeline snapshots. A pending lifecycle reason is explicit:
`source_lifecycle_review_required`. Direct head hashes enter the source
fingerprint. An accepted current Paper/Work mapping can conservatively carry a
Work hold to Paper-backed reads; its combined digest binds the direct and Work
event heads. Pending/rejected maps do not assert this identity. All accepted
relation types carry this conservative negative hold, including supplement,
correction and unknown; they are not thereby approved for positive scientific
equivalence. This inheritance
does not prove two results equivalent and does not authorize a claim review:
claim review requires the claim's explicit `paper_id` or `work_id` foreign key.

The new envelope is consumed by material/ancestor visibility, source semantic
checks, claim reads, independent-source hydride checks, search/Ask hydration,
paper detail, saved-history current metadata, Timeline live reads, prospective
shadow import and ML07 metadata admission. Ingestion mirrors the pure negative
policy and reads direct/accepted-Work heads before recomputing supported fields.
Database event creation does not itself sweep every derived table or vector.

API resolver inventories are capped at 20,000 supplied source positions and
processed in batches of 1,000. Missing rows are omitted, preserving exact
inventory checks. Sources with events have their head record and current
semantic hash checked in SQL without transferring raw source JSON to Python.
Missing ledger/schema or invalid bindings do not fall back to ordinary status.
Ingestion trusts the guarded immutable ledger and fails rather than continuing
without the ledger. Caller-specific repeatable-read, byte and time budgets still
apply; the hash operation is not itself a hard database CPU/memory deadline.

Timeline still stores raw bibliographic dependency snapshots for reproducible
cache comparison, then gates projected and fallback output against current
lifecycle state. It does not repeatedly rebuild simply because an envelope
differs from raw status. Saved Ask answers/citations stay historical; the new
hold appears only in separately labeled current evidence metadata. This does
not revalidate a previously generated answer or add the future post-generation
source check required by RG02.

## Exact-version processing review

The internal service surface is:

- `inspect_source_lifecycle`: bounded direct revision history and separate current
  head; at most 100 events per page, using a revision cursor rather than timestamps.
  Its effective hold/digest includes an accepted Work hold even if the Paper has
  no direct events; `direct_lifecycle_review_required` distinguishes that case.
- `preview_source_review`: read-only preparation of a closed canonical document.
- `record_source_review`: append-only review; default `dry_run=True` rolls back
  the savepoint and never commits the caller's outer transaction.
- `inspect_source_review`: historical receipt plus separately recomputed currentness.

Only `retain_hold` and `requires_supersession` are supported. Both leave
`lifecycle_review_required=true`, `source_reinstatement=false`,
`scientific_acceptance=false` and `ml_training_approved=false`. The first means
retain the restriction; the second records that a separately reviewed successor
is needed. Neither means an existing claim has been accepted or a source cleared.

The caller must provide the exact current event ID/hash, an optional claim ID
and exact current claim hash together, decision/reason, a bounded actor-scoped
idempotency key, explicit predecessor for a subsequent review, registered review
artifact ID and actual immutable canonical review bytes (maximum 1 MiB).
The database and service recheck live bindings. The service additionally requires
`access='restricted'` and actual canonical bytes. SQL independently checks review
kind, verified declared byte/record hashes, exact document metadata and active
explicit reviewer authority; it neither fetches bytes nor treats an access tag
as publication permission. No URL fetch or self-declared checksum replaces the
service's actual-byte requirement.

Review authority requires an active, email-verified user with an explicit live
ML07 `reviewer` grant. Legacy `is_admin`/`is_reviewer` flags are insufficient.
Actor IDs must be supplied by a trusted authenticated caller; the service does
not authenticate a UUID supplied in arbitrary JSON. This batch introduces no
HTTP review-write endpoint, grant provisioning or curator UI.

Review predecessors are exact within `(event_id, claim_id)` scope; older reviews
are not modified. Identical current requests return the existing receipt;
reuse of a key for different content is rejected. Source/claim change or grant
revocation makes a retry fail current binding checks, preserving its historical
receipt. Superseded reviews are not reported as current and an older valid
review is not used as fallback after later review or authority changes.

## Transactions, retention and migration safety

Source capture uses a nonblocking advisory lock and epoch fence, with ordinary
READ COMMITTED source writes supported. A stale REPEATABLE READ/SERIALIZABLE
snapshot cannot append against an old epoch. Contention/serialization failures
require retrying the whole outer transaction from a fresh snapshot.

Review writes require a clean dedicated SERIALIZABLE session and acquire locks
in fixed order: scientific integrity `540017026`, publication authority
`550017026`, then source lifecycle `560017026`. The scientific fence protects
new artifact/claim audit attachments against stale scientific writers; publication
and lifecycle fences protect reviewer authority and source revisions. Review
insertion also locks the exact live source/optional claim/artifact rows.

Events and reviews reject UPDATE, DELETE and TRUNCATE. Tracked source identity
cannot be deleted/reused. Referenced review artifacts are immutable. Reviewer
account deletion returns the existing controlled 409 audit-retention response,
including after the grant is revoked; private account data and audit history
are not partially erased. No new account or research-role grants are created
outside synthetic tests.

The migration is additive and separately reversible only while its history is
empty. Nonempty downgrade refuses to erase source observations or reviews.
The migration harness also continues exercising each older ledger's independent
nonempty guard rather than treating 0056's refusal as proof of all older guards.
Runtime schema admission uses the new head. Deployment requires a separately
authorized migration plan, backup/restore rehearsal and staging acceptance.

## Remaining work

1. A reviewed positive supersession/reinstatement policy and canonical result
   promotion. Immutable held releases must not gain scientific/ML approval or
   regain publication visibility through in-place source edits or checkbox overrides.
2. An indexed dependency inventory and bounded refresh queue with exact
   requested/completed revisions, retries, failures and lag measurements.
3. Result-scoped mixed-source admission and explicit dependency identity for
   zero-point Timeline candidates, chunks, prospective ML membership and RPS.
4. RG02 post-generation live-source validation, explicit historical release
   notices and independently authenticated curator interaction.
5. Real reviewed source cases in staging and human scientific/rights review.

Synthetic tests establish these software invariants only. They do not demonstrate
real source adjudication, ML-label quality, a production SLA or completion of SC08.
