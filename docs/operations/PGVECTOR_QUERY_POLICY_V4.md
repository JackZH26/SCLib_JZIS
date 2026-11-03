# Purpose-specific ANN budgets

Policy `sclib-pgvector-query-policy/4.0.0` has SHA256
`51b1c348b6f22039ac76cfd7a7cc3230fe12d6445740cfb3c7bec66748504832`.
It preserves V3 text-query ef_search1000/candidate_pool1024, the bounded exact
year path, m32/ef_construction200, canonical float32/768-dimensional vectors,
four shared SQL slots, the two-second SQL limit and three-second transport limit.

Only a complete stored-source batch uses ef_search256/candidate_pool257.
`query_many` applies this budget to every validated source and retains its one
outer deadline, process-wide semaphore, complete source order, exclusion list
and sibling cancellation. Text Search/Ask continues through the original
larger budget. A batch does not receive another connection pool or SQL permits.
Public readers still require the exact frozen complete QueryBudget object.

This distinction follows the owned full-corpus experiment: reducing the text
budget improved throughput but lost all reference neighbors for some outliers.
Those text settings were rejected. Stored-source fidelity is evaluated against
independent complete exact scoring with whole-paper revision exclusions;
complete HTTP, hydration/currentness and peak-load checks remain separate.
The engineering experiment is not a public acceptance or activation receipt.

Year and exclusion predicates now include only the validated, present bounds
and nonempty exclusion list. Values remain bound parameters and table names
remain derived solely from canonical build UUIDs. The exact cohort ceiling,
full scoring, canonical tie order and failure behavior are unchanged. The
closed predicate avoids nullable OR clauses obscuring an index in a generic
prepared plan. No statement deadline is increased.

Migration0117 adds one new build-admission function and rebinds the INSERT
trigger. V2/V3 policy JSON, digests, functions, physical seals and histories are
retained. All three policies remain readable by control/history code; the new
public coordinator admits only V4. Every V4 projection therefore needs its own
build identity, full binary/source readback and operator evidence. Existing V3
bytes and verification artifacts are never relabelled. A retained V4 build
prevents downgrade to0116, with prior rows/functions preserved on refusal.

This document describes the implementation contract. It does not establish
that any production cutover or performance/quality acceptance has completed.

## Complete source-batch execution

The source coordinator sends at most20 validated vectors in one correlated
LATERAL statement. Each source has its own HNSW candidate frontier, pool257,
EF256 and distance/ID ordering. Year bounds and revision exclusions apply
inside every source scan; a bounded exact cohort is counted once against the
sealed immutable projection. Source order and every neighbor binding remain
validated before any complete batch is returned.

The statement acquires one of the same four global SQL permits. Its two-second
SQL deadline covers the entire source batch; queue and pool wait still share
the three-second transport deadline. Settings are established together and
remain transaction-local. This removes repeated connection/setup round trips
without adding permits, extending a deadline or changing the V4 candidate
policy. A statement or validation failure rejects the whole batch.

Inputs are materialized as typed vector(768) values once per source before
the correlated scans. This preserves the same canonical float32 conversion
while avoiding repeated parsing of each text vector for candidate distances.
The actual20-source profile visited the same HNSW index/pages, with execution
falling from1736ms to249ms for that diagnostic case. This observation is not
a substitute for the affected HTTP load gate.

## Serving process budget

Run four independent single-process API instances behind the retrieval upstream,
with a separately reserved four-connection ANN pool per instance and zero
overflow. Four database transaction advisory permits, in a closed query-only
namespace, limit active ANN work across all instances to four statements.
An instance can borrow an idle permit rather than queue behind its fixed share. Each
instance retains the same bounded coordinator, queue/pool deadline and SQL
limits. Keep metrics on separate scrape targets so counters are not mixed
between processes. Ordinary API pools remain separate from ANN. Background
graph and full-validation processes share two CPU cores and low scheduling
priority. Connection acquisition remains inside the unchanged three-second
transport deadline rather than imposing a separate half-second pool failure.

Authority reuse is limited to one established read-only REPEATABLE READ
transaction. Leaving that scope, replacing/rolling back the transaction, or
checking a different pin requires a new database authority resolution. Source
rights and per-member integrity checks still run. The final selection always
uses a new snapshot, including its first uncached authority check.

Global permits are acquired nonblockingly within the original outer deadline.
Only one successful transaction lock is retained; polling yields to the event
loop. Commit, rollback, cancellation or a lost connection releases it at the
database. Ordinary catalogue reads and publisher roles do not use this lock
namespace. Candidate counts, source exclusions and SQL math are unchanged.
