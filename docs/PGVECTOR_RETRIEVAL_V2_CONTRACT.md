# Retrieval v2 implementation contract

Status: development, not a production cutover. This document separates the
implemented native capture component from the remaining P3/P4 contract. The
[migration plan](PGVECTOR_MIGRATION_PLAN.md) acceptance gates remain binding.

## Implemented: retained inputs and native revisions

Migration `0107_retrieval_native_v2` adds `retrieval_input_receipts_v2` and
`retrieval_native_revisions_v2`. No provider resource/generation is created.
Existing v1 generations, resources, manifests and activation history are not
rewritten or relabelled as a test backend.

An input receipt observes a complete retained regular file under an explicit
archive root. It binds its actual byte count/SHA-256, optional delivery count
and checksum, source paper snapshot, representation scope, parser/chunker
versions and observation time. Files are neither copied nor deleted. Absolute
paths, parent traversal, symlink escapes, empty/oversized files, changed files
and mismatched delivery evidence are refused. The database stores metadata,
not another copy of the input file.

`abstract`, `full_text` and `structured_record` describe different retained
parser inputs. A complete retained input does not establish completeness of
the publisher's whole work, source-use permission, an original publisher root
or scientific acceptance. Archive locators are private operator metadata.

A native revision binds that input to the exact current chunk, paper snapshot,
RAG evidence, complete document embedding receipt, original float32 bytes and
all their hashes. Its `rv2_<revision-hash>` member identity includes the input
receipt binding. Retained legacy windows cannot be labelled as native inputs.
Parser labels such as `unknown` are refused. Original-root, permission and
scientific-review fields remain under their existing evidence contracts.

Input/revision history is append-only, has no foreign key to mutable Chunk,
and survives mutable chunk deletion. Preview and exact replay preserve state;
the caller owns the outer transaction. The capture component performs no
provider call, content publication, activation or backend selection.

Observation timestamps use canonical UTC text. The v2 record hash normalizes
bytea to hex before hashing; session timezone and `bytea_output` cannot change
its meaning. The original v1 hash functions and records remain unchanged.

Actual local checks: 104 native and existing generation/receipt tests passed
on fresh owned PostgreSQL 16.15 services, plus the complete schema rehearsal.
The latter verifies empty 0107 roundtrip with all rows/functions/triggers,
actual synthetic capture on the migrated schema, no provider generation
creation, and a nonempty downgrade refusal with complete before/after parity.
The synthetic native receipt is separate from the existing schema-rehearsal
format and explicitly grants no deployment/scientific authority. Linux 16.13
checks must independently pass before deployment.

Do not release this migration by itself while an old exact-head standby can
restart against it. API, migration, ingestion and standby images/configuration
must be coordinated at the later rehearsed maintenance/cutover stage.

## Content membership and remaining backend registry

The 0108 component now implements independent content references, bounded native
paper publications, partition manifests and complete-source seals; see
[content v2](PGVECTOR_CONTENT_V2.md). None is installed in production. Backend
build/validation, activation and operational publication queue work remain.

- A content version materializes immutable member references. The first import
  references the complete sealed v1 generation. Later versions reference
  retained v1 members and captured native revisions, retaining their different
  provenance and missing-parent status. Original text is not copied for a
  legacy reference.
- Bounded partitions contain at most 1,000 members. A partition seal
  hashes ordered member ID, paper ID, revision/content/vector hashes and origin
  binding. The root hashes ordered partition ID, count and manifest. Separators
  cannot occur in identities. Immutable source bindings are checked before
  sealing; counts alone are insufficient.
- For the first import, all unique allowed members must come from the exact
  source generation and the final inventory must equal its complete membership.
  A later native batch must equal its sealed base minus explicitly replaced or
  removed papers plus all revisions in the frozen publication events. Arbitrary
  subsets cannot validate their own declarations as complete content.
- Publication events bind actual inputs, current evidence and real embedding
  receipts. No fresh Vertex resource is invented for new papers. Unchanged
  members/vectors are reused. Changed provenance with identical text needs
  explicit receipt-reuse lineage, not a fabricated new provider observation.
  This reuse/publisher path is not implemented by the capture module alone.
- A backend build binds content, embedding profile, cosine/float32 rules,
  extension and implementation versions, signed image identity, graph and
  validated query parameters, and complete manifests. Its physical SQL objects
  derive only from canonical build IDs in a dedicated projection schema.
  Public request/configuration strings cannot provide SQL object names.
