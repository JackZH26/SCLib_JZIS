# Batch55 — exact ML-use intake and online dependency preflight

Date: 2026-09-12. Base HEAD: `00718749b6eb15926ae8cbfc58e02a9432488815`.
Branch: `codex/sclib-research-v2`. Existing uncommitted batch52–54 work is preserved.
Related tracking: ML07 #68, ML06 #70 and ML09 #76. None is closed by this batch.

## Outcome and bounded scope

The verified baseline preparation can now produce an eight-input, purpose-bound
ML-use declaration. An authenticated, read-only API then reconstructs the
registered capsule/source requirements in one current database snapshot.
This is a concrete intake/preflight step, **not** the complete ML-use approval
system. It does not persist a request, issue a source permission, authenticate a
human rights review, authorize a run or open the real-data training entry point.

The [operator/API contract](../../ML_USE_PREFLIGHT.md) includes commands, exact
field definitions, interim admission, source scope, limitations and next steps.
The only v1 purpose is `private_baseline_evaluation`; no general-purpose research
grant, public prediction release or provider execution is inferred.

## Implemented changes

| Component | Delivered behavior |
| --- | --- |
| `api/models/ml_use_request.py` | Closed, bounded intake descriptor: dataset/release, exact eight file pins, explicit purpose and sorted unique feature-binding pins |
| `scripts/ml_use_request.py` | Private offline `prepare`/`verify`; complete original baseline replay, input identity/byte rechecks, no-clobber output and exact request reconstruction |
| `api/services/ml_use_preflight.py` | Current exact ML/curator membership admission, stored capsule/pin integrity, complete registered feature-binding comparison, SQL-derived dependency closure and negative currentness checks |
| `api/routers/ml_use_preflight.py` | Default-off private access/preflight endpoints, session recheck after body receipt, read-only bounded SQL, sanitized errors and bounded resource use |
| `api/main.py` | Registers the separate intake router; existing membership/other endpoints remain unchanged |
| Tests | Offline contract/file adversaries, native authenticated preflight boundaries and actual SQL → offline request → HTTP pipeline |
| Documentation/evidence | Contract, baseline/README/index links, historical-receipt annotations and a fresh Discovery compatibility capture |

The eight file pins cover the manifest, dataset task, feature-source companion,
review companion, label companion, audited dataset, baseline configuration and
baseline preparation receipt. Only IDs/hashes and the explicit purpose appear
in the declaration, not input matrices, targets, source text or private paths.

The online boundary currently requires administrator **and** explicit curator
**and** explicit ML requester. This preserves the existing private audit-export
boundary until proper dataset ACLs exist. It is an interim technical policy,
not a recommendation to give every researcher admin rights. No real roles were
provisioned and the feature flag was not changed.

## Source/scientific correctness

All frozen rows are conservative source-graph roots, including unused rows,
labels, policies and review artifacts. Registered feature bindings supply extra
roots. Foreign-key dependencies and owned child rows come from SQL, including
claim-source occurrences, paper/Work mappings and capture siblings. The client
cannot bypass the registered inventory by supplying a shorter source list.

The response identifies each current row and hash, its frozen hash where one
exists, change status and a purpose-permission requirement. Existing catalogue,
material ancestry, lifecycle and exact-result negative gates are consulted.
These diagnostics neither adjudicate superconductivity nor reinterpret source
quantities, scientific evidence, feature applicability or RPS scores.

The source inventory has an explicit limit: it covers the registered capsule
and feature-binding graph, not all external dependencies or every companion-only
audit artifact. The other seven declared input files are not uploaded or rebuilt
online. `online_private_input_reconstruction_verified` therefore stays false
even after an actual successful local replay. The implementation does not trust
a client assertion that a hash came from the CLI.

Every requirement reports an unavailable purpose-specific permission; the
overall decision is always `not_authorized`. Existing metadata distribution
rights, source access/licence strings, clean catalogue status and scientific
review cannot supply a training licence. All six scientific/release/training/
reviewer/live-rights/external-completeness authority flags remain false.

## Verification

| Check | Observed result |
| --- | --- |
| Complete new offline request tests | 86 passed; 3.71s |
| Initial native preflight module | 34 passed; 28.26s |
| Actual feature-bearing SQL → offline prepare/verify → authenticated HTTP pipeline | 1 passed; 67.16s |
| Full scripts suite | 1,863 passed; 36 subtests passed; 67.98s |
| Final combined native role/preflight/pipeline/Discovery modules | 152 passed; 159.85s; owned cleanup verified |
| New API configured Ruff checks and new scripts F/I checks | Passed |
| English CLI `--help` smoke | Passed |
| Full frontend component suite, two workers | 1,353 passed across 40 files; 93.29s |
| Frontend source checks, including English-default language/locale | 38 passed |
| TypeScript `tsc --noEmit --incremental false` | Passed |
| `git diff --check` and workflow/report links | Passed |

