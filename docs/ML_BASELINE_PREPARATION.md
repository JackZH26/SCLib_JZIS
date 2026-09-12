# Private baseline preparation from an audited dataset

Tracking: [ML06 #70](https://github.com/JackZH26/SCLib_JZIS/issues/70),
[ML09 #76](https://github.com/JackZH26/SCLib_JZIS/issues/76).
Contract: `ml-baseline-preparation/1.0.0`.

## Delivered workflow

`scripts/ml_baseline_preparation.py` connects the existing identity-audited v4
dataset to the existing baseline view-preparation service. Researchers can now
generate a configuration draft, inspect a reproducible preparation, and verify
it later without writing ad hoc Python. **It cannot fit a prediction model.**

This is a private offline workflow, not a new website endpoint, source-access
grant, human review, scientific release or authorization to use real data in ML.
Only use inputs whose local access and processing are already authorized. The
tool cannot decide whether those permissions exist. The real-data runner still
refuses with `ml_use_authorization_unavailable`; the separately executable
[numerical rehearsal](ML_BASELINE_REHEARSAL.md) still uses only its fixed toy.
The new [ML workflow membership registry](ML_USE_GOVERNANCE.md) supplies explicit
role administration, not a data-use grant. It does not change these offline
permissions or enable the real-data runner.
The [ML-use request CLI and online preflight](ML_USE_PREFLIGHT.md) can now
replay this preparation and derive registered source-review requirements for
one explicit private-baseline purpose. A successful preflight is not approval.

The workflow preserves all existing v1–v4 dataset, audited-package and baseline
configuration contracts. It does not alter stored material fields, scientific
claims, review decisions, frozen views, feature selectors or train-only
preprocessing rules. Preparing a v4 dataset **rebuilds** those rules from the
original inputs, including training-fold preprocessing. That is distinct from
fitting a predictive baseline, which is not called.

## Inputs and modes

Every mode requires the same six independently pinned inputs:

1. The closed research capsule: canonical `manifest.json` and every declared
   retained `.bin` artifact in its original directory.
2. Source/feature companion.
3. Exact-result review companion.
4. Label-currentness companion.
5. Dataset task v4, including its frozen split and feature policies.
6. The complete [identity-audited dataset](ML_IDENTITY_AUDITS.md), not just its
   embedded base dataset or a self-reported audit status.

`prepare` and `verify` also need a separately pinned baseline configuration.
`verify` additionally needs the independently retained whole-file receipt hash.
File pins are SHA-256 of canonical **whole-file bytes**, not an embedded body
hash. A hash is an integrity anchor, not a signature or source-use license.

| Mode | Result | What it does not do |
| --- | --- | --- |
| `draft` | Verifies the whole audited package against all original inputs, then writes a baseline configuration draft | Does not approve the default model grid, choose models using held-out scores, or authorize execution |
| `prepare` | Re-verifies the package, validates the pinned configuration, projects the declared views, and saves a private preparation receipt if the structural gate passes | Does not fit, predict, score, issue a training grant or publish anything |
| `verify` | Rebuilds the complete preparation and compares it with the independently pinned receipt | Does not trust a resealed receipt, renew rights/currentness or perform a numerical model replay |

For `draft`, optional repeated `--view` arguments must be explicit, sorted and
unique; omission uses the existing view inventory. A configuration edited after
drafting needs a new independent hash. For example, inspect the scientific target,
Tc criterion, feature scopes and proposed candidate grid before pinning it.
The default grid is an engineering example, not a preregistered study design.
`prepare` and `verify` do not accept `--view`: the pinned configuration is the
single authority for the exact requested arms and columns.

## Commands

All paths below are illustrative private paths. The tool does not create input
directories or obtain permissions. Run using the repository's locked API Python.
The same six input arguments must be repeated for every operation:

```bash
api/.venv/bin/python scripts/ml_baseline_preparation.py draft \
  --manifest /private/study/capsule/manifest.json --manifest-sha256 MANIFEST_FILE_SHA \
  --companion /private/study/source.json --companion-sha256 SOURCE_FILE_SHA \
  --review-companion /private/study/reviews.json --review-companion-sha256 REVIEW_FILE_SHA \
  --label-companion /private/study/labels.json --label-companion-sha256 LABEL_FILE_SHA \
  --task /private/study/task-v4.json --task-sha256 TASK_FILE_SHA \
  --package /private/study/audited.json --package-sha256 AUDITED_FILE_SHA \
  --view 'C@B' --output /private/study/baseline-config.json

api/.venv/bin/python scripts/ml_baseline_preparation.py prepare \
  --manifest /private/study/capsule/manifest.json --manifest-sha256 MANIFEST_FILE_SHA \
  --companion /private/study/source.json --companion-sha256 SOURCE_FILE_SHA \
  --review-companion /private/study/reviews.json --review-companion-sha256 REVIEW_FILE_SHA \
  --label-companion /private/study/labels.json --label-companion-sha256 LABEL_FILE_SHA \
  --task /private/study/task-v4.json --task-sha256 TASK_FILE_SHA \
  --package /private/study/audited.json --package-sha256 AUDITED_FILE_SHA \
  --config /private/study/baseline-config.json --config-sha256 CONFIG_FILE_SHA \
  --output /private/study/baseline-preparation.json

api/.venv/bin/python scripts/ml_baseline_preparation.py verify \
  --manifest /private/study/capsule/manifest.json --manifest-sha256 MANIFEST_FILE_SHA \
  --companion /private/study/source.json --companion-sha256 SOURCE_FILE_SHA \
  --review-companion /private/study/reviews.json --review-companion-sha256 REVIEW_FILE_SHA \
  --label-companion /private/study/labels.json --label-companion-sha256 LABEL_FILE_SHA \
  --task /private/study/task-v4.json --task-sha256 TASK_FILE_SHA \
  --package /private/study/audited.json --package-sha256 AUDITED_FILE_SHA \
  --config /private/study/baseline-config.json --config-sha256 CONFIG_FILE_SHA \
  --receipt /private/study/baseline-preparation.json --receipt-sha256 PREPARATION_FILE_SHA
```

Printed hashes are useful for recording a new artifact, but must subsequently be
retained through the approved independent process. Copying a hash from a mutable
receipt is not independent verification. A configuration generated from a
technically no-go package is not written.

## What to inspect in the receipt

The receipt contains the exact configuration, seven input pins, full prepared
views and their hash, structural diagnostics, implementation/runtime pins, and
false authority flags. Prepared views contain private labels, features and
identities. They are **not** a public Discovery DTO. The receipt does not copy
original `.bin` source artifacts. Even its aggregate stdout summary should be
treated as private until sharing permissions are reviewed.

For each requested arm, diagnostics report:

- Actual train/validation/test row counts and captured leakage-component counts.
  Components are not demonstrated independent works or experiments.
- The exact requested feature scope and columns, retained columns, dropped
  features and the original train-fitted preprocessing parameter hash.
- Raw missing/present counts by feature and split, with explicit denominators.
  An imputed value does not convert a missing source value to a reported one.
  Presence is not a claim that a field is scientifically valid or licensed.
- Cohort hash and pairwise identical/nested/overlapping/disjoint row populations,
  including common and only-side counts. Cohorts must not be added together.
  Easier structure subsets are not evidence of the causal value of structure.

No held-out target values are used to calculate these diagnostics. There are no
predictions, metrics, selected hyperparameters, confidence intervals or inferred
independence counts; `independent_support_count` remains `null`. Configuration
choices made by a human after inspecting outcomes still require an appropriate
study protocol; this software cannot prove blinding or preregistration.

An arm with no retained training features or an empty train, validation or test
partition produces a structural `no_go`, with exact arm/reason codes and no
preparation file. Nonempty partitions only establish the minimal structure for
this workflow. They do not guarantee numerical solvability, statistical power,
generalization, sufficient independent support, or a useful model.

## Integrity, limits and authority boundaries

Every input is reread after preparation, checking bytes and file identity. The
receipt is reread last during verification. Mutated in-memory inputs, changes
to the capsule's closed inventory, substituted files, aliases and different
implementation hashes fail closed. Exact reconstruction detects altered
features, coverage, authority flags or omitted blockers even when all affected
receipt hashes are recomputed.

The output writer reuses the audited-dataset owner's 0600/no-clobber checks,
single-link verification, file/directory syncing and uncertain-outcome handling.
Outputs cannot be written inside the closed capsule directory. Absolute paths,
existing non-symlink parents and canonical bounded JSON are required. The
existing audited-package and prepared-view limits apply: up to 12 arms,
256 columns per arm, 100 rows per view and 120,000 feature/missingness cells;
the outer file is bounded by the audited-package reader/writer's 32 MiB and
400,000-node limits. These are engineering bounds, not production throughput
or recommended scientific sample sizes. Inputs and files may still change
after the tool finishes; an offline observation is not a perpetual guarantee.

Exit 0 means the requested **preparation** operation passed. Exit 3 means a
structural no-go without output. Exit 2 means invalid input/replay or an error;
a verified-data preparation refused by its underlying compiler is an error,
not a newly approved partial dataset. Static errors do not echo private values.
`output_state_unknown` uses `output_written=null`: independently inspect that
exact target before retrying. It must not be interpreted as a guaranteed rollback.

The implementation records its file-access/orchestration and preparation code,
API lockfile, Python version and platform. The audited input already pins its
dataset and identity compilers. Exact replay requires that recorded code/runtime;
old receipts are not silently relabeled as executed by newer code.

`training_execution` is always `disabled`. Its blockers explicitly state that
an authenticated ML-use grant is unavailable, live recursive rights were not
checked, and real reviewed-pilot acceptance was not checked. This does not infer
that an external permission or review does not exist; it means this workflow
has not authenticated it. All six scientific/release/training/reviewer/live-rights/
external-completeness authority flags remain false. Publication of predictions
would also need its own approval, separate from any future training grant.

No network/provider/database operation, real training, automatic human signoff,
website publication, issue closure or production deployment is performed here.
The [ML08 pilot](pilot/ML08_Pilot_Protocol.md), authenticated ML-use boundary and
real baseline evaluation remain unfinished acceptance work.
