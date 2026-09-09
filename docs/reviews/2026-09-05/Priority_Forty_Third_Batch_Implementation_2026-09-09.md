# Forty-third implementation batch — deterministic ML baseline rehearsal

Date: 2026-09-09. Branch: `codex/sclib-research-v2`.
Baseline: `0b5b4cccdce24c111fd1ad1f3a5c535f3bd67599` (forty-second batch).
Issue: [ML09 / #76](https://github.com/JackZH26/SCLib_JZIS/issues/76).
Operator contract: [ML baseline rehearsal](../../ML_BASELINE_REHEARSAL.md).
Original handoff: [implementation design](ML_Baseline_Rehearsal_Implementation_Design_2026-09-09.md).

## Outcome and scope

Implemented actual deterministic numerical fitting, validation-only model
selection, per-example predictions, explicit failures, descriptive evaluation
and complete computational replay. The public service/CLI executes one fixed
implementation-owned synthetic fixture. It does not execute an arbitrary
caller-supplied dataset and does not claim predictive accuracy on superconductors.

A separate read-only preparation function verifies an actual identity-audited
v4 package against its five independently pinned inputs and projects its
declared feature views. Genuine disposable SQL integration fixtures connect
this preparation to the private numerical seam. Their scientific values and
review declarations are synthetic; they are not real reviewed research data.

General real-data execution rejects before parsing or fitting with
`ml_use_authorization_unavailable`. No `approved` or `synthetic` flag, metadata
publication role or RPS distribution permission activates a real model fit.
All six scientific/training/release/reviewer/live-rights/external-completeness
authority flags remain false. A private Python function is not an authentication
boundary and must not be presented as one.

No historical v1–v4 compiler, capsule, companion, identity-audit or preprocessing
source was modified. No schema migration, public endpoint, frontend, production
operation, live source extraction, real model training, paid provider call,
scientific approval, remote push, PR, deployment or issue closure was performed.

## Delivered implementation

### Explicit task and verified preparation

`api/models/ml_baseline_task.py` defines the closed, versioned task:
input hash, exact arms/views/columns, bounded candidate grid, validation MAE,
lexical tie-breaking, complete validation coverage, retained failures and no
post-selection refit. Unknown fields and unsupported or ambiguous declarations
are rejected. A generated draft is not a scientific preregistration or approval.

`api/services/ml_baseline_rehearsal.py` reuses complete audited-package
verification before preparing data. Package/configuration/manifest inputs are
detached, independently pinned and checked after projection. Source companions
retain their existing verification and limits; this increment does not widen
historical admission contracts.

Composition-only means exactly the existing 121 composition columns.
Composition-plus-conditions adds reported pressure and magnetic field.
`view_all` means the exact verified inventory of the selected view. A `C@B`
name does not disguise condition columns as composition-only information.
Projection retains and remaps the original train-fitted preprocessing parameters
without fitting on held-out values. Raw missingness retains its own column
inventory, including dropped columns.

The frozen claim supplies pressure state/value for evaluation strata. Unknown
pressure does not become zero or ambient; ambiguous pressure stays ambiguous
even when accompanied by a finite numeric value. Exact identity/component
assignments and shared-row bindings survive projection and comparison.

### Numerical baseline kernel

`api/services/ml_baseline_numerics.py` implements global training median,
per-family training median, ridge regression and ordinary least squares.
The family baseline records fallback to the global training median for missing
or unseen families. No held-out family label supplies that fallback.

The bounded standard-library solver uses centered normal equations and
deterministic partial pivoting with recorded thresholds. Ridge penalizes slopes,
not the intercept, under SSE plus `alpha` times squared slopes. OLS retains
singular/ill-conditioned failures instead of silently changing to ridge or a
pseudoinverse. This small engineering solver is not claimed to be a generally
well-conditioned production ML library.

Fitting/selection receives only training and validation rows/targets. Prediction
receives features/families and a fitted model, not targets. Complete validation
prediction coverage and finite MAE are mandatory for selection. Every candidate
remains in the ledger, including failed fits or validation predictions. Test
scores cannot select a model; there is no train-plus-validation refit.

If no candidate is eligible, all requested predictions receive explicit failure
records. If no feature survives train-only preprocessing, the required arm is
no-go, without calling the kernel or manufacturing an intercept-only feature
model. Nonfinite predictions remain failures; finite negative predictions are
not clipped or mislabeled as negative observations.

### Metrics, comparisons and replay

`api/services/ml_baseline_metrics.py` validates exact positive Observed Tc in K
under one transition criterion. Censored, computed, mixed-criterion or missing
targets are not silently converted to this estimand. Bounded exact-rational
means protect descriptive errors from intermediate overflow and subnormal
averaging loss; float linear algebra retains its explicit failure policy.

MAE and median absolute error accompany requested/predicted/failed counts,
coverage, failed IDs/reasons and split/family/pressure/declared-component
summaries. Comparisons validate shared labels and assignments, distinguish
same/nested/overlapping/disjoint cohorts, and retain only-side and common-failed
cases. A common-success error difference is descriptive, not causal feature
value or evidence of significance.

The receipt records exact configuration, input/prepared hashes, candidate
ledgers, models, full prediction execution including family fallback, metrics,
comparisons, missingness, model-card limitations and implementation/runtime pins.
Verification repeats fitting, selection, prediction and scoring, not just hash
calculation. Repinning manipulated models, outcomes or metrics does not validate
them. Mutation during projection, numerical execution or replay is refused.

Independent experimental support and uncertainty remain `null`. Captured
component IDs do not prove replication, and a fixed toy does not justify
bootstrap intervals, sample-size power or a scientific continue/narrow/stop
recommendation.

### Fixed synthetic CLI and filesystem boundary

`scripts/ml_baseline_rehearsal.py` exposes only fixed-fixture `build` and
independently pinned `verify`. There is no dataset/configuration/approval input.
The twelve-example fixture uses locally computed formula descriptors and
explicitly invented Tc, condition and structure-field values. Its invented
structure numbers are not coordinate-derived evidence; actual coordinate
admission is covered separately by native SQL integration.

The existing hardened no-clobber writer provides new private 0600 output,
path/inode/content checks and durability handling. Verification rereads the
receipt after replay. Invalid input is exit 2; no-go is exit 3 and writes no
receipt; exit 0 means an engineering pass only. Publication/cleanup ambiguity
remains `output_state_unknown` with `output_written=null`, not presumed absence
or permission to retry blindly.

## Review findings resolved

1. The first numerical mean could underflow when dividing each subnormal term
   before summation. Bounded exact-rational means now preserve the correctly
   representable mean; regression tests cover both validation MAE and the
   constant OLS intercept.
2. An empty train-selected feature inventory initially needed a clearer
   coordinator outcome. It now produces a complete failed arm and prediction
   ledger without a kernel call or misleading feature-model success.
3. A caller-owned package or manifest could change between verification and
   projection. Detached snapshots and post-projection independent pin checks
   reject changed values; actual SQL-backed tests exercise this boundary.
4. Configuration mutation between arms and receipt mutation during replay could
   mismatch recorded pins and returned results. Execution/replay now rejects
   these changes, and verification derives its outcome from the rebuilt result.
5. Implementation identity omitted modules supplying imported authority and
   canonical behavior. Their source hashes now participate in the fixed
   receipt, alongside numerical/preprocessing/formula code and runtime identity.

An early focused overflow test used finite `1e308` input that still yielded a
finite prediction. The assertion, not the implementation policy, was incorrect.
The fixture was changed to a finite `1.79e308` input whose actual multiplication
overflows, preserving the required explicit failure. No guard was weakened.

## Verification

Final verification used the frozen production and test sources listed above.
Subsequent changes only finalized documentation and the next implementation
handoff; no code was changed after the verified source freeze.

| Check | Result |
| --- | --- |
| Guarded native API, exact ten-module selection below | **547 passed**, 1 existing warning; **386.96 seconds**, exit 0 |
| Complete scripts regression | **1,664 passed plus 36 subtests**, **31.47 seconds**, exit 0 |
| All eleven new Python files, Ruff `I,F` | Passed |
| Git whitespace and unchanged historical source checks | Passed |

The native runner confirmed removal of only its own disposable services and
temporary test data. The single warning is the existing FastAPI `regex`
deprecation in `routers/admin.py`, unrelated to this increment. There are no
failed or skipped cases in the final combined selection.

New coverage consists of 49 numerical, 106 metric, 41 coordinator, 23 snapshot
boundary, 9 native SQL/CLI and 43 script-boundary cases. Focused runs overlap
the final selection and are not additional independent evidence. Script service
doubles test command/filesystem behavior, not scientific data admission.

Native integration preserves actual SQL freeze guards and independently pinned
capsule → v4 → audited-package construction. It exercises real feature and
coordinate admission with synthetic fixtures, condition/composition scope,
held-out-target perturbation, unchanged fitting/selection/predictions, retained
singular/all-failed outcomes, repinned tampering and detached-input mutation.
An actual fixed CLI subprocess builds/replays its receipt, rejects arbitrary
dataset/approval flags and runs with network/database/provider paths denied.
Owned fixture state is checked for unintended changes.

Reproduce from the repository root:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server --suite api -- \
  tests/test_ml_baseline_numerics.py tests/test_ml_baseline_metrics.py \
  tests/test_ml_baseline_rehearsal.py tests/test_ml_baseline_snapshot_boundaries.py \
  tests/test_ml_baseline_rehearsal_sql.py tests/test_ml_identity_audit.py \
  tests/test_ml_audited_dataset_contract.py tests/test_ml_identity_audit_sql.py \
  tests/test_ml_preprocessing.py tests/test_ml_composition.py \
  -q --tb=short --show-capture=no

api/.venv/bin/python -m pytest scripts/tests -q --tb=short --show-capture=no
```

This is the stated API selection, not the entire API suite, Linux release-image
CI, browser verification or production acceptance. No previous test run is
presented as new verification in this batch.

## Remaining acceptance and next priority

A fresh read-only GitHub check on 2026-09-09 found **38 total review issues,
38 OPEN and 0 CLOSED**. Live #76 remains open. Its full acceptance requires a
real audited/reviewed dataset, exact authenticated ML-use rights, actual study
evaluation and delivery evidence. ML08's real reviewed pilot and ML07's source
rights/release boundaries remain dependencies. Synthetic scores cannot close
these gates.

The implementation removes the missing numerical-engine gap. The next bounded
P1 item is [exact RPS rights preparation](RPS_Rights_Preparation_Implementation_Design_2026-09-09.md)
under ML07 / #68: replace direct-SQL preparation of the existing fixed-schema
rights artifact with a reviewer-authenticated preview/atomic-commit/replay
operation for one registered package dependency. This is a concrete operator
gap in the current workflow, not a general ML-use grant. Live #68 was separately
read and remains open; the linked design is not yet implemented.

Remote delivery, production operations and human scientific decisions remain
separate authority boundaries. The overall upgrade goal remains active.
