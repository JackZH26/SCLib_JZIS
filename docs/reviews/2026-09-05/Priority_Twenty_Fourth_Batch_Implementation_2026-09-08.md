# Twenty-fourth implementation batch — scientific evaluation integrity

Date: 2026-09-08. Branch: `codex/sclib-research-v2`.
Baseline: `95de0ff` (twenty-third batch).
Priority: [RG04 / #75](https://github.com/JackZH26/SCLib_JZIS/issues/75).
Specification: [scientific evaluation protocol](../../SCIENTIFIC_EVALUATION_PROTOCOL.md).

## Outcome and scope

Added a versioned, executable offline package for corpus/question/result/run
integrity, two declared reviews plus explicit dispute resolution, whole-corpus
development/held-out separation and paired captured-run metrics. Its read-only
CLI requires an independently supplied exact-file hash, never contacts SQL/ANN
or model providers, and never interprets consistency as scientific acceptance.

This is **RG04c local implementation**, not completed RG04 acceptance. There is
no newly acquired 120-question gold set, genuine human-review result, original
root authentication, live retrieval replay, production performance claim,
paid provider run or authenticated source-use permission. The overall goal
remains active. No migration, frozen 0052–0062 contract or default UI language
was changed. No push, PR, deployment, production write/backfill, source release
or remote issue closure was performed.

## Implemented

1. **Closed portable object model.** Versioned protocol, complete bounded
   retained-generation corpus, raw source text/descriptors, exact extraction
   Result bindings, questions/conditions/OR-of-AND support bundles, declared
   reviews/resolutions, paired run manifests, observations and output judgments.
   Strict finite JSON, UUID/timestamp/hash identities, true booleans, bounded
   text/resources, no unknown approval fields or implicit coercions.
2. **Exact object consistency.** Recompute existing 0062 manifests, text hashes,
   raw extraction hashes and the actual deterministic parent UUID. Bind results
   to generation/event/manifest/vector/evidence/parent; bind each case review
   and run to the normalized protocol/corpus/dataset; bind output judgments to
   the unchanged observation. A rehashed altered raw record does not preserve
   its original extraction identity. These are declarations, not trusted SQL
   authentication or proof that a self-resealed corpus contains every real row.
3. **Whole-corpus split graph.** Include unreferenced sources and transitive
   links through Paper, Work, declared root, capture ID/hash, evidence revision,
   parent revision and exact full text before attaching case/query groups.
   A connected component cannot straddle development and held-out. Missing
   roots remain explicit; unknown real-world relationships are not certified.
4. **Two-review adjudication workflow contract.** Two distinct declared
   reviewers, exact object bindings, immutable disagreement history and an
   explicitly distinct third resolver. Missing/disputed output labels do not
   become majority-averaged gold. Package-wide review IDs cannot be reused
   across different subjects. Known synthetic versus declared-human/captured
   mixing is rejected without pretending declarations authenticate identity.
5. **Complete claim/citation annotation.** Exact nonoverlapping codepoint spans,
   all numeric citation indices and selected-source positions. Citation-only
   spans, omitted indices and malformed numeric syntax fail. Positive support
   needs typed original, non-held passages; expected-claim coverage requires
   a complete declared support bundle. No extraction supports itself.
6. **Actual retained request verification.** Optional complete canonical
   text-only model/system/configuration/question/source payload, not a prompt
   rebuilt from current code. Exact source-entry keys/types, evidence and
   packing position/vector/catalogue-snapshot/group checks. Unknown extra
   acceptance fields and mismatched declared Work groups fail. Missing payloads
   stay unavailable; a digest alone does not establish input reproducibility.
7. **Honest metrics and denominators.** Bundle completion, declared-root recall,
   condition/numerical/unit/refusal labels, claim precision/coverage and separate
   mechanical citation syntax. Missing, disputed, undetermined and not-applicable
   outcomes remain explicit. Operational p95, observed fallback, known/complete
   usage/cost totals and cost per supported answer have explicit completeness
   conditions. No invented token price, independence estimate or probability.
8. **Paired and held-out comparisons.** Exact same full case inventory in each
   arm, explicit `not_run`/`unavailable`, improved/regressed/tied/unscored counts,
   per-split and overlapping family/language/task/tag coverage. Declared ratio
   gates apply only to candidate held-out results and count `scored_cases`,
   never a larger number of roots, claims or citations as independent N.
   Missing observations withhold a threshold decision. No default success
   threshold or confidence interval is invented.
9. **Safe CLI and actual CI gate.** No-follow ancestor/file checks, regular
   single-link file only, bounded strict UTF-8/JSON, duplicate-key/nonfinite
   rejection, independent raw SHA and two full file/identity captures before
   reporting. Fixed-code errors omit input paths and raw source/reviewer text.
   Imports create no bytecode; verified subprocesses deny sockets, SQLite
   connects and write-open operations. Added an explicit pytest CLI step in
   the locked API-runtime CI job; did not claim remote CI has executed.
10. **Actionable scientific protocol.** A draft 120-question acquisition plan
    (100–200 capacity range), cross-family hazards, raw-condition preservation,
    independent review/custody requirements, root-aware split rules, preregistered
    gates and measured-run prerequisites. Actual acquisition and review remain
    outstanding. Older operational aggregator/SSH stratification scripts are
    explicitly not reused as scientific evaluation tools.

## Independent review findings resolved

- Ignoring unreferenced corpus sources allowed hidden Work/root bridges across
  a declared split; the graph now covers the full source inventory first.
- Checking only a subset of cited indices allowed omitted citations and naked
  `[1]` spans to inflate support; the complete numeric inventory and actual
  assertion span are now required.
- Distinct IDs within one observation did not prevent the same review ID being
  reused elsewhere; review identity is now unique across the package.
- Claim/root/citation denominators could otherwise inflate minimum sample-size
  gates; a separate contributing-case count now controls `min_n`.
- Rehashed request entries could contain unsupported fields or mismatched
  packing declarations; strict entry shape and actual grouping bindings now
  reject them. Input-builder failures are normalized to a static evaluation
  rejection, including invalid models, empty inputs, boolean token limits and
  oversized requests.
- Ordinary unittest discovery omitted pytest-style CLI tests; CI now runs the
  dedicated suite explicitly without attaching the API database conftest.
- Documentation now distinguishes deletion under an unchanged declared manifest
  from a completely resealed fabricated corpus, and disposable SQL capture tests
  from the entirely offline CLI.

## Verification

Verification uses guarded disposable PostgreSQL/Redis for API and migration
checks; ingestion uses inert connection targets. All new sample passages and
reviewers are explicitly synthetic. Actual SQL integration writes 0060 evidence,
0061 embedding receipts and 0062 generations through the real service code,
retains five immutable members after a mutable replacement with three, and
checks source/parent/request tampering. Provider transport alone is substituted.

| Check | Result |
| --- | --- |
| Complete API collection | 3,654 passed; 20 existing warnings; 326.24 seconds |
| Final entire new API evaluation module set | 253 passed; one existing warning; 13.07 seconds |
| Complete ingestion suite | 1,275 passed; 34 existing warnings |
| Complete script suite | 363 passed plus 36 subtests |
| Final offline CLI rerun | 76 passed; actual subprocesses deny network/SQLite/write-open events |
| Frontend source / component-unit suites | 35 + 401 passed |
| TypeScript | Passed |
| Complete migration rehearsal | Passed through 0062, including independent populated-history rollback refusals |
| API and ingestion dependency locks | Both checks passed |
| Changed/new Python Ruff I/F and staged whitespace checks | Passed |

The complete API collection began before the final five new request-builder
error regressions were added. Those five and all other evaluation-module tests
passed in the final 253-case rerun after the static exception-boundary fix.
They are not misrepresented as part of the earlier 3,654-case collection; the
full API suite was not repeated a second time after that isolated new-module
fix. The final CLI suite was also rerun against the final implementation.

Unique ordinary tests exercised across the full runs and those five later new
cases: **5,733**, plus **36 script subtests**. This batch adds **329 ordinary
tests** (253 API and 76 CLI); repeated focused runs are not double-counted.
No skipped tests, weakened scientific assertions or real provider calls were
used to obtain these passes. Native macOS/offline SDK checks are not hosted
Linux CI, a browser canary, real-world expert accuracy or production acceptance.

## Remaining acceptance and next work

Issue #75 was re-read and remains **OPEN**. The portable evaluator deliberately
keeps reviewer/root/catalogue/execution/preregistration authentication,
scientific acceptance and release authorization false. Source rights and a
complete real experiment-root graph are not inferred from accepted votes.
The bounded pilot remains 1,000 retained members, not a million-chunk benchmark.

Next dependency-ready development is the actual mixed numerical/explanatory
request path and its source-to-Result association boundary. Same-paper or
same-Work retrieval alone must not attach a mechanism to a different sample,
pressure, phase or extraction. Preserve raw-parent identity, negative-result
detection limits and unknown conditions; require clarification when the input
or original association is not supportable. A new schema without a real route
consumer is not sufficient completion.

Read-only dependency analysis confirmed that `/ask` currently returns early
from its `result_query()` branch. `lookup_scientific_results()` consumes its own
transaction boundary and does not expose private selection pins to a longer
mixed workflow. `ScientificResultBinding` and reported sample/phase strings do
not establish an original experiment association. The next increment should
extract an internal prepared lookup result with exact parent identity and pins,
retain the existing numerical wrapper, and add a mixed coordinator using one
generation and one combined final currentness check. Display structured rows
and individually cited explanation candidates separately, explicitly marking
`numerical_explanation_not_established` until an actual reviewed Result-to-claim/
sample-to-original bridge exists. Merely adding sibling passages to Gemini
would not meet that requirement. Existing source-occurrence witnesses can help
validate an explicit bridge but cannot supply a missing one.

In parallel, actual scientific acceptance needs authorized original-document
access, appointed reviewers and a custodian, agreed quotas/thresholds, a frozen
real question inventory, blinded judgments and separately authorized measured
baseline/candidate runs. Production canary, source release and paid provider
evaluation are separate authority gates. Local regression success alone must
not close the issue or complete the overall upgrade goal.
