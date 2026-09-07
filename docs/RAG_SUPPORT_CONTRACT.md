# Scientific claim-support contract: RG01

Policy version: `scientific-claim-support/1.0.0`.

Implementation: `api/services/claim_support.py`. This is a deterministic,
bounded, local checker. It does not call an LLM, retrieve additional documents,
write scientific records, approve results, or calculate a probability of truth.

## Meaning of the outcomes

`supported` means that each checked claim has an explicit, self-contained,
attributable matching reported tuple in every source it cites, within the narrow
grammar described below. It does **not** mean that the reported science is true,
scientifically accepted, independently replicated, or usable as ML ground truth.

`contradicted` means that a cited source explicitly reports an incompatible exact
value or opposite polarity for the same fully bound context. This is a conflict
with that reported excerpt, not a scientific adjudication. A different material,
pressure, sample, criterion, or result origin is normally an attribution failure
(`undetermined`), not proof that the claim is physically false.

`undetermined` covers missing context, unsupported grammar/language, ambiguous
attribution, incompatible relations, uncertainty that cannot be resolved,
conflicting cited evidence, and ineligible or unresolved sources. It is an
abstention, not a low score or a negative result.

`not_checked` applies to no-source cases, empty answers, and a small allowlist of
whole-answer refusal sentences. A refusal prefix does not erase an appended
assertion: “I cannot verify it but …” remains a detected, undetermined statement.

Mechanical citation-index checks remain separate. A valid `[n]` only identifies
an available source; lexical overlap never establishes support. The root RAG
integration determines answer delivery and any abstention/extractive fallback.
When a generated draft is withheld, its assessment is labeled as belonging to
that draft, not to a subsequently quoted fallback. Provider-failure quotes and
no-source refusals are not retroactively labeled supported science.

## Supported first-phase grammar

The initial checker recognizes conservative English and Chinese/mixed-language
reported Tc statements, for example these **synthetic grammar fixtures**:

- `H3S has an observed Tc of 100 K at 2 GPa.`
- `H₃S 的 Tc 为 100 K，压力为 20 kbar。`
- `H3S showed no superconducting transition at 100 K and ambient pressure.`

These sentences are invented test inputs, not claims about the named materials.

A usable tuple contains exactly one unambiguous formula, a directly bound Tc or
superconducting-transition temperature, and one explicit pressure context.
Single-element and multielement chemical tokens are checked against element
symbols; Unicode digit typography is normalized. Formula equality is a necessary
local text-attribution condition, **not** a join to catalogue material identity.
Variable stoichiometry, isotope/charge qualifiers, complex formula syntax,
formula aliases, and other notation without safe exact recognition are left
undetermined; the parser never strips them to manufacture a simpler identity.

The answer and the matching source clause must retain the same explicitly stated
sample/state/phase, supported sample form, onset/zero-resistance/midpoint/offset
criterion, result origin, and primary/cited role. Missing or differing qualifiers
are not filled from a nearby sentence, material maximum, title, or extraction
metadata. A generic reported Tc can match another generic reported Tc, but that
does not establish an observed or primary result. Explicit missing pressure is
not ambient pressure. Bare numeric zero pressure remains ambiguous; explicit
ambient text uses the existing ambient-reference convention, not a claim of
zero absolute thermodynamic pressure.

All quantities are reparsed through the shared scientific-value parser. Permitted
unit conversions include K/mK and kbar/GPa. Relation, bounds, ranges,
approximation, and uncertainty are compared as reported; a range endpoint or
bound is not substituted for an exact Tc. Equal unspecified uncertainty notation
can match, but does not acquire a one-sigma or other statistical interpretation.
No numerical tolerance or display rounding makes nearby values identical.
Nonfinite, invalid, incompatible-unit and nonpositive Tc inputs do not establish
support. A measurement temperature without a directly bound Tc/transition label
cannot supply a Tc value.

Negative reports also preserve temperature semantics in public quantities.
“No superconducting transition at 100 K” yields `tested_temperature_k`, not a
measured `tc_kelvin`. A negated specific Tc value yields `negated_tc_value_k`;
only positive Tc/transition reports use `tc_kelvin`. The accompanying
`temperature_role` is `transition_test_temperature`, `negated_tc_value`, or
`reported_tc`. Equal numbers in the two different negative statement types do
not establish support for one another. This avoids manufacturing positive Tc
labels from negative-observation checkpoints for downstream ML consumers.

