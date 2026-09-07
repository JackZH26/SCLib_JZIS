# Bounded research integrity capsules

Issue: ML04 / #64. Schema: `0054_research_release`.

This is an internal, bounded freeze of existing research rows and their declared
dependencies. It is not a second scientific-object registry, automatic promotion
of shadow proposals, a public release, or proof that a dataset is suitable for ML.
The service has no HTTP write route, provider calls, production execution CLI,
source extraction, or automatic outer transaction commit.

## What is frozen

The root is an existing `ml_dataset_snapshots` record containing 1–100 examples.
The server enumerates actual database rows using a versioned policy, rather than
accepting a caller-supplied list of scientific inputs. The closure includes:

- Every example and its feature input rows, target claims and their QC records.
- Referenced events, their claims, properties and evidence, with exact composite
  event/material/result/revision associations.
- Sample/state/structure records, producer and parent runs, settings and artifacts.
- Source snapshots and their event memberships; referenced papers, works,
  bibliographic mappings, material identities/ancestry and explicit chunk records.
- Explicitly selected source-version witnesses or shadow import memberships and
  receipts, including the receipt's pinned row dependencies and revision ancestry.
- At least two explicit policy artifacts, intended to retain the task and registry
  contracts, and a separate exact processing-review artifact.

The fixed wire specification covers 28 existing tables. User profiles and
credentials are not traversed; reviewer IDs are opaque actor references.
`services/research_release_spec.py` is a frozen dependency of migration 0054,
not a live ORM export. Future schema changes must introduce a new versioned
specification and migration rather than change this file's contract in place.
JSON metadata and arbitrary text are preserved but are not automatically parsed
as additional authoritative dependencies. The declared relational and receipt
policy cannot discover undocumented scientific inputs. In particular, retaining
policy documents does not validate their scientific adequacy or implement ML06's
task-specific feature/split checks.

Each pin stores the actual table/key, full UTC-rendered SQL row and a separate
canonical full-row hash. Existing `record_sha256`, source hashes, interpretation
hashes and file hashes keep their different meanings; none is substituted for
the full-row hash. Tc remains in `material_claims`. RPS is not a target label.

## Four additive tables

| Table | Role |
| --- | --- |
| `research_integrity_epoch` | Singleton serialization generation for protected research writers and freezes; not scientific evidence |
| `research_releases` | Immutable internal capsule manifest, dataset reference, hashes and creation-transaction identity |
| `research_release_pins` | Exact copies of existing canonical or selected shadow rows, not new observations |
| `research_release_notices` | Append-only reviewed correction, withdrawal or supersession notices separate from historical manifest bytes |

`scientific_acceptance` and `public_release` are permanently false on capsules;
the portable manifest also fixes `ml_training_approved=false`. The service does
not set the legacy dataset's `status` to `frozen`, or make existing legacy
`frozen` flags sufficient for research access. ML07 still owns release admission.

## Database protection and concurrency

Protected scientific/dependency writers share a nonblocking transaction-scoped
advisory lock and update the serialization epoch. The same mechanism applies to
direct SQL, including child insertion, update, deletion and truncation. A stale
REPEATABLE READ or SERIALIZABLE transaction must fail/retry instead of performing
a cycle check against an old snapshot. Existing scientific writers may still use
READ COMMITTED; release creation itself requires SERIALIZABLE.

The database rejects multi-hop scientific `derives_from` cycles and run-parent,
structure-parent and event-supersession cycles. Reciprocal supports/refutes/context
links are not automatically treated as computation cycles. Relational containment
also has legitimate cycles: an event owns a property and the property references
its event. Closure traversal and scientific DAG checking are different operations.

Pinned scientific rows cannot be updated or deleted. New owned dependencies
cannot be appended to a pinned event, example, dataset or relevant source
snapshot. A new event revision may reference an old event without modifying it.
A new source snapshot can capture the same event; membership protection follows
the owning snapshot, not a blanket prohibition on referencing a frozen event.
Source witnesses/captures selected for a historical capsule remain fixed even
when later witnesses are registered separately.

Material/paper/work/mapping/chunk catalogue copies remain immutable *inside the
capsule*, while live catalogue updates remain possible. They do not acquire the
global research-writer lock, so freezing does not serialize ordinary catalogue
ingestion or prevent a current retraction flag. SERIALIZABLE capture preserves a
consistent historical view; a concurrent catalogue update can logically follow
that view. Historical inspection is not current-governance reassessment.

Pin insertion checks the actual canonical SQL row and exact membership in the
immutable manifest. Pins can only be assembled in the parent's creation
transaction. Deferred parent checks require the complete distinct pin set,
matching dataset root and example count, supported exact foreign-key references,
all current owned child rows and declared shadow-receipt dependencies. Thus a
direct SQL caller cannot omit an existing owned input merely by shortening the
manifest. These checks do not authenticate a human or inspect external files.

UPDATE/DELETE/TRUNCATE of release history is rejected. Populated release history
prevents downgrade. Ordinary DML cannot bypass these safeguards with an ad hoc
session setting; privileged owners disabling triggers remain outside the threat
model. Existing derivation/ancestry cycles fail migration preflight without
silently deleting or repairing evidence.

