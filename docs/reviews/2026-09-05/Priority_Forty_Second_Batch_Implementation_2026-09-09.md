# Forty-second implementation batch — mandatory typed ML identity audits

Date: 2026-09-09. Branch: `codex/sclib-research-v2`.
Baseline: `99001f5420a3e31985738ad5c4bae81c02da7255` (forty-first batch).
Issue: [ML06 / #70](https://github.com/JackZH26/SCLib_JZIS/issues/70).
Operator contract: [ML identity audits](../../ML_IDENTITY_AUDITS.md).

## Outcome and scope

Added a mandatory audited wrapper around the unchanged v4 dataset builder.
It reports complete typed identities, controlled grouping witnesses, distinct
counting units and actually computed partition violations. The existing v4
grouping was enforced but exposed opaque component IDs and a literal empty
crossing list. This increment addresses that reporting/verification gap; it is
not evidence that an old dataset leaked or that production prevalence was
measured.

The new package is `ml-identity-audited-dataset/1.0.0`, embedding the full
unchanged `ml-task-dataset/4.0.0` base and a mandatory
`ml-identity-audit/1.0.0` report under policy `captured-typed-identity/1.0.0`.
Only a passing base **and** audit gate permits the new CLI to write a dataset.
Verification recomputes both layers and compares the complete package bytes.

No database schema, public endpoint, frontend, stored scientific result or
historical v1–v4 source file is changed. No live SCLib source was extracted,
real training performed, source right granted, reviewer impersonated, production
data modified, branch pushed, PR opened, site deployed or remote issue closed.
All positive integration evidence uses owned synthetic fixtures.

## Delivered implementation

### Complete captured identity inventory

`api/services/ml_identity_audit.py` reconstructs the exact existing grouping
rules using a separate local graph, with no monkeypatch of the old compiler.
It compares its complete typed-key/component map with the unchanged `_groups`
result. A missing key or changed component hash invalidates the audit.

The inventory retains all captured roots, excluded candidates, unselected
features and noncandidate bridges. It includes Work/Paper/revision/capture/
occurrence, material/state/sample, structure/coordinate bytes, run/artifact and
verified feature-binding identities. Controlled join witnesses pin the relevant
frozen rows, source mappings and retained review/declaration bytes. A
conservative context or pending bibliographic mapping is not called a reviewed
causal relation.

Every example retains its candidate status, exact claim/component, selected
partition, B/P/S/PS membership, direct identity references and missing identity
kinds. Per-cohort/per-partition counts separate directly attached label
identities from the full identities in associated leakage components. Alias
namespaces normalize to one underlying row for counts without changing the
old component hash.

Material parent-series, declared sample-trajectory and declared structure-near-
duplicate subgraphs report explicit-edge components separately from unlinked
identities. Equal formula/sample strings do not manufacture a new identity or
relationship. `independent_support_count` remains `null`: neither distinct
papers nor distinct stored IDs prove independent experiments.

### Computed invariant checks

Actual selected partitions are accumulated for every component and normalized
identity. Crossings produce controlled no-go records, rather than a constant
empty list. Additional checks cover candidate/row/cohort consistency, P/S/PS
subset/intersection rules, shared view assignments, same-cohort comparisons and
the declared split policy.

The full frozen graph remains intact before label/feature holds. Mixed or
unknown-family components in family holdout remain excluded and unassigned;
their presence alone does not invalidate other eligible components. Assigning
such a component fails the audit. Chemical-system grouping is applied only for
the corresponding requested split mode.

Malformed references, incomplete inventories, duplicate identities, incorrect
pins and exhausted budgets invalidate a complete report. Well-formed crossing
or assignment violations produce no-go. Nothing truncates a graph and reports
it as complete. Bounds are 20,000 typed nodes, 50,000 joins, 200,000 cumulative
references, 16 MiB serialized audit, 200,000 JSON nodes and depth 48, alongside
the existing capsule/context limits. These are engineering limits, not a
production-capacity measurement.

### Mandatory wrapper and replay

`api/services/ml_audited_dataset.py` calls the actual v4 builder and passes a
private copy of its canonical base to the audit. It rejects base mutation,
incorrect child versions/pins/authority, incompatible view inventories,
noncanonical encoding and source-code drift. The outer package separately
pins the two new implementation modules and their combined map while retaining
all historical source pins inside the unchanged base.

The version-owned outer serializer/parser permits up to 32 MiB, 400,000 JSON
nodes and depth 64, without modifying the old capsule/companion limits. Parsing
bounds token allocation before constructing the tree. Complete verification
rebuilds the base and audit; recomputing the hashes of tampered memberships,
counts, assignments or authority does not make the package valid.

The six scientific/training/publication/reviewer/live-rights/external-
completeness authority flags remain false. A valid technical package is not an
authorized real training release.

### Offline CLI and honest filesystem outcomes

`scripts/ml_audited_dataset.py` requires the five independently pinned v4 input
files. It checks them again after computation and rechecks the package last
during verification. It rejects aliases, nonregular files, noncanonical JSON,
oversize input, changed bytes/inodes and output inside the closed capsule
directory.

Successful output is a new 0600 file, with no overwrite, file/directory sync,
created-inode ownership and final requested-path/content checks. A detected
replacement is not removed as if it belonged to the tool. Publication or
cleanup/durability ambiguity returns `output_state_unknown` and
`output_written=null`; operators must inspect before retrying. These are final
observations, not protection against arbitrary later file changes.

## Independent review findings resolved

1. The first wrapper required all nine views even for a valid composition-only
   task. It now checks the actual 1/3/3/9 task-dependent view inventory.
2. Structure prototypes can legitimately have no coordinate artifact. The new
   audit now follows the old nullable-artifact rule and invents no coordinates.
3. Real physical-feature witnesses include a `feature_binding` namespace. The
   new graph now maps it to the exact verified companion binding instead of
   rejecting a valid full-feature package.
4. Context/source join witnesses needed the actual captured Paper–Work mapping
   pins in addition to endpoint IDs. The added pins improve traceability without
   reclassifying conservative joins as reviewed scientific support.
5. A moved output directory or replaced temporary/final leaf could yield a
   misleading successful write. The CLI now retains the created inode, checks
   ownership before cleanup and verifies the requested parent/output after
   publication. Replaced leaves are preserved and uncertain outcomes are explicit.

## Verification

Final verification after freezing the new production and test sources:

| Check | Result |
| --- | --- |
| Guarded native API, exact nine-module selection below | **473 passed**, 1 existing warning; **261.73 seconds**; exit 0 |
| Complete scripts regression | **1,621 passed plus 36 subtests**, **27.67 seconds**; exit 0 |
| All seven new Python files, Ruff `I,F` | Passed |
| Git whitespace and unchanged historical source checks | Passed |

The final native run includes all 12 new real SQL/canonical integration cases
in one passing selection. The runner confirmed cleanup of only its own
disposable services and temporary test data. No failed, skipped or weakened
case is hidden in the final result. Subsequent edits only finalize documentation.

The final full script regression passed **1,621 tests plus 36 subtests** in
**27.67 seconds**. New CLI coverage includes five independent pins, changed
bytes/inodes, complete final rereads, no-clobber output, files above the old
8 MiB writer limit, bounded parsing, publication/cleanup/fsync/close failures,
parent-directory moves and temporary/final-file replacement. Service doubles
in file/contract tests are explicitly not scientific admission evidence.

The native integration exercises real disposable SQL/canonical captures:
composition-only and physical/coordinate positives, Paper versions/repeated
occurrences, exact Sample/State IDs, parent series, both reviewed declaration
types, excluded family bridges, optional-source holds, Tc-derived renamed
multi-hop results, resealed tampering and actual offline CLI subprocesses.
The CLI subprocess denies database/network/provider execution and the tests
retain the actual freeze guards. Historical v4 rebuilds remain byte-identical.

An earlier integrated run completed **472 passed / 1 failed**: the new renamed-
feature fixture supplied selectors out of the existing required sorted order.
The unchanged validator correctly rejected it. Only the new test fixture was
sorted; neither source data nor the guard was weakened. The final integrated
rerun includes that correction and the final CLI publication checks.

The core checkpoint passed 44 tests and the wrapper checkpoint 111 tests.
These overlap the final integrated selection and are not additional coverage.
All native runs used the guarded runner with owned disposable PostgreSQL/Redis;
cleanup is part of the recorded run result. The existing FastAPI `regex`
deprecation is unrelated to the new contract.

Reproduce the exact nine-module selection from the repository root:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server --suite api -- \
  tests/test_ml_identity_audit.py tests/test_ml_audited_dataset_contract.py \
  tests/test_ml_identity_audit_sql.py tests/test_ml_dataset_v4.py \
  tests/test_ml_dataset_adversarial.py tests/test_ml_feature_provenance_v2.py \
  tests/test_ml_coordinate_features.py tests/test_ml_composition.py \
  tests/test_ml_preprocessing.py -q --tb=short --show-capture=no

api/.venv/bin/python -m pytest scripts/tests -q --tb=short --show-capture=no
```

This is the stated integrated API selection, not the whole API suite, Linux
release-image CI, frontend/browser verification or deployed-site acceptance.
The previous batch's larger compatibility run is historical evidence and is
not presented as a new run here.

## Remaining gates and next bounded item

A fresh read-only GitHub check on 2026-09-09 found **all 38 review issues OPEN**.
#70's real-data/release acceptance and its dependencies remain open. The audit
deliberately reports exact identities, not unsupported independent replication;
actual reviewed units, scientific labels, source rights, release authority and
delivery evidence must still be supplied. No issue can be closed merely by
interpreting the new technical gate as scientific approval.

The next engineering handoff is [ML09 baseline rehearsal](ML_Baseline_Rehearsal_Implementation_Design_2026-09-09.md):
a deterministic baseline/replay kernel tested on an owned synthetic end-to-end
fixture, with preregistered train/validation selection and held-out perturbation
canaries. General real-package execution remains no-go until an actual exact-
use ML authorization boundary exists. Current metadata/RPS distribution roles
and false-authority dataset packages cannot be relabeled as training permission.
This is future work, not a model trained by the present batch.

The overall upgrade goal remains active. Remote branch/PR/CI delivery and any
production/review/research actions requiring new authority remain separate.