The parser rejects unresolved negation scope, compound/multimaterial bindings,
extra quantities, hypothetical language, and unsupported residual relationships.
It cannot approve a mechanism, commercial feasibility, world-record claim,
experimental reproducibility claim, or causal explanation merely because the Tc
and pressure numbers match. Unknown languages and unsupported statements remain
visible as undetermined checks. English and Chinese regression coverage is not
a claim of unrestricted multilingual entailment.

## Evidence binding and source eligibility

Each citation is considered separately. A positive support outcome requires one
complete tuple within one source clause. Values cannot be assembled across
papers, samples, clauses, or material-evidence records. A matching uncited source
cannot rescue an incorrect citation. Opposing support/conflict evidence is
reported as unresolved rather than choosing the first match.

Only sources with freshly resolved, recognized source-visibility metadata and an
eligible active reported-claim state can support a report. Missing, malformed,
unrecognized, held, or restriction-bearing metadata fails closed. Restriction and
classification conflicts in material evidence can lower support, but metadata
cannot provide a missing assertion or override the excerpt. These are one-way
negative checks, not a route from extracted values to scientific approval.

Known derived Facts sections, derived/generated source identifiers, and embedded
`Section: Facts` headers cannot independently support a scientific claim without
resolved original evidence roots. Normalizing section separators prevents
`derived_facts` from evading that restriction. This is a conservative first-phase
guard, not the complete root/derivation graph planned under RG02.

Titles are not evidence clauses. Source instructions are untrusted data and
cannot change validation, status, citation numbers, or policy. Recognized
instructional text blocks support. Source-wide withdrawal, nonconfirmation,
hypothetical, and uncertainty language prevents selecting an isolated favorable
clause while discarding its caution. This intentionally over-abstains when
context scope cannot safely be resolved.

## Public response and explicit bounds

`assess_answer(answer, sources)` returns:

```text
policy_version
status: supported | contradicted | undetermined | not_checked
claims[]:
  claim_id, text, cited_indices, status, reason_codes
  evidence[]: source_index, paper_id, excerpt
  quantities?: material, temperature_role, pressure_gpa, polarity
    plus exactly one of tc_kelvin | tested_temperature_k | negated_tc_value_k
warning_codes[]
coverage:
  total_claims, assessed_claims
  supported_claims, contradicted_claims, undetermined_claims
  truncated, limits
```

The source protocol reads `index`, `paper_id`, `text`, `section`,
`material_evidence`, `source_visibility`, and `visibility_resolved`. A caller must
not mark untrusted source-written visibility as freshly resolved metadata.

The initial limits are 12,000 answer characters; 32 answer segments; 800
characters per claim/source clause; 24 sources; 6,000 characters and 32 clauses
per source; 50 material-evidence entries; three displayed evidence excerpts per
claim; and 500 characters per displayed excerpt. Metadata string/list shapes are
also bounded. Input objects remain unchanged, and public quantities contain only
allowlisted normalized scalar fields. Excerpts are source text, not executable
instructions or UI markup; render them as escaped/plain text.

Any assessment input limit yields explicit reasons, `coverage.truncated=true`,
and an aggregate outcome that cannot be `supported`. An overlong source clause
is not silently discarded while other clauses approve the claim. Excerpt-only
display truncation is different: when the full clause was assessed, its excerpt
is visibly abbreviated with an ellipsis and a display-warning code without
claiming that evaluation itself was incomplete. Evidence-count display limits
are also reported separately.

“Claims” in this initial coverage report are bounded sentence/clause segmentation
units, not a complete semantic census of every possible atomic proposition.
Unsupported compounds remain undetermined rather than being partly accepted.
After answer clipping, `total_claims` describes the visible bounded prefix; the
truncation flag explicitly prevents treating that count as complete coverage.

## Release limitations and human evaluation gate

This first phase favors narrow precision and explicit abstention. It is not a
general entailment engine and is expected to have low coverage on unconstrained
research prose. Tables, multi-chunk synthesis, mechanisms, causal statements,
multilingual paraphrases beyond the grammar, uncertainty propagation, arbitrary
state variables, bibliographic-root resolution, and scientific acceptance remain
outside its positive-support capability.

The unit and adversarial tests are labeled synthetic software regressions. They
do not report real-world support precision, recall, or scientific correctness.
Before claiming a calibrated or broadly reliable support capability, freeze a
versioned corpus/index and develop a human-adjudicated gold set with original
evidence roots and material/state/quantity/polarity labels. Separate development
cases from held-out evaluation by work/evidence root. Report citation-index
accuracy independently from support precision/coverage, numeric/unit correctness,
abstention, and performance. Reviewers must resolve disagreements and agree
release thresholds before inspecting held-out results. No numerical accuracy
guarantee is inferred from the size of the current vector database or the count
of passing synthetic tests.
