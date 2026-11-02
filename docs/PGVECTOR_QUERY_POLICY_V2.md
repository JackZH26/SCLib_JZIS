# Bounded SQL candidate policy v2

This is an unwired transport component. A projection address is not a database
validation/activation record. Backend authority, dedicated runtime pool/role
configuration, request pins, hydration/rights/cache/history/frontend and
publication integration remain required before public route cutover.

The owned full-corpus English diagnostic found one strict-iteration query with
zero recall despite an overall 0.99229 mean. That result remains recorded.
Changing only to a bounded relaxed scan followed by an exact distance sort
recovers late closer candidates. The materialized pool contains at most 1,024
candidate IDs/bindings/distances, not another copy of their text or vectors.
Output is ordered by actual cosine distance and canonical member ID. Filters
remain inside the candidate CTE. Small filtered cohorts still use bounded exact
computation; graph exhaustion cannot be a successful partial filtered result.

The frozen evaluation policy is m32/ef_construction200, ef_search1000,
relaxed_order, pool1024, work_mem8MiB, scan_mem_multiplier1 and max_scan20000.
The SQL statement budget remains two seconds; queue/pool/SQL share the existing
three-second request deadline. `QueryBudget` rejects a candidate pool that
cannot expand beyond ef_search. The backend registry must bind the selected
policy rather than letting ordinary requests select arbitrary settings.

Measured on the isolated restored PostgreSQL 16.13/pgvector 0.8.7 database:
240 distinct English query vectors against all 1,183,943 declared source
members, mean recall@20 0.99895833, minimum 0.95, no failed query. The 160 reused
exact references match the identical query-vector and source hashes; 80 new
references independently scan the complete byte-verified source. Temporary
exact-reference vectors were removed after durable references, preserving all
source content and retained vectors. The policy SHA-256 is
`54125fcefefcd65e04898504ced5c8a2a7e5f8915c2553435e13d8e486a018f6`.
Docker/psql process roundtrip p95 was 0.561 seconds, not public API latency.
Filtered cohorts, human-labelled nDCG, Ask/Similar, site/load and recovery gates
remain unmeasured. Chinese is excluded by the user's scope amendment.

Projection names now derive from canonical build UUIDs in the dedicated
`retrieval_projection` schema. The transport creates no schema/table, accepts
no DSN, and grants no permissions. Only the separately scoped builder may own
DDL; runtime readers require read privileges. A later registry must resolve
and validate that actual build before calling this transport.

Local owned PostgreSQL 16.15 extension/transport checks include reuse of the
same physical connection to verify that transaction-local HNSW, memory and
timeout settings reset. The frozen evaluation is evidence for this candidate
policy, not production activation or scientific approval.
