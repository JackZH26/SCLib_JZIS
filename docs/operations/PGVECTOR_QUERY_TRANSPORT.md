# pgvector candidate transport

Implementation: `api/services/pgvector_query.py`. This is the first P3 read component. It is not connected to public routes and is not a production publisher, a build validator or an activation coordinator. The existing v1 generation records, resource objects, manifests and public retrieval metadata remain unchanged.

`ProjectionSpec` contains canonical build and content-version UUIDs plus a content manifest. It is an address only. A future database registry must bind these fields to an independently validated backend build. SQL table names are derived only from the build UUID: `public.retrieval_vectors_<32 lowercase hex digits>`. Callers cannot provide SQL object names.

The publisher must create one sealed table per build with these columns:

| Column | Type and meaning |
| --- | --- |
| `vector_id` | Immutable member ID; text primary key |
| `paper_id` | Authoritative paper identity; text |
| `year` | Retained source year or null; integer, indexed |
| `content_sha256` | SHA-256 of the exact member text |
| `vector_sha256` | SHA-256 of original canonical big-endian float32 bytes |
| `chunk_revision_sha256` | Immutable evidence/receipt/snapshot binding |
| `embedding` | `vector(768)`, original float32 values |

This transport supports the retained `text-embedding-005` 768-dimensional cosine space. It does not generate embeddings or infer a compatible space from a dimension alone. Query provenance and profile equality must be checked by the read coordinator before calling it.

The process must reuse one `PgvectorQueries` coordinator per event loop, with a dedicated read engine whose connection pool is reserved separately from normal API traffic. Defaults allow four concurrent requests, a three-second total deadline including queue/pool wait, a two-second SQL timeout, 250 ms lock timeout and 8 MiB work memory. Settings are transaction-local inside a read-only transaction. Bounds reject unlimited settings. SQL/database errors expose no statements, input values, DSNs or provider credentials.

Year filters and source revision exclusions execute in SQL. A filtered cohort of at most 1,000 members uses an exact materialized sort; larger cohorts use iterative HNSW with explicit scan and memory budgets. An underfilled large filtered search fails rather than representing graph budget exhaustion as a complete empty result. The small-cohort count and exact query assume a sealed immutable projection; sealing is a mandatory publisher responsibility. An unfiltered ANN result never claims exhaustive retrieval.

Returned IDs, hashes, distances, order, year filters and exclusions are checked as a complete batch. The coordinator must still verify member bindings against authoritative content, apply live source permissions and lifecycle overlays, hydrate immutable evidence, and check the active pointer again before publication. Transport success does not grant rights or establish relevance.

Before route integration, P3 must still deliver the v2 registry and immutable content/native revision contract, complete inventory validation, atomic activation/CAS and rollback, cache identities, historical read compatibility and lifecycle admission. P4/P5 must exercise real incremental publication, the complete corpus, difficult filtered cohorts, relevance/citations, load and the whole website. These gates are not waived by the transport tests.

Actual local validation on 2026-11-02: 29 tests passed using fresh owned PostgreSQL 16.15 / pgvector 0.8.7 services, including the existing seven extension checks. These are synthetic transport/runtime checks, not production corpus or Linux 16.13 acceptance. The pgvector CI job additionally runs both test modules on the frozen Linux 16.13 image.
