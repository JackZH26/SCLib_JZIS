# SCLib Phase A — Eighth implementation batch

Date: 2026-09-07. Primary issue: [SC10 #53](https://github.com/JackZH26/SCLib_JZIS/issues/53). Tracker: [#41](https://github.com/JackZH26/SCLib_JZIS/issues/41).

Status: local implementation and verification complete; not scientific approval or production rollout. Work remains on `codex/sclib-research-v2`, based on `c6f05f1ca757f692d3f5169768b2fd75c6f685eb`. Existing uncommitted SC07, SC06 and RG01 work is preserved. No commit, push, production connection, deployment, production migration/backfill or paid extraction run is part of this batch.

GitHub progress publication remains pending. The preceding batch's comment attempts were rejected with HTTP 403 (`Resource not accessible by integration`). This batch does not bypass that permission boundary, claim a remote update or close SC10.

## Outcome and scope

The material catalogue now separates reported classifications, unresolved missingness, family priors, extraction inconsistencies, state variability and bibliographic support. Missing evidence does not become `false`; family heuristics do not become observed labels; multiple identifiers do not establish independent replication.

The first contract deliberately covers only three existing properties: `pairing_symmetry`, `is_unconventional` and `has_competing_order`. Other quantitative properties retain their existing atomic evidence and anomaly-review contracts. This is not a complete ontology of superconductivity, a reviewed training dataset or a mechanism adjudicator.

## Shared semantic contract

`material_semantics.version = material-semantics/1.0.0` is implemented by byte-identical API and ingestion modules. The derived envelope is rebuildable metadata, not input evidence or scientific approval.

| Status | Meaning and restriction |
| --- | --- |
| `reported` | An eligible retained source assertion; not scientific acceptance or a universal material property |
| `unknown` | The value or reason for absence is unresolved; no negative inference |
| `not_reported` | Explicit declaration that the source does not report the property; not inferred from a missing extraction key |
| `not_extracted` | Explicit extraction-status declaration, distinct from source silence |
| `not_computed` | Explicit computation-status declaration, not a computed zero or negative result |
| `failed` | Explicit unsuccessful assessment status; not a physical outcome |
| `conflicted` | Unresolved field conflict; known extraction inconsistencies remain distinct from a generic source-declared conflict |
| `not_applicable` | Explicit declaration with a reason; never inferred solely from family membership |

Missing legacy keys remain `unknown` when source silence cannot be distinguished from incomplete extraction. The NER prompt must not invent pipeline, review or acceptance statuses. Optional new booleans require literal JSON booleans, not string or numeric truthiness.

### Reported values and qualified negatives

- A reported `false` must retain an attributable source, method and detection conditions. An unqualified raw `false` remains inspectable evidence but cannot populate a material-wide negative summary or match a false classification filter.
- Qualification checks metadata completeness and format; they do not verify whether an experiment can establish the asserted absence. Absence is limited to the reported detection conditions, not universal.
- Existing explicit `competing_order` labels can support a reported order indicator, with their original label retained. The envelope explicitly warns that a reported order is not proof of causal competition with superconductivity. Bare CDW/SDW/AFM transition temperatures cannot produce this boolean.
- Preserve source role, result origin, method, sample/state, pressure, doping, locator and bounded status reasons. Private structured reviewer/curator metadata is not exposed as semantic evidence. This is an allowlist boundary, not a general personal-data detector for arbitrary source prose.
- Conflicting alternatives are not resolved by confidence weighting, majority voting or source counts. Exceeding bounded assessment limits invalidates reported-value promotion; truncation and incomplete assessment are explicit.
- Pairing text longer than the existing 100-character storage limit remains unresolved, with an explicit reason. It is not truncated into a different label; the full raw record remains intact.

### Priors, variation and governance

Historical cuprate family heuristics are displayed separately as `Inferred` priors, with their application-rule provenance, policy version and non-universal applicability. They are not newly adjudicated scientific references and do not populate reported properties or classification filters. Other family defaults are removed from those observed-looking summary slots rather than replaced with invented literature-backed rules.

Different state-dependent reports and extraction conflicts have separate diagnostic channels. A Tc-variability diagnostic requires differing finite, positive, exact reported Tc values and explicitly different known state/sample/pressure/doping context; bounds and uncertain values are not converted into point observations for this check. Numerical Tc spread alone no longer creates a new scientific-dispute flag. Explicit reported disputes, curated refutations and pre-existing catalogue dispute holds remain unadjudicated and are not automatically cleared. The upsert boundary preserves an existing database `disputed=true`, including when a fresh extraction omits the flag.

The existing family/classification audit remains a review signal, but its suggested action no longer tells a curator to manufacture a negative label from a family category. Its operational rule identity and hold behavior are unchanged.

### Support counts

Expose retained occurrence counts, distinct bounded occurrence identities, source-backed occurrences and bibliographic identifier counts separately. DOI, arXiv and catalogue identifiers can describe the same work. Legacy `total_papers` can also include parent rollups or other catalogue counting policies; an explicit count-basis diagnostic explains why totals may differ.

`independent_work_count` and `independent_replication_count` remain `null`. Neither copied passages, repeated extraction records, publication versions, shared sample IDs nor repeated papers establish experimental independence. Numeric-pool selection remains a legacy heuristic, with its wording changed from confirmation to bibliographic support; SC10 does not validate that numerical heuristic.

## Read surfaces and filtering

Material lists, details, variants and bookmarks rebuild semantics from retained records. Stored `material_semantics` cannot override the current evidence or source-status map. Public reads use current paper governance status; corrected, retracted or unresolved source eligibility cannot be rescued by a stale stored envelope. Direct legacy/offline projections without a source-status map explicitly warn that current status was not checked.

The three classification filters now operate on the same reported summaries shown by the response, not stale scalar SQL prefilters. Unknown, unsupported false and family priors cannot match. Eligibility is applied before exact counts and pagination.

The response declares `classification_filter_policy_version` and `classification_filter_scope = material_reported_summary_not_joint_state`. These classification predicates do **not** assert a joint Tc/pressure/sample observation with the existing same-result numerical filters. Inspect the individual classification evidence before combining it with a quantitative result. The API documentation and English UI state this limitation.

English-default material cells distinguish unknown, reported, scoped false and not applicable. The detail panel separates priors, conflict diagnostics and support counts. Older or malformed envelopes fail closed rather than falling back to legacy flags. The Discovery stage's visible label changes from “Literature-confirmed” to “Literature-reported”; the persisted stage code and score calculation are unchanged.

## Storage and migration 0051

Migration `0051_material_semantics`, following the preceding batch's 0050, adds a non-null, rebuildable JSONB envelope with an empty default. API ORM and ingestion table definitions stop reintroducing a false default for `has_competing_order`.

Important historical detail: migration 0004 had already removed the database false default. The verified drift was in the hand-maintained ORM/writer definitions and aggregation behavior; this report does not assert that the current production column still has that default. Migration 0051 idempotently enforces the nullable/no-default contract.

No existing raw record, false flag, prior-looking scalar or dispute hold is rewritten by the migration. Downgrading drops only the rebuildable envelope and retains the previous nullable/no-default behavior and existing NULLs. Subsequent aggregation would update derived summaries only when separately approved and run. Direct SQL consumers must not treat untouched historical booleans as verified labels.

## Verification

Final verification: **2,240 tests passed** — 1,247 API + 671 ingestion + 61 operational-script + 35 frontend source + 226 frontend component/unit tests. The 80 pure-semantics and 19 read-surface tests are included in the API total, not added a second time. Operational-script subtests and the scripted migration scenarios are also not counted as additional tests.

| Check | Result |
| --- | --- |
| Full API suite on the final shared module | 1,247 passed; one pre-existing FastAPI `regex` deprecation warning |
| Full ingestion suite after the 100-character compatibility fix | 671 passed |
| Operational-script suite | 61 passed; 20 subtests also passed |
| Frontend tests after the final source-status safeguard | 35 source + 226 component/unit passed |
| TypeScript and production build | Passed; 28/28 static-generation items, 30 application routes plus not-found |
| Guarded migration integration | 0051/0050 material-semantics and NULL-default roundtrip, existing 0050 Timeline roundtrip, raw/governance preservation and correction-ledger rollback protection passed |
| Scoped Ruff I/F and whitespace checks | Passed for new/changed SC10 logic; see the existing indexer-file exception below |
| Seven shared API/ingestion scientific modules | Byte-identical |
| Synthetic desktop/mobile Chromium smoke | Passed; qualified false and its source/conditions remain inspectable; unknown, priors and legacy-unchecked responses remain distinct |

The pre-existing `ingestion/ingestion/index/indexer.py` import-order and two unused-import findings remain unchanged. The same three I/F findings were verified against `HEAD`; the two SC10 schema changes do not add a lint finding. This is a scoped lint result, not a claim that the entire historical repository is lint-clean.

The browser checks used local synthetic fixtures with external requests blocked. Screenshots were visually inspected: mobile viewport and document width were both 390 px, with a 358 px panel and internal table scrolling. No page errors or external requests were observed, and owned browser-test servers exited. The screenshots precede only the final nonvisual source-status/family-default helper safeguard; tests, TypeScript and build were rerun afterward. This is not a real-device, screen-reader, production-data or representative-scale performance certification.

All API/database and migration checks run through the guarded disposable-service runner. Ingestion tests use unreachable loopback database/Redis endpoints; frontend verification uses synthetic fixtures and unreachable loopback APIs. No production credentials or data are used.

```bash
api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server --suite api -- -q --tb=short

api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server --suite migrations
```

Disposable test services and their temporary data were cleaned up. Earlier test-fixture assumptions about the pre-0051 database default and a literal material ID were corrected against the existing migration history and canonical ID function; final relevant suites and migration checks passed.

## Release gates and deferred work

1. Review the exact code revision and deploy schema/application compatibility together. This local batch does not execute 0050 or 0051 in production or authorize a historical backfill.
2. Preserve unresolved old values and dispute holds until a source-linked curator decision. Do not blanket-convert historical false values into accepted negatives or automatically clear historical numeric-dispute flags.
3. Validate representative real records and review negative-detection metadata. Synthetic regression tests demonstrate software invariants, not scientific precision, coverage or inter-reviewer agreement.
4. Establish source-version/work/sample lineage before counting independent evidence or building independence-aware ML splits. Those counts remain unknown in this contract.
5. Bind future ML features and labels to reviewed result/state revisions. Classification summaries, family priors, source counts and UI coverage are not automatically admissible training targets.
6. Measure latency with representative record volumes. Classification filters scan the current eligible source pool to preserve exact semantics; this batch adds no independently invalidated shared semantic cache or indexed result-level classification projection.
7. Extend the three-field vocabulary only with explicit provenance, missingness and applicability rules. Do not expand every scientific column or add uncalibrated confidence/probability scores merely to fill the schema.

See [the material semantics contract](../../MATERIAL_SEMANTICS_CONTRACT.md), [the preceding Ask batch](Phase_A_Seventh_Batch_Implementation_2026-09-07.md) and [the shared visibility contract](../../VISIBILITY_POLICY.md).
