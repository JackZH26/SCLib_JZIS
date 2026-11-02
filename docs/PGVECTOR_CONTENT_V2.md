# Retrieval content v2

This branch implements retained publication/content construction. Backend
builds, projection validation, activation, readers, caches, saved-answer v2,
frontend compatibility and production ingestion wiring remain separate work.
Neither 0107 nor 0108 may deploy independently of the coordinated exact-head
API/migration/ingestion/standby maintenance rehearsal.

The user's 2026-11-02 scope amendment limits search acceptance to English.
Chinese normalization/evaluation is excluded; earlier diagnostic artifacts
remain historical evidence. All other migration gates remain unchanged.

`retrieval_publications_v2` and its member/seal tables freeze a complete current
paper revision. Every member references an actual native revision with its
retained input, evidence and existing complete embedding receipt. The seal
checks every current chunk of that paper, exact snapshot/source hashes and
current evidence links. An honest count for an incomplete subset is refused.
One event supports at most 1,000 chunks; a larger paper fails explicitly rather
than silently dropping chunks. This bound must be revisited with a separately
designed complete partition protocol if actual ingestion needs larger papers.

The paper seal uses the existing source fence for its bounded currentness
check. A sealed publication records a historical observation; it grants no
rights and cannot override later source holds, retractions or corrections.
The service creates no provider receipt, resource or generation and performs no
provider call. The current implementation requires an already complete receipt
bound to each exact native chunk/evidence revision.

`retrieval_contents_v2` and its change/member/partition/seal tables separate
content membership from an ANN provider. The initial content references every
member of one complete retained v1 generation. Later batches reuse a sealed
base, omit all old members of each explicitly replaced paper, and include all
members of that paper's selected sealed native publication. A new paper uses
the same path. Each batch selects at most one event per paper. Removal-only
events and ingestion queue authorization are not implemented by this module.

Content members store references and binding hashes, without copying original
text or vectors. Legacy references preserve their exact generation/member IDs;
native references preserve actual native revision IDs. The trigger derives
paper, chunk and hash fields from the referenced immutable authority, and
admits only the declared source universe. All identifiers are unique within
the content version. Current source-use decisions remain independent of this
historical inventory.

Partition writes and seals lock their content row, not the global source
fence. After the first member is staged, the change plan cannot expand.
Partitions contain 1..1,000 members; their ordered hashes bind every reference,
origin, paper, chunk, content/vector/revision digest. The root binds the ordered
partition IDs, counts and manifests. A final independently counted source
universe, unique admitted members and complete partition seals prevent a
caller from validating a self-declared subset. The safety cap is five million
members; raising it requires new capacity validation.

Internal services default to preview and leave the outer commit to the caller.
Exact replay verifies retained record hashes and changes no rows or epochs.
Partition inserts use bounded executemany and a single bounded replay inventory,
avoiding millions of Python round trips. `source_reference_page` uses keyset
pagination over the source universe. These services are not exposed as public
write APIs and do not authenticate an operator by themselves.

All publication/content history is append-only. Downgrade refuses any retained
row. The owned migration rehearsal compares all old rows/functions/triggers
across the empty boundary and before/after a populated downgrade refusal.
Synthetic native addition and same-paper reference replacement tests do not
qualify as the required real ingestion/revision publication, whole-site
acceptance or scientific review. Linux 16.13 CI must pass independently of Mac
16.15 tests before any production deployment.

The original [migration plan](PGVECTOR_MIGRATION_PLAN.md) quality, rollback,
website and seven-complete-day gates remain in force. Content seals are not
backend validation or activation authority.