- Runtime API roles read projections. A separately scoped builder performs
  bounded DDL/import. The API cannot grant itself DDL. Before validation, a
  projection is sealed against INSERT/UPDATE/DELETE/TRUNCATE. Complete readback
  then checks every declared member, actual vector bytes, all bindings, missing
  and extra rows; the index must be valid with the declared parameters.
- Long construction/readback operations must not hold the global source-write
  fence. Content/projections are immutable; current lifecycle and permission
  overlays remain independent. Activation is a short transaction after fresh
  validation, using the exact expected predecessor event.
- Activation/rollback append events and move a guarded current pointer.
  Transition from v1 compares its actual generation/event/manifest. The v1
  pointer is retained for history, and old writers cannot change the effective
  corpus after v2 takes authority. A local previous build is the immediate
  rollback; user writes are not restored from an old whole-database backup.

The operational publication queue, full-scale content import, backend registry,
projection validation, activation/CAS and local rollback still need to be
implemented or exercised. The bounded paper/content seals do not grant backend
activation authority.

## Remaining: readers and historical compatibility

A v2 pin has an explicit version, content version, backend build, activation
event, manifest and embedding profile. It is not a v1 generation with renamed
resource fields. The authoritative active build comes from the database.

Search, Ask, Similar, lexical/formula lookup, scientific routes, hydration,
evidence selection and caches must use the same pin for the whole request.
Candidate hashes must match authoritative members before text can influence
results. Live permission, source lifecycle and currentness checks remain in
force, including a final check before an answer is published.

The SQL transport prototype is currently unwired. Its projection spec is only
an address. Integration must select a database-validated build, reserve a read
pool/concurrency budget across all workers, enforce the validated query policy
and apply the existing evidence/rights checks. A filtered graph budget
exhaustion cannot masquerade as a successful empty result. Small filtered
cohorts use bounded exact computation.

Public read metadata, saved-answer receipts and frontend validators need a
versioned v2 path. Saved v1 answers retain their exact identities and hashes;
history resolves immutable content directly without requiring Google ANN.
Mixed v1/v2 result sets are inadmissible. Backend names and graph tuning are
operator details rather than ordinary page controls.

Canary/shadow/primary modes must distinguish backend selection from authoritative
build identity. Any temporary Google fallback reruns a complete equivalent v1
selection and reports its actual identity. It cannot serve newly native content
from an older Google corpus. Fallback must be off before the seven complete
stable days preceding current Google retirement.

## Current quality findings and language compatibility

The initial fixed 200-input full SQL comparison is retained unchanged. For
`m=16, ef_construction=64`, mean recall@20 was 0.734 / 0.90625 / 0.91825 at
`ef_search=100 / 400 / 1000`; none met 0.95. Boundary-tolerant recall gave the
same result, so ties do not explain the gap. A denser isolated build is being
measured. These are not production-quality acceptance results.

There are only 162 distinct provider vectors: the 40 different Chinese inputs
mapped to two vectors. Google documents `text-embedding-005` as an English/code
model. This is consistent with the observation; it does not prove relevant
Chinese retrieval. [Official model documentation](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/embeddings/get-text-embeddings)

Keep the original failed probe and its exact references. The user subsequently
limited acceptance to English on 2026-11-02. Chinese normalization/evaluation
has stopped and is excluded from migration acceptance. Its earlier diagnostic
artifacts remain unchanged. Do not mix embedding models merely because they
both have 768 dimensions.

The English-only set has been frozen separately: 160 unchanged original
English/formula queries and 80 supplemental English queries. No Chinese query
contributes to its metrics. On the original 160 English inputs, m32/ef200 with
ef_search=1000 achieved mean recall@20 0.99875, minimum 0.95. Full 240-input
evaluation is pending. This neither grants human relevance labels nor proves
filtered, full-service or production quality.

Google currently schedules `text-embedding-005` retirement for 2027-04-01.
Record a separate embedding-space migration before that date; changing the
entire document space is not part of this engine replacement.
[Official lifecycle](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/model-versions)

The existing 100-case author-curated SCWiki routing benchmark is useful for
SCWiki regression, not the required 240-case human-labelled paper-relevance
benchmark. Paper relevance, 60 Ask and 60 Similar cases, full website/load
checks, actual native increment/revision replay and role/backup/maintenance
rehearsals remain separate acceptance gates. None is marked passed here.
