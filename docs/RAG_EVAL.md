# RAG reliability and evaluation

SCLib first interprets a bounded scientific query. Numerical/evidence predicates
and Search UI scientific filters use provider-free, exact-parent extraction
lookup; unsupported scientific clauses require clarification. These records are
not scientific-support judgments. Pure mechanisms/comparisons select only typed
original passages; full mixed synthesis remains unfinished. See
[scientific routing and consumer migration](SCIENTIFIC_QUERY_ROUTING.md).

For ordinary topic retrieval, SCLib uses hybrid retrieval rather than treating
a vector-nearest-neighbour result as sufficient evidence:

1. An active immutable generation is pinned; Vertex semantic and PostgreSQL
   full-text candidates are fetched within that generation. Without an active
   generation, Search/Ask are explicitly legacy lexical-only and Similar is
   unavailable. Positional legacy ANN IDs are not a mutable SQL authority.
2. Reciprocal Rank Fusion combines both lists.
3. A deterministic query-term coverage reranker reorders the bounded candidate
   set.
4. `/search` and `/ask` hydrate exact retained generation members and apply
   fresh source/material/permission holds. Search retains its paper-result
   deduplication. Ask can expand and pack complementary original passages under
   exact catalogue-snapshot and accepted Work diversity limits, with one citation
   per unchanged chunk. Grouping never establishes independent scientific roots.
   Generation mode preserves original attribution after replacement.
5. `/ask` treats excerpts as untrusted JSON data in a system-separated prompt;
   complete ordered inputs must fit both the canonical UTF-8 resource budget and
   actual provider CountTokens limit before generation.
6. Citation-index checks are separate from scientific-support status/coverage
   and answer mode. Deprecated `citation_valid` remains a mechanical/lexical
   compatibility field, not scientific acceptance. Derived Facts and unresolved
   roots do not validate their own extractions. Post-generation checks can
   withhold a draft after source/permission/activation changes.

See [typed evidence](RAG_EVIDENCE_LINEAGE.md) and
[generation identity and rollout](INDEX_GENERATIONS.md), and
[complementary evidence packing](COMPLEMENTARY_EVIDENCE_PACKING.md). These gates do not
establish scientifically calibrated retrieval or source-use permission.

## Public regression set

The small, reviewable seed set is in
`api/tests/fixtures/rag_gold.json`. It covers exact formula/numeric search,
hydride pressure terminology, and cuprate pairing terminology. The unit gate
currently requires 100% top-1 accuracy on this seed set.

Run the reliability gate through the disposable-services safety runner, from
the repository root (Docker backend shown; native requires explicit local
PostgreSQL/Redis binary paths):

```bash
api/.venv/bin/python scripts/run_disposable_tests.py --backend docker --suite api -- -q tests/test_rag_reliability.py
```

This seed set is a smoke benchmark, not a scientific-quality claim. It should
grow with adjudicated production misses. Additions must include the query,
candidate texts, independent lexical/vector orders, and expected top document.

The `test_scientific_query*`, `test_scientific_lookup_contract.py` and
`test_scientific_search_routing.py` suites add deterministic parser, original
quantity, real SQL parent/generation, UI-filter and public-wire regressions.
They do not turn the seed file into an independently adjudicated gold set.
Keep the planned reviewed 100–200-question set, held-out protocol, source-root
adjudication, true mixed numerical/explanatory synthesis and actual cost/latency measurements as
separate RG04 acceptance requirements.

The `test_complementary_*`, `test_evidence_packing.py`, `test_retrieval_groups.py`
and `test_rag_*budget*` regressions cover complete input accounting, same-source
role expansion, multi-paper Work limits, immutable identity, withdrawal after
currentness changes, real SDK offline serialization and cancellation/circuit
behavior. They are synthetic development tests, not reviewed scientific gold.

## Frozen scientific evaluation objects

The [scientific evaluation protocol](SCIENTIFIC_EVALUATION_PROTOCOL.md) defines
the executable RG04c offline package, exact generation/source/Result/request
bindings, whole-corpus connected split checks, two declared reviews plus an
explicit disagreement resolver, and paired captured-run comparison. The target
is 120 real reviewed questions, not an already collected benchmark. New
`test_scientific_evaluation*` suites use synthetic development fixtures, with
separate capture tests against disposable SQL. The independently hash-pinned
read-only CLI remains entirely offline.

Metrics retain missing, disputed, undetermined and not-applicable cases, with
explicit denominator units and candidate held-out threshold checks. Portable
consistency does not authenticate reviewers, original roots, permissions,
preregistration or execution. Scientific acceptance and release authorization
remain false even when declared scores pass; no actual ANN replay is provided.
Real expert acquisition, true mixed synthesis and external release gates remain
unfinished. Do not run the older aggregator/SSH stratification scripts as this
evaluation pipeline.

## Failure and safety metrics

Operational logs distinguish semantic-provider fallback, Gemini extractive
fallback, invalid citation indices, uncited claims, and weak lexical support.
Provider calls have separate timeouts and circuit breakers. ANN retains bounded
retries for immediate failures; Ask's count+generation pipeline uses one attempt
and a shared deadline. Provider faults remain failures even when a sealed safe
fallback is returned to the user; local no-call refusals are neutral, while a
successful token count rejected by the application token limit is not a provider
fault. Unknown usage/start state remains null. A Vertex failure
degrades to generation-scoped PostgreSQL full-text search; a Gemini failure can
return cited source excerpts only under the same evidence/currentness gates.
Unavailable or changed evidence may instead require an explicit abstention.

Recommended release metrics are top-k recall on the adjudicated set, paper
diversity, citation-valid rate, fallback rate by provider, and p95/p99 latency.
Do not treat lexical overlap as proof of entailment; flagged answers require
human verification against the linked paper.
