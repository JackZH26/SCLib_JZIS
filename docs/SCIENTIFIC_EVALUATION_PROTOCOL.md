# Scientific evaluation and adjudication protocol

Version: `scientific-evaluation-protocol/1.0.0`. Date: 2026-09-08.
Related issue: [RG04 / #75](https://github.com/JackZH26/SCLib_JZIS/issues/75).
Implementation: `api/models/scientific_evaluation.py`,
`api/services/scientific_evaluation.py`,
`api/services/scientific_evaluation_metrics.py` and
`scripts/validate_scientific_evaluation.py`.

## 1. Outcome and limits

This increment provides an executable **offline integrity and declared-judgment
comparison contract**. It does not provide a reviewed scientific gold set,
original-experiment authentication, live ANN replay, provider execution receipts,
source-use authorization or production acceptance. It makes no calibrated
superconductivity-probability or discovery-score claim.

There are three distinct outcomes:

1. Representation is valid: bounded, closed, versioned JSON with finite values.
2. Portable objects are mutually consistent: exact hashes, references, frozen
   generation inventory, declared split graph and review bindings agree.
3. Scientific acceptance: qualified independent humans, original documents,
   permissions, preregistration custody and measured runs satisfy externally
   authorized criteria. This implementation cannot establish this outcome.

A caller can recompute every hash in a fabricated package. Consequently all
reports retain `reviewer_authority_authenticated`, `source_roots_authenticated`,
`catalogue_bindings_authenticated`, `execution_authenticated`,
`preregistration_authenticated`, `scientific_acceptance` and `release_authorized`
as **false**, including when both reviewers declare agreement and all numerical
thresholds are met. `ann_replay_available` is also false. No JSON field, name,
ORCID, self-supplied signing key or synthetic fixture promotes these flags.

The existing 1,000-member retained-generation pilot is the size boundary of this
contract. It is not an evaluation of all 1,115,930 reported historical chunks.
Historical chunk counts are not verified current eligible-corpus counts.

## 2. Target question inventory

Plan 120 reviewed questions, within an explicit 100–200-question capacity range.
This is a feasible first pilot, not a statistical power calculation. Every
planned question remains in each arm; use `not_run` or `unavailable` when an
execution is missing. Never compare only the successful intersection.

Suggested primary task allocation, to be approved before capture:

| Task | Planned questions | Scientific purpose |
| --- | ---: | --- |
| Numerical | 30 | Preserve exact Result, pressure, criterion, unit and uncertainty |
| Mechanism | 25 | Distinguish observed evidence from a mechanism hypothesis |
| Comparison | 20 | Compare like conditions and retain inconsistent findings |
| Mixed | 20 | Test numeric/explanatory association and honest current limitations |
| Clarification | 15 | Identify ambiguous material, sample or unsupported predicate |
| General | 10 | Establish a broad-topic retrieval baseline without numeric inference |

These counts are a draft acquisition plan, **not implemented defaults or already
collected cases**. The protocol object holds explicit quotas. A suggested
language balance is 80 English and 40 Chinese questions; website-owned UI copy
remains English. Language and task quotas are separate from overlapping family
and hazard tags, not a full Cartesian-product sampling requirement.

Include conventional elemental/intermetallic and boride systems, cuprates,
iron-based materials, pressure hydrides, nickelates, heavy fermions, organics and
low-dimensional/interface systems when admissible original sources exist.
Multiple family tags are allowed; do not force disputed classifications or
interpret multiple tags as multiple independent cases. Report each family's
coverage and gaps. Sparse families do not acquire a reliable performance
estimate merely by appearing once.

Deliberately include these cross-family hazards:

- Ambient pressure explicitly reported versus pressure missing; zero and
  unknown are different states.
- Onset, midpoint, zero resistance and thermodynamic/magnetic criteria;
  resistive anomalies alone are not automatically bulk superconductivity.
- Isotope substitution, doping, phase, sample and pressure-series ambiguity.
- Measurements, calculations, predictions, review statements and quoted work.
- Negative findings with a stated detection window; no detected transition is
  not a fabricated `Tc = 0 K` measurement or a global non-superconducting label.
- Contradictions, retractions/withdrawals, permission holds, unresolved roots,
  and table values requiring headers, caption, footnotes or Methods context.
- Two extracts from one experiment versus independent experiments; duplicate
  versions/translations and multilingual paraphrases.

The final allocation depends on an authorized coverage audit of actually
retained sources. An unmet quota remains unmet rather than being filled with
invented data or relabeled easy questions.

## 3. Frozen object scheme and integrity

| Object | Required relationship | What it does not establish |
| --- | --- | --- |
| Protocol | Version, timestamp, scope, cutoffs, quotas, explicit gates | Trusted preregistration date or threshold approval |
| Corpus | Generation UUID, activation event, manifest, resource/profile and complete source inventory | Live ANN state or actual deployment |
| Captured source | Full text, vector ID/hash, catalogue snapshot, closed 0060 descriptor; optional declared Work/root/capture | PDF authenticity, rights or independent experiment |
| Captured Result | Exact scientific binding, raw record and raw-record hash | Correctness of the extraction or scientific support |
| Case | Raw query, split/group, language/task/families/tags and expected conditions/claims/results | Expert adjudication |
| Case review | Case/protocol/corpus hashes, reviewer declaration, time, decision and rationale | Reviewer identity or independence beyond distinct declared IDs |
| Run | Same protocol/corpus/dataset hashes, code/config/lock/prompt/model/policy declarations | Genuine execution, environment or billing |
| Observation | Exact case hash, ordered retrieved/selected IDs, results, answer/hash and optional full request | Complete historical logs or original output authorship |
| Output review | Observation hash, exact claim spans/citation map, typed judgments and rationale | Entailment proven by software |

The full manifest is recomputed with the existing frozen 0062 ASCII-TSV
`manifest_sha256` convention using vector ID, content SHA and vector SHA. A
partial corpus cannot omit members while retaining the declared manifest.
A resealed subset has a different declared manifest; the offline report does
not authenticate completeness against live SQL/ANN. Text bytes are checked
against the frozen descriptor. Result bindings must refer to the same generation,
activation event, manifest, source, evidence revision and parent revision.
The parent extraction UUID is reconstructed from the original raw record,
existing projection/extractor version, paper and catalogue snapshot. An unrelated
raw record cannot be attached to a convenient Result by copying its hash alone.
Opaque stored record hashes remain declarations without the trusted SQL records.

`source_snapshot_sha256` hashes a Paper catalogue/lifecycle snapshot; it is not
a raw PDF checksum. A declared `capture_sha256` is not proof that anyone obtained
the document lawfully. Original descriptors remain unresolved under the current
0060 contract. This batch changes no frozen migration or evidence semantics.

Portable hashes are domain-separated SHA-256 over canonical JSON:
`["scientific-eval-json/1", object_kind, normalized_object]`. Normalization uses
the complete closed model dump, including defaults, sorted keys, compact
separators, UTF-8 and finite JSON numbers. Case order is retained in the dataset.
The observation hash excludes its appended judgments/resolution. It binds the
observation content, not independently authenticated run execution. Review IDs
are unique across the package; a review cannot silently name multiple objects.

The command-line `--sha256` is a separate hash of the **exact raw file bytes**,
obtained through an independent custody channel. Whitespace changes that raw
hash even when normalized object hashes do not change. Computing a digest from
an untrusted file immediately before accepting it provides no authentication.

## 4. Source, condition and claim annotation

Preserve raw reported formulas, inequalities, uncertainty, units and condition
phrases. Do not canonicalize isotope labels into hydrogen, guess pressure from a
material family, transfer values between samples, or combine review tables into
a synthetic original Result. Structured conditions include formula, pressure,
Tc, sample, isotope, doping, phase, Tc criterion, origin, source role, outcome
and bounded other conditions, with explicit source references.

Each expected claim specifies an OR of AND evidence bundles. For example,
`[[methods-A, results-A], [complete-table-A]]` means either the paired Methods
and Results context, or a complete table containing all required qualifiers.
Retrieving Methods alone does not complete the first bundle. Derived extraction
Facts cannot be positive original-support alternatives. A supported output claim
mapped to an expected claim must cite a complete declared bundle for that claim.
New genuinely sufficient evidence requires a reviewed dataset revision, not a
silent post-hoc change to scoring.

Human annotators must inspect the original document, table headers/caption and
footnotes, sample/pressure relations, supplements and original cited roots where
needed. Section heuristics do not establish this completeness. Record unresolved
associations instead of inferring a tuple. Distinct Paper/Work/DOI values are not
necessarily independent experiments; the same Work may contain several roots.
The portable source carries a bounded declared root identifier only. If a
passage cannot be assigned one unambiguous root, leave it unresolved or prepare
separately reviewed passages; do not force a false many-root equivalence.

Output claims use nonoverlapping codepoint intervals in the unchanged answer,
not byte offsets or rewritten sentences. The declared `[n]` inventory must
exactly match all numeric citation tokens within each claim span and selected
source positions. Grouped/zero-prefixed/non-ASCII indices are not silently
repaired. A citation-only span cannot count as a claim. Complete inventory is a
human declaration: syntax checks do not prove all uncited assertions were found.
Supported, contradicted and undetermined judgments remain separate.

## 5. Independent review and disagreement

Before collecting real judgments, appoint two qualified reviewers and a distinct
resolver, agree on compensation/conflicts if relevant, and retain an authorized
identity/custody record outside this self-declared package. Reviewers should be
blind to arm identity where practical. Run IDs are opaque declarations, not a
blinding guarantee. The current tooling does not implement a reviewer UI,
access-control workflow, invitation process or signature trust registry.

For every case, each reviewer independently checks source eligibility, the
question, exact conditions, support bundles, relevant Result IDs and permitted
answer/refusal behavior. Append two records; do not overwrite the first vote.
Fewer than two is `unreviewed`; different votes remain `disputed`. Agreement
produces a declared decision only. A resolution must reference those exact two
reviews, bind the same frozen objects, be dated no earlier than both reviews and
name a different resolver. It does not erase disagreement history.

Repeat independent review for each captured output: condition, numerical, unit
and refusal correctness, plus complete claim inventory and support. Exact label
agreement or a valid third-party resolution is required to use output labels.
Unresolved output disagreement is missing adjudication, not an average vote.
All original reviews remain available in the input artifact.

`development_synthetic` requires synthetic reviewers/resolvers and synthetic
runs; `real_candidate` requires declared-human reviewers and captured runs.
Known mixing is rejected, but changing a declaration still cannot authenticate
a person or an execution. Repository fixtures use visibly synthetic identities
and prose and are never called the real gold set.

## 6. Development/held-out isolation

Build a connected-component graph over **every source in the declared corpus**
before attaching cases. Edges include shared paper, Work, declared root,
capture hash/capture ID, evidence revision, parent extraction revision and exact
full-text hash. Attach cases through condition/claim/Result references, query
group and the raw query normalized only by NFC and whitespace. Do not remove
isotopes, phase markers or material distinctions during duplicate detection.

An unreferenced third passage can bridge two seemingly separate questions.
Every connected case component must have one split. Exact duplicate text is a
conservative leakage edge, not an assertion of scientific equivalence.
Missing root assignments and unknown real-world links are reported: a disjoint
declared graph is not proof that the original-experiment graph is complete.

Aim initially for 80 development and 40 held-out questions, but assign whole
components before tuning and revise the counts honestly if the graph cannot
support that split. Balance tags only within this constraint. Freeze the
development/held-out allocation, corpus, question set, policy and thresholds
with an independent custodian before running held-out comparisons. Do not move
a difficult component into development after observing its answer. New data,
changed gold labels or rerun tuning create a new version and invalidate the
previous held-out claim. A timestamp string alone cannot enforce this policy.

## 7. Baseline and candidate capture

Use exactly one baseline and one candidate sharing protocol, corpus and dataset
hashes. Retain code revision, dependency-lock digest, configuration and digest,
prompt version, requested/observed model identifiers and policy versions. Each
run must explicitly contain every planned case exactly once.

Capture ordered retrieved and selected source IDs separately. Empty completed
retrieval is a genuine zero-recall observation; missing execution is not zero.
Keep full answer bytes and actual result references. Unknown latency, input
tokens, total usage, cost or fallback state stay null. A provider-free refusal
is not a zero-cost paid request unless a reliable cost boundary establishes it.
CountTokens preflight input and actual reported total usage remain distinct.

When the actual complete canonical text-only request is retained, verify its
digest, profile, model, question and ordered source text/evidence against this
observation. Retain system instructions and generation configuration in the
same payload. A digest alone is not a retained request. Never reconstruct an
old prompt from the latest code or infer full input from token totals.
Unsupported retained request profiles fail verification rather than being
silently converted. Historical captures without a full payload can still be
compared, but cannot claim payload-level reproducibility.

This evaluator scores **captured source order and declared output judgments**.
It does not call a retriever, replay live ANN, regenerate answers, verify a
model identifier remotely, purchase provider usage or establish a causal effect
of one code change. Compare one preregistered change at a time and retain actual
execution receipts through a separately authorized capture workflow.

## 8. Metrics, denominators and thresholds

Report all/development/held-out splits separately, overlapping stratum coverage,
raw counts and missingness. Only accepted cases and completed observations
enter scientific label/relevance ratios. Mechanical citation syntax is reported
independently of scientific acceptance.

| Metric | Numerator / denominator and important limit |
| --- | --- |
| Evidence-bundle completion at k | Expected claims with any complete OR alternative in top-k / all expected claims |
| Declared-root recall at k | Retrieved relevant declared roots / relevant declared roots, deduplicated within case; any unknown relevant root makes that case missing |
| Condition, numerical, unit and refusal correctness | Correct / (correct + incorrect + undetermined) case labels; not-applicable is separate |
| Claim-support precision | Supported / all declared answer claims; incomplete claim inventories are missing |
| Expected-claim coverage | Expected claim IDs covered by supported, bundle-complete claims / expected claims |
| Mechanical citation precision | Valid individual in-range ASCII indices / detected numeric citation occurrences; no entailment claim |
| Provider fallback | Observed true / observed boolean flags; unknown flags are missing |

Root recall uses the union of declared relevant roots across alternatives; it
is distinct from bundle sufficiency. Do not interpret the two as interchangeable
precision/recall estimates. Claim/root/citation ratios are micro-aggregated;
their denominator is not a count of independent experiments. `scored_cases`
separately counts cases contributing a nonzero denominator.

Missing and not-applicable counters use **case units**, even when the ratio
denominator uses claims or roots. Undetermined labels/claims remain in the
denominator. Show these counters alongside values; never silently drop failed
retrievals, unresolved reviews or unsupported outputs to raise an accuracy.

Operations include nearest-rank p95 latency with observed/missing counts,
known token/cost totals and a complete total only when every observation is
present. All-unknown is null, not zero. Cost per supported answer is withheld
unless cost and output adjudication are complete and at least one answer has
all its declared claims supported. It is not cost per discovered superconductor.

Paired comparisons retain improved/regressed/tied/unscored counts for every
planned case, using exact rational comparisons rather than rounding. Do not
infer statistical significance or independent confidence intervals from these
counts. A later analysis must account for connected source/experiment clusters,
predefine its estimator and uncertainty method, and justify sample size.

There are **no guessed release thresholds**. Version 1 gates can name only
implemented ratio metrics at declared k values, specify a minimum or maximum in
[0, 1], and set `min_n` in scored-case units. Duplicate or contradictory gates
are rejected. Gates apply to the candidate held-out split, not an easier pooled
development score. A missing case, absent value or insufficient scored-case
count leaves a threshold unmeasured rather than passed. Not-applicable cases
remain visible; these gates do not establish applicability or independent N.

Threshold checks are conditional declarations, even if all pass. Quotas use
accepted-case counts, with held-out counts shown separately. Review the task/
family coverage, missingness and safety failures jointly. External authority,
source rights, complete roots, preregistration and execution gates remain
unmet in every portable report. Do not close #75 using this diagnostic output.

## 9. Safe local operation

Use the locked API Python runtime, not the obsolete aggregator/stratification
scripts. Provide an absolute regular-file path with no symlink ancestors and
an independently obtained lowercase SHA-256. Examples use placeholders:

```bash
api/.venv/bin/python scripts/validate_scientific_evaluation.py validate /absolute/private/evaluation.json --sha256 INDEPENDENT_RAW_FILE_SHA256
api/.venv/bin/python scripts/validate_scientific_evaluation.py compare /absolute/private/evaluation.json --sha256 INDEPENDENT_RAW_FILE_SHA256
```

The CLI is read-only and offline. It rejects symlinks, hardlinks, devices/FIFOs,
path/inode changes, duplicate JSON keys, nonfinite values, oversized input and
resource-exhausting JSON. It captures the file twice and verifies exact bytes
and observed identity before emitting a report. Those local observations do not
guarantee future immutability or provenance. Maximum input is 64 MiB, nesting 32
and 500,000 JSON nodes; source text is at most 512 KiB, answer 128 KiB and cases
200. It never follows package URIs, connects to services or creates bytecode.

Exit 0 means a diagnostic report was produced, **not release approval**. Exit 2
means rejected/unavailable input or report; errors use fixed codes without raw
paths, credentials, source text or exception messages. Output omits queries,
source excerpts, answers and reviewer rationales, but contains bounded declared
IDs/tags and object-hash metadata, not raw configuration bodies. This is not a universal
secret-redaction service; use non-sensitive IDs/tags and retain artifacts and
reports in an authorized private location. No source redistribution is implied.

Run API tests only through `scripts/run_disposable_tests.py` against disposable
services. The separate CLI pytest gate uses the API runtime without API
conftest/database attachment; its positive subprocess tests deny network and
write-open operations. CI includes that explicit CLI gate. A local pass does
not claim the hosted CI, Linux release image or production system passed.

## 10. Prior tools and remaining work

`scripts/aggregator_eval.py` and `scripts/golden_set_stratification.py` are not
dependencies of this workflow. The former installs test stubs at import and
copies obsolete admission/temperature logic; the latter performs operational
directory/SSH actions and uses a paper-level, output-conditioned stratification.
Neither is the current question-level, frozen, expert-adjudicated benchmark.
The three-row `rag_gold.json` remains a lexical/ranking smoke fixture only.

Remaining acceptance work, in dependency order:

1. Appoint actual reviewers/custodian; approve source access and retention,
   root/table/sample annotation instructions, quotas, thresholds and split.
2. Capture an authorized complete pilot generation and original documents;
   annotate real cases, conditions, bundles, roots and negative-result limits.
3. Resolve disagreements without erasing original judgments; freeze and
   independently pin corpus/protocol/dataset before held-out access.
4. Implement and validate true mixed Result-to-original explanation association;
   current clarification/limited modes must not masquerade as that capability.
5. Under separate authority, capture actual baseline/candidate executions,
   provider receipts and blinded output judgments. Run the offline comparison,
   inspect every regression and publish only permitted aggregate results.
6. Complete production canary and external acceptance gates; only then consider
   remote issue closure. No paid runs, production writes, deployment or source
   release are authorized by this engineering increment.

## Methodological references

Separating answer correctness from citation quality follows the evaluation
distinction in [ALCE](https://aclanthology.org/2023.emnlp-main.398/).
Shared-corpus and provenance-aware evaluation are motivated by
[KILT](https://aclanthology.org/2021.naacl-main.200/).
Reference-free component diagnostics such as
[RAGAs](https://aclanthology.org/2024.eacl-demo.16/) can support later triage,
but are not a substitute for superconductivity-specific expert adjudication.
The object contract, split rules and authority boundaries above are SCLib's
engineering design, not claims that those papers certify this implementation.
