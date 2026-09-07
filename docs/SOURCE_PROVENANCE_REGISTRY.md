# Immutable source provenance registry — ML01 bounded persistence

Status: additive internal infrastructure; no production registration, backfill,
public write API, source-history verification campaign, or ML release is performed.

The schema contract is frozen in `api/models/source_provenance_v1.py` and migration
`0052_source_provenance`. It does not alter the historical `0045` registrar.
The service contract is `source-provenance-registry/1.0.0`.

## Scientific boundary

A work is a bibliographic identity, a source revision is one explicitly identified
version, a capture records bytes of a particular representation, and an occurrence
binds an existing `MaterialClaim.id` to a locator in that capture. They are not
interchangeable. `source_snapshots` remain database-export lineage records.

An exact reviewed version can establish **known by this version's public time**.
It does not establish the result's first-ever appearance, discovery priority,
scientific truth, independent replication, rights to redistribute source text, or
absence of LLM pretraining contamination. A later capture time is recorded
separately and never substituted for a public version time. Date-only values are
not silently converted to midnight. Unknown or uncertain public time remains NULL.

No match by formula, Tc, semantic fingerprint, paper title or family merges
scientific results. Multiple source-version occurrences can explicitly reference
the same existing claim; the authorized binder must establish that identity.

## Three append-only tables

| Table | Identity and purpose | Important safeguards |
| --- | --- | --- |
| `source_revisions` | UUID; paper ID; optional work ID; caller-owned revision key; optional exact provider revision; pinned/unresolved version status; nullable public time with known_by/unknown/uncertain status and basis; metadata and canonical registry-row hashes | Unique paper/revision key and paper/provider revision; no guessed version or date; known_by requires an explicit pinned version and public time |
| `source_captures` | UUID; source revision ID; capture key; exact timezone-aware capture time; original representation and byte hash; canonical registry-row hash | Unique revision/capture key; only named source representations; one representation's conflicting bytes within a version are rejected by the writer and invalidate resolver eligibility if inserted outside it |
| `claim_source_occurrences` | UUID; existing claim and work IDs; revision and capture IDs; occurrence key; bounded coordinate locator and its hash; pending/reviewed binding; optional pinned review artifact; canonical registry-row hash | Composite FKs enforce claim/work, revision/work, capture/revision and artifact/kind consistency; pending never becomes verified merely by having matching text |

The occurrence work ID is required. NULL-work legacy claims and source revisions
can remain unresolved; captures may still be retained, but they cannot enter a
verified result/work association through a nullable composite-FK loophole.
The only existing-table change is an additive `(id, work_id)` unique key on
`material_claims`. Its existing primary key ensures historical rows, including
NULL work IDs, do not require rewriting to satisfy it.

PostgreSQL triggers reject UPDATE, DELETE and TRUNCATE on all three tables.
Direct changes by the database owner, trigger disabling, restores or arbitrary
DDL remain outside this application's trust boundary. Upstream paper/work/claim
and review-artifact rows are not made immutable by this change; the resolver
revalidates their relevant binding state and hashes.

## Internal writer

```python
await import_source_provenance_bundle(db, bundle, dry_run=True)
```

The bundle contains `version` and arrays named after the three tables. Unknown
fields are rejected. IDs, metadata hashes, provider revision identifiers and
capture metadata must be supplied explicitly; the writer does not fetch them.
Row hashes and locator hashes are calculated using sorted-key, compact UTF-8 JSON
with normalized UUIDs and exact UTC instants. At most 1,000 total rows are accepted.
Ordering within each array is normalized deterministically.

The writer uses a nested transaction and a registry-specific advisory transaction
lock. It inserts missing rows or verifies every existing field identically.
An ID/key collision with different content fails the complete bundle. It does
not run an overwrite upsert. A second capture with a different representation,
such as PDF versus source archive, may legitimately have a different byte hash;
a different hash for the same version and representation is a conflict.

Dry-run rolls back this function's savepoint. Live mode releases its savepoint,
but **never commits the caller's transaction**. The returned `committed` is
therefore always false; `inserted` describes rows attempted in this operation,
including a rolled-back dry-run. An administrative caller must decide whether
to commit. SQLAlchemy can flush pre-existing pending ORM state when opening a
savepoint; callers should use a dedicated clean administrative session.

