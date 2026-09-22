# Twentieth implementation batch — complete inputs and embedding receipts

Date: 2026-09-08. Local branch: `codex/sclib-research-v2`.
Baseline: `33c788e` (nineteenth batch). Priority:
[RG03 / #69](https://github.com/JackZH26/SCLib_JZIS/issues/69), after the
0060 typed-evidence and existing disposable-test foundations.
Operational specification: [complete-input contract](../../EMBEDDING_COMPLETENESS.md).

## Outcome and scope

Future chunks are bounded by their complete text, including metadata and
overlap. Embedding calls explicitly disable automatic truncation, validate
every response and retain exact text/vector-bound completion metadata. Actual
arXiv and APS SQL writers persist immutable response receipts atomically with
their chunk/evidence writes. Similar failures are bounded and explicit.

This is the complete-input foundation for RG03, **not completion of RG03**.
No production corpus has been re-chunked, re-embedded, reconciled or activated.
No cloud embedding, paid provider request, index upload, deployment, branch
push, PR creation or issue closure was performed by this batch. Public copy
remains English. Native synthetic tests are not Linux release-image CI or
scientific evaluation.

## Implemented changes

1. **Source-preserving chunker 2.0.0.** Exact complete-string cl100k bounds;
   bounded, visibly shortened title/section prefixes; exact character windows
   and parsed-section locators; progress-safe overlap; Unicode-safe splitting
   for long sentences, abstracts, OCR, formulas, CJK and tables. The body is
   never repaired by replacing undecodable token fragments.
2. **Atomic Facts renderer 2.1.0.** Exact full-input counting and the shared
   prefix policy. Oversized scientific units fail before returning a partial
   Facts list. Negative outcomes, pressure, detection limits, field, origin and
   role remain part of the statement. Rejection has a fixed code rather than
   copying sensitive transient/source content into the failure audit.
3. **Closed embedding contract.** Distinct document/query tasks; reviewed
   model/dimension profile; separate local and provider count methods/limits;
   exact response inventory, explicit untruncated statistics and valid vectors.
   All document batches validate before any new in-memory completion is
   assigned. SDK conversion is covered, not merely a mock configuration field.
4. **Transport-real vector identity.** Canonical float32 values and binary32
   hashes match the index protobuf wire representation. Invalid numerical
   vectors, overflow and zero-after-underflow fail before publication.
5. **0061 completion ledger.** Text-free append-only observations bind to the
   current 0060 revision, current source snapshot and actual SQL chunk hashes.
   Vector and local-count checks run in the trusted writers. API tokenizer
   initialization occurs before the shared integrity fence. Exact replay and
   dry-run preserve the full database state. SQL-only chunks have no invented
   completion. Frozen schemas/capsules remain untouched.
6. **Actual writer/publication integration.** Both production code paths append
   inside the paper/chunk/evidence SQL transaction. Publication prevalidates
   the whole input inventory before obtaining a cloud client. Failure cannot
   silently skip one unembedded chunk and upload the rest as a complete set.
   SQL transaction atomicity does not extend to the later cloud operation.
7. **Attempt observations.** Small fixed-shape summaries expose local full-text
   counts, stage timing and validated returned provider-token subtotals. Missing
   reports and failed attempts retain unknown usage/cost; no source text or
   raw receipts are logged by the summary. This is not a billing/corpus ledger.
8. **Similar failure contract.** Incomplete input, embedding/ANN failures and
   timeout return sanitized 503. Successful empty retrieval stays 200. One
   bounded provider attempt avoids repeating already completed per-chunk work;
   after timeout no subsequent call starts when the current SDK call returns.

## Independent review findings resolved

- Raw SQL could accept a numerical JSON hash that happened to stringify to
  64 valid digits. Controlled text fields now require actual JSON strings.
- The internal receipt service initially trusted a declared cl100k count.
  A 101-token input claiming one token reproduced the gap. It now independently
  recounts the actual SQL text, with unavailable-tokenizer refusal and rollback.
- Hashing Python float64 values did not bind the actual float32 index transport.
  Canonicalization and overflow/underflow tests now enforce the wire identity.
- Similar did not handle the new strict embedding failures. HTTP regression
  tests verify sanitized failure, timeout, no additional SDK work and genuine
  empty success.
- A failed all-or-nothing embedding attempt can leave pre-existing fields
  unchanged. Observation summaries must not attribute those old reports to the
  failed attempt's provider usage.
- Initial integration fixtures used an invalid synthetic arXiv identifier.
  The fixture was corrected; the real identifier validator was not weakened.

## RG03 acceptance matrix

| Acceptance area | This increment | Remaining work |
| --- | --- | --- |
| Complete chunk bounds | Implemented and adversarially tested for final strings and atomic Facts | Authorized corpus coverage and semantic/context QA; long-label storage cases |
| Explicit truncation and model profile | Strict document/query response validation and persisted completion metadata | Actual deployed-index resource/model verification and future profile migration |
| Immutable identities/current hydration | Exact content/vector hashes and immutable response/evidence history | Generation-scoped chunk IDs, parser identity and pinned query hydration |
| Shrink/replacement/interruption | SQL rollback, historical receipt preservation and complete upload admission | Real staged vector inventory, stale-ID handling and no partial active generation |
| Reconciliation | No production action; mismatch risks explicitly documented | Bounded SQL/vector dry-run audit, orphan/missing/hash/profile reports and repair plans |
| Build/promotion/rollback | Additive migration/receipt rehearsal only | Disposable staged build, validation, explicit activation and reversible generation switch |
| Operational evidence | Local tests and per-attempt counters/timing with unknown cost | Authorized before/after corpus metrics, actual spend and build/query latency; separate retrieval/science evaluation |

## Verification

All final suites passed after the independent review fixes. The initial
ingestion run passed 1,237 tests before the 33 observation tests were added;
the final run below includes those tests. Focused runs are not counted again.

| Check | Final result |
| --- | --- |
| Full API, disposable native PostgreSQL/Redis | 2,430 passed |
| Full ingestion, explicit inert service configuration | 1,270 passed |
| Full scripts | 272 passed; 36 additional subtests |
| Frontend source / unit | 35 / 288 passed |
| Distinct ordinary tests | 4,295 passed, excluding the 36 script subtests |
| TypeScript | `tsc --noEmit` passed |
| Scoped Ruff I/F; diff | Passed |
| API and ingestion lockfile checks | Passed with pinned uv 0.11.16 |
| Real 0061 migration rehearsal | Passed, including actual service calls, full-state no-op/rollback and populated downgrade refusal |

Migration verification first exercises every older independent 0052–0060
populated-history guard, then the 0061 empty round trip and populated receipt
guard. It must not let the newest guard mask an older destructive downgrade.
Native API tests emitted 20 existing-style FastAPI/Alembic deprecation warnings;
ingestion emitted 34 SQLAlchemy dialect-rendering warnings. No test failures
or skipped tests were reported in the final suites. These results do not prove
current-SHA Linux CI, release-image parity, provider availability or corpus
retrieval performance. No test connects using the application `.env` DSNs.

## Rollout and next priority

Keep #69 open. The next local work is immutable index generations, bounded
SQL/vector reconciliation and staged promotion/rollback with exact query
hydration. Positional IDs and independent SQL/vector writes are still an
integrity risk; a response receipt does not make an old active index safe.

Apply 0061 through the explicit migration job before compatible writers.
Do not delete populated receipt history for a downgrade. Prepare the Facts
renderer transition alongside corpus/index generation migration: historical
2.0.0 bindings are retained but are not silently treated as current 2.1.0.
Actual source-use/scientific approvals, current-SHA Linux/image-parity CI,
staging and explicit production authorization remain separate gates.
