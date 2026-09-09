# Mandatory typed identity audits for private ML datasets

Issue: [ML06 / #70](https://github.com/JackZH26/SCLib_JZIS/issues/70).
Contract: `ml-identity-audited-dataset/1.0.0`, containing an unchanged
`ml-task-dataset/4.0.0` base and a mandatory `ml-identity-audit/1.0.0` audit.
Grouping policy: `captured-typed-identity/1.0.0`.

## Purpose and non-goals

An opaque leakage-group hash is insufficient for inspecting how Works,
specimens, states and declared trajectories contribute to a dataset. This
increment exposes the complete captured grouping inventory and computes its
partition checks. It does not establish a newly discovered leak in the old
compiler, add a scientific independence model or train a superconductivity
predictor. Existing v1–v4 source files, output formats and source-checksum
contracts remain unchanged.

The new entry point builds the actual v4 base and then audits it. Both technical
gates must pass before the CLI writes the package. An optional sidecar, an
unchecked `pass` flag or a fresh checksum on modified output is not an
alternative: verification recomputes both layers from the independently pinned
inputs. The low-level audit function alone does not authenticate an externally
supplied base; use the complete wrapper and verifier.

This package is private. It includes source identities and frozen scientific
records, not a public Discovery DTO. All six authority flags remain false:
scientific acceptance, public release, ML training approval, reviewer
authentication, live source-rights checking and external dependency completeness.
Hashes detect differences against trusted pins; they are not signatures, source
rights or evidence of genuine human review.

## What the units mean

| Unit | Exact captured basis | Interpretation limit |
| --- | --- | --- |
| Work / Paper | Frozen IDs, result references and captured Paper–Work mappings | Bibliographic identities, not independent experiments; a conservative mapping join is not positive alias approval |
| Revision / capture / occurrence | Frozen source revision, retained capture and claim occurrence IDs | Several occurrences or revisions can describe the same experiment |
| Sample / State | Exact sample/state IDs and their material references | Equal names or conditions do not create a specimen alias |
| Material series | Explicit `parent_material_id` edges | No inference from a formula family or legacy grouping string |
| Sample trajectory | Exact endpoint rows and retained `sample_trajectory` review declarations | Unlinked samples are not known independent trajectories |
| Structure | Exact record IDs, parent links and verified coordinate-byte identities | Equal composition is not equal structure; different bytes do not disprove a near duplicate |
| Near-duplicate component | Exact `structure_near_duplicate` endpoint and review-artifact declarations | No unrecorded similarity search or all-structure completeness claim |
| Run / artifact | Actual declared run, parent, manifest and dependency references | A declaration does not authenticate calculation execution |

The grouping inventory preserves the old namespace keys because their sorted
members determine the old component hash. Counts normalize keys such as
`material_ancestor` / `material`, `structure_ancestor` / `structure` and
`run_artifact` / `artifact` to the same underlying identity. A row is not counted
twice merely because two grouping rules name it differently.

`independent_support_count` is always `null`. No general adjudicated
replication registry is available. Unknown external relationships remain unknown;
zero captured edges is not evidence of zero real relationships.

## Inspectable audit fields

- `nodes`: sorted typed grouping keys, normalized identity, component hash and
  exact frozen row pins. Synthetic composition/system keys have no independent
  scientific identity.
- `components`: complete sorted members, normalized identity counts and full
  captured family sets, including excluded/noncandidate bridging nodes.
- `join_witnesses`: controlled rule, typed endpoints, supporting row pins and
  retained artifact hashes. These explain conservative grouping, not causal
  mechanisms or scientific approval.
- `examples`: every frozen root example, including excluded candidates; exact
  claim/component, candidate status, admitted base partition, B/P/S/PS
  membership, direct identities and missing direct-identity kinds.
- `counts`: each cohort's `all`, `train`, `validation` and `test` rows and
  components, with separate `direct_label` and `full_components` identity counts.
- `relationship_components`: explicit-edge material-series, sample-trajectory
  and structure-near-duplicate subgraphs, plus separately reported `unlinked_ids`.
- `checks` and `gate`: actual calculated violations and controlled no-go codes.

`direct_label` counts identities directly attached to selected labels by the
captured claim/event/state/source-occurrence references. It is not a count of
accepted positive supporting sources. `full_components` includes all identities
associated through the complete leakage graph, including excluded examples,
unselected features and conservative source mappings. It must not be presented
as the selected labels' direct experimental support.

The denominator for a missing-direct-identity count is the selected `rows` in
that cohort/partition. These are missing identity references, not measurements
of missing physical properties. Counts across cohorts must not be added: P and S
are subsets of B and can overlap; PS is their intersection. The same identity
can support several rows, so identity counts need not equal row counts.

## Computed checks and exclusions

The service reconstructs the existing grouping rules with its own local graph
and compares the complete typed-key-to-component mapping with the unchanged
compiler's `_groups`. It does not patch the old grouping implementation. Every
join must remain inside one component.

Actual base partitions are accumulated for every component and normalized
identity. A component or identity spanning multiple partitions produces a no-go
violation. The audit also checks candidate/row and cohort membership, one base
assignment reused across views, the requested split policy, and identical
members/assignments in each same-cohort comparison. The view inventory follows
the task: a composition-only task does not require unavailable enhanced views.

The complete frozen graph is formed before negative label or feature holds.
Removing a training label must not sever its Work/sample/material/structure
bridge. Current review actors and currentness-only observation rows do not add
scientific grouping edges. The base still performs its original source,
temporal, method, target-ancestry and train-only preprocessing gates.

For family holdout, all families in a component matter, including excluded
bridges. Mixed/unknown-family components remain excluded and unassigned.
Their presence alone does not force an otherwise valid dataset to no-go;
assigning them is a violation. Chemical-system grouping applies only when the
task requests chemical-system extrapolation, not ordinary interpolation.

Malformed or incomplete references, duplicate inventories, incorrect pins and
exhausted budgets raise an invalid-input error. Well-formed assignment or
crossing violations produce an audit no-go. A technically valid no-go package
can be inspected in memory; the build CLI does not publish it as a dataset.

## Independent pins, versions and offline operation

The outer package contains `base_dataset`, `base_dataset_sha256`,
`identity_audit`, `identity_audit_sha256`, `audit_policy_version`, exact new
`audit_implementation` module hashes, their combined hash, aggregate `gate` and
false `authority`. Historical compiler hashes stay inside the unmodified base.
Changes to either new implementation module invalidate replay against the old
outer package; retain the exact implementation revision for reproducibility.

The five input files and their independent canonical whole-file SHA-256 pins
are the same as for [v4 label-currentness compilation](ML_LABEL_CURRENTNESS.md).
Internal observation/body hashes do not replace the file pins. The new CLI is:

```bash
api/.venv/bin/python scripts/ml_audited_dataset.py build \
  --manifest /private/capsule/manifest.json --manifest-sha256 CAPSULE_FILE_SHA \
  --companion /private/source.json --companion-sha256 SOURCE_FILE_SHA \
  --review-companion /private/review.json --review-companion-sha256 REVIEW_FILE_SHA \
  --label-companion /private/labels.json --label-companion-sha256 LABEL_FILE_SHA \
  --task /private/task-v4.json --task-sha256 TASK_FILE_SHA \
  --output /private/new-audited-dataset.json
```

For verification use `verify`, the same five pinned inputs, and `--bundle` /
`--bundle-sha256` instead of `--output`. The bundle pin is the **outer package's
whole-file hash**, not the embedded base or identity-audit hash. Verification
rebuilds the complete package, including counts, memberships and implementation
pins; resealing a manipulated audit does not make it valid.

Inputs are reread after computation, including file identity checks. Verification
also rereads the package after those input checks. Paths must be absolute with
existing non-symlink parents. The readers reject aliases, nonregular files,
oversize files, duplicate/nonfinite/noncanonical JSON and changed inputs. The
output cannot be placed inside the closed input capsule directory.

A successful build creates a new owner-only 0600 file, never overwrites an
existing target, and syncs the file and output directory. It keeps the created
inode open, checks temporary-file ownership before cleanup, and reopens the
requested parent/output to check directory identity, created inode, single-link
status, permissions and complete content hash. A detected replacement is not
deleted as if it were the tool's own temporary file. These are final integrity
observations, not a guarantee that another process cannot change files later.
A publication syscall,
cleanup or post-publication durability failure can leave an uncertain outcome:
the CLI then reports `status=output_state_unknown`, `output_written=null`, exit
2. Inspect the exact target independently before retrying; do not infer it is
absent. Normal technical pass is exit 0, no-go is 3, invalid input/error is 2.
None is a scientific approval level.

No database, provider, network, training, publication or production operation is
performed by this offline entry point. Its currentness evidence remains the
captured observations, not a newly authenticated live rights decision.

## Resource bounds and delivery boundary

The audit limits typed nodes to 20,000, join witnesses to 50,000, cumulative
references to 200,000, serialized audit bytes to 16 MiB, JSON nodes to 200,000
and depth to 48. Existing manifest/context limits also apply. The audit's base
preflight uses its bounded canonical validator. No partial graph is truncated
and labeled complete.

The outer package owns separate cumulative limits: 32 MiB, 400,000 JSON nodes,
depth 64. Its parser bounds token allocation before constructing the JSON tree.
These new limits do not enlarge historical capsule or companion limits. They
are engineering bounds, not measured corpus capacity or runtime guarantees.

The batch report records actual local tests. Synthetic SQL/canonical fixtures
establish implementation behavior, not real reviewed support, calibration,
scientific validity or independently replicated superconductivity. ML06, ML09,
ML07 and the evidence pilot retain their separate acceptance/release gates.
