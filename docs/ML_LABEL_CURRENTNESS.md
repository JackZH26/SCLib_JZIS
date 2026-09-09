# Private captured label-currentness for ML datasets

This opt-in v4 workflow extends [review-aware feature compilation](ML_REVIEW_COMPANIONS.md)
with observations rooted in **every label of the frozen dataset**. It addresses
ML06 / #70 and the prospective-dataset part of SC08 / #66. It does not overwrite
a frozen capsule, feature companion, review observation, earlier compiled
dataset, or scientific result. No model training or public release is authorized.

## Why a separate label boundary is needed

The v3 review companion starts from optional `ml_example_inputs`. Its holds
affect the physical and structure feature cohorts, but intentionally do not
change the base label cohort. That is not proof that a label without optional
features has been checked against current Claim, QC, event and source records.

In v4, an independently pinned label observation supplies negative-only reasons
to exclude a frozen label before any cohort, split or train-fitted transformation
is produced. It does not replace the old label with a new measurement. A hold
means this captured version is unavailable for the requested technical build;
it is not a conclusion that the material is non-superconducting or its value
has been experimentally falsified.

| Artifact | Version / policy | Role |
| --- | --- | --- |
| Original capsule | `research-release/1.0.0` | Frozen scientific rows and original artifact bytes |
| Original feature source companion | `ml-feature-companion/1.0.0` | Exact historical source bindings for optional features |
| Feature review companion | `ml-feature-review-companion/1.0.0` | Captured negative feature-review and source observations |
| Label observation | `ml-label-observation/1.0.0` | Complete label-root inventory and current scientific/source audit rows |
| Label companion | `ml-label-companion/1.0.0` | Binds label observation to the three independently pinned inputs above |
| Task | `ml-task/4.0.0` | V3 fields plus `label_currentness_policy="captured_negative_only/1.0.0"` |
| Dataset | `ml-task-dataset/4.0.0` | Fully rebuilt cohorts, splits, preprocessing, exclusions and audit |

The task validator still checks all v3 scientific and feature policies. The
first supported label remains an exact positive Observed Tc under its declared
criterion and measurement conditions. Unknown/missing Tc, censored results,
Computed targets and Discovery control membership do not become negative class
labels. This is not a universal all-family superconductivity probability model.

## Complete inventory, not a selected successful subset

The root is the capsule's `dataset_id`. Every frozen `ml_examples` row owned by
that dataset supplies an exact example pin and a claim reference; repeated
claims are deduplicated only in the claim inventory. Previously excluded
examples remain in the denominator. Optional feature availability does not
decide whether a label is observed. Callers cannot select a convenient subset
of labels or pass an arbitrary list of claim IDs.

The current observation retains SQL-canonical row text and its hash, rather than
trusting copied database `record_sha256` values. Its closure includes current
example/claim bindings, ClaimQC, research events, state, sample, structure/run,
material ancestry, exact claim-source occurrences, event evidence and decision
artifacts, snapshot memberships, source revisions/capture siblings, Paper/Work
identity mappings, and negative lifecycle chains. Explicit event supersession
is observed as a reason to hold an older label, never as a substitute value.

All references must resolve with their complete composite identity. Missing
roots, invalid row shapes, malformed closure or an exceeded budget reject the
whole capture; they do not produce a partial successful inventory. Valid changes
to scientific values, units, conditions, methods or exact source associations
are reported as label holds. New occurrences are observed instead of relying
only on the source rows present at freeze time. Operational metadata and
scientific fields are compared according to the versioned projection, not an
unqualified equality of two different JSON serialization protocols.

The existing 0054 database guards still reject updates to frozen scientific
rows. This workflow does not disable those guards to make a test or correction
succeed. Actual later changes use permitted catalogue/source governance or
append-only evidence and event revisions. Tests of hypothetical changed frozen
row bodies in an offline observation are verifier-defense tests, distinct from
tests proving which writes the real database accepts or rejects.

Typed dates are compared as dates/instants and SQL numbers without a lossy
intermediate conversion. The original row text/hash remains unchanged. No
approximate comparison can rescue an unresolved scientific difference.

This audit closure does **not** add causal feature-dependency edges or new
scientific group links. A shared actor, audit request, event-context citation or
review time is not independent support, feature availability or a measurement
date. Conservative audit holds must not be described as proof that every
referenced claim is false.

## Private, same-snapshot capture

The internal entry point is `capture_ml_label_companion` in
`api/services/ml_label_capture.py`. No public HTTP writer or export endpoint is
introduced. The caller must supply an active verified administrator account,
its exact active curator grant and explicit
`export_scope="ml_label_full_audit/1.0.0"`. These are private processing gates,
not scientific or publisher roles.

