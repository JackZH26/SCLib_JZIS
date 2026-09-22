# Bounded shadow research import

Issue: ML03 / #61

Schema: `0053_research_import` (after `0052_source_provenance`)

Offline verifier: `sclib-shadow-import-verifier/1.0.0`

Verified payload: `verified-shadow-import/1.0.0`

Internal service: `shadow-research-loader/1.0.0`

## Scope and non-goals

This increment connects the existing offline source exporter and claim planner
to an append-only **shadow** import ledger. It provides bounded verification,
preview, separately reviewed internal processing, rollback rehearsal, exact
post-load checks, and historical receipts. It does not establish that a real
canary, staging load, production migration, or scientific review has occurred.

The only write targets are the five `research_import_*` tables below. The
service does not insert or modify `materials`, `papers`, `works`,
`paper_work_map`, `material_claims`, `source_snapshots`, composition aggregates,
research events/states/structures, source-version witnesses, or ML releases.
There are no new public routes, website approval controls, or production import
CLI. The Python service resides in the API package but is not an HTTP endpoint.

A preserved legacy source-record identity is not proof that the record is an
atomic experimental result. A material catalogue entry is not a joint
measurement, and a scholarly work is not an independent replication. No Tc,
sample-state, or event copy is promoted to canonical scientific data here.

## Five immutable shadow tables

| Table | Stored role and bindings | What it does not mean |
| --- | --- | --- |
| `research_import_snapshots` | Export snapshot UUID, full verified export manifest, manifest/license hashes, dataset and code versions, database watermark, source schema revision, paper/material/chunk/raw-record counts; fixed status `captured`. | Not a source-publication version, historical result-availability witness, validated dataset, or release. |
| `research_import_occurrences` | Stable legacy claim UUID, original source-record hash and identity version, material/paper/work references, normalized identity-bearing raw record and source locator. `id = legacy_claim_id`; no canonical claim insertion is required. | Not a new independent observation, scientific adjudication, or a second canonical Tc target. |
| `research_import_revisions` | Pending interpretation JSON, mapper version and interpretation hash, occurrence ID, sequential revision number and exact predecessor linkage. | Not permission to overwrite the source, accept a label, or select the newest interpretation for every historical snapshot. |
| `research_import_memberships` | Exact snapshot–occurrence–revision association, matching source hash, and full captured raw-record objects with their original zero-based ordinals for selected occurrences. | Not deduplicated independent-evidence counts; repeated and derived-only raw variants remain auditable. |
| `research_import_receipts` | Plan hash, snapshot and loader identity, processing-review artifact binding, selection manifest with exact row IDs/hashes, governance fingerprint, and complete occurrence-disposition accounting. | Not current eligibility, scientific acceptance, public readiness, or authorization for another plan. |

Every shadow row has a content hash. PostgreSQL constraints bind memberships to
the exact occurrence source hash and exact interpretation revision. Revision
chains cannot point to a different occurrence, skip a predecessor number, or
create competing successors. Interpretation rows have
`review_status='pending'` and `scientific_acceptance=false`; accepted scientific
validity is not a permitted interpretation payload status.

The migration installs update/delete and truncate rejection triggers on all
five tables. Downgrade refuses to destroy a populated ledger. This is an
append-only application/database boundary, not protection against a privileged
administrator disabling database safeguards. There is no generic delete-based
rollback after an outer transaction has committed.

## Offline verification and exact capture bindings

`scripts/verify_shadow_import.py` accepts two explicit absolute manifest paths
and two independently pinned SHA-256 values. It never opens a database or
provider connection. Reading hashes solely from the same bundle's sidecars is
not operator pinning.

The verifier:

1. Captures bounded source/plan bytes through non-following directory/file
   descriptors. Traversal, symlink ancestors or leaves, hard-link aliases,
   special files, missing files, unexpected inventories, and mutation during
   capture are rejected. Temporary verification copies are private and cleaned
   up; originals are checked again before returning.
2. Rejects duplicate JSON keys, nonfinite numbers, malformed or oversized
   records, unsupported fields and versions, and invalid leaf hashes/counts.
   The existing source-export validator checks exact egress schemas, stable
   ordering, declared transaction metadata, license policy, and checksums on
   the captured private copies. It does not retrospectively authenticate the
   database transaction or grant source rights.
3. Binds the plan's snapshot UUID, dataset version, Git SHA, database watermark,
   chunk count, license hash, source schema revision, source-manifest hash, and
   exact input file names/hashes to that verified source capture. Only the
   current claim mapper, work-identity policy, and formula-parser versions are
   replayed. The published v1 artifact formats are retained; mismatched older
   interpretations are not silently upgraded.
4. Rebuilds works, mappings, claims, compositions, warnings, and summary from
   the verified source rows, then separately runs shadow parity against the
   received plan. Zero plan failures and a passing independent parity report
   are required. Source accounting includes duplicates; the parity report also
   binds the full raw occurrence inventory and original ordinals. Qualified
   upper-bound negative outcomes and dimensionally normalized pressures are
   checked using their explicit semantics.
