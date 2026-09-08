# RAG reliability and evaluation

SCLib uses hybrid retrieval rather than treating a vector-nearest-neighbour
result as sufficient evidence:

1. An active immutable generation is pinned; Vertex semantic and PostgreSQL
   full-text candidates are fetched within that generation. Without an active
   generation, Search/Ask are explicitly legacy lexical-only and Similar is
   unavailable. Positional legacy ANN IDs are not a mutable SQL authority.
2. Reciprocal Rank Fusion combines both lists.
3. A deterministic query-term coverage reranker reorders the bounded candidate
   set.
4. `/search` and `/ask` hydrate exact retained generation members, apply fresh
   source/material/permission holds, and keep at most one result/source per
   paper. Generation mode preserves original attribution after replacement.
5. `/ask` treats excerpts as untrusted JSON data in a system-separated prompt.
6. Citation-index checks are separate from scientific-support status/coverage
   and answer mode. Deprecated `citation_valid` remains a mechanical/lexical
   compatibility field, not scientific acceptance. Derived Facts and unresolved
   roots do not validate their own extractions. Post-generation checks can
   withhold a draft after source/permission/activation changes.

See [typed evidence](RAG_EVIDENCE_LINEAGE.md) and
[generation identity and rollout](INDEX_GENERATIONS.md). These gates do not
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

## Failure and safety metrics

Operational logs distinguish semantic-provider fallback, Gemini extractive
fallback, invalid citation indices, uncited claims, and weak lexical support.
Provider calls have separate timeouts, bounded retries for immediate failures,
and circuit breakers. A Vertex failure
degrades to generation-scoped PostgreSQL full-text search; a Gemini failure can
return cited source excerpts only under the same evidence/currentness gates.
Unavailable or changed evidence may instead require an explicit abstention.

Recommended release metrics are top-k recall on the adjudicated set, paper
diversity, citation-valid rate, fallback rate by provider, and p95/p99 latency.
Do not treat lexical overlap as proof of entailment; flagged answers require
human verification against the linked paper.
