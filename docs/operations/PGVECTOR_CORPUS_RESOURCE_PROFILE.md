# Corpus storage and cache profile

The owned 1,183,943-member retained-corpus trials keep graph m32/ef200,
ef_search1000, relaxed materialized1024, four SQL slots and the two-second SQL
statement policy unchanged. They use the signed PG16.13/vector0.8.7 image and
the same source/vector bytes. These are unfiltered single-client ANN results,
not full-service or human relevance acceptance.

| Owned runtime/workload | Queries | Failed | Process roundtrip p95 |
| --- | ---: | ---: | ---: |
| Inline, unprepared relation-cache cold, 512 MiB shared | 240 | 29 | 2.732 s |
| Inline, explicit OS read prewarm, 512 MiB shared | 240 | 0 | 0.785 s |
| Inline, 6 GiB shared graph prewarm, cold start | 240 | 0 | measured separately |
| Inline, 6 GiB shared, after complete logical backup scan | 240 | 24 | 2.678 s |
| Inline, 16 GiB shared, prepared cold start | 240 | 0 | 0.431 s |
| Inline, 16 GiB shared, after complete logical backup scan | 240 | 0 | 0.808 s |

The six-GiB profile held all 587,997 HNSW pages after preparation but none after
the backup scan. Public source TOAST relations alone occupied about 8.2 GB;
fitting the 4.82-GB graph did not reserve the complete backup working set. The
sixteen-GiB profile used a 24-GiB process limit, two CPUs and seven-GiB dynamic
shared-memory budget. Preparation took 27.65 seconds. After its complete scan,
404,461 graph pages remained; after the following 240 queries, 451,735 remained.
Zero query failures do not mean the whole graph stayed resident or that future
memory pressure cannot evict it.

The private coordinator now refuses larger-than-smoke builds (over 1,000
members) below the measured sixteen-GiB shared-buffer floor. The graph must
also fit its existing 80% buffer guard. This is the conservative admitted
profile for this migration, not a universal pgvector minimum. Exact-build
runtime/resource and quality evidence remain mandatory, including for future
larger native collections.

The separately invoked maintenance Compose override requires explicit signed
image, dynamic shared memory, process memory and shared-buffer inputs. Its
memory-plus-swap limit equals process memory. The ordinary production Compose
database service remains byte-for-byte at its approved baseline until the
coordinated maintenance operation. Do not infer a deployment from this file.

New v2 projections import the nullable publication year in their first binary
COPY. Previously, copying vectors then updating every wide row's year created
another heap version before graph construction. The new bounded eight-field
source format emits seven projection fields, retaining original float32 bits
and exact int4 year, with NULL allowed only for unknown year. The six-column
rehearsal converter remains unchanged. API and owned-host converters are
identical; complete SQL readback still compares every source binding and year.
Sealed builds, original snapshots and historical rows are not rewritten.

The earlier complete durable 13.43-GB custom archive passed traversal/SHA.
Discard-output scans are explicitly diagnostics, use `--no-sync`, and are not
backups. Actual disk-backup contention on the selected final runtime, complete
restore, full-service 8.22-rps replay, filtered/human relevance and whole-site
acceptance remain required. Production backup jobs have not been changed.
