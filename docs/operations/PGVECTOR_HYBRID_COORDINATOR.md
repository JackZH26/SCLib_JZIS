# Content-pinned hybrid candidate coordinator

The opt-in `ContentRetriever` joins the v2 authority, pgvector transport,
lexical/formula navigation, retained hydration, rank fusion and existing
deterministic reranker. It selects the database's exact active content, build,
activation event and frozen query policy. Caller mappings and physical table
names cannot supply that authority. Each SQL stage owns a short read-only,
repeatable-read session; the navigation connection is returned before waiting
for embedding I/O. The application must provide a separately reserved ANN pool
and one shared coordinator per event loop.

`query_embedding` calls only the existing Google text-embedding-005 service,
with `RETRIEVAL_QUERY`, 768 dimensions, explicit no truncation, a five-second SDK
timeout and one attempt. Local input bounds and explicit provider completeness
statistics remain required. It never reads a Matching Engine endpoint or
deployment setting, constructs an ANN client, or uploads document vectors.
Removing index hosting does not remove the existing embedding service.

Four dedicated embedding workers bound running calls and pending submissions.
A cancelled request retains its worker permit until the real synchronous SDK
call ends. Queue wait is inside the provider deadline; circuit isolation and
metrics use the existing provider wrapper. The old wrapper's default execution
path remains unchanged. The application must close the coordinator during
teardown; SDK timeouts and worker admission remain bounded if a caller leaves.

The hybrid operation keeps one v2 identity through semantic and lexical
retrieval, exact candidate binding verification, hydration and reranking. A
changed activation, incompatible policy, missing origin, invalid provider
response or failed SQL branch discards the complete result. It cancels and
awaits sibling tasks. There is no implicit Google ANN or partial lexical
fallback, result cache, activation, history insertion or DDL here.

These are private candidates, not permission or scientific acceptance. Public
orchestration must still apply live evidence/rights, grouping and the fresh
final-currentness barrier before publishing. V2 scientific execution, saved
answer receipts/history, Similar aggregation and native publication orchestration
remain separate integration work. This component alone does not switch routes.

Fresh owned-service tests exercise real legacy/native SQL hybrid reads,
detached v2 identity, provider-independent ANN, stale/forged authority,
activation during provider I/O, failure/cancellation cleanup and frozen-policy
refusal. Provider tests mock actual network calls while checking the SDK
configuration and malformed/truncated vectors. A real worker cancellation test
verifies that cancellation cannot admit overlapping SDK work beyond capacity.
