# Forty-first batch: complete captured label-currentness for ML datasets

Date: 2026-09-09. Base commit: `7005f83c002acc308f705bde0205e540e7965112`.
Primary issue: [ML06 / #70](https://github.com/JackZH26/SCLib_JZIS/issues/70).
Also advances prospective-dataset invalidation in
[SC08 / #66](https://github.com/JackZH26/SCLib_JZIS/issues/66).
Schema head remains `0068_answer_evidence`.

## Outcome and scope

The v3 review companion starts from optional feature inputs. Its feature-only
holds are not a complete current-label audit, especially for composition-only
examples without any optional inputs. This batch adds an independent,
negative-only label companion and opt-in v4 compilation. Every frozen root
example remains in the observation denominator, including previously excluded
examples. Valid current holds exclude labels before the base cohort, splits
and training-only transformations are produced.

The full contract and operator instructions are in
[ML_LABEL_CURRENTNESS.md](../../ML_LABEL_CURRENTNESS.md).
No model is trained; no synthetic result is presented as scientific acceptance.
There is no migration, public endpoint, external provider call, source approval,
production backfill, deployment or change to remote issue state in this batch.

## Implementation

| New component | Responsibility |
| --- | --- |
| `api/services/ml_label_observation.py` | All-root inventory, current SQL-canonical dependency closure, strict scalar/hash/compound-reference checks, source lifecycle replay and controlled negative hold codes. |
| `api/services/ml_label_companion.py` | Closed independently pinned document binding the base, source and review companions to the complete label observation. |
| `api/services/ml_label_capture.py` | Explicit private admin-and-curator admission, exact database release/binding recheck, same-snapshot feature-review recapture and bounded read-only label capture/recheck. |
| `api/models/ml_task_v4.py` | Closed `captured_negative_only/1.0.0` label policy while retaining all v3 scientific task requirements. |
| `api/services/ml_dataset_builder_v4.py` | Label holds before base-cohort construction; full frozen grouping bridges, rebuilt nested cohorts/partitions/train fits and complete offline recomputation. |
| `scripts/ml_current_dataset.py` | Five independently pinned input files, strict no-alias rereads and atomic no-overwrite 0600 output; no-go builds write no dataset. |

The new versions are `ml-label-observation/1.0.0`,
`ml-label-companion/1.0.0`, `ml-task/4.0.0` and
`ml-task-dataset/4.0.0`. Old manifests, source/review formats, v1/v2/v3 compiler
sources and retained artifact bytes are not rewritten. The v4 provenance map
inherits the v3 map and adds the four new pure task/compiler/verifier modules;
the SQL capture service is not represented as an offline dependency.

### Scientific identity and current negative observations

The closure starts from every example in the frozen capsule's root dataset,
not a caller-selected list of successful labels. It includes Claim/QC, exact
event/state/sample/material and ancestry, source occurrences and revision
capture siblings, evidence/decision artifacts, snapshot memberships,
Paper/Work mappings and append-only negative lifecycle observations.
Missing roots/dependencies, malformed inventories and exhausted bounds reject
the whole capture. They cannot yield a partial successful subset.

The implementation preserves exact SQL row text and hashes. Typed timestamps
are compared as instants; numerical comparison does not pass through a lossy
float representation. Explicit global material holds, provenance quarantine
and family-identity changes cannot be cleared by catalogue source scoping.
Unknown/missing evidence does not become a negative superconductivity label.

Supersession targets the exact assessed result and explicit dependency events.
A frozen current event r2 with historical predecessor r1 is not considered
superseded merely because it contains that predecessor reference. A later
appended r3 that supersedes r2 holds the older label. Review history, actors and
audit-only source links are not new causal feature-dependency/grouping edges.

The actual 0054 database guards already refuse modifications to frozen Claim,
QC and event rows. Tests assert the refusal and unchanged SQL state instead
of disabling guards. Permitted post-freeze governance updates and append-only
source/event records exercise actual current changes. Altered offline row-body
canaries are separately identified as verifier defenses, not claims that those
writes are allowed by the real schema.

### Capture versus live authorization

Capture requires a verified active administrator and its exact active curator
grant, plus `ml_label_full_audit/1.0.0`. The caller owns a clean UTC READ ONLY
repeatable-read/serializable transaction with statements bounded to five
seconds. All phases share a twenty-second total budget, sixteen-MiB byte budget
and aggregate 4,000-row accounting; repeated rows across phases are charged
conservatively again. Decoded label SQL bodies also share a 200,000-node budget
with depth limited to 48. These are safety limits, not production capacity or SLA.

The service verifies the actual database base release and complete 0064 binding
inventory, recaptures the independently pinned feature review in the same
snapshot, then observes all labels. Shared observations must match exactly.
Fresh rechecking requires a new caller transaction; an existing stable snapshot
remains historical after another transaction commits a change.

Raw label/review companions stay private. Hashes cannot authenticate database
completeness, human review, rights or a later live state. Scientific acceptance,
training/publication approval, reviewer/database authentication and live-rights
authority remain false. Capturing an empty hold list does not repair missing
frozen label conditions, scientific evidence or a supported Tc review profile.

### Rebuild, do not post-filter

All frozen grouping components are constructed before any label exclusion.
An excluded row can therefore still connect surviving work/state/series/
structure nodes and prevent leakage across splits. Label holds affect B and
every nested P/S/PS cohort; feature-only review holds remain feature-only.
All paired views are regenerated from raw eligible inputs, with imputation
and scaling fitted only on their training partition.

Excluding labels may change deterministic group quotas and surviving splits.
The bundle explicitly reports that cross-artifact assignment stability is not
guaranteed. Only same-cohort, same-partition comparisons within the current
bundle are established. `C@B` remains coverage context, not a cross-population
enhanced-feature comparator.

## Verification

Final source-frozen verification:

| Check | Result |
| --- | --- |
| Guarded native API compatibility, exact 31-module selection below | **1,113 passed**, 1 existing warning; **1,714.06 seconds** (28 min 34 s); exit 0 |
| Complete script regression after the final v4 receipt change | **1,536 passed plus 36 subtests**, **41.35 seconds**; exit 0 |
| Changed Python files, Ruff `I,F` | Passed |
| Git whitespace checks | Passed |

The guarded native runner confirmed removal of only its own disposable services
and temporary test data. Its one warning is the existing FastAPI `regex`
deprecation in `routers/admin.py:83`; no test failed or errored. This is the
specified integrated compatibility selection, not a claim to have run the
entire API suite, the Linux release image or the deployed website.

CLI file-safety unit tests use explicit compiler test doubles and do not
establish scientific admission. Native integration uses actual disposable
SQL/canonical captures, including a real offline CLI build/verify subprocess
with denied network/database access. All production source files stayed frozen
through the final combined run; subsequent changes only complete this report.

The isolated observer contract checkpoint passed **87 tests** in **15.60
seconds**, with the existing FastAPI deprecation warning and owned disposable
service/temp cleanup completed. Checkpoint counts overlap the final combined
selection and must not be added as distinct coverage.

The last two added native regressions also passed together in **26.18 seconds**
with owned cleanup completed: an appended real 0064 binding invalidates the old
inventory, while a feature-only source hold preserves independent base labels,
their assignments and fitted base preprocessing. These cases are included in
the combined selection, not additional distinct coverage.

The test-only extreme-value canary exercises the unchanged train-only view
function on an in-memory copy of actual compiler rows. Its deliberately changed
numbers are not represented as newly validated source evidence or a permitted
overwrite of frozen SQL rows.

Earlier development runs exposed two incorrect test assumptions: the real
freeze guards reject direct scientific-row overwrites, and assignment receipts
legitimately bind the new task version even when the underlying partitions are
unchanged. Fixtures/assertions were corrected without weakening either rule.
The observer also gained explicit material-status/provenance holds, historical-
predecessor-safe supersession, decoded-body cumulative bounds and lifecycle
scalar validation during review.

Reproduce the exact 31-module native selection from the repository root:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server --suite api -- \
  tests/test_ml_foundation_exporter.py tests/test_ml_feature_provenance_v2.py \
  tests/test_ml_dataset_adversarial.py tests/test_ml_coordinate_features.py \
  tests/test_ml_task_dataset_sql.py tests/test_ml_foundation.py \
  tests/test_ml_physical_feature_sql.py tests/test_ml_dataset_v3.py \
  tests/test_ml_review_projection.py tests/test_ml_reviewed_dataset_sql.py \
  tests/test_ml_frozen_provenance.py tests/test_ml_claim_visibility.py \
  tests/test_ml_foundation_schema.py tests/test_ml_feature_companion.py \
  tests/test_ml_review_companion_integrity_sql.py tests/test_ml_preprocessing.py \
  tests/test_ml_review_capture.py tests/test_ml_review_companion_contract.py \
  tests/test_ml_review_source_observation.py tests/test_ml_feature_contract_v2.py \
  tests/test_ml_composition.py tests/test_scientific_adjudication_contract.py \
  tests/test_scientific_adjudication_schema.py tests/test_scientific_result_subject.py \
  tests/test_scientific_result_effects.py tests/test_scientific_adjudication.py \
  tests/test_scientific_adjudication_operators.py tests/test_scientific_result_public_gates.py \
  tests/test_ml_label_companion_contract.py tests/test_ml_label_capture.py \
  tests/test_ml_dataset_v4.py -q --tb=short --show-capture=no

api/.venv/bin/python -m pytest scripts/tests -q --tb=short --show-capture=no
```

All SQL tests use capability-owned disposable PostgreSQL/Redis, never inherited
development or production endpoints. No frontend or migration source changed;
no previous frontend/Linux release-image result is presented as a new run here.

## Remaining gates

A read-only GitHub audit on 2026-09-09 found all **38 review issues, including
the tracker, still OPEN**. Live issues #70 and #66 remain OPEN. Complete dataset
quality/release evidence,
scientifically reviewed real labels, source/rights approval, actual evaluation,
effect-specific fresh authorization, agreed propagation SLA and deployed
acceptance remain separate requirements. No classification target, RPS
ground-truth label or calibrated superconductivity probability is created.

Remote branch/PR/CI delivery, merge and production actions are not implied by
local verification. The overall upgrade goal remains active; this report is
an implementation checkpoint, not closure of all repository issues.

## Next bounded dependency item

The live ML06 acceptance criteria require a machine-verifiable leakage and
dataset-quality artifact, including typed work/state/trajectory identities,
split balance and coverage. Current v4 grouping is enforced during construction,
but its report exposes opaque group IDs and a constant empty crossings list,
not a complete typed membership/count audit. This is a reporting/verification
gap, not evidence of a reproduced split leak.

The next increment should derive deterministic typed component memberships and
actual crossing checks from the complete frozen graph and admitted rows, retain
excluded bridging nodes, and report per-cohort/per-split counts and unknown
relationships. Work/identity/component counts must not be called independently
replicated experiments. New report verification must replay the exact inputs
and reject tampering or incompatible assignments. This remains future work;
the present report does not claim that it is implemented or that such a report
could grant scientific, training or release approval.

The bounded future design is recorded in
[ML_Dataset_Identity_Audit_Implementation_Design_2026-09-09.md](ML_Dataset_Identity_Audit_Implementation_Design_2026-09-09.md).
It proposes a mandatory new audited wrapper around an unchanged v4 base,
rather than modifying frozen v4 sources or copying the entire builder.
