# Twenty-first implementation batch — immutable index generations

Date: 2026-09-08. Branch: `codex/sclib-research-v2`.
Baseline: `859df57` (twentieth batch).
Priority: [RG03 / #69](https://github.com/JackZH26/SCLib_JZIS/issues/69),
following the 0060 evidence and 0061 complete-input foundations.
Operational specification: [index generations](../../INDEX_GENERATIONS.md).

## Outcome and boundaries

Search, Ask and Similar now read an explicit immutable generation instead of
interpreting positional ANN IDs as current mutable SQL chunks. A retained
generation can be published, fully verified over its declared membership,
explicitly activated and rolled back while preserving its original text,
attribution and vectors. A real five-to-three ingestion replacement cannot
silently mix old vectors with new text.

This is a **bounded local implementation increment**, not RG03 closure or
production migration. Each generation is limited to 1,000 members and 16 MiB
aggregate retained chunk/Paper JSON. Production sources, rights, full-corpus
inventory, recall, actual cloud spend, Linux/release-image CI and deployment
acceptance have not been demonstrated by synthetic native tests. No production
write, paid provider call, branch push, PR or issue closure was performed.
All new public and operator copy remains English.

## Implemented work

1. **Additive 0062 immutable history.** Frozen generation headers, full chunk
   and Paper snapshots, canonical float32 vectors, exact evidence/receipt
   hashes, parser/chunker versions, complete manifests, validation observations
   and activation events. Retained members do not depend on replaceable Chunk
   foreign keys. Append-only triggers and populated-downgrade refusal preserve
   history. Frozen 0052–0061 contracts and ML04 capsules are unchanged.
2. **Bounded exact staging.** Count/byte SQL preflight before payload hydration;
   exact current evidence/receipt/source binding; independent full-text token
   recount; actual producer labels; tokenizer setup before shared fences.
   Dry-run, outer rollback and exact replay preserve all rows and epochs.
3. **Actual writer bridge.** Prospective parser identity and a read-only
   receipt-bound candidate bridge. Both actual APS and arXiv writers expose a
   SQL-only staging callback inside their real paper/chunk transaction. Failure
   rolls back all layers. Normal ingestion does not implicitly publish or
   activate a corpus; the declared member set is an explicit operator choice.
4. **Verified vector adapter.** Immutable opaque IDs; actual resource/profile,
   distance, normalization and deployment validation; generation/space query
   restrictions; returned full float32 vectors and three binding hashes. Public
   low-level SDK messages preserve numeric restrictions and full datapoints.
   Existing same-ID conflicts fail closed; missing-only publication resumes
   interrupted batches. No delete path is implemented.
5. **Honest reconciliation.** Compare all declared members, not aggregate
   counts. Read-only missing/hash/orphan/pending/upsert-candidate plans. Public
   known-ID readback does not assert unknown-orphan absence; disposable fixtures
   enumerate only their synthetic generation. Unknown hits cannot pass SQL
   membership but unknown remote data could still reduce ANN recall.
6. **Fresh validation and CAS.** Canonical observation UUID and microsecond UTC
   completion time; both observation and DB-receipt freshness checks; separate
   explicit activation, predecessor/event-number CAS, exact idempotency and
   genuine rollback. Direct SQL and service paths enforce source/accepted-Work
   holds, including corrected→active ABA. No activation confers scientific or
   source-use authority.
7. **Live retrieval integration.** All three routes pin before ANN and hydrate
   only matching members; lexical fallback stays inside the same generation.
   Frozen bibliography/text is separated from fresh source/material/permission
   governance. Post-LLM checks detect activation ABA and held evidence. Search
   rechecks retained SQL years and withholds restricted/stale material payloads.
   Similar bounds the union of source-chunk queries and stops subsequent work
   after timeout. With no active generation Search/Ask are legacy lexical-only;
   Similar returns sanitized 503.
8. **Public read identity.** Closed `index-read/1.0.0` metadata exposes only mode,
   generation UUID, activation UUID and manifest hash. It contains no private
   resource details or scientific-quality claim. Existing Ask history does not
   yet persist this response-level generation/event pin.
9. **Usable private operator CLI.** Explicit database target and strict schema
   admission; preview-only defaults; separate publication, remote readback,
   validation and activation authority. Inspect reports exact current active
   event for recovery. Historical activation receipts are not mislabeled current.
   Failure output handles uncertain commits without leaking SQL/source payloads.

## Independent review findings resolved

- Hash-only retention cannot restore old source text after replacement: retain
  actual full snapshots and canonical vectors, not a mutable row pointer.
- A service-only lifecycle check was bypassable by raw SQL after Paper status
  ABA or through an accepted Work's durable hold. A native reproduction showed
  the gap; direct SQL now checks those histories too.
- A 15-minute DB receipt age did not bound an old report's delayed first
  submission. The actual observation completion time is now independently
  bounded at recording and activation; no provider-attestation claim is made.
- Declared-ID readback is not full remote enumeration. Separate these scopes;
  reject unknown ANN members without claiming orphan cleanup or unchanged recall.
- Remote year metadata can change independently of content/vector/revision
  tags. Recheck the retained SQL year after ANN. Withheld evidence must also
  withhold material payloads that might contain source quotations.
- Read-only inspection must work without current cloud-profile compatibility;
  it must show the exact active event needed after an uncertain commit. Replayed
  historical receipts must remain distinct from current active state.
- CLI imports do not run FastAPI schema admission. Add the same strict schema
  check on a fresh connection before opening an operator session.
- The new receipt foreign key rejects plain TRUNCATE before its append-only
  trigger. Test both that FK refusal and trigger refusal for CASCADE in the
  guarded disposable database, with unchanged-state assertions.

## Verification

Verification is performed only through the guarded disposable native runner,
inert ingestion configuration and synthetic/mocked vector providers. No live
corpus or provider credentials are used by tests. Focused tests are included in
their full suites and are not counted twice.

Final suites passed after the independent review and regression fixes:

| Check | Result |
| --- | --- |
| API full suite | 2,592 passed; 20 existing deprecation warnings |
| Ingestion full suite | 1,275 passed; 34 existing dialect warnings |
| Scripts full suite | 287 passed + 36 subtests |
| Frontend source/unit suites | 35 + 288 passed |
| Frontend TypeScript | Passed |
| Dedicated 0062 core | 47 passed, included in full API suite |
| Vector adapter | 66 passed, included in full API suite |
| Generation/currentness routes and related regressions | 189 passed, included in full API suite |
| Root operator/ingestion/metadata integration | 8 + 10 + 12 focused tests; included in full API suite |
| Complete migration rehearsal | Passed, including independent older guards, 0062 empty roundtrip, stage/validation/CAS, retained rollback and populated downgrade refusal |
| Locked dependency resolution | Both API and ingestion checks passed |
| Ruff I/F and whitespace | Passed for changed/new Python files and final diff |

Total: **4,477 ordinary tests plus 36 script subtests**, excluding duplicate
focused runs and counting migration/type/lint/lock checks separately.

The first full API run exposed the receipt test's expected error ordering and
a test using the wrong validation outcome name. Both were corrected; no schema
guard was relaxed. The final suite is rerun from a fresh disposable database.
Ruff import/undefined-name checks and whitespace checks cover changed and new
Python files. Native macOS verification is not Linux release-image acceptance.

## Acceptance still outstanding

| Area | Remaining requirement |
| --- | --- |
| Corpus-scale migration | Reviewed membership/coverage plan beyond the 1,000-member pilot; no silent canary replacement of the whole site |
| Remote reconciliation | Unknown remote inventory, operational lag metrics, tombstone/retention approval and bounded cleanup implementation |
| Measurement | Actual before/after corpus coverage, rejection/truncation, provider tokens/cost and build/query latency; no synthetic recall claims |
| Historical answers | Persist/resolve response-level generation/event pins and separately revalidate prior answers under source changes |
| Scientific/RG02 dependencies | Reviewed original roots, permission and canonical Result bindings; generation integrity is not evidence acceptance |
| Release | Current-SHA Linux/release-image CI, authorized canary, documented no-active behavior, exact activation/rollback rehearsal and explicit production approval |

Issue #69 was checked read-only and remains **OPEN**. Dependencies #65/#42 and
other issues retain their own acceptance gates; no status is inferred from this
implementation report. Continue local dependency-ready work, but obtain new
authority for production/cost/source-release actions rather than silently
expanding the scope of the persistent goal.

## Next local increment

Prioritize RG04a, formula-safe, same-result scientific query routing, under
[RG04 / #75](https://github.com/JackZH26/SCLib_JZIS/issues/75). Preserve raw
formula/notation and explicit unresolved qualifiers; equivalently render
`MgB₂/MgB2` and `LaH_{10}/LaH10` without merging isotope, variable-composition,
phase or interface ambiguity. Reuse the shared quantity/pressure/origin/outcome
semantics on one exact source-linked occurrence. Keep generation/currentness
checks and explain interpreted constraints/refusal in English.

Tests must reject cross-result Tc/pressure pairing and unknown-as-ambient,
preserve computed/cited/not-detected/bounded distinctions, and retain current
source/permission holds through fallback and rollback. This is a development
regression increment, not an adjudicated gold benchmark. Full complementary
evidence packing, independent reviewers, held-out evaluation, actual cost and
latency remain distinct gates. Do not repurpose existing metadata-disclosure
review authority as scientific-result acceptance. The RAG evaluation document's
unsafe bare-pytest example and pre-generation descriptions were corrected in
this batch; future evaluations must use the guarded test runner.
