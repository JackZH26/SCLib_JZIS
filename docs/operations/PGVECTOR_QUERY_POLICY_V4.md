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
