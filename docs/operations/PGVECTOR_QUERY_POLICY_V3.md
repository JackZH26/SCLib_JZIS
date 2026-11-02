# Bounded exact year filtering

Policy `sclib-pgvector-query-policy/3.0.0` is independently identified by SHA256
`c55de6c3f91622ce9ebbc080bf0cb53c90296d2e7aa75eb61d1ba566b86f417f`.
It retains the existing 768-dimensional float32 vectors, cosine metric,
m32/ef200 graph, ef_search1000, candidate pool1024 and20k ANN scan ceiling.
SQL statements remain bounded to two seconds, the transport deadline to three
seconds, and process-wide ANN concurrency to four.

The actual retained corpus exposed low-recall year-filtered queries under the
old ANN policy. Raising the scan ceiling to50k improved averages but did not
reliably repair the complete payload/predicate path. A separate read-only trial
of46 exact year-filter cases, including repeats of the three outliers, matched
the independent exact references in every case. P95 was0.755seconds on the
owned clone (2CPU,24GiB memory,16GiB shared_buffers); largest cohort141,833.
This is engineering evidence, not production or full-service acceptance.

V3 counts at most200,001 eligible IDs when a year bound is present. Cohorts up
to200,000 are scored exactly with a non-ANN distance-order expression and a
bounded top-N sort. Only output metadata and computed distance are sorted;
the query does not materialize every3-KiB vector. Larger year cohorts retain
the bounded ANN path. Source-revision exclusions without a year bound still
count only1,001 rows and retain their original1,000-row exact ceiling, so a
20-source Similar request does not perform twenty200k-row counts.

Migration0115 adds a new build-admission function and rebinds only the build
INSERT trigger. The original v2 function, v2 policy, stored build identities,
content, source rows and saved receipts remain intact. Both registered policy
objects can be loaded by control/history code. The new public reader admits
only V3; it cannot silently apply the new algorithm to an old V2 build.
The builder explicitly requests a policy version, defaulting to V3. A retained
V3 build prevents downgrade to a schema which cannot admit that policy.

Legacy migration proofs explicitly construct V2 fixtures so their original
nonempty rollback guards remain reachable. A final separate V3 fixture proves
the new downgrade refusal without rewriting or deleting older history.

Before serving, create a distinct V3 backend build, perform complete binary and
source readback, repeat the frozen English and difficult-filter cases, and
complete the full-service/load, publication/replay, role/recovery and human
review gates. Current production remains on its original Google backend;
ingestion remains paused and APS originals remain retained.