The caller owns a clean, UTC, **READ ONLY**, repeatable-read or serializable
transaction, with a statement timeout no greater than five seconds. The capture
rechecks the actual base release and complete immutable feature-binding
inventory, reconstructs the feature review observation, and compares it to the
independently pinned review companion in that same database snapshot. It then
captures the label closure. Shared row/lifecycle observations must agree;
hashing two contradictory snapshots separately does not make a valid package.
The label admission retains the same actor/grant as the bound feature review
observation, with its own explicit export-scope version.

The capture has a twenty-second total budget, shared sixteen-MiB observation
byte budget and aggregate 4,000-row accounting. Existing per-subject/parser
limits also apply; complete package verification is bounded by depth and node
limits. Exceeding any bound fails closed rather than truncating sources. These
are engineering limits, not measured capacity or a promised production SLA.
Completed capture phases share one ledger; repeated rows in distinct phases
are conservatively charged again. The label verifier also counts decoded SQL
body nodes cumulatively, not just the outer strings containing those bodies.

`recheck_ml_label_companion` repeats the capture and compares the independently
pinned observation. A caller seeking newer committed changes must open a new
stable transaction. Rechecking inside an existing repeatable-read transaction
does not make that snapshot fresh. A future training/export operator still
needs a separately authorized, effect-specific currentness/rights boundary.

Private observations may contain raw scientific records, source text, locators,
review notes and identifiers. They must not be served on Discovery or placed in
a public artifact directory. Offline checks cannot authenticate a live database
or a human reviewer. Every scientific, training, publication, reviewer/database
authentication and live-rights authority flag remains false.

## Rebuild before fitting

V4 preserves the complete frozen grouping graph before exclusion. Subsequently
held examples and noncandidate nodes still bridge work/version/sample/material/
series/structure components. Removing a label is not permission to sever a
leakage connection and place the remaining members across prohibited splits.

Label holds apply before constructing `B`, the base label cohort. All nested
physical (`P`), structure (`S`) and joint (`PS`) cohorts are then rebuilt.
Feature-only holds remain feature-only. Every view is reconstructed from its
admitted raw inputs, and imputation/scaling are fitted on that view's training
partition alone. Post-filtering an already fitted v3 bundle is not this workflow.

When label exclusion removes a component, deterministic group quotas and
partitions can change. V4 reports the resulting assignments; it does not claim
that an old v3 score and a new v4 score remain a paired comparison. Fair feature
comparisons still require the same cohort and partition within a build.
`C@B` remains coverage context, not an enhanced-feature comparator on a different
population. Test-only extremes must not affect train-fitted parameters.

## Independent pins and offline use

The CLI is `scripts/ml_current_dataset.py`. It requires independently identified
canonical whole-file SHA-256 pins for the capsule, feature source companion,
feature review companion, label companion and task. The label companion's
internal body hash and observation hash are different from its whole-file pin;
none can replace another. Verification additionally requires the compiled
bundle's independent pin and repeats the **complete** computation.

```bash
api/.venv/bin/python scripts/ml_current_dataset.py build \
  --manifest /private/capsule/manifest.json --manifest-sha256 CAPSULE_FILE_SHA \
  --companion /private/source.json --companion-sha256 SOURCE_FILE_SHA \
  --review-companion /private/review.json --review-companion-sha256 REVIEW_FILE_SHA \
  --label-companion /private/labels.json --label-companion-sha256 LABEL_FILE_SHA \
  --task /private/task-v4.json --task-sha256 TASK_FILE_SHA \
  --output /private/new-dataset-v4.json
```

Use the same inputs with `verify`, `--bundle` and `--bundle-sha256` instead of
`--output`. Paths must have existing absolute, non-symlink parents. The CLI
rejects duplicate/nonfinite/noncanonical JSON, aliases, nonregular files,
oversized observations, changed bytes or inode identities, capsule-directory
output and overwrite attempts. A successful technical build writes a new 0600
file atomically; a no-go build writes no dataset. Exit codes are 0 for technical
pass, 3 for no-go and 2 for invalid input/error, not levels of scientific approval.
No database, provider, network, training or publication operation is performed.

## Acceptance and delivery status

The batch implementation report records actual test results separately from
this contract. Required coverage includes zero-optional-input labels, native
refusal of frozen Claim/QC/event overwrites, permitted post-freeze governance and
source changes, append-only evidence/revisions, complete source inventories,
same-snapshot consistency, fresh-transaction rechecks, retained grouping bridges,
held-training-label refits, test-only feature extremes, immutable old replay and
whole-bundle tamper rejection. File/CLI test doubles establish only file safety,
not scientific or dataset admission; real SQL/canonical fixtures are required
for the latter engineering behavior.

This increment alone does not close ML06 or SC08. Real adjudicated labels,
source rights, release approval, evaluation data, deployment and propagation
SLA remain separate requirements. Historical artifacts stay reproducible even
after a later hold; new positive reviews do not repair the evidence of an old
frozen label or supply a missing Tc review profile.
