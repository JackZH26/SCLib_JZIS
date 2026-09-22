# Batch56 — private exact-input reconstruction

Date: 2026-09-12. Base commit: `d42d0dd4ed0ae263fd7b4720982e1ed670bc4598`.
Branch: `codex/sclib-research-v2`. Related ML06 #70 / ML07 #68 / ML09 #76.

Historical note: batch57 subsequently adds the current full-audit endpoint.
The execution/source identity below belongs to batch56; its exact Discovery
capture is retained as `discovery-main-barrier-native.batch56.wire.json` under
`frontend/tests/fixtures/`. The active filename follows the latest separate run.

## Current backlog and delivered increment

A fresh read-only GitHub query found all 37 execution issues and umbrella #41
still open. Their acceptance definitions were not replaced with local test
counts. This increment advances the missing exact-input reconstruction step
identified by batch55; it does not close these issues, publish a dataset or
claim a completed research evaluation.

The operator can now package the actual eight pinned input files and capsule
artifacts. A private authenticated endpoint rebuilds the audited dataset,
train-only preprocessing and preparation content in an owned CPU-bounded child,
then repeats current admission and registered-dependency inspection in a fresh
SQL snapshot. [The complete operator/API contract](../../ML_USE_RECONSTRUCTION.md)
defines the byte format, bounds, provenance interpretation and remaining gates.

| Component | Change |
| --- | --- |
| `api/services/ml_preparation_receipt.py` | Shared unchanged deterministic receipt-content and diagnostics functions, extracted from the CLI |
| `scripts/ml_baseline_preparation.py` | Reuses those functions and includes the shared source file in its implementation pins |
| `api/services/ml_use_reconstruction.py` | Closed canonical upload, eight independent file pins, exact artifact inventory and full data-derived reconstruction |
| `api/services/ml_use_reconstruction_worker.py` | Installed server-owned subprocess, minimal environment, I/O/fit denial, bounded time/output, cancellation and owned-child cleanup |
| `api/routers/ml_use_preflight.py` | Additive private `/reconstruct` endpoint with pre-body, pre-worker and post-worker admission/currentness checks |
| `scripts/ml_use_reconstruction.py` | Complete local request replay and stable-file checks before creating a private no-clobber upload; no HTTP submission |
| Tests | File/envelope adversaries, real worker cleanup, authenticated route boundaries and real SQL → offline CLI → upload → worker → SQL pipeline |

The existing descriptor-only preflight endpoint retains its original limited
scope and response semantics. No tables, migrations, material fields, scientific
quantities, dataset/companion versions, RPS scores or training entry points change.
Schema remains 0071. No new dependency is required; the worker uses the installed
API packages and standard-library Unix resource controls, not repository-local
CLI imports. Source changes are represented by new pins, never relabeling old
migration receipts or preparation artifacts as current.

## Scientific and permission interpretation

Every data-derived preparation field is recomputed, including configuration,
input pins, prepared views, missingness/coverage diagnostics, technical gate and
all-false authority statements. The current dataset compiler's existing exact
implementation verification remains in effect. An inconsistent receipt is not
accepted merely because its outer checksum was recomputed.

The client environment/source record is bounded and retained as **self-reported
provenance**, not cryptographically authenticated execution history. The server
does not echo it as verified truth. Its separately recorded runtime and source
pins identify the actual reconstruction implementation. The original offline
same-runtime receipt replay remains stricter and unchanged in meaning.

A verified input reconstruction is not a complete current source licence
inventory. Review/label companion bytes are rebuilt but their full current SQL
observations are not recaptured in this increment. The endpoint explicitly
reports `companion_observations_rechecked_online: false` and retains that blocker.
The registered capsule/binding scope is not upgraded to external-source
completeness. Source permission, independent run approval and ML08 acceptance
remain unavailable; the overall decision is always `not_authorized`.

## Verification evidence

- Initial native route/preflight/pipeline selection: **53 passed**, 107.98s;
  guarded owned PostgreSQL/Redis cleanup confirmed. This predates the final
  pipeline extension that additionally invokes the actual upload-packaging CLI.
- Complete scripts suite after the final CLI/unit-test changes: **1,933 passed,
  36 subtests passed**, 69.56s. The new 70 reconstruction cases are included,
  not additive to that total.
- Final combined native role/preflight/reconstruction/pipeline/preparation/
  Discovery selection: **173 passed**, 185.00s; owned PostgreSQL/Redis cleanup
  confirmed. This includes 65 role cases, 34 original preflight cases, 18 new
  route cases, one actual extended pipeline, three baseline-preparation cases
  and 52 Discovery cases. It is not the entire API suite.
- New/changed API configured Ruff and scripts F/I checks: passed.
- English CLI help smoke: passed.
- Frontend source checks: **38 passed**. TypeScript `tsc --noEmit --incremental
  false`: passed.