5. Derives the proposed legacy-shaped source snapshot from verified manifests
   and replayed counts. The unchecksummed convenience
   `source_snapshots.jsonl` must exactly match that independently derived row;
   it is never authoritative. Its status stays `building`, and the shadow
   service does not insert it into the legacy `source_snapshots` table.

The internal function returns only JSON-serializable values: verified source
and plan manifests/hashes, bounded source rows, replayed proposals, parity and
summary diagnostics, and the proposed snapshot. Its `payload_sha256` covers
canonical UTF-8 JSON of **every other returned field**, with sorted keys,
compact separators, preserved Unicode and no nonfinite numbers. It is a
self-excluding integrity fingerprint, not a signature, approval token, or
proof that a caller actually ran verification. The downstream processing review
must pin this complete payload, not merely a successful Boolean flag.

The CLI emits summary metadata and the payload fingerprint, not raw source
records. The following is a non-executable template until the local paths and
independently recorded hashes are replaced:

```bash
ingestion/.venv/bin/python scripts/verify_shadow_import.py \
  --source-manifest /absolute/local/canary-source/export_manifest.json \
  --plan-manifest /absolute/local/canary-plan/manifest.json \
  --expected-source-manifest-sha256 '<operator-pinned-source-sha256>' \
  --expected-plan-manifest-sha256 '<operator-pinned-plan-sha256>'
```

Paths must not traverse symlink ancestors; on systems where a temporary path
is an alias, use its actual canonical directory. Exit code `0` means this
bounded offline check passed; `2` reports rejection, not partial success.

## Preview, independent processing review, and import

The internal entry points are in `api/services/shadow_import.py`:

- `preview_shadow_import(db, verified)` performs a read-only forecast.
- `processing_review_payload(preview)` constructs the exact document to be
  independently reviewed; calling this helper grants no authority.
- `import_shadow_research(db, verified, review_artifact_id=..., dry_run=True)`
  defaults to a rollback rehearsal and requires a matching review artifact.

Use the following order in a separately authorized controlled environment:

1. Actually invoke the offline verifier; do not substitute an uploaded or
   user-constructed dictionary bearing the same version label.
2. Open a clean dedicated `SERIALIZABLE` transaction and preview. The service
   checks all exported material and paper rows against their exact captured
   fields, including unused papers and zero-record materials. A missing or
   changed exported row is a source-capture failure, not an implicit exclusion.
   It separately reads current material ancestry/visibility, source lifecycle,
   work mapping, work status, and existing shadow interpretation history.
3. Review the complete forecast, including failures, quarantine reasons,
   repeated occurrences, source distribution, selected revision IDs, and
   expected revision heads. The preview hash includes the governance
   fingerprint and this selection/accounting state. Close or roll back the
   read transaction before the human review interval; do not preserve a stale
   open transaction across it.
4. Through a separately authorized artifact-registration process, retain the
   exact reviewed document as an `evidence_artifacts` record of kind `review`
   and schema `shadow-import-processing-review/1.0.0`. Its `record_sha256` must
   match the canonical reviewed document, with declared `hash_status='verified'`
   and a nonempty `bytes_sha256`. The service does not fetch the artifact URI or
   revalidate external bytes; truthful byte verification belongs to the trusted
   registration process. The payload pins `preview_sha256`, complete
   `payload_sha256`, and both manifest hashes, with exactly
   `restricted_internal_processing_approved=true`,
   `scientific_acceptance=false`, and `public_release_approved=false`.
   The service does not create this approval, authenticate a human reviewer,
   or infer permissions from a checksum. No public UI authorizes this action.
5. Re-run the forecast inside a fresh clean `SERIALIZABLE` import transaction.
   Source drift, governance changes, changed selections, or new revision heads
   invalidate the reviewed preview; obtain a fresh review rather than rewriting
   the old artifact. Any failed occurrence blocks the import. Quarantined
   occurrences remain in the accounting denominator and reasons, but receive
   no selected occurrence/revision/membership rows. Preserve the verified source
   bundle for their full raw provenance.
6. Rehearse with `dry_run=True`. Review its exact post-load parity result and
   rollback outcome. A real shadow write requires a separate explicit decision
   to call with `dry_run=False`; the caller still owns the outer commit.

The planner's work proposals are not permission to merge works. Import requires
the live material, paper and work to exist, and the live paper/work association
to be `accepted` and match the planned work ID. Missing, pending, rejected or
mismatched associations fail; this loader does not create or adjudicate them.
An accepted bibliographic association is not scientific acceptance of a result.

Current catalogue/source holds, retractions, disputes and exclusions are
quarantined. Negative-result condition deficiencies also remain explicit
quarantine reasons. Missing Tc is not manufactured into a negative sample;
unknown pressure does not become ambient. SQL shape checks and offline parity
do not replace experimental validation or expert review.

