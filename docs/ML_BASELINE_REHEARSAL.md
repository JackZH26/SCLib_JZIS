# Deterministic ML baseline engineering rehearsal

Issue: [ML09 / #76](https://github.com/JackZH26/SCLib_JZIS/issues/76).
Versions: `ml-baseline-task/1.0.0`, `ml-baseline-prepared-views/1.0.0`,
`ml-baseline-rehearsal/1.0.0`, `ml-baseline-numerics/1.0.0` and
`ml-baseline-metrics/1.0.0`.

## What is executable, and what is not

The repository now has actual numerical baseline fitting, validation-only
selection, per-example prediction, error/coverage accounting and complete
replay. The public executable entry point runs **one fixed implementation-owned
synthetic fixture**. It is an engineering rehearsal, not a scientific benchmark
or a model fitted on real SCLib observations.

The actual verified-data preparation path consumes the
[identity-audited v4 package](ML_IDENTITY_AUDITS.md) and five independent inputs.
It recomputes the package and prepares explicitly selected views, but does not
fit a prediction model. Native integration tests connect this preparation to
the private numerical seam using genuine disposable SQL capsules whose labels,
review declarations and scientific values are all synthetic.

`run_baseline_dataset(*args, **kwargs)` refuses every supplied dataset with
`ml_use_authorization_unavailable` before parsing or fitting. The fixed
`run_synthetic_rehearsal()` accepts no dataset, configuration, approval or factory
argument. There is no arbitrary file input enabled by `--synthetic` or
`--approved`, no authenticated ML-use grant, and no general real-data runner.
An internal Python numerical function is not an authentication boundary; its
existence must not be represented as authorizing supplied data.
The separate [ML workflow membership registry](ML_USE_GOVERNANCE.md) now allows
explicit role administration and current status checks. These memberships are
not source licenses or execution approvals; the runner's denial is unchanged.
The [exact intake/preflight](ML_USE_PREFLIGHT.md) adds private request drafting
and live registered-dependency inspection, still without an execution grant.

The separate [private preparation CLI](ML_BASELINE_PREPARATION.md) now exposes
configuration drafting, verified view preparation and exact offline replay for
the audited five-input dataset workflow. It does not call model fitting or
change this fixed-fixture runner's authority boundary.

All six scientific/training/release/reviewer/live-rights/external-completeness
authority flags remain false. ML08 still needs its real reviewed pilot, and
ML07's metadata/RPS distribution roles do not grant general ML training rights.
No real training, provider call, active learning, calculation, public prediction
release or production operation is performed by this workflow.

## Explicit configuration and feature arms

The task pins its input package/fixture, candidate methods, finite hyperparameters,
exact arm/view/column inventory and selection/failure policies. Unknown fields,
booleans used as numbers, duplicate identifiers, unsupported methods, invalid
feature scopes and exhausted bounds fail closed. Defaults are engineering
examples, not a scientifically approved search space or preregistered study.

`draft_task_for_package` inspects view names and column inventories only. It
creates a draft to be independently pinned before execution; it does not
choose a model from held-out errors. `prepare_audited_baseline_inputs` requires
both an independent package hash and an independent configuration hash, along
with the five original dataset inputs/pins.

| Feature scope | Required column inventory |
| --- | --- |
| `composition` | Exactly the existing 121 composition descriptor columns |
| `composition_conditions` | Those composition columns plus reported pressure and magnetic field |
| `view_all` | Exactly the selected verified view's columns, including any declared physical/structure fields |

`C@B` can already contain pressure/field when the original label task declares
`feature_budget=composition_conditions`. Its name does not make it a
composition-only baseline. Such default drafts add a separately named
composition-only arm; falsely labeling condition-bearing columns as composition
is refused.

Projection reuses the verified view's independent per-column training medians
and z-score parameters. It remaps selected/dropped column indices and retains
the source parameter hash; it does not refit on validation/test values.
Raw missingness remains indexed by each arm's requested column inventory.
Pressure strata use the exact frozen claim's pressure state/value, not an
imputed or standardized feature or an assumption that unknown means ambient.

Preparation uses detached package/configuration/manifest snapshots and checks
their pins again after projection. Numerical execution checks its prepared
input and configuration for mutation. Verification uses captured input bytes,
rebuilds the result and derives return fields from the rebuilt object, rejecting
receipt mutations during replay.

## Fitting, selection and failure handling

The numerical `fit_select` function accepts training and validation matrices,
targets and families only. It has no test-target argument. The separate
`predict` function accepts features/families and a fitted model, with no targets.
There is no automatic train-plus-validation refit after selection.

| Method | Training behavior | Explicit limitation |
| --- | --- | --- |
| `median_train` | Global training-label median | Does not model composition or conditions |
| `family_median_train` | Per-family training median; unseen/missing family falls back to global training median | No held-out family labels are consulted; each fallback is recorded |
| `ridge` | Linear least squares with positive L2 slope penalty and unpenalized intercept | Fixed float solver and pivot thresholds; no guarantee of adequate scientific model fit |
| `ols` | Unpenalized linear least squares with explicit rank/conditioning checks | Singular/ill-conditioned systems fail; no silent pseudoinverse or ridge substitution |

Ridge minimizes sum of squared training errors plus `alpha` times squared
slopes; its penalty is not implicitly normalized by the number of rows. These
details and the deterministic partial-pivot normal-equation solver are pinned
in the numerical policy. The implementation uses the standard library, not an
unrecorded external model package. Bounded exact-rational means avoid intermediate
overflow and subnormal averaging loss; linear algebra remains ordinary float
arithmetic and does not claim universal numerical conditioning.

Every configured candidate remains in the ledger with method/parameters,
fit outcome, fitted model if available, validation predictions, validation MAE
or an explicit failure. A candidate is selectable only with complete validation
prediction coverage and a finite validation MAE. Lowest validation MAE wins;
exact ties use lexical candidate ID. Test errors cannot choose a candidate.

If no candidate is eligible, the arm has no selected model and every requested
prediction receives a failure record. If no requested feature survives training
preprocessing, the entire arm is no-go with `arm_no_training_features`; it is
not silently relabeled an intercept-only feature model. Missing feature columns
are not filled from test data to make the arm succeed. A required failed arm
makes the overall engineering gate no-go.

Each selected-model prediction retains its index, success/failure reason and
family-fallback status in `prediction_execution`. The accompanying prediction
records bind exact example/group/assignment, split, family, pressure and label.
Finite negative predictions are retained without clipping, but they are not
negative observations or evidence that a material is non-superconducting.
Nonfinite prediction arithmetic remains an explicit failed prediction, not a
dropped denominator or fabricated finite value.

## Metrics and comparisons

The supported target remains exact positive **Observed** Tc in K under one
transition criterion. The metrics helper rejects mixed criteria, nonpoint or
censored targets, computed targets, missing labels and nonpositive truths.
It does not silently log-transform, substitute zeros or mix target definitions.

MAE and median absolute error are calculated only on successful predictions,
alongside the complete requested, predicted and failed counts, coverage and
failed IDs/reasons. Errors are descriptive, with separate split, family,
pressure-stratum and declared-component summaries. Reported/explicit ambient,
reported zero, unknown and ambiguous pressure remain distinct. Ambiguous
numeric pressure is preserved as ambiguous rather than converted to ambient.

Each comparison checks exact shared labels, metadata, group/split and assignment
hashes. It identifies same-row, nested, overlapping or disjoint populations,
retains only-side IDs and common failed predictions, and separately reports the
common-success error difference. Better performance on a smaller/easier
structure subset is not the causal value of adding structure features.
Changes between separately pinned tasks require their own alignment review;
matching formulas or partition names alone do not establish a paired benchmark.

Identity counts from the audited package remain separate from metric component
counts. Neither is a count of independent experiments. Uncertainty and independent
support remain `null`, with explicit reasons; no bootstrap confidence interval,
significance, power claim or real-world continue/narrow/stop recommendation is
manufactured from this rehearsal.

## Fixed fixture and private CLI

`ml09-owned-numerical-fixture/1.0.0` defines twelve invented numeric examples
with fixed train/validation/test membership. Formula descriptors are computed
locally; its Tc, condition and structure-field numbers are test values, not
source-backed measurements or coordinate-derived structures. It exercises
composition, composition-plus-condition and nested structure-subset arms.
The native SQL tests separately establish actual frozen-input/coordinate
admission; the fixed toy alone does not establish that boundary.

```bash
api/.venv/bin/python scripts/ml_baseline_rehearsal.py build \
  --output /private/new-fixed-rehearsal.json

api/.venv/bin/python scripts/ml_baseline_rehearsal.py verify \
  --receipt /private/new-fixed-rehearsal.json \
  --receipt-sha256 INDEPENDENT_WHOLE_FILE_SHA256
```

The receipt contains the fixture hash, pinned task and prepared-input hash,
candidate ledgers, selected models, full predictions/failures, metrics,
comparisons, model-card limitations and implementation/runtime hashes. It does
not contain a successfully approved real research dataset. All output is
private and default error/CLI strings are English.

Verification reruns the **fixed** fixture through fitting, selection, prediction
and scoring and compares the complete receipt. Newly hashing manipulated
coefficients, selections, predictions, coverage or metrics does not make it
valid. The prepared-data verifier is a separate numerical test seam; it does
not authenticate or authorize the caller's source data.

The fixed receipt records exact source-module hashes, the API lockfile, Python
build/implementation, machine/byte order and numerical policy. Exact replay
requires the recorded implementation/runtime. The solver's numerical tolerance
is not a promise of bit-identical artifacts across platforms, and the strict
receipt verifier does not silently accept a different runtime under tolerance.

Output reuses the hardened owner-only, no-clobber writer. Absolute non-symlink
paths, final inode/content checks, single-link files and post-replay rereads are
required. Build writes only on engineering pass; no-go writes no receipt.
Uncertain publication/cleanup remains `output_state_unknown` with
`output_written=null`, requiring inspection before retry. Exit 0 is engineering
pass, 3 no-go, and 2 invalid/error, never scientific approval.

## Bounds and remaining acceptance

Configuration permits at most 12 arms, 16 candidates and 256 columns per arm.
Prepared views retain at most 100 rows each and 120,000 feature/missingness cells
in aggregate. The numerical kernel additionally caps train/validation rows,
matrix cells and estimated operations per complete candidate grid; exceeding a
bound fails before fitting that grid. Reports are capped at 16 MiB, with the
existing strict JSON depth/node bounds also applied. These are engineering
limits, not production throughput or sample-size guarantees.

The implementation report records actual tests separately. Real study execution
still requires an exact authenticated ML-use boundary, complete recursive
source rights/currentness, approved source/label/unit interpretation and a real
reviewed pilot. Public prediction distribution requires its own approval.
ML09 and its dependencies are not closed by synthetic scores or local tests.