- Full frontend component suite with two workers: **1,353 passed across
  40 files**, 47.57s, including the actual new native capture and all 264 current
  backend source hashes.
- Tracked-change `git diff --check`, linked operator/report documents, archived
  capture hash and equality with all original native response strings: passed.
  This check did not include new untracked files; the later staged whitespace
  warning is documented in the batch57 commit-preflight record.

Initial runs are overlapping checks, not extra
unique tests or scientific samples. No real-source training or human review is
claimed by synthetic fixtures.

The first unit run caught a mutable test-fixture pin dictionary: adding the
preparation pin mutated the receipt used to calculate that same pin. The fixture
now takes an independent dictionary snapshot. The implementation's whole-file
hash check was retained; no assertion, timeout or scientific gate was relaxed.

The final actual pipeline generates the upload with the real CLI while denying
networking, SQL connections and predictive fitting in its offline process. The
HTTP handler launches its actual reconstruction worker (not a compiler mock),
compares the prepared-content hash, then inspects current SQL. Removing one
required capsule artifact is rejected. All original files and SQL state remain
unchanged. Separate unit/route doubles are explicitly labeled; they exercise
adversarial fields and concurrent role changes without being called evidence
of successful scientific compilation.

Worker tests exercise real owned processes on deadline, cancellation during
creation, cancellation after creation and output overflow; child reaping and
the minimal environment are checked. Repeated API timeouts do not exhaust the
shared capacity slots. The existing FastAPI `regex` deprecation warning remains
unsuppressed and unrelated to the new endpoint.

## Current compatibility capture and source identity

The final successful native run generated
`/tmp/sclib-reconstruction-wire-DCbwXU/test_barrier_edit_needs_new_pr0/main-barrier-wire.json`.
Its seven raw response strings are preserved unchanged in
`frontend/tests/fixtures/discovery-main-barrier-native.wire.json`; only the outer
archive is formatted. The current archive has **264 backend source pins**,
202,633 bytes and SHA-256
`9e245e6ab25082a48cb7842b3aa4c2818961cd9e7bfab640473bcb4c56b7addc`.
These scoped backend pins are not a whole-repository inventory or CI attestation.

The previous batch55 capture is preserved byte-for-byte as
`frontend/tests/fixtures/discovery-main-barrier-native.batch55.wire.json`, SHA-256
`fceb5673302755deb975dba759f536af70db78d9f3a7c56e7cbb36ebcdc92aa9`.
Batch52/54 archives and 0070/0071 migration receipts are unchanged. No new schema
rehearsal or Linux release-image execution is claimed by this additive API work.

| Changed implementation | SHA-256 |
| --- | --- |
| `api/services/ml_preparation_receipt.py` | `1644a66809c77ccf1b5ac32870368deeaaafb154e855c18b277ef9d9358d5070` |
| `api/services/ml_use_reconstruction.py` | `99d7c6ea47f22ab005a4de8607cd6a16387917182cc4586d42fb1fc4814cea27` |
| `api/services/ml_use_reconstruction_worker.py` | `8a2d8e46762578446afc2baace6c2268323c7c68b890f0b48f930419582e7d56` |
| `api/routers/ml_use_preflight.py` | `a65b45441acddaf33095485009ddb34c10d043006038f1f24c0c562a99cbc27b` |
| `scripts/ml_baseline_preparation.py` | `4428f6bded2de7a975ec0648b672db06cd72bab3cb26bcbd136bcfd0a209b875` |
| `scripts/ml_use_reconstruction.py` | `9e60dc27955b93d93ea3b71d130ef0824a739e5a5b7c49b8777cb96d995ee580` |

## Reproduce

```bash
api/.venv/bin/python -m pytest scripts/tests -q

api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/bin/redis-server --suite api -- -q \
  tests/test_ml_use_governance.py tests/test_ml_use_preflight.py \
  tests/test_ml_use_reconstruction.py tests/test_ml_use_request_pipeline.py \
  tests/test_ml_baseline_preparation_sql.py tests/test_discovery_main_barrier.py
```

Frontend compatibility uses the actual current native capture, preserving the
old batch55 archive unchanged. No frontend production UI changes or new
production build are claimed for this API increment.

## Next dependent work

1. Recheck the full review/label SQL observations and enumerate companion-only
   audit dependencies, then persist the exact versioned request/inventory with
   recoverable submission and input-retention/access policy.
2. Add purpose-specific source decisions with independent rights-review roles,
   exact reviewed evidence, expiry and revocation. Metadata distribution rights
   must not silently become training rights.
3. Add exact independent run approval and final currentness/consumption checks;
   connect a genuinely reviewed ML08 pilot before authorized baseline evaluation.

Actual PR/CI delivery, Linux final-image parity and remaining real scientific
acceptance are still separate backlog work. This batch performs no commit,
push, remote issue mutation, role provisioning, production migration, source
redistribution, live provider call, model fit or deployment.