## Review and actual bytes

All referenced evidence artifacts must have verified byte hashes, and their
actual bytes must be supplied. Selected source captures require their bytes too.
Missing/unavailable files are not replaced with metadata or empty stand-ins.
The processor verifies the byte hashes; it does not execute imported files or
follow their network locations. Source retention/processing permission is a
separate prerequisite, not inferred from byte availability.

The sequence is:

1. Build `preview_research_release` in a clean dedicated SERIALIZABLE session.
   The preview rolls back its savepoint, including the temporary epoch update.
2. Independently review the full preview, source scope, pending statuses,
   restrictions and dependencies. Close the read transaction during human review.
3. Register the exact processing document in `evidence_artifacts` using schema
   `research-freeze-processing-review/1.0.0`. Its actual canonical document bytes,
   record hash and `metadata.shadow_freeze_review` must match. The document pins
   the complete preview hash and approves only restricted internal processing.
4. Call `freeze_research_release(..., dry_run=True)` in a fresh transaction.
   Live source/dependency changes invalidate the old review. No checksum helper
   creates authority or authenticates the registrar/reviewer.
5. Only after separate authorization, call with `dry_run=False` and inspect the
   report before committing the outer transaction. The service never commits it.

The processing-review row is a separate isolated root so its document can pin
the preview without a self-referential hash. Final verification removes only that
isolated row to reconstruct the reviewed base. A scientific decision artifact
cannot be silently removed through this mechanism.

The application verifies exact post-write pins and forces the deferred
completeness checks even in dry runs. Failure rolls back its own savepoint. Busy
or serialization failure requires a full outer rollback and a fresh transaction.
Identical freeze retries insert no duplicate capsule or pin. Technical lock/epoch
bookkeeping may advance on a successful non-dry retry, but scientific history does
not. No generic delete-based post-commit rollback is provided.

## Offline bundle and historical inspection

The portable bundle is a canonical UTF-8 `manifest.json` (no trailing newline)
and exactly the required `<sha256>.bin` artifact leaves. The manifest embeds the
bounded row set, explicit roots, closure-policy version and byte inventory.
The manifest hash and bundle-binding hash are distinct. The latter hashes
`{"manifest_sha256": ..., "artifacts": ...}` using the same canonical JSON rule;
it is not a tar/ZIP file hash.

Offline check template, requiring real local paths and an independently retained
manifest hash:

```bash
api/.venv/bin/python scripts/verify_research_release.py \
  --manifest /absolute/local/research-capsule/manifest.json \
  --expected-manifest-sha256 '<independently-pinned-sha256>'
```

The CLI has no database/network calls and emits metadata only. It rejects unsafe
paths/aliases, unexpected files, capture mutation, duplicate JSON keys, nonfinite
numbers, field/type/version mismatches, broken exact references, missing byte
leaves and scientific derivation cycles. It reconstructs the closure over the
pinned capture; it cannot prove that an entirely re-created and rehashed capture
has not omitted an unknown database record. Independent pinning and the server's
guarded enumeration are essential.

`inspect_research_release` checks retained manifest bytes, actual supplied artifact
bytes and exact pins. It does not move an old release to newer interpretations or
reassess current eligibility. Reviewed notices are returned separately and their
record/document/reference bindings are checked. Their external review files are
not re-fetched during that read, and reviewer identity is not authenticated by a
hash check; those limitations are explicit in returned metadata.

`append_release_notice` requires the exact independently registered notice review
and actual document bytes. Notices never rewrite the original capsule. Automatic
propagation to projections, caches, public warnings or releases is SC08 work and
is not performed by this helper.

## Limits and unresolved operating gates

Caps: 100 examples, 1,000 total rows, 200 unique byte artifacts, 8 MiB per manifest
or leaf and 64 MiB combined, plus JSON depth/node limits. The server checks
expanded SQL JSON byte sizes before fetching row bodies and maintains a cumulative
unique-row budget. This bounds client transfers, not the database CPU needed to
serialize a very large legacy value. Constraint graph scans and manifest lookup
costs still need representative staging/load measurements.

This is not the operational release pipeline. Before a real run, confirm source
rights, environment/role authority, backup and recovery, truthful canary selection,
independent review, and service/dependency-writer retry behavior. No production
migration, scientific data freeze, artifact redistribution or full-vector export
was executed during development.

**Do not freeze unresolved live canonical rows expecting to approve them by an
in-place update later.** Scientific pins prohibit that update. Until reviewed
canonical revision/promotion contracts are available, diagnostic exercises belong
in an authorized isolated clone. Pending shadow interpretations cannot be turned
into accepted target claims by freeze success. Source-review supersession,
scientific property validation (ML05), task/leakage admission (ML06), recursive
permissions (ML07), real pilot review (ML08) and public correction propagation
(SC08) remain separate gates.

See [schema rollout](SCHEMA_ROLLOUT.md), [shadow import](SHADOW_RESEARCH_IMPORT.md),
[source provenance](SOURCE_PROVENANCE_REGISTRY.md) and
[temporal consumers](TEMPORAL_CONSUMERS.md) for adjoining boundaries.
