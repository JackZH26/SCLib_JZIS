# Batch57 — full current audit and dependency inventory

Date: 2026-09-12. Base HEAD `d42d0dd4ed0ae263fd7b4720982e1ed670bc4598`, branch
`codex/sclib-research-v2`; development retained the complete batch56 changes.
Local commit preflight finalized on 2026-09-13 at the user's request.
Historical note: batch58 preserves the exact capture below as
`discovery-main-barrier-native.batch57.wire.json`; the active fixture filename
follows the latest separately verified run, not a relabeling of this evidence.
Related dependencies: ML06 #70, ML07 #68, ML09 #76. Fresh read-only GitHub status
still lists 38 open issues including the umbrella; no issue was closed or
acceptance requirement replaced with a local implementation count.

## Delivered outcome

The exact-input reconstruction path now has a separate full-currentness
operation: `POST /v1/ml/use/preflight/reconstruct/current`. It takes the same
private upload, performs actual server-side reconstruction, then compares the
complete review and label observations in one new bounded SQL snapshot. It
also produces a versioned dependency inventory including audit-only records
and members of historical/current scientific subjects.

See [the operator and response contract](../../ML_USE_CURRENTNESS.md) for
complete semantics and limits. The original descriptor-only preflight and
reconstruction-only endpoints keep their original versions/response scopes.
No dataset, companion, baseline, material/RPS or database schema version changes.

| Implementation | Delivered behavior |
| --- | --- |
| `api/services/ml_use_currentness.py` | Reuses the existing full label/review recapture, exact observation comparison and source/role negative gates; projects qualified, sorted dependency representations |
| `api/routers/ml_use_preflight.py` | Shared admitted worker stage; new private current endpoint; fresh session/account/exact-grant checks; explicit closed upload fields in OpenAPI |
| `api/tests/test_ml_use_currentness.py` | Native full-audit inventories, newer decisions, revoked/inactive review/capture identities, source/material changes, replay drift, bounds and snapshot semantics |
| Existing reconstruction/pipeline tests | Both routes share admission/body/timeout regressions; actual CLI upload and server worker feed the complete currentness check |

The authenticated current requester can differ from the declared historical
capturer. Both current requester admission and the capture identity's existing
full-audit eligibility are checked separately. The service compares SQL content
read-only; it never authenticates an old capture session or submits a decision
as the declared person. `historical_capture_session_authenticated` remains false.

## Scientific interpretation and failure boundaries

- Recapture includes current decision heads, entire request siblings, scientific
  subjects, reviewers and their grants/revocations, every frozen label root,
  source/lifecycle records and newly discovered owned source rows. Omitting a
  newer record by keeping an old checksum cannot pass the observation comparison.
- Frozen row projections, current audit SQL text, lifecycle snapshots and subject
  membership references retain separate encodings and temporal scopes. No decimal
  or timestamp normalization invents equivalence between checksum formats.
- Subject-member pins bind a full subject-container hash plus `(table, row_id)`;
  they are explicitly not standalone row-content hashes. Raw subject/row/source
  text, reviewer rationale and credentials are absent from the response.
- Artifact byte sizes are reported only for actually uploaded verified bytes;
  referenced-but-not-uploaded digests retain a null size. No access or licence
  follows from knowing a digest.
- Counts measure inventory rows/representations, not independent experiments.
  External dependency completeness and all scientific/publication/ML/source-use
  authority remain false. The final decision is still `not_authorized`.
- A completed inspection describes one MVCC snapshot, not a durable lease.
  Later committed holds require a new inspection and eventual run-time checks.
  This increment neither persists an approval request nor implements permissions.

The new phase has 30 seconds, retaining the existing 20-second cumulative
full-label capture, five-second statement and read-only UTC RR/SERIALIZABLE
checks. Its HTTP handler has a 90-second ceiling including the unchanged bounded
worker/body stages. The inventory has 4,000-row / 16,000-representation bounds,
and a 1 MiB final response ceiling. No partial success is returned on failure.
These guards are not measured production capacity or an OS sandbox claim.

## Verification

- Initial actual worker/pipeline and both reconstruction-route boundaries:
  **37 passed**, 69.75s; owned disposable PostgreSQL/Redis cleanup confirmed.
- Initial new full-audit module: **16 passed**, 149.89s; owned cleanup confirmed.
  This predates the additional snapshot/unavailability/schema cases in the final
  combined run, and must not be treated as that later whole-module result.
- Complete scripts suite: **1,933 passed and 36 subtests passed**, 48.22s.
  This is source-only/offline regression evidence, not reviewed scientific data.
- New/changed API configured Ruff checks: passed.
- Broader native role/preflight/currentness/pipeline/preparation/Discovery run:
  **210 passed**, 617.09s; owned cleanup confirmed. This run predates the final
  addition of native-import membership references and named OpenAPI input keys.
  It is retained as that broader checkpoint, not relabeled as the final source.
- Frontend source checks: **38 passed**; TypeScript check passed.
- Final native currentness/reconstruction/pipeline/Discovery selection:
  **109 passed**, 441.25s; owned disposable PostgreSQL/Redis cleanup confirmed.
  This includes 20 currentness, 36 route, one actual pipeline and 52 Discovery
  cases, on the final native-import membership and OpenAPI implementation below.