## Source diagnostics, interpretation revisions, and time

Stable occurrence identity excludes only the mapper's reserved derived
annotations: `result_classification`, `pressure_semantics`,
`property_evidence`, `anomaly_review`, `visibility`, `structure_evidence`,
`ingestion_capture`, and `temporal_provenance`. Other raw scientific fields
remain identity-bearing. Full captured raw variants and original ordinals stay
in the selected snapshot membership, so exclusion from identity is not silent
loss of audit evidence. Duplicates never count as independent confirmation.

Identity, raw source and locator fields are separated from interpretation JSON.
Interpretations retain pending typed proposals and parser/mapper diagnostics;
capture and temporal-provenance envelopes are excluded from interpretation
identity. The service enforces the current exact claim-field contract rather
than accepting arbitrary extra fields as new scientific labels.

For unchanged occurrence, mapper version and interpretation content, reuse the
exact previous revision, even if another later revision exists. A changed
interpretation appends a new pending revision with an exact predecessor; it
does not overwrite the old interpretation or retarget historical memberships.
A changed identity-bearing raw result is a different occurrence, not an edit
to the old raw observation.

`available_at` must remain null for this legacy import. Export watermarks,
work-first dates, capture times and source-provided temporal annotations cannot
establish result-level known-by time. Existing source-version review does not
automatically carry over to a shadow interpretation. The separate reviewed
witness and dependency policies in [Temporal consumers](TEMPORAL_CONSUMERS.md)
are still required; no historical feature eligibility or LLM-pretraining
contamination claim is made here.

## Transaction, retry, and receipt semantics

The caller must use a clean dedicated `SERIALIZABLE` session, not mix unrelated
writes into the import transaction. The loader owns a savepoint and requests a
nonblocking transaction-scoped advisory lock. A busy response means retry the
whole operation in a fresh transaction; it is not permission to bypass the lock.
The revision-history assessment is bounded and fails closed if its limit is
exceeded.

Writes use insert-or-verify-identical semantics, never overwrite upserts.
Before a receipt is written, the loader re-reads exact shadow rows, compares
their fields, recomputes hashes, and records pinned row IDs/hashes. Source
occurrence accounting always reconciles to `reused + inserted + revised +
quarantined + failed`; repeated occurrences remain visible in that denominator.

`dry_run=True` rolls back all loader writes through its savepoint. An exception
also rolls back loader writes. With `dry_run=False`, success releases only that
savepoint; it does **not** commit the caller's outer transaction. Consequently a
returned `committed=false` is deliberate. Serialization failures require a full
outer rollback and fresh transaction, not retrying a statement in a failed
transaction. Close the dedicated session to release transaction-scoped locks.

A receipt replay validates the same approval artifact, complete verified-payload
binding, original selected row IDs and pinned row hashes. It inserts zero new
rows and returns the original accounting. It does not switch an old receipt to
the current interpretation head and explicitly reports
`current_eligibility_reassessed=false`. Replay success proves retained historical
integrity within this protocol, not current eligibility or dataset readiness.
Reassessing current governance is a new preview, not mutation of the old receipt.

## Canary limits and remaining operational gates

The verifier accepts at most 1,000 raw occurrences, 1,000 material rows and
2,000 paper rows (and bounded mapping rows), with 8 MiB per file, 2 MiB per JSONL
row, 64 MiB combined source/plan bytes, JSON depth/node limits and bounded
formula text. These are engineering canary caps, not approved scientific quotas
or evidence of representativeness. Duplicate records count toward 1,000. The
service additionally limits its complete serialized verified payload to 64 MiB.
Exceeding any limit rejects the operation; nothing is silently sampled.

The existing exporter exports every paper row, so even a small material subset
can exceed the paper or byte caps. **Do not slice files, invent a new capture
identity, edit counts or licenses, or reseal a subset and call it the original
transactional export.** A controlled, authorized canary export or reviewed clone
with truthful capture provenance and complete work/source dependencies remains
an operational gate. Any separate selection/export workflow needs its own
review; this increment does not implement or approve it.

Before an actual run, the operator must establish environment authority, source
access/retention permissions, truthful canary provenance, independent processing
review, backup/recovery procedures, exact rollback and commit checks, and
appropriate database privileges. Public publication, canonical result/event/state
promotion, full-corpus import, scientific QC, reviewed temporal availability,
dataset release and leakage-safe ML training remain separate gates. Development
tests and summary verification output are not substitutes for those decisions.

## Code and related documents

- [Offline verifier](../scripts/verify_shadow_import.py)
- [Internal service](../api/services/shadow_import.py)
- [Shadow schema](../api/models/research_import_v1.py)
- [Migration 0053](../api/alembic/versions/0053_research_import.py)
- [ML Foundation](ML_FOUNDATION_PHASE1.md)
- [Temporal consumers](TEMPORAL_CONSUMERS.md)
- [arXiv capture provenance](ARXIV_CAPTURE_PROVENANCE.md)
