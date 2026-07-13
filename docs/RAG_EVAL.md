# RAG reliability and evaluation

SCLib uses hybrid retrieval rather than treating a vector-nearest-neighbour
result as sufficient evidence:

1. Vertex semantic candidates and PostgreSQL full-text candidates are fetched
   independently.
2. Reciprocal Rank Fusion combines both lists.
3. A deterministic query-term coverage reranker reorders the bounded candidate
   set.
4. `/search` and `/ask` hydrate authoritative PostgreSQL rows, reject retracted
   papers, and keep at most one result/source per paper.
5. `/ask` treats excerpts as untrusted JSON data in a system-separated prompt.
6. Citation checks reject nonexistent source numbers and report uncited or
   weakly supported claims through `citation_valid` / `citation_warnings`.

## Public regression set

The small, reviewable seed set is in
`api/tests/fixtures/rag_gold.json`. It covers exact formula/numeric search,
hydride pressure terminology, and cuprate pairing terminology. The unit gate
currently requires 100% top-1 accuracy on this seed set.

Run the reliability gate with:

```bash
cd api
pytest -q tests/test_rag_reliability.py
```

This seed set is a smoke benchmark, not a scientific-quality claim. It should
grow with adjudicated production misses. Additions must include the query,
candidate texts, independent lexical/vector orders, and expected top document.

## Failure and safety metrics

Operational logs distinguish semantic-provider fallback, Gemini extractive
fallback, invalid citation indices, uncited claims, and weak lexical support.
Provider calls have separate timeouts, bounded retries for immediate failures,
and circuit breakers. A Vertex failure
degrades to PostgreSQL full-text search; a Gemini failure returns cited source
excerpts instead of an uncited synthesized answer.

Recommended release metrics are top-k recall on the adjudicated set, paper
diversity, citation-valid rate, fallback rate by provider, and p95/p99 latency.
Do not treat lexical overlap as proof of entailment; flagged answers require
human verification against the linked paper.