For a non-NULL source work ID, an existing accepted `paper_work_map` entry is
required. This is bibliographic grouping, not adjudicated independent evidence.
No paper-work mapping, review artifact or historical claim is created by this
writer. No production CLI or public registration route is introduced.

## Reviewed occurrence linkage

`source-occurrence-review/1.0.0` is a strict internal review payload under an
existing `evidence_artifacts.metadata.source_provenance_review` object. It pins:

- Claim, work, paper, source revision and capture identifiers.
- Provider revision, exact public and capture times, representation and byte hash.
- Locator hash and a digest of the current complete claim row, excluding only its
  `created_at` and `updated_at` bookkeeping timestamps.
- Explicit boolean `binding_verified`, `version_resolved` and
  `public_time_verified` assertions.

The artifact must have kind `review`, verified hash status, a byte hash, and
`record_sha256` equal to the canonical review payload hash. The occurrence pins
that artifact ID and record hash. Creating the payload with
`source_occurrence_review_payload(...)` performs no review and creates no artifact.
The authorized review/import boundary is a prerequisite, not an automated
scientific approval workflow or authentication supplied by this helper.

The resolver compares the actual current review row, all linkage values, the
claim digest, source/capture/occurrence row hashes and the current accepted
paper-work mapping. A changed review, claim content, work mapping or mismatched
locator fails closed. A reviewed flag alone, stored public envelope, raw NER date,
unlinked artifact or stale source text cannot establish availability.

This intentionally conservative current-row digest may invalidate a witness when
non-scientific claim metadata changes. A later immutable claim-revision contract
can refine that boundary without silently relaxing this version's rule.

## Authoritative read boundary

```python
await resolve_claim_source_witnesses(db, claim_ids)
# dict[str, list[SourceAvailabilityWitness]]; canonical claim UUID string keys
```

The resolver accepts at most 500 claim IDs. Missing occurrences return an empty
list. Existing pending or invalid witnesses retain false verification flags so
the pure `temporal-provenance/1.0.0` consumer reports uncertainty, not false absence
of conflicts. At most 101 occurrences per claim are returned: 101 deliberately
exceeds the pure consumer's 100-item limit and fails closed as incomplete coverage.
Database failures propagate; callers must not substitute an apparently verified
legacy date or cached envelope.

Internal witnesses contain UUIDs, bounded version/representation labels, exact
timestamps, hashes and allowlisted coordinate locators. Review references are
opaque internal artifact UUID/hash strings and must not appear in public output.
No quotation, URI, reviewer notes or private source body is stored in the new
registry. The public envelope is generated by the shared temporal policy, which
also states `scientific_acceptance: false`.

## Migration and operating limits

Upgrade creates empty new tables and adds the redundant claim/work unique key;
it does not populate historical dates or source revisions. Existing rows and
source hashes remain unchanged. Applying the unique key still takes a database
lock and should be scheduled after an ordinary backup and migration rehearsal.
New RESTRICT associations can deliberately prevent deletion or work reassignment
of referenced historical claims/sources. This is a compatibility consequence,
not an implicit permission to delete or rewrite evidence.

Downgrade obtains exclusive locks and refuses if any registry table contains a
row. Empty disposable upgrade/downgrade round trips are supported. There is no
destructive post-import rollback path; corrections require an explicitly designed
subsequent append-only correction/review contract, not a secret UPDATE.

There is no automatic supersession of pending bindings in this first version:
an earlier pending occurrence keeps the result uncertain even when a later
separate occurrence is reviewed. Likewise, an unresolved source row cannot be
promoted in place. Do not bulk-register unresolved associations expecting later
automatic approval. Retain diagnostic captures separately until explicit review,
and design an additive adjudication/amendment contract before operational rollout.

Current limitations: no automatic source-version capture registration, no durable
adjudicator/signature registry, no source byte download/re-hash in the resolver,
no claim-version immutable ledger, no ingestion backfill, no leakage-safe dataset
release, and no full-corpus source-history audit. Hashes preserve and verify the
registered contract, not the physical truth or legal redistributability of source
content. Tests use synthetic authorized-review fixtures only.
