# Thirty-ninth implementation batch: measured index migration

Date: 2026-09-09. Base commit: `3eba8b2`.
Issue advanced: [RG03 / #69](https://github.com/JackZH26/SCLib_JZIS/issues/69).
Related contracts: RG02 original/derived evidence, EN01 disposable test safety,
EN02 explicit migrations, ML04 frozen dependencies and 0068 private answer
receipts. Existing schema head remains `0068_answer_evidence`.

## Outcome

The previously missing local before/after measurement is now implemented and
retained. A standalone, fixed-input runner compares the exact historical
chunker with the current one, then performs real SQL/index lifecycle work on
newly owned disposable PostgreSQL/Redis. Migration and measurement run in
separate fresh processes, without importing API test fixtures.

This batch changes measurement tooling/tests/documentation, not production
services, schema definitions or website behavior. The website's English-default
policy is unchanged. No paid provider, existing index, production database,
source redistribution, remote issue closure, push, PR or deployment was used.

See [the runnable operator contract](../../INDEX_MIGRATION_MEASUREMENTS.md) and
the exact [retained report](measurements/RG03_Index_Migration_2026-09-09-01.json).
This is synthetic engineering acceptance evidence, not scientific validation,
training approval, embedding quality, production recall or an SLA.

## Historical/current chunking: actual denominators

The historical bytes come from commit
`44fd6ce377c89d4b4e1b78dbe082f420c33b8814`, path
`ingestion/ingestion/chunk/chunker.py`. The immutable fixture SHA-256 is
`43ee1e764a32fd39ac3c7f13c99bf94e525a54ab11a46ad4be0ea36336435139`.
Both algorithms run under the current recorded runtime, not a reconstructed
historical environment: CPython 3.12.14, tiktoken 0.13.0, `cl100k_base`.

There are ten common original/abstract stress cases and two current-only Facts
cases. Common input corpus hash:
`5aa2b2eba270b6cf01ff5d76d56f3918dab0acd757570862d5143eba18b67ad4`.
The corpus hash covers all twelve fixed cases; Facts are excluded from the
following historical/current aggregate.

| Ten original/abstract cases | Historical algorithm | Current algorithm |
| --- | ---: | ---: |
| Output chunks | 38 | 47 |
| Chunks exceeding the full 512-token bound | 37 | 0 |
| Maximum full-input token count | 4,479 | 512 |
| Stored-token count mismatches | 4 | 0 |
| Sum of emitted full-input local tokens | 139,170 | 21,340 |
| Explicit metadata-prefix truncations | Not instrumented; legacy counter is 0 | 1 |
| Exact locator coverage | Unknown: no compatible legacy locators | 56,294 / 56,294 characters; 64,574 / 64,574 UTF-8 bytes |

These are deliberately adversarial fixtures, **not** a production defect rate
or a measured 84.7% billing reduction. Long repeated metadata dominates the
historical token total. Current coverage is measured as a union of exact
source intervals, so overlaps are not counted twice. Parsed text is covered;
correct PDF parsing, table semantics and scientific recall are not measured.
The current chunker does more work to enforce complete input/locator bounds;
its retained per-case timings do not establish a speedup. For example, the OCR
case took 12.665 ms historically and 60.081 ms currently in this one run.

The separate Facts fixtures preserve two positive/negative atomic parents,
including a non-detection tested down to 1.5 K rather than a fabricated Tc=0.
The cap fixture has 42 inputs, 42 renderable records, 40 retained records,
2 cap-skipped records and 0 unrenderable records. These exclusions are explicit,
not silently presented as complete coverage. Facts remain derived evidence.

Thirteen deliberately invalid local/provider-contract cases reject 22 input
items: twelve single-item cases and one ten-input response. Each case records
its input unit and rejected denominator. Truncation, missing/unknown statistics,
wrong vector shape, nonfinite/zero vectors and aggregate request overflow are
not silently admitted. Provider response statistics are simulated fixtures;
there were no observed provider attempts or calls. Tokens and actual provider
cost remain unknown, not copied from local token counts or assumed zero.

## Actual two-paper index lifecycle

G1 contains all seven passages from the two measured sources (5 + 2). G2
contains five (3 + 2): two positional passages disappear and the second paper's
first passage changes content/parser revision at the same position. Both
generations are combined declared corpora, not two independent single-paper
generations misrepresented as a complete index.

Paper metadata, raw records and lifecycle/permission state are unchanged; this
is a parsed-representation migration, not a corrected scientific source. No
current-source or lifecycle guard is weakened to permit rollback.

The worker executes these actual checks:

1. Run the real chunker, strict completion-receipt validator and ingestion
   writer; stage complete retained members with actual canonical float32 bytes.
2. Publish, read back, validate and explicitly activate G1. Queries pass the
   actual disposable adapter, SQL member verification and retained hydration.
3. Interrupt the real G2 publish after exactly one point is written. Readback
   sees 1/5; validation is rejected; attempted activation is refused and G1's
   pointer/event remains unchanged.
4. Compute the read-only repair plan: four missing/pending/upsert candidates,
   no delete candidates, no observed generation-scoped orphans, and not ready
   for promotion. Transport and pointer/event/epoch fingerprints stay equal.
   Explicit publication resumes with one already present and four new points.
5. Perform a valid G2 activation inside its service savepoint, then roll back
   the outer transaction. Fresh SQL state and event count remain unchanged.
   Commit the same intended activation, then replay its exact key; event count
   stays two and pointer/event/epoch fingerprints are byte-equivalent.
6. Verify G2's current five chunks contain neither removed ID, while all seven
   G1 members remain retained. Before rollback, readback verifies G1's complete
   old vector manifest; republishing writes zero new points and finds seven
   already present. Explicit rollback appends a distinct third event.
7. Query the original G1 again. All seven exact hit IDs and the retained
   hydration hash equal the first G1 measurement. Old inactive members are
   retention history, not automatically deletable orphans.

The saved 0068 answer selects one actual passage from each measured paper; both
selected and saved-binding inventories require exactly those two papers. The
real 0054 release closure binds the same two sources through claims and source
memberships and retains 23 pins. Answer rows/receipt, release row/manifest,
release-pin rows and verified artifact inventory have identical hashes in all
three phases. No unrelated auxiliary release is used to claim retention.

The first-generation retained vector payload is 21,504 bytes and the second is
15,360 bytes (768 float32 values per member). Local document counts are 202 and
150 tokens respectively. Neither is an embedding-provider bill.

## Raw local timings and interpretation

| Operation | G1 before, ms | G2 after, ms | G1 rollback, ms |
| --- | ---: | ---: | ---: |
| Real ingestion | 299.432 | 205.203 | Not repeated |
| SQL generation staging | 147.013 | 93.430 | Retained generation |
| Publish / validate / activation | 200.591 | 439.558 | 176.519 |
| Query sample 1 | 119.795 | 59.698 | 71.483 |
| Query sample 2 | 77.163 | 54.419 | 66.355 |
| Query sample 3 | 72.538 | 54.015 | 62.239 |

The G2 publish/activation measurement includes outer-rollback and idempotency
probes, unlike G1. Workloads also differ (7 vs 5 members). All queries use
`synthetic_vector_id_order`, not semantic ANN. The three samples per phase
are retained individually; no p95, production latency, throughput or scientific
quality estimate is manufactured. Partial-publication/diagnostic checks took
267.900 ms; creating/verifying the initial history/release took 904.616 ms.

The complete parent run took **18,623 ms**, including setup (2,513 ms), migration
(2,753 ms), measurement worker (11,866 ms), cleanup (648 ms) and source/report
overhead. It migrated an actually empty owned database to 0068. It does not
replace the separately retained populated legacy/schema migration rehearsal.

## Verification and exact artifact

| Verification | Result |
| --- | --- |
| Full scripts suite on frozen source | **1,464 passed + 36 subtests**, 69.15 seconds |
| New contract/parent filesystem and orchestration tests | **168 passed**, 2.18 seconds; included above, mocked orchestration clearly separated from actual measurements |
| New corpus tests | **51 passed**, included in full scripts result |
| New protocol/CLI tests | **45 passed**, included in full scripts result |
| Final integrated 10-module native API regression | **319 passed**, 72.93 seconds; one existing FastAPI `regex` deprecation warning; owned cleanup confirmed |
| Dedicated native worker regression | **8 passed**, 13.65 seconds; included in the integrated result |
| Independent-process actual parent rehearsal | **Passed**, 18.623 seconds; migration and measurement workers, verified cleanup before publication |
| Existing-destination actual CLI retry | **Rejected with exit 2** before service startup; original file preserved |
| Scoped Ruff I/F and whitespace | All new Python files pass; `git diff --check` clean |

No frontend files changed; this batch does not claim a new browser or Linux
release-image run. API work used the capability-guarded disposable runner,
never an inherited or preexisting database. Offline tests import no API conftest.

The exact report is 124,785 bytes, initially retained with mode `0600`:

- Full-file SHA-256, including newline:
  `d44dfd8e7c8d7ed8d5dbc07de45461f0fe161a407dca01a31e9565dd96b4151a`.
- Canonical body SHA-256:
  `cd7cad55c5305077d555012d2ead7199334cb2d0fc99ec266dbc0eb6bb94e375`.
- Conservative source inventory: **676** API/scripts/ingestion Python,
  lock/config and fixed-baseline inputs; inventory SHA-256
  `6bd9f69f555bedd91e42b30c32cace0d58001b819f7837725f042ca80557a856`.
- Actual runtime: native PostgreSQL 16.13, CPython 3.12.14, Darwin arm64.
- UTC interval: `2026-09-09T04:02:50.277232Z` to
  `2026-09-09T04:03:08.900644Z`.

The artifact preserves actual pre-commit HEAD `3eba8b2` and dirty-state flags.
It was copied byte-for-byte, not regenerated or relabelled to claim a later
commit existed during execution. Inventory equality was rechecked against the
final source. All authority flags remain false and all unmeasured production,
provider-cost/token and scientific-quality fields remain null. No raw source,
capability, credentials or release artifact bytes are in the archive.

### Corrections made during verification

Early native fixture work exposed a tuple-return adaptation and incomplete
synthetic source/state/Paper fields. The first broader regression collected the
pre-correction negative-test Paper lacking its required abstract: 318 passed,
one fixture failure. The final fixture supplies both required authors and
abstract; no existing service, schema guard or scientific policy was changed.
The frozen final 319-case run and standalone measurement then passed. Failed
attempts are not counted as successful migration artifacts.

Peer review tightened actual partial-write injection, complete two-paper
generation/retention binding, whole-request rejection accounting, outer rollback
and no-op replay, and pre-rollback verification of existing G1 vectors. It also
identified a potential FIFO wait after the child timeout: new stage/source
readers now use nonblocking regular-file admission. Older frozen report/helper
versions remain unchanged.

## Remaining work and issue boundary

This fills the local retained before/after measurement gap identified in batch
38. RG03 acceptance explicitly allows disposable fixture corpus migration;
uncontrolled full-production re-embedding is not needed for this engineering
exercise. The live issue remains OPEN: remote delivery/linked revisions and
closure are not fabricated by local test success.

Keep source-use review, agreed production canary thresholds/costs, real provider
tokens/billing, actual ANN/corpus quality and operational rollout separate.
Known-ID public readback cannot prove absence of unknown remote vectors or
complete production cleanup. Reviewed scientific evaluation and downstream
ML/RPS acceptance still require their declared data and review gates. The
overall upgrade goal remains active; this artifact grants no new authority.
