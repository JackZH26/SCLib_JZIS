# Inline vector storage and contention acceptance

The retained rehearsal projection stored 4,903,985,152 bytes in its TOAST
relation and 440,860,672 bytes in the main heap. With the frozen m32/ef200,
ef_search1000/relaxed/materialized1024 policy, two of 240 English queries hit
the two-second SQL statement timeout during a complete database backup. A
later quiet repetition had mean recall@20 0.99895833, minimum0.95 and no failed
query. The failed concurrent run remains evidence, not an accepted result.

New private projections now select `STORAGE PLAIN` for the vector and every
bounded ID/hash field before their first binary COPY. Protecting only the
vector caused PostgreSQL to externalize those small metadata fields while
trying to reach its normal TOAST target; the first full-copy trial caught
570,531,840 bytes of such TOAST storage and was rejected. The corrected
layout requires an empty TOAST heap. The stored vector remains 3,080 bytes; all canonical
float32 values and immutable member bindings remain unchanged. The graph and
query policy are unchanged. Existing sealed builds/history are not rewritten
or relabelled. Merely changing a populated column's storage catalog setting
does not rewrite its existing data. Operators must construct and validate a
new physical build, then use the existing guarded activation protocol.

An owned network-isolated full-corpus trial copies the vector datums directly
into a separate inline heap, compares every source/member/hash/vector byte,
then builds an independent graph with identical parameters. The original
source and rehearsal projection remain retained. Disk reserve, memory/CPU and
primary-health observations remain enforced. Construction and source copying
are not evidence that the timeout has been resolved.

Before acceptance, repeat all 240 frozen English queries against the same
exact reference with the two-second SQL budget, then repeat under an actual
owned backup workload and the planned service concurrency. Preserve every
failure and report each workload separately. Filtered cohorts, human nDCG,
Ask/Similar, whole-site/recovery and production-role gates remain required.
A smaller ef400/pool512 prototype lost recall and is excluded.

This follows the documented inline storage option in
[pgvector](https://github.com/pgvector/pgvector#troubleshooting) and PostgreSQL's
[storage settings](https://www.postgresql.org/docs/16/sql-altertable.html).
The performance improvement is a hypothesis until the full trial completes.