- Full frontend component suite after refreshing the exact native capture:
  **1,353 passed across 40 files**, 82.24s, with two workers. All 265 current
  backend source pins and historical archive hashes passed the compatibility
  assertions. Frontend source checks (**38 passed**) and TypeScript were also
  rerun successfully during the 2026-09-13 commit preflight.
- Final configured API Ruff and script F/I checks, linked
  operator/report documents, and equality of all seven native response strings:
  passed. No backend source changed after the final native run.
- The earlier unstaged `git diff --check` covered tracked changes only. The
  final staged check also includes newly added files and reports one existing
  blank line at EOF in `api/services/ml_preparation_receipt.py:79`. This cosmetic
  warning is retained in the requested checkpoint to preserve the tested source
  bytes and their native capture pins; it is not reported as a clean staged
  whitespace check or a runtime/test failure.

Earlier selections overlap the final run and are not extra unique
test counts. The existing FastAPI `regex` deprecation warning is not suppressed.

During the completeness review, native-import package, outcome and source-file
references were found beside (rather than inside) a scientific subject's row
snapshots. They were added as container-bound memberships before final acceptance.
An additional test obtains a real native scientific subject from SQL and checks
those exact identities and byte references, without claiming its partial test
projection is a complete ML input or that referenced files were uploaded.

The direct currentness tests deliberately supply a labeled worker-result double
so they can focus on actual SQL audit behavior with independently created
scientific decisions. They are not claimed as complete dataset compilation.
The separate actual request pipeline executes the original offline CLIs, exact
upload-packaging command, genuine server-owned reconstruction subprocess and
fresh SQL inspection without replacing the compiler. Both levels are needed;
a mocked worker test alone does not prove complete scientific reconstruction.

## Current compatibility capture and source identity

The final 109-case native run generated
`/tmp/sclib-current-final-wire-JqcQoZ/test_barrier_edit_needs_new_pr0/main-barrier-wire.json`.
Its seven raw response strings are preserved unchanged in
`frontend/tests/fixtures/discovery-main-barrier-native.wire.json`; only the outer
archive is formatted. The current archive has **265 backend source pins**,
202,781 bytes and SHA-256
`b5b131b248e7c5e1f17ae1731db2a466972e0b8b5103cfb40ec0e3e99a5cca40`.
All source pins were checked against the final backend files. These are scoped
compatibility pins, not a whole-repository inventory or CI attestation.

Batch56's exact previous capture is preserved as
`frontend/tests/fixtures/discovery-main-barrier-native.batch56.wire.json`, SHA-256
`9e245e6ab25082a48cb7842b3aa4c2818961cd9e7bfab640473bcb4c56b7addc`.
The batch52/54/55 historical archive hashes also remain unchanged. The earlier
210-case checkpoint is not substituted for this final capture.

| Final backend source | SHA-256 |
| --- | --- |
| `api/services/ml_use_currentness.py` | `cb80736a36bff551fd036e973b2c7026a444489c25f43839fe544167f45a4737` |
| `api/routers/ml_use_preflight.py` | `9b9c66c59b5b1e8a7afcf1861083833651486b072638ff75e30fd88af84f9b03` |
| `api/tests/test_ml_use_currentness.py` | `25636c684ceb4b266a494bfe88bbadfaa1ce2166f6ef02b1168442f3eafe9252` |
| `api/tests/test_ml_use_reconstruction.py` | `a55e215738e01f7a345d3836b86a3fb6baa7b28d4f44684c63f7f32551071649` |
| `api/tests/test_ml_use_request_pipeline.py` | `68b16ba3617bae344789a6912ce608ccdb8bb78df5d3bd7162925fc53bb3eab5` |

## Reproduce

```bash
api/.venv/bin/python -m pytest scripts/tests -q

api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/bin/redis-server --suite api -- -q \
  tests/test_ml_use_governance.py tests/test_ml_use_preflight.py \
  tests/test_ml_use_reconstruction.py tests/test_ml_use_currentness.py \
  tests/test_ml_use_request_pipeline.py tests/test_ml_baseline_preparation_sql.py \
  tests/test_discovery_main_barrier.py
```

The final source-specific selection after the broader checkpoint was:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/bin/redis-server --suite api -- -q \
  tests/test_ml_use_currentness.py tests/test_ml_use_reconstruction.py \
  tests/test_ml_use_request_pipeline.py tests/test_discovery_main_barrier.py
```

No new migration rehearsal, release-image parity or production UI/build result
is claimed. Schema remains 0071 and its retained native receipt is historical.

## Next dependent work and authority boundary

Persist the exact request and inventory with private input-retention/access
policy, recoverable submission and explicitly timestamped observation semantics.
Then implement independent purpose-specific source decisions, expiry/revocation,
exact run approval and final consumption checks. A complete current inventory
does not remove the need for actual ML08 review or source-use permission.

No push, PR, remote issue mutation, real account provisioning, production
migration/backfill, data redistribution, real model fit, external calculation or
deployment occurs in this batch. All test SQL and artifacts are synthetic and
live only in the guarded runner's owned disposable services or retained fixtures.
