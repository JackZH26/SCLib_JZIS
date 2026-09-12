# Batch53 — executable private ML baseline preparation

Date: 2026-09-12. Base HEAD: `00718749b6eb15926ae8cbfc58e02a9432488815`.
This increment preserves the preceding uncommitted batch52 work.
Tracking: ML06 #70 and ML09 #76; ML07 #68 remains an authority dependency.

## Outcome

The verified baseline preparation service already existed, but the researcher
had to call it from Python. A new private offline command now provides the
complete **draft → prepare → verify** workflow. It consumes the original five
independently pinned inputs, the identity-audited v4 package, and an independently
pinned baseline configuration for preparation/replay.

The [usage and contract document](../../ML_BASELINE_PREPARATION.md) includes exact
commands, file semantics, output fields, gates and limitations. No prediction
model is fitted by this command. Rebuilding the dataset does execute its existing
train-only preprocessing rules; those are not a new predictive training grant.
The current `run_baseline_dataset` denial and fixed-toy rehearsal remain unchanged.

## Delivered changes

- `scripts/ml_baseline_preparation.py`: verified configuration drafting,
  exact view preparation, structural diagnostics, private no-clobber output and
  complete independently pinned replay. No dataset configuration can activate
  training through `--approved`, `--synthetic` or a new permission flag.
- `scripts/tests/test_ml_baseline_preparation.py`: 102 boundary/diagnostic cases,
  including every independent pin, same-byte inode substitution, aliases,
  in-memory mutation, invalid JSON, no-go paths, resealed receipt manipulation,
  unchanged inputs/runtime, exact population relationships and safe errors.
- `api/tests/test_ml_baseline_preparation_sql.py`: three integration cases using
  genuine disposable SQL capsules with **synthetic** labels and declarations.
  Child CLI processes deny network/database access and predictive fitting;
  all original source files and SQL state are checked unchanged.
- README, baseline rehearsal documentation and the review index link the new
  workflow. Website-owned UI remains English and is not modified in this batch.

Diagnostics disclose each arm's exact column inventory, raw per-split missingness,
train-preprocessing drops, row/component counts and cohort overlaps. Shared
groups do not get counted once per row, and nested subsets are not labeled
same-case comparisons. No diagnostic computes prediction scores or reads targets
for model selection. Independent experimental support remains unknown, not an
inferred count of formulas, Works or leakage components.

## Verification

| Check | Final result |
| --- | --- |
| Full scripts suite, including all 102 new cases | 1,773 passed; 36 subtests passed; 88.41s |
| Three selected API modules under capability-owned native PostgreSQL/Redis | 35 passed; 454.76s; one existing FastAPI `regex` deprecation warning |
| Disposable cleanup | Runner confirmed removal of only its owned services and temporary test data |
| New scripts' Ruff F/I checks and new API test's configured Ruff check | Passed |
| English CLI `--help` smoke test | Passed |
| `git diff --check` | Passed |

The 35-test run includes the three new SQL-to-CLI cases and existing numerical
and snapshot regressions. It is not the whole API test suite. The 102 new script
cases are already included in 1,773 and must not be added a second time.

Commands:

```bash
api/.venv/bin/python -m pytest scripts/tests -q

api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/bin/redis-server --suite api -- -q \
  tests/test_ml_baseline_preparation_sql.py \
  tests/test_ml_baseline_rehearsal_sql.py \
  tests/test_ml_baseline_snapshot_boundaries.py
```

The native integration covers composition-only and composition/condition/physics/
structure preparations, old numerical replay compatibility, target perturbations,
target-derived feature exclusion and snapshot-mutation checks. No real observed
SCLib research dataset is trained or scientifically accepted by these tests.

During test expansion, five new population-comparison test cases initially
reused composition rows for a condition-bearing arm, producing mismatched
missingness-vector lengths. The fixture was corrected to preserve each arm's
own column layout. No production check was weakened; all five corrected cases
passed before the final full script regression.

New source-file SHA-256 pins:

| File | SHA-256 |
| --- | --- |
| `scripts/ml_baseline_preparation.py` | `e800cfced5b89934efef2e28ff04db33f9ac1bf33e1f2bf04e84d9c3e0bf96e2` |
| `scripts/tests/test_ml_baseline_preparation.py` | `905a863da49d258cc63c1f94e23da206694ee7ebfd36854204ac0e2bc8f95608` |
| `api/tests/test_ml_baseline_preparation_sql.py` | `93608f113458951de0998e8ab71463800ea35ecb917879a0f8da20df9c51070f` |

These are local source pins, not CI provenance, reviewer signatures or a
production deployment manifest.

## Compatibility and remaining work

There are no changes to API implementations, database tables/migrations, frozen
dataset compilers, baseline task/service versions or frontend code in batch53.
No migration or new frontend production build is required for this CLI-only
increment. The batch52 0070 schema receipt remains unchanged: its whole-tree
source inventory predates the newly added command/tests. It is historical
batch52 evidence, not a rerun against batch53.

All scientific/public-release/training/reviewer/live-rights/external-completeness
authority flags stay false. An offline preparation neither refreshes current
source rights nor proves genuine human review. The remaining research path is:

1. A separately scoped authenticated ML-use boundary, including exact inputs,
   permitted purposes and current recursive source-rights checks.
2. Approved source inventory, fixed selection and actual human reviews for ML08;
   this batch adds no real pilot events or human decisions.
3. A genuinely authorized baseline evaluation against the reviewed dataset,
   followed by its own prediction-release approval if publication is intended.

Remote branch delivery, real Linux CI and any deployment remain separate. This
batch performs no commit, push, PR creation, remote issue mutation, production
operation, paid calculation or source redistribution, and does not close #70/#76.
