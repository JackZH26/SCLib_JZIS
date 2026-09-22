# SCLib Phase A — Sixth implementation batch

Date: 2026-09-06. Primary issue: [SC06 #50](https://github.com/JackZH26/SCLib_JZIS/issues/50). Tracker: [#41](https://github.com/JackZH26/SCLib_JZIS/issues/41).

Status: local implementation and verification, not issue closure or production rollout. The branch remains `codex/sclib-research-v2`, based on commit `c6f05f1ca757f692d3f5169768b2fd75c6f685eb`. The preceding SC07 batch was already uncommitted when this work started and has been preserved; the complete Git diff contains both batches. No commit, push, production connection, production migration/backfill, deployment, paid extraction or scientific approval was performed. Migration checks used disposable test databases only.

Progress has been recorded on [SC06 #50](https://github.com/JackZH26/SCLib_JZIS/issues/50#issuecomment-5557657988) and [the tracker #41](https://github.com/JackZH26/SCLib_JZIS/issues/41#issuecomment-5557658112). Both issues remain open pending the release gates below.

## Outcome

The website now calls this view **Reported Tc Timeline**. It presents provenance-bearing reported results, not a complete discovery history or verified world-record progression. Numerically overlapping results are retained; display clustering and sampling no longer determine scientific result identity.

This matters for subsequent ML work: two sources, samples or Tc criteria must not become one label simply because their plotted coordinates happen to be close. A bibliographic year must not become a measurement or discovery date without evidence, and an extrema summary must not be inferred from a display sample.

## Implemented scientific contract

### Identity and chronology

- Removed rounded year/Tc/pressure deduplication. Different papers, samples, states, source locations and onset/zero criteria remain separate even when their values coincide.
- A supplied result ID and revision are retained, but are not represented as checked against an adjudicated registry. Conflicting occurrence content claiming the same ID/revision remains visible as separate points with explicit identity warnings.
- Legacy occurrences receive material-scoped content identifiers. Known derived/governance metadata is excluded from scientific identity; original scientific/source content is retained in the fingerprint. Exact repeated occurrences consolidate only with an explicit `occurrence_count`, not an assertion of independent replication.
- Point ordering and IDs are stable under input permutation. Source filtering no longer depends on whichever nearby result happened to be encountered first.
- Each point includes a `point_id` and bounded `result_metadata`: result ID/revision, identity basis, year basis, source date/basis/version, state/sample fields, Tc criterion, source locator, occurrence count and warnings.
- Chronology prefers explicit measurement fields, explicit report fields, then generic legacy year, bibliographic publication/submission dates and a compatibility source-year fallback. Generic `year` is labelled `legacy_record_year_unspecified`. Disagreeing valid assertions are disclosed; malformed explicit chronology is not silently replaced by another date.
- Database edit/ingestion timestamps never become scientific dates or invented source revisions. Missing version information remains missing. Raw alternatives remain in the authorized material Archive.
- Nonfinite, non-exact, malformed or scientifically held values are excluded individually by extraction rather than repaired, rounded into a different result or allowed to crash the response. A 0.03 K result remains 0.03 K. Existing raw records are not rewritten.

The SC07 **whole-material governance hold** remains separate: a malformed/held record can still hold its material out of the default catalogue. Explicit Archive mode can show its numerically eligible sibling results while retaining the parent warning. This batch does not silently relax that policy or claim that all default eligibility is result-local.

### Sampling and complete filtered-data summaries

The display sampler stratifies by family, resolved origin, pressure state and decade. It reserves global Tc/time bounds where the budget permits, then selects deterministically across groups, prioritizing small strata before adding density. If the budget cannot represent every group, omitted strata and rare-group counts are reported.

This deliberately balanced display is **not a statistically representative population sample**. No inference about corpus frequencies, reliability or ML performance should be made from rendered marker density.

`record_summary` is computed from the complete currently filtered, eligible, unsampled point set. It includes counts by family/origin/year basis/pressure state; material and bibliographic-source counts; minimum/maximum reported Tc; family maxima; and a bounded list of tied highest-Tc results with the true tie count. Pagination and display budgets cannot change that summary or the underlying dataset digest. The phrase “highest reported Tc in this filtered dataset” never becomes “world record.” Source counts describe bibliographic identifiers, not resolved independent works or experimental replications.

Sampling metadata distinguishes full results, selected results before pagination, returned results, represented/omitted groups and selected source coverage. Result counts refer to retained occurrences after exact duplicate consolidation, not a count of every original JSON row.

### Frontend and accessibility

- English page, metadata, navigation and API-reference copy consistently describe reported results, not discoveries or a complete historical inventory.
- Identical year/Tc coordinates form display-only clusters. No horizontal date jitter or scientific value substitution is used. All received members, identities and source counts are inspectable; server sampling can omit additional members from the underlying full dataset and is disclosed separately.
- A keyboard-accessible paginated table and overlap selector provide material/source links, result anchors, pressure/origin/source-role information and expandable source/state/revision details. These are links to existing material/source pages and received result rows, not invented canonical-result endpoints.
- Non-color marker symbols distinguish reported origins and mixed/unknown groups. Observed origin is not independent experimental confirmation.
- Significant figures and mK labels preserve small positive temperatures. Linear, logarithmic and 0–1 K views expose low-temperature results without changing their values.
- The SVG fallback has a disclosed 3,000-coordinate-cluster renderer bound. It is not another alleged representative sample; every received result remains in the accessible table, even when not rendered.
- Full-data extrema/coverage are shown only when supplied by the server with `full_filtered_unsampled` scope. The frontend does not reconstruct them from received markers.
- Dynamic source strings are escaped before Plotly interprets HTML. Shared formula HTML handling also escapes source text while preserving formula formatting.
- Legacy result review remains explicitly unavailable/unreviewed. The API rejects `reviewed_only=true` instead of silently returning legacy results. SC07 Archive/noindex/cache and privacy safeguards remain intact.

## API and projection versions

| Contract | Version / change |
| --- | --- |
| REST response envelope | Existing schema `1` retained for additive-field compatibility |
| Timeline interpretation | `reported-tc-timeline/2.0.0` |
| Result identity / chronology | `timeline-result/1.0.0` |
| Display sampling | `timeline-stratified/1.0.0` |
| Rebuildable projection | Schema `5` |
| Database migration | `0050_timeline_identity`, derived `result_metadata` JSONB only |

The response exposes these semantic versions; additive envelope compatibility does not imply unchanged point counts or deduplication. Frozen research exports and unrelated property/claim identity contracts have not been silently redefined.

Migration 0050 invalidates projection readiness in both directions. Existing numeric-bucket rows cannot be mistaken for current occurrence identities until a controlled rebuild completes. Downgrade removes only derived metadata, not raw source records or correction ledgers. The disposable migration regression verifies upgrade, downgrade/upgrade, readiness invalidation, original 0.03 K preservation and refusal to discard a nonempty scientific-correction ledger.

Projection reads retain SC07 live material/parent/source governance. New materials, changed source dates or source deletion invalidate stale projections; internal source snapshots detect deletions/date races and are stripped from public metadata. Missing/corrupt metadata, false cached acceptance, invalid scalars or unsupported metadata shapes trigger current-raw fallback. Lookups and upserts are batched to stay below PostgreSQL/asyncpg parameter limits, including a fallback fixture with 33,001 source IDs.

This is a rebuildable read projection, not an immutable source-revision store. Source changes conservatively require full refreshes; performance and concurrency limitations remain release gates below.

## Verification

Final verification: **1,841 tests passed** (957 API + 644 ingestion + 61 operational-script + 33 frontend source + 146 frontend component/unit). Targeted runs are not double-counted in this aggregate.

| Check | Result |
| --- | --- |
| API full suite | 957 passed; one pre-existing FastAPI `regex` deprecation warning |
| Ingestion full suite | 644 passed |
| Operational-script suite | 61 passed |
| Frontend source tests | 33 passed |
| Frontend component/unit tests | 146 passed |
| TypeScript and Next production build | Passed; 28 static-generation items; both API bases set to unreachable loopback, not production |
| Migration 0050 and correction-ledger rollback guards | Passed in capability-checked disposable services |
| Scoped Ruff I/F, whitespace and six scientific-module parity checks | Passed |
| Local Chromium smoke with synthetic fixtures | Passed; two overlapping results remain selectable, logarithmic view works, and the full 2019–2027 fixture domain remains visible on mobile |

Tests include permutations, close/equal coordinates across sources/states/criteria, conflicting canonical-ID assertions, source date precedence, missing/malformed chronology, nonfinite values, low-T precision, projected/fallback parity, deleted/changed sources, invalid cached metadata, bounded source queries/upserts, unsampled summaries versus display pages, rare-group omissions, cluster membership, keyboard table navigation, safe links, symbols and escaped Plotly strings.

API and migration checks must run through the capability-checked disposable runner:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server --suite api -- -q

api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server --suite migrations
```

The final browser smoke used only owned loopback frontend/API fixtures; non-loopback requests were blocked. At a 390 px viewport, document width was 390 px and both plot container and SVG were 356 px, without horizontal page overflow. The displayed material values and dates were synthetic test fixtures, not production observations. The owned browser-test servers and temporary test databases/services were cleaned up. Synthetic regression success is not a current production-data audit, Linux CI validation or real-device WebGL/accessibility certification; it also does not constitute a screen-reader audit or production-scale performance benchmark.

## Release gates and next work

1. Review a traceable PR/revision and coordinate API/frontend/migration versions. Keep #50 open until its dependency, review and release evidence is accepted; this local batch is not production authorization.
2. On an authorized representative snapshot, compare retained-result counts and date/identity coverage. Content-preserving transitional IDs intentionally retain possible duplicates when identity cannot be proved; `occurrence_count` is not replication.
3. Measure raw fallback, memory, source lookups, full rebuilds and browser rendering at realistic scale. Conservative source freshness checks can increase rebuild/fallback work; an indexed dependency graph and transactional source/governance epoch are needed before optimizing shared caching or claiming release-consistent concurrent reads.
4. A permalink to a received legacy point is not an immutable release permalink. Canonical result/state/revision registries, temporal availability and approved ML data releases remain separate ML01/ML03/ML04/ML07 work. Do not train directly on Timeline display samples.
5. Complete staging browser testing, including actual WebGL failure, keyboard focus, small screens and screen readers. API/unit tests and a successful build do not replace that release check.

Recommended next batch: [RG01 #62](https://github.com/JackZH26/SCLib_JZIS/issues/62), separating citation-index validity from scientific claim support and adding quantity/unit/polarity/material-state checks in Ask. Its adjudicated gold-set and scientific-support claims remain gated; a lexical or LLM score is not proof.

See [the result and chronology contract](../../TIMELINE_RESULT_CONTRACT.md) and [the preceding SC07 implementation](Phase_A_Fifth_Batch_Implementation_2026-09-06.md).
