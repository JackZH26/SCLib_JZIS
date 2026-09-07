# Exact-source impact inspection — SC08, version 1.0.0

Date: 2026-09-07. Local schema head: `0057_source_impact`.
Issue: [SC08 / #66](https://github.com/JackZH26/SCLib_JZIS/issues/66).
Prerequisite: [Observed source lifecycle ledger](SOURCE_LIFECYCLE_LEDGER.md).

## Outcome

An operator can inspect which explicitly identified catalogue objects and
historical release references are potentially affected by a current Paper/Work
lifecycle event. The bounded, indexed inventory includes record-backed material
candidates even when no Timeline point exists. Its deterministic relationship
fingerprint changes when the covered dependency graph changes, even if the
source lifecycle event stays the same.

This is an **on-demand read-only impact plan**, not a persisted processing
receipt, dependency database, refresh queue or proof of scientific dependence.
Every next action is `not_scheduled`; `propagation_complete`,
`scientific_acceptance`, `ml_training_approved` and `source_reinstatement` are
false. The existing negative admission guards remain authoritative. No scan
clears a source hold, revises a claim or modifies a frozen capsule.

The initial plan to connect refresh tracking was narrowed after inspection:
the existing Timeline loop performs a global SQL refresh and separate best-effort
Redis invalidation. It cannot provide an atomic per-source-version acknowledgement
across SQL, caches, vectors and datasets. A useful next worker must consume an
explicitly bounded inventory and revalidate its graph, rather than treating one
successful global refresh as completion of source propagation.

## Declared exact-ID scope

| Relationship | Inventory meaning | Important limit |
| --- | --- | --- |
| Paper event → that Paper | Direct source anchor | Never fans out to sibling papers through a shared Work |
| Work event → accepted current Paper/Work maps | Conservative source-identity inheritance | Pending/rejected maps excluded; no formula/title inference |
| Paper/Work → explicit claim FKs | Source-linked claims to inspect | Does not accept or invalidate the scientific result |
| Paper → `materials.records[].paper_id` | Record-backed material candidates | Exact typed JSON containment; no string trimming or malformed-ID repair |
| Record-backed material → descendants | Child views inherit parent governance | Only explicit parent IDs; depth/cycle/resource guards apply |
| Claim → its material ID | Claim-view material context | Does not prove that material records contain the claim; not a new record-backed propagation root |
| Paper → chunks/hydride rows | Direct source references to inspect | No text loading, vector update or inferred hydride material relationship |
| Paper/material → Timeline rows | Existing projection references, including inactive rows | Projection rows are not the source of zero-point candidate discovery |
| Claim/Work/record-backed material → ML examples | Explicit label, Work or material-governance references | Not transitive feature lineage; not permission to rewrite labels |
| Example → dataset snapshot | Explicit membership reference | No automatic training eligibility or dataset mutation |
| Reached object → frozen release pin | Historical review/notice candidate | Pin bodies are not loaded or rewritten |
| Release → publication proposal | Historical publication reference | Not a live-publication decision, action or withdrawal notice |

The manifest returns its supported and unsupported scopes explicitly. Deferred
coverage includes transitive research-event and ML-feature inputs; provider
revision/capture and shadow-import lineage; indirect extracted-material mentions
in other sources; sample/structure lineage; file-backed RPS; saved answers and
external vector-index state; and dependencies introduced after the snapshot.
An exact identifier may itself contain readable material text: the response
does not promise to redact identifiers. It excludes source bodies and dedicated
formula/Tc/measurement fields, personal notes and frozen scientific row payloads.

`complete_for_declared_scope=true` means every supported query completed within
its bounds in that one database snapshot. It does **not** mean complete scientific
lineage, exhaustive cross-system impact, current public eligibility, actual
refresh completion, or real-world retraction lag. Missing scopes are not zero
affected objects.

## Manifest and currentness

Each response binds:

- A policy version and the exact current lifecycle event ID, record hash,
  source snapshot hash, revision and source identity.
- Sorted unique nodes `(table, row_id)` with sorted relationship descriptors
  `(kind, via_table, via_id)`, per-table counts and Timeline candidate material IDs.
- A SHA-256 over the deterministic inventory body, including scope and limits.
  This is a relationship fingerprint, not a scientific target-row hash or
  authenticated review signature.
- Separate observation metadata: database transaction time, isolation and
  `current_in_database_snapshot`; `persisted=false` and `refresh_scheduled=false`.
- Unscheduled next-action domains for material/Timeline, retrieval context,
  prospective ML membership and historical frozen-reference review.

The observation timestamp is excluded from `inventory_sha256`, allowing two
identical graph inspections to compare equal. A changed edge can change the
digest even if all node IDs and counts remain the same. Bibliographic values or
scientific rows may change without altering graph relationships; this digest
must never substitute for exact source/result hashes in a future execution plan.

A current source event does not freeze the graph. Material records/parents,
accepted maps, chunk source IDs and dataset membership can change independently.
The manifest is true only for the stated snapshot, not forever or necessarily
at the later instant a client displays it. A future worker must revalidate both
the source head and dependency graph before claiming its narrowly defined work
complete. A graph can also change after a manifest is saved locally; no server
receipt or durable queue entry is created by downloading it.

## Internal HTTP interface

These routes are installed under the existing ML Foundation operational switch,
which remains disabled by default. Despite its legacy `public` setting name,
the new routes are private:

```text
GET /v1/ml/source-lifecycle?paper_id=<exact-paper-id>
GET /v1/ml/source-lifecycle?work_id=<work-uuid>
GET /v1/ml/source-lifecycle/<event-uuid>/impact?expected_event_sha256=<exact-hash>
```

Source history accepts exactly one Paper or Work, `limit` from 1 to 100, and an
optional positive 32-bit `before_revision` cursor. It preserves direct history
while separately reporting effective inherited Work holds. Use the current head
ID/hash from this inspection to request its impact manifest.
Impact requires a direct lifecycle event. An untracked Paper whose hold comes
only from an accepted Work can have `head=null`; inspect that accepted Work's
own history instead. The combined `effective_lifecycle_revision` is not an event
record hash and must not be supplied as `expected_event_sha256`. This first
interface does not add an automatic Work-discovery/curator navigation workflow.

A valid browser session or JWT plus an active, verified account and an explicit
live research grant are required. Legacy administrator/reviewer flags are not
grants. The grant/account are checked in the same snapshot as the inventory.
Anonymous access is rejected; revoked grants are rechecked on the next request.
This batch adds no write route, grants, public export or automatic operator.

All responses and errors use `private, no-store`. No conditional 304 path,
ETag, public cache or download redirect can bypass a fresh read. Invalid/currently
unavailable source bindings return a sanitized 409 for impact, missing source
history a 404, invalid parameters a 422, and failed role admission a 403.
Database/read-time failures return a generic 503 without SQL or DSN details.
Over-limit inventories return a 409 with `impact_inventory_incomplete`,
`complete_for_declared_scope=false` and `refresh_execution=not_scheduled`—not
an empty successful inventory or an actionable truncated plan.

## Read and resource boundaries

The service accepts a clean dedicated REPEATABLE READ or SERIALIZABLE session;
READ COMMITTED and unflushed ORM changes are rejected. The HTTP endpoint owns a
REPEATABLE READ, READ ONLY transaction, a 5-second SQL statement timeout and a
10-second asynchronous budget. The service does not change transaction settings,
start a worker, mutate guard epochs, commit, or write an audit record.

Limits are 1,000 mapped Papers, 2,000 total unique nodes, 4,000 relationship
descriptors, material ancestry depth 32 and a 1 MiB serialized manifest. Query
steps use an overflow probe rather than returning an arbitrary first page as
complete. Exact ID/relationship columns are selected; raw source JSON, chunk
content and frozen row bodies are not transferred. The material-source query
uses bound JSONB containment rather than expanding all records into Python.

A connected ancestry cycle or exceeding any depth/row/byte limit makes the
inspection unavailable/incomplete. These caps bound returned data and graph
construction, not a hard PostgreSQL CPU/memory limit or benchmarked query latency.
SQL can still evaluate a large relation before returning its limited rows;
statement timeout, staging measurements and deployment discipline remain needed.

## Index-only migration

Migration `0057_source_impact` adds six reverse indexes:

| Table / column | Index | Reason |
| --- | --- | --- |
| Materials `records` | GIN, `jsonb_path_ops` | Exact source-ID containment, including zero-point candidates |
| Timeline `paper_id` | B-tree | Source reference lookup |
| Timeline `material_id` | Nonpartial B-tree | Include inactive as well as active historical projections |
| ML examples `claim_id` | B-tree | Label-claim lookup without a dataset-prefix scan |
| ML examples `work_id` | B-tree | Explicit Work reference lookup |
| ML examples `material_id` | B-tree | Current material-governance reference lookup |

Existing parent, claim, chunk, accepted-map, release-pin and proposal indexes are
reused. No speculative lineage indexes, new columns, tables, data triggers or
new ledger are added. Frozen migrations/contracts 0052–0056 are unchanged.

This uses ordinary transactional CREATE INDEX, not concurrent index creation.
Staging must measure table size, write-block duration and disk headroom before
deployment. Startup still requires the exact application schema head. An
index-only downgrade removes only these six indexes even when older history is
nonempty; attempting to continue into a protected nonempty ledger is refused
and rolls back the transaction. The migration rehearsal verifies both directions
and compares existing application rows, including old immutable histories.

## Next implementation boundary

The next step is a narrowly scoped, durable request/attempt/receipt protocol
using the exact source and graph fingerprints, with retries, stale/superseded
states and clearly defined target-specific completion. Then connect bounded
executors and measure them in staging. SQL projection, Redis invalidation,
vector maintenance, prospective dataset review and historical notices are
different operations; one successful operation cannot acknowledge all of them.

Positive scientific supersession/reinstatement, result-scoped mixed-source
admission, RG02 post-generation source validation, broader feature/event lineage
and real human-reviewed source cases remain separate unfinished gates. SC08
remains open; no production rollout or propagation SLA is claimed.