The 86 new cases are included in the full scripts total and must not be added
again. No test counts are claims about real scientific samples or independently
reviewed sources. All native runs use newly created capability-owned PostgreSQL
and Redis with synthetic scientific inputs/accounts; the runner confirmed owned
cleanup after each completed run. The existing FastAPI `regex` deprecation
warning remains, without a new suppression.
The final 152-test run includes 65 existing ML-role cases, all 34 new preflight
cases, the actual new pipeline case and 52 main-barrier cases. Earlier selected
runs overlap it and are not additional unique tests. This is not the full API suite.

File tests cover all eight independent pins, no-go/failed baseline replay,
byte/inode changes, hardlink/symlink rejection, copied-container integrity,
resealed request substitution, duplicate/unsorted/excessive bindings, unknown
purposes/fields and private parser errors. The CLI cannot skip full baseline
reconstruction simply because a preparation receipt declares success.

Native preflight tests cover metadata permissions present/absent, no new ML
authority, current source-row holds, exact dataset/release/manifest/binding pins,
admission before private body parsing, session/account/admin/curator/requester
changes during body receipt, private failures, body bounds and capacity release.
The service requires a bounded read-only snapshot and captures caller data
before async boundaries.

The actual pipeline uses genuine registered feature bindings and a five-example
synthetic audited dataset. Offline child processes deny database/network calls
and predictive fitting. The generated request passes online registration
inspection; removing one feature-binding pin and resealing the request produces
409. Original input files and SQL state remain unchanged by the complete
inspection workflow. The API still reports that private inputs were not rebuilt
online and grants no permission.

The first pipeline attempt tried to create separate test accounts while its
fixture's deliberate read-only capture snapshot was still open. The fixture
now ends that inspection transaction before test-only account setup. No
production read-only check was changed or weakened; the complete pipeline then
passed.

## Compatibility and retained evidence

This batch adds no table or migration. Schema remains `0071_ml_use_roles`;
the frozen capsule, v1–v4 dataset, baseline, feature/review/label companion and
membership ledger implementations are not rewritten. Existing source snippets,
material fields, priority scores and real-data training denial are unchanged.

The batch54 0071 migration receipt remains byte-identical. Its 645-file source
inventory predates this new API/CLI code, so it is historical evidence rather
than a fresh migration rehearsal of batch55. A new migration rehearsal is not
claimed for this additive read-only API increment.

The old Discovery capture is preserved as
`frontend/tests/fixtures/discovery-main-barrier-native.batch54.wire.json`, with
its original full-file hash
`bcdd029d75d726b8450e675b41abe608067b63ee948c595bf21d9ddec40d7fd2`.
The batch52 capture is also unchanged. A fresh current capture replaces the
active compatibility fixture without relabeling those historical source pins.
The final successful native run produced the current 261-source capture:
`frontend/tests/fixtures/discovery-main-barrier-native.wire.json`, 202,172 bytes,
SHA-256 `fceb5673302755deb975dba759f536af70db78d9f3a7c56e7cbb36ebcdc92aa9`.
All source hashes were independently verified against current files; only the
outer archive is pretty-printed, with every raw response string unchanged.

New implementation SHA-256 pins (local worktree identity, not CI provenance):

| File | SHA-256 |
| --- | --- |
| `api/models/ml_use_request.py` | `10d791fe0866d76341bd4c66d7b98ef38e857d3ed392c589e05cd57bbc04b36a` |
| `api/services/ml_use_preflight.py` | `13c7e554b51160c9046e99a71314a964d9f3bed15ebea1efd0be65f961ecb7b5` |
| `api/routers/ml_use_preflight.py` | `d259c23d4be77c83116202f394f5af5aa8d6f6774e7b36610d604a14b727e1a5` |
| `scripts/ml_use_request.py` | `85fc56e5923ebcb0df4cd1ccd7729cf953cca89cbb97f23f7bd99d2eaa87b723` |

## Reproduce

From the repository root:

```bash
api/.venv/bin/python -m pytest scripts/tests -q

api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/bin/redis-server --suite api -- -q \
  tests/test_ml_use_governance.py tests/test_ml_use_preflight.py \
  tests/test_ml_use_request_pipeline.py tests/test_discovery_main_barrier.py
```

Frontend compatibility checks use the actual fresh capture, not a client-side
fabricated payload. No frontend production UI is changed by this increment;
it does not claim a new production bundle or live-browser acceptance.
From `frontend/`, run `pnpm exec vitest run --maxWorkers=2`, `pnpm test:source`
and `pnpm exec tsc --noEmit --incremental false` for those checks. Limiting worker
count does not change assertions or timeout thresholds.

## Next development and authorization boundary

1. Add private artifact intake and exact online reconstruction for all eight
   inputs; do not promote the current hash-only descriptor into an approved grant.
2. Persist the resulting complete request/inventory and introduce purpose-
   specific source decisions with independent authenticated rights review,
   exact evidence, expiry, revocation and currentness checks.
3. Add independent exact run approval and final consumption checks, then connect
   an actually reviewed ML08 pilot and a separately authorized baseline runner.

The current preview/requirements output is not an approval queue or an ML-use
licence. Actual pilot reviews, model fitting, active learning, external calls,
source redistribution, prediction release and deployment remain separate.
This batch performs no commit, push, PR creation, remote issue mutation,
production migration, real account provisioning or paid computation.
