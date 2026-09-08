# Scientific query interpretation and qualified extraction lookup

Status: local RG04a plus qualified mixed-retrieval implementation, **not** an adjudicated scientific assistant
or completion of [RG04 / #75](https://github.com/JackZH26/SCLib_JZIS/issues/75).
Depends on [typed evidence](RAG_EVIDENCE_LINEAGE.md),
[complete inputs](EMBEDDING_COMPLETENESS.md) and
[immutable generations](INDEX_GENERATIONS.md). No SQL migration is added.

## What the routes now do

| Request | Execution and output |
| --- | --- |
| Ordinary topic keywords, including `hydride pressure result` | Existing pinned hybrid retrieval; legacy lexical-only when no generation is active |
| Formula notation, e.g. `MgB₂`, `MgB2`, `MgB_{2}` | Conservative notation-equivalent candidates plus ordinary lexical retrieval; no phase/sample identity claim |
| `What is the Tc of MgB2?` or explicit Tc/pressure conditions | Provider-free, exact-parent structured extraction lookup |
| Explicit origin/source-role/outcome conditions, including `experimental MgB2` | Same-record lookup; conditions cannot fall through to unfiltered generic retrieval |
| Search UI family/Tc/pressure/origin/source-role/experimental filters | The same structured lookup; remaining general-query keywords retain generation-scoped PostgreSQL English fulltext semantics |
| Pure mechanism or non-numerical comparison in Ask | Only typed `original_passage` candidates can enter generation; derived Facts are not explanatory source passages |
| Mixed numerical/evidence lookup and explanation, or a comparison with typed property/evidence requests | Qualified extraction rows and original candidates displayed separately, with a complete unresolved association matrix and one joint currentness check; no Gemini numerical synthesis |
| Unsupported material-state, isotope, doping, criterion, time or logical conditions | Explicit clarification preserving the unresolved original span; no silent condition removal |

Year filters alone remain ordinary bibliographic search. They are not historical
knowledge cutoffs. Search `sort=tc` in structured mode sorts only exact,
non-approximate, uncertainty-free points; censored/interval/missing quantities
remain at the end. No midpoint or paper-wide maximum is manufactured.

See [mixed scientific retrieval](MIXED_SCIENTIFIC_RETRIEVAL.md) for the actual
Ask coordinator, shared input budget, private presentation seals and closed
`scientific_mixed` response. Purely numerical comparisons intentionally also
receive original candidates; this does not imply experimental comparability.

The deterministic English/Chinese grammar is intentionally bounded and is not
a general language model. Ordinary unknown topic words remain opaque fulltext
input. For general queries combined with UI scientific filters, recognized
formula/condition spans are removed only from the remaining fulltext clause;
the selector independently applies those scientific predicates. An English
FTS match is a retrieval condition, not scientific entailment or a claim of
general Chinese semantic retrieval. Unsupported explicit scientific conditions
still require clarification. Whitespace-only requests return 422; query-scope
overflow returns a bounded clarification instead of an internal error.

## Formula identity boundary

Preserve the original query and codepoint spans. Only Unicode numeric
subscripts and supported LaTeX numeric subscripts are rendered equivalently.
There is no empirical-formula reduction, atom reordering, alias expansion,
isotope substitution, D/H equivalence, variable-composition collapse, charge
stripping or phase/interface removal. A notation hit does not identify a
particular sample, structure, preparation history or thermodynamic state.

Source scanning uses the complete retained text and a separate bounded token
iterator, not the short query's 20,000-character/256-mention DTO limit. It does
not split an overlong qualified token into an apparent shorter formula. The
full declared generation remains limited to 1,000 members and 16 MiB retained
JSON; this is not a million-chunk deployment strategy.

## One record, original quantities, explicit non-approval

All quantity, pressure, family, origin, role and outcome conditions apply to
one occurrence. A 39 K result at 150 GPa and a 20 K ambient result cannot satisfy
`Tc > 30 K at ambient pressure` together. The full reported uncertainty extent
or interval must satisfy each requested bound; strict endpoints remain strict.
`39 ± 5 K` does not satisfy `Tc >= 38 K`. Uncertainty has unspecified statistical
interpretation: it is not automatically a confidence interval. Approximate
values do not establish exact numerical filter bounds.

Raw extraction values, aliases and validation flags are checked against cached
top-level values. Conflicting raw/top values, pressure states, classifications
or outcomes cannot be repaired by trusting a cached normalized scalar. Existing
local anomaly-admission rules are reused; JSON claiming an approved anomaly
review cannot grant authenticated scientific authority. Unconstrained unusual
reports can retain explicit warnings; constrained property admission is stricter.

Missing pressure and legacy numeric zero are not ambient pressure. An explicit
ambient report is a reference state, not a zero-pressure measurement. Even an
`include_unknown_pressure` UI option cannot prove a requested pressure bound;
the result notes explain this narrower structured-lookup meaning.

Non-detection is kept separate from a positive Tc. A minimum measured
temperature is a detection-condition field, not `Tc = Tmin`, a universal
`Tc < Tmin` conclusion, or an automatically eligible negative ML example.
Method, sample, form, phase and criterion are reported when retained and
unambiguous; they are not inferred or adjudicated by this lookup.

## Exact extraction association, not original passage support

Original ingestion chunks may carry all material extractions from their paper.
That attachment does not show that a particular passage supports any particular
record. The numerical route therefore admits only an immutable `derived_fact`
whose verified 0060 parent has the SHA-256 of that **entire exact input record**.
Paper identity, source snapshot, evidence hash and extraction hash must agree.
Another record in the same chunk cannot borrow that parent.

Each public row includes:

- A versioned qualified report with Tc, pressure, minimum temperature,
  classification, outcome, reported context and warnings.
- Exact paper/vector/generation/activation/manifest/content/evidence/parent
  identifiers and hashes, with association scope
  `derived_extraction_not_original_support`.
- Literal boolean `false` for scientific acceptance, ML-training eligibility
  and verified detection adequacy. Numeric zero is not accepted as a boolean.

Repeated renderings of one parent are deduplicated **after** individual source
admission. An unavailable rendering cannot suppress an eligible alternative.
These are machine-extraction references, not canonical reviewed research
Results or independent experimental confirmations. Original-root resolution,
rights and scientific adjudication remain separate gates.

Current Paper/accepted-Work lifecycle, permission and linked-material visibility
are checked before output. Selected source inputs are checked again through a
fresh session after the request read transaction is closed. The active event
is then rechecked, including generation A → B → A. Changed or unverifiable
evidence withholds the entire prepared result set. Historical rollback does
not remove current holds; activation still requires the target's source binding.

## Wire and consumer migration

Search/Ask add `scientific_query`, `scientific_lookup`, and
`scientific_results`. The interpretation retains `raw_query`, normalized
notation, intent, requested fields, formula/quantity/evidence spans and
clarification clauses under `scientific-query/1.0.0`.

Lookup status is `not_requested`, `completed`, `unavailable` or
`clarification_required`; its scope is
`declared_generation_derived_extractions`. Count, distinct parent identity,
generation/event/manifest and opaque vector prefix are cross-validated.
At most 20 rows are returned, with explicit `has_more`. This is a bounded
declared-generation result set, not full-corpus completeness or a benchmark.

**Consumer change:** structured Search responses have `results=[]` and
`total=0` for paper hits; use `scientific_lookup.returned_count` and
`scientific_results` for extraction rows. Do not interpret empty paper hits as
an absence of matching records. An active generation with bound derived parents
is required; no-active scientific/UI-filter lookup returns `unavailable` with
no legacy numerical fallback. Ordinary topic/year-only Search remains usable.

Non-comparison structured-only numerical Ask uses no embedding or generation provider. Its static text explains
the qualified rows; `tokens_used=0`, `scientific_support_status=not_checked`,
`assessment_scope=none` and `answer_mode=abstention` mean no scientific synthesis
was performed. The frontend calls it **Source-linked extraction lookup**, not
an AI-validated answer. Mixed/typed-comparison Ask may use semantic retrieval
but does not call Gemini CountTokens or generation; zero generation tokens is
not zero total provider cost. Non-numerical answers retain their support policy.

Existing Ask history cannot persist/replay these response-level bindings or
structured rows. It stores a static request summary, no fake citation sources
and no unbound numerical rows, and explicitly says to rerun the query. This is
not reproducible historical-answer support. Clarification history retains the
clarification text. Replayable version-bound answer history is still unfinished.

The frontend validates query equality, codepoint spans, closed wire shapes,
quantity relations and generation bindings before displaying numbers. Query-keyed
remounts, request generations and AbortSignals prevent old Search/Ask results
or errors from appearing under a newer query. Website-owned copy is English;
source wording and the user's original language remain intact.

## Verification and remaining acceptance

Regression coverage includes exact source-parent association, same-record
matching, raw uncertainty, non-detection, retained replacement/rollback, fresh
source holds, activation ABA, alternate rendering admission, long source text,
UI predicate routing, mixed queries, wire corruption and stale UI requests.
Native SQL tests run only through `scripts/run_disposable_tests.py`; no provider
costs or production writes are required by those fixtures.

These tests are synthetic development regressions, **not** an adjudicated gold
set or evidence of scientific accuracy. Complementary catalogue-source/Work
packing, actual input budgets for generation, portable evaluation objects and
qualified dual mixed retrieval are now implemented locally; original-root
independence remains unestablished. Remaining RG04 work includes true supported
mixed/comparative synthesis, authenticated Result/root bindings, a reviewed
100–200-question gold set and actual held-out evaluation, per-family/condition coverage,
actual recall/support/cost/latency measurement and current-revision release CI.
Corpus-scale indexing, source permission, authorized canary deployment and
scientific approval are separate gates. Do not close #75 on this increment.
