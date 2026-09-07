# SCLib Phase A — Seventh implementation batch

Date: 2026-09-07. Primary issue: [RG01 #62](https://github.com/JackZH26/SCLib_JZIS/issues/62). Tracker: [#41](https://github.com/JackZH26/SCLib_JZIS/issues/41).

Status: local implementation and verification, not scientific approval or production rollout. Work remains on `codex/sclib-research-v2`, based on `c6f05f1ca757f692d3f5169768b2fd75c6f685eb`. Existing uncommitted SC07 and SC06 work is preserved. No commit, push, production connection, deployment, production migration/backfill or paid model/extraction run is part of this batch.

GitHub progress-comment attempts for RG01 #62 and tracker #41 were rejected with HTTP 403 (`Resource not accessible by integration`). No remote progress comment was created and no issue was closed. The verified delivery record is this local report; publishing its summary requires a GitHub integration with the appropriate repository write permission.

## Outcome and intentional limits

Ask now separates mechanical citation-index checks, the deprecated lexical heuristic and bounded scientific-claim consistency checks. Correct citation numbers and high word overlap cannot establish that a generated numerical claim matches the excerpt, still less that it is scientifically true or suitable as an ML label.

The first implementation deliberately supports a **narrow, explicit Tc/transition-and-pressure report grammar**, with English and Chinese handling and Unicode formula normalization. It is not a general scientific entailment model, a reviewed NER system, an expert-adjudicated dataset or a complete multilingual physics validator. Unsupported phrasing, mechanism explanations, incomplete state context and unresolved provenance remain undetermined.

This conservative scope reduces synthesized-answer coverage. When the draft cannot pass the checks, Ask withholds that synthesis and returns an explicit abstention or clearly quoted eligible source excerpts. Improving coverage requires evaluated extensions, not treating lexical overlap or an LLM confidence score as proof.

## Implemented contract

The additive response contract uses `support_policy_version = scientific-claim-support/1.0.0` and retains REST v1 compatibility.

| Field | Meaning |
| --- | --- |
| `citation_indices_valid` | Whether the original draft's citation indices resolve mechanically; invalid indices are not repaired into success |
| `lexical_support_checked` | Whether the legacy lexical comparison ran, not whether it proves support |
| `scientific_support_status` | `supported`, `contradicted`, `undetermined` or `not_checked`, within the explicitly limited automated scope |
| `claim_assessments` | Bounded draft segments, cited indices, consistency outcomes, reason codes and attributable source excerpts |
| `support_coverage` | Identified/assessed outcome counts, truncation and explicit work limits; not literature-retrieval recall or scientific completeness |
| `answer_mode` | Delivered synthesis, extractive fallback or abstention; the reserved limited-synthesis value does not relax checks |
| `assessment_scope` | `generated_draft` versus `none`; draft assessments do not certify replacement excerpts |
| `support_warnings` | Explicit limitations, omitted assessment scope and withholding reasons |
| `citation_valid` | Deprecated legacy combined citation/lexical heuristic, retained for compatibility and marked deprecated in OpenAPI |

`supported` means only that an eligible cited excerpt explicitly contains a matching report tuple under the implemented grammar. It does not establish discovery, validity, independent replication, scientific acceptance, source licensing or training-label eligibility. The frontend therefore uses **Excerpt consistency checks passed**, not a scientific-verification badge.

### Scientific tuple and attribution safeguards

- Bind each supported numerical statement to its formula, Tc/transition quantity, pressure, polarity and explicit sample/state, Tc criterion, result origin and source role.
- Compare within a self-contained source assertion. Do not combine a Tc from one material/source with pressure or sample information from another.
- Preserve exact values, bounds, ranges, approximation and uncertainty. Reuse the existing raw-preserving scientific-value normalization contract for permitted units; equivalent pressure units can match without converting bounds into point labels.
- Do not equate measurement temperature with Tc, computed with observed, onset with zero resistance, cited work with a primary result or a missing condition with an established one.
- Negative transition observations expose a tested-temperature field, not `tc_kelvin`; negating a particular Tc value uses a separate negated-value field. The explicit temperature role prevents the normalized audit tuple from becoming a false positive Tc label.
- Numerical, negation and state counterexamples can fail even when every citation index is valid and the old lexical heuristic passes.
- Treat source text and extracted metadata as data, never validator instructions. Titles alone and unresolved derived Facts cannot establish a supported original-source report. Existing source/material visibility restrictions remain in force.
- Bound answer length, segment length/count, source text/count and evidence display. Exceeding assessment limits must not quietly establish complete support.

The public `claim_assessments` list contains conservative candidate segments. A compound segment that the grammar cannot atomize remains undetermined; the implementation does not claim complete semantic atomic-claim extraction. Transitional claim IDs identify a draft segment, not canonical scientific-result IDs or immutable paper revisions.

### Answer delivery, history and observability

- Generation prompts explicitly preserve quantities, relations, uncertainties, negation, conditions and origin/source-role distinctions.
- Server-side finalization applies after generation, including alternate adapters returning legacy result objects. A provider's citation-valid flag cannot bypass this boundary.
- An internal consistency fingerprint binds a checked result to its delivered text, quality metadata and source context. In-process postprocessing changes invalidate the marker. This is not a public approval signature or immutable scientific-source revision. Malformed drafts/checker responses fail closed before history persistence; supported evidence must resolve to a cited source.
- Contradicted drafts are withheld. Undetermined drafts are withheld in favor of eligible, bounded and clearly quoted source excerpts, or an abstention when no fallback excerpt is eligible.
- No-source and blocked/empty/provider-failure paths explicitly report `not_checked`. They do not claim successful scientific verification through an empty set of assertions.
- Source-controlled Markdown, HTML and bracket citations are escaped in fallback quotes. Source instructions cannot create new citation links or become an assistant instruction.
- Persist only the delivered answer, not a rejected synthesis. This batch does not add an immutable per-answer validation snapshot to the history database: saved-history views explicitly say the scientific-support snapshot is unavailable, and do not reconstruct approval from old citations. That persistence/versioning work remains a release limitation.
- Existing legacy metrics remain compatible. A separate bounded-label support-outcome counter distinguishes citation-index validity, draft support outcome and delivered answer mode. Outcome counts are not measured scientific accuracy.

### Website behavior

English-default notices distinguish mechanically valid citations, undetermined support, conflicts and checks not performed. Expandable draft details expose source indices, reason codes and literal evidence excerpts. Links require a unique positive source index and matching paper identifier; unavailable evidence is not turned into a fabricated link. Missing or unknown policy metadata from an older backend is displayed as unchecked. Existing source-governance notices remain visible.

## Verification

Final verification after the negative-temperature semantics correction: **2,059 tests passed** (1,148 API + 644 ingestion + 61 operational-script + 33 frontend source + 173 frontend component/unit). Targeted test runs are not added a second time to this aggregate.

| Check | Result |
| --- | --- |
| API full suite | 1,148 passed; one pre-existing FastAPI `regex` deprecation warning |
| Ingestion full suite | 644 passed |
| Operational-script suite | 61 passed; 20 subtests also passed and are not counted as additional tests |
| Frontend source tests | 33 passed |
| Frontend component/unit tests | 173 passed |
| TypeScript and production build | Passed; 28/28 static-generation items, 30 app routes plus not-found; build APIs restricted to unreachable loopback |
| Scoped Ruff I/F and whitespace checks | Passed |
| Six shared API/ingestion scientific-module mirrors | Byte-identical |
| Chromium synthetic desktop/mobile smoke | Passed: valid citation indices with contradicted draft/abstention, expanded evidence, legacy unchecked response; viewport and document width both 390 px |

The new backend regressions cover independent numerical/negation/pressure changes, English/Chinese and Unicode formulas, compatible units, range/bound/uncertainty preservation, material/state/criterion/origin/source-role attribution, derived Facts, malformed metadata, cross-sentence qualifications, unsupported claims and languages, negative-temperature roles, provider/no-source fallbacks, postprocessing mutation, response shape and history delivery. These are **synthetic software fixtures**, not factual superconductivity claims, production observations or human-adjudicated gold evidence.

All API/database tests use the guarded disposable runner:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server --suite api -- -q --tb=short
```

Browser smoke used local synthetic API fixtures with external requests blocked. CSP bypass was used solely for fixture interception, so this is not a CSP certification. Owned browser-test services have exited; disposable API test services and temporary test data were cleaned up. The screenshots were visually inspected; this is not a real-device/screen-reader audit, representative-scale latency benchmark or production-data validation. No database migration is introduced by RG01; migration 0050 belongs to the preceding SC06 batch.

## Release gates and deferred work

1. Keep RG01 open until dependencies, reviewed revisions, deployment compatibility and acceptance evidence are approved. Local synthetic tests do not close the issue's human-adjudicated evaluation gate.
2. Build an independently reviewed gold set and report citation-index accuracy separately from support precision/coverage, numeric/unit correctness and abstention. No real-world accuracy, sensitivity, recall or calibration claim is made here.
3. Review and extend the controlled grammar against real permission-eligible excerpts, including multilingual and compound scientific assertions. Unsupported languages/phrasing remain undetermined. Do not waive hard number, negation or material-state failures using aggregate pass rates.
4. Implement immutable source-version/root lineage and original-versus-derived evidence contracts under RG02/ML01. Current paper/chunk metadata cannot prove evidence independence or source-version completeness.
5. Preserve per-answer draft/assessment/source revisions in an explicitly designed, privacy-conscious audit snapshot before using saved answers as reproducible research artifacts. Existing history is not that audit ledger.
6. Validate representative-scale latency and source/governance concurrency in staging. This batch adds no shared scientific cache and does not claim to solve changes to source restrictions during an in-flight model call.

Recommended next implementation batch: [SC10 #53](https://github.com/JackZH26/SCLib_JZIS/issues/53), separating unknown values, family-derived priors, conflicting claims and genuinely independent evidence in material semantics. This continues the Phase A database-quality work; it does not replace RG01's remaining human-evaluation gates.

See [the support contract](../../RAG_SUPPORT_CONTRACT.md), [the previous Timeline batch](Phase_A_Sixth_Batch_Implementation_2026-09-06.md) and [the shared visibility contract](../../VISIBILITY_POLICY.md).
