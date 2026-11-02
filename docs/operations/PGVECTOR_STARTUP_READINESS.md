# Explicit projection preparation before v2 queries

The full-corpus inline layout eliminates TOAST lookups and passed five warm
240-query English trials, including complete durable backup overlap, without a
query failure. However, stopping the owned restored database, advising only its
inline heap/index relation files out of OS cache and restarting it without query
warmups produced **29 SQL timeouts in 240 queries**. Those failures remain
unaccepted. They use the same two-second statement timeout, graph and query
policy as the successful warm trials.

An explicit synchronous `pg_prewarm(..., 'read')` of the heap and indexes took
33.70 seconds on that owned two-CPU/16-GiB clone with 512-MiB shared buffers.
The following 240 queries had no failure, mean recall@20 0.99833333 and process
roundtrip p95 0.784864 seconds. This establishes a measured startup preparation
effect, not permanent cache residency or full-service acceptance. Disk/device
caches may still exist; the cold procedure does not globally drop host caches.

`ProjectionReadiness` adds an explicit preparation stage to the private v2
coordinator. It requires the exact authoritative active pin, a nonempty valid
physical projection and operator-installed `pg_prewarm`. It runs only SELECTs
in an owned read-only session. It does not install an extension, grant a role,
activate a build or warm an arbitrary caller table. It reads the heap and
primary key into OS cache, then loads the HNSW graph into shared buffers. The
graph may occupy at most 80% of configured shared buffers. That budget refusal
is a resource guard, not evidence that a particular runtime has passed load
acceptance.

After warming, a **new** read snapshot must match the content/build/event,
server boot time, physical OIDs, relation file nodes, sizes and buffer budget.
The in-memory ready witness is checked again before the coordinator can start a
query. Restarts, ABA activation/rollback, a graph rewrite, failed preparation or
an overlapping preparation invalidate it. An unprepared query fails before
embedding or ANN; queries do not perform an expensive implicit warmup. The
readiness witness grants no source rights or scientific approval.

The six-GiB shared-buffer profile and full backup-scan interference are being
measured separately on the owned clone, including actual HNSW page residency.
The original discard-output scan reached archive close but failed when trying
to fsync `/dev/null`; preserve that failed command and do not call it a valid
backup. Discard-output diagnostic scans use `--no-sync`. The completed 13.43-GB
durable custom archive used normal synchronization and passed full traversal
and SHA verification. No production backup configuration is changed.

Before public v2 cutover, application lifespan and health orchestration must
prepare the selected build and expose retrieval readiness, including after
backend changes. Bind readiness to the final measured runtime profile and
repeat full-service concurrency, backup and recovery acceptance. A successful
warmup cannot guarantee that later memory pressure will not evict data; measure
that behavior and retain failed trials. Current public routes and `/readyz`
remain on the existing backend until that complete orchestration is ready.

The disposable runner installs `pg_prewarm` only through its admin bootstrap
when `--pgvector` selects newly owned test services. Tests cover real read-only
reader preparation without DDL/superuser, physical REINDEX invalidation, ABA,
server-boot identity mismatch, insufficient buffers and preparation/probe races.

See [PostgreSQL 16 pg_prewarm](https://www.postgresql.org/docs/16/pgprewarm.html)
for `read`/`buffer` behavior and cache-eviction limitations.
