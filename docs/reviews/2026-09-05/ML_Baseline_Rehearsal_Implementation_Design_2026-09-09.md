# Proposed next increment: deterministic baseline engineering rehearsal

Date: 2026-09-09. Issue: [ML09 / #76](https://github.com/JackZH26/SCLib_JZIS/issues/76).
Status: implementation handoff only; **not implemented, trained or approved**.
Prerequisite engineering contract: [mandatory identity audits](../../ML_IDENTITY_AUDITS.md).

Subsequent implementation: [forty-third batch](Priority_Forty_Third_Batch_Implementation_2026-09-09.md)
and [operator contract](../../ML_BASELINE_REHEARSAL.md). The original design
status above records the handoff point; the fixed synthetic numerical rehearsal
is now implemented. Real training and scientific approval remain unavailable.

## Why this is the next bounded step

The current repository has exact task-specific dataset construction, train-only
preprocessing, source/label currentness observations and typed leakage auditing.
It has no ML baseline execution/replay engine. The next useful deliverable is
an executable small baseline kernel and an end-to-end **synthetic** rehearsal,
not another schema that promises an evaluation without running one.

Two distinctions remain essential:

1. A technical audited-package pass does not authorize training. Every package
   retains `ml_training_approved=false`; changing that field is tampering.
2. A working baseline implementation is not a scientific benchmark. The ML08
   preparation protocol still records zero selected actual events and zero
   human reviews. It cannot supply an evaluated real training release.

Live #76 was read on this date and remains OPEN. Its dependencies #70, #68 and
#54, actual source rights, scientific review, real evaluation and delivery gates
must remain visible rather than being replaced by synthetic test success.

## Real interfaces to reuse

- `services.ml_audited_dataset.verify_audited_task_dataset`: independently
  pinned full recomputation; do not accept an outer checksum or child pass flag
  as the entire dataset check.
- The embedded v4 `views`: exact row identities, partitions, feature inventory,
  cohort hash, fitted preprocessing and transformed features.
- `services.ml_dataset_builder_v2._view` and `ml_preprocessing.fit_transform`:
  the existing train-only fit contract; do not modify these frozen sources.
- `identity_audit`: direct versus complete-component units, full component
  assignments and missing identity references; not independent replication.

The existing public research contract is metadata-only. The structured
distribution contract admits RPS bundles, not general ML training datasets.
An administrator/curator capture grant is not an ML-use grant. A new real-data
execution boundary therefore requires its own authenticated, exact-use scope
and recursive source/rights/currentness checks before fitting. Client-supplied
`approved=true`, role names or license text must not substitute for that boundary.

## First implementation boundary

Implement a private deterministic numerical kernel and exercise it through a
fixed, clearly synthetic rehearsal. Unit tests may use explicit small matrices;
the native integration test should construct actual disposable frozen capsules,
companions and audited packages from owned synthetic fixtures before invoking
the numerical path. Keep file tests and numerical tests distinct from that
actual capture-to-evaluation integration evidence.

Do not add a general `--dataset` path that runs arbitrary private packages on
the basis of a `--synthetic` or `--approved` declaration. If a rehearsal CLI is
added, it must select only an implementation-owned, bounded fixed fixture and
produce a private engineering receipt. Reject unsupported caller-supplied real
packages before any fit. A real-data runner remains explicitly no-go until the
missing authorization boundary is implemented and separately exercised.

No real SCLib model fit, production read/write, public prediction release, paid
provider call, live calculation or active-learning experiment is part of this
increment. An engineering receipt keeps scientific/release/real-training
authority false and labels every synthetic result as such.

## Preregistered execution rules

Pin the exact evaluation configuration before accessing held-out labels:

- Dataset/package and task pins; selected views and exact feature columns.
- A small finite set of statistical/family and composition/condition/available-
  structure methods; bounded hyperparameter candidates and deterministic seed.
- Train/validation/test use, validation metric, deterministic tie-break rule,
  failed-candidate policy and prediction-coverage denominator.
- Runtime/dependency and implementation identities; documented floating-point
  tolerance where byte equality cannot be promised.

Do not silently tune after seeing the test metrics. Train-only family summaries
need an explicit fallback for families absent from training; an unseen family
cannot borrow its held-out targets. Retain singular, nonfinite, unsupported and
otherwise failed candidates in the ledger, rather than deleting them until
only the winner remains. If none is admissible, return a no-go with no research
prediction artifact.

The numerical module must have a fit/select phase without test targets, followed
by prediction and scoring. A held-out target perturbation should change only
the reported held-out errors, never fitted transformations, coefficients,
family summaries, chosen hyperparameters or predictions. A validation target
may affect selection under the pinned rule, but not training preprocessing.

## Feature arms and fair comparisons

The v4 label task's `feature_budget` determines whether `C` already includes
pressure and field. A view named `C@B` is therefore not sufficient evidence of
a composition-only arm. Record and validate exact columns; do not relabel the
same condition-bearing matrix as two different baselines.

Paired comparisons must use exactly the same example IDs and partition
assignments. The existing C/P/S/PS view comparisons provide that boundary within
one package. Comparisons between separate tasks need an explicit additional
alignment check; their task-bound assignment hashes can differ even when some
partition labels coincide. A better error on the easier structure subset is
not evidence of the causal value of structure information.

Keep all original requested examples in coverage accounting, including failed
predictions. Do not calculate a common-subset metric without also reporting
which cases were removed and why. Preserve the full frozen leakage groups;
post-fit failures do not authorize regrouping or repartitioning the survivors.

## Output, interpretation and replay

The proposed receipt should pin configuration, complete audited input,
implementation/runtime, candidate ledger, selected model, per-example
predictions/failures and metric inputs. Recompute MAE, median absolute error,
coverage and declared family/pressure/component summaries from that inventory.
The independent verifier should repeat the fit/selection/prediction path where
the runtime supports the declared determinism, not merely recalculate a hash.

The presently supported target remains exact positive Observed Tc under one
declared criterion/state scope. Missing, censored, not-detected or computed
results do not become zero, negatives or log-transformed observations through
the evaluator. Any future target/observation model needs a distinct contract.

Per-component errors are descriptive. Captured Work/trajectory IDs do not prove
independent experiments; do not invent confidence intervals, sample-size power
or significance when independent units and sample size are unresolved.
Synthetic scores do not establish predictive accuracy on superconductors.

A later real data/model card must record applicability, failures, selection and
publication bias, uncertainty limitations and a justified continue/narrow/stop
recommendation. Improvement is not a required outcome. This engineering
rehearsal alone cannot provide that scientific recommendation.

## Required adversarial acceptance tests

1. Actual synthetic capsule → v4 → audited package → pinned baseline replay,
   while preserving historical compiler bytes and SQL freeze guards.
2. Held-out target and test-only feature extremes cannot alter fitting or
   selection; validation-only changes follow the predefined selection rule.
3. Same-cohort arms retain exact members/assignments; nested subsets are labeled
   and condition columns cannot masquerade as composition-only features.
4. Missing/censored/negative/computed targets and forbidden dependency chains
   remain outside the supported label boundary.
5. Failed/singular/nonfinite candidates and missing predictions remain in
   bounded ledgers and coverage denominators; no all-failed fallback success.
6. Repinned edits to model coefficients, predictions, failures, selections,
   group counts or metrics fail recomputation.
7. A caller-supplied real package or approval boolean cannot activate a fit;
   no test uses a real training grant or fabricates human review/source rights.

This is a bounded future design, not a newly implemented API or permission to
conduct the real baseline study.
