# Restricted task-specific ML dataset compilation

Version: `ml-task/1.0.0` and `ml-task-dataset/1.0.0`.
Issue: [ML06 / #70](https://github.com/JackZH26/SCLib_JZIS/issues/70).

## What this delivers

The existing 0054 research capsule is now an executable input boundary, not an
unused snapshot definition. A compiler reconstructs task-specific labels,
features, leakage components, partitions and train-fitted preprocessing from
its exact frozen rows and artifact bytes. A separate offline verification call
repeats the entire computation and compares the complete canonical output.
The original capsule, task and output each need an independently supplied pin.
A changed output with a newly computed outer hash still fails recomputation.

This is a **restricted internal technical report**, not a published training
release. The technical gate can pass with synthetic fixtures or declared review
states. `scientific_acceptance`, `ml_training_approved`, `public_release`,
`reviewer_authority_authenticated` and `live_source_rights_checked` stay false.
It does not create a model, authorise training, authenticate a scientist, grant
source rights, or update the website. ML07 and actual scientific review remain
separate gates. Output can contain private material/source identifiers: do not
place it in a public directory or serve it through Discovery.

## First supported estimand

`observed_tc_point_given_reported_state`: an exact positive experimental Tc,
under one explicit transition criterion and the declared pressure/field scope.
It is conditional on the published measurement, not a probability that an
untested material will superconduct. All current examples are selected from
known positive reports; selection/publication bias is explicitly recorded.

| Task dimension | First implementation |
| --- | --- |
| Target | Exact positive Tc in K; lower-exclusive, upper-inclusive task label window |
| Origin | `Observed`, primary experimental measurement only |
| Criterion | Exactly one of onset, zero resistance, midpoint, diamagnetic, heat capacity |
| Pressure | Explicit ambient, or a closed numeric reported range; unknown never means ambient |
| Magnetic field | Explicit maximum and either exclude unknown or preserve missingness |
| Measurement window | Optional requirement for reported Tmin; Tmin must not exceed target Tc; upper acquisition bound is unavailable |
| Review | Accepted claim/event, approved event with verified decision-artifact bytes, approved timestamped QC; declarations are not authenticated authority |
| Features | Formula-only 121 columns, or those columns plus reported pressure and magnetic field |
| Time | Aware cutoff; public-knowledge or operational-capture mode |
| Splits | Grouped interpolation, chemical-system extrapolation, or explicitly named family holdouts |
| Preprocessing | Train-only median imputation and population-standard-deviation scaling |
| Censoring | Missing, not-detected, interval and bounded results are excluded, never converted into point or negative labels |

`default_task()` in `api/models/ml_task.py` creates an explicit draft. Defaults
are engineering defaults, not an endorsed experimental protocol. The task must
be reviewed for the actual study before its hash is pinned. Unknown fields,
unsupported budgets/origins/targets, booleans in numeric fields, naive cutoff
dates and malformed group references fail closed. Nothing silently falls back
to a universal all-family regression task.

Computed Tc, classification, censored regression, structure/physical-property
feature admission and learned retrieval/feature adapters are unsupported in
this version. They require separate contracts and tests, not a configuration
string that bypasses the present gates. No RPS or Discovery score is a label.

## Exact candidate and label boundary

Only `ml_examples` owned by the root frozen dataset are candidates. Other claims
and events in the closure support identity/dependency checks; they are never
silently added to the training denominator. Candidate identity is checked
against its exact claim, material and Work. The event revision and claim
interpretation revision travel with each accepted row.

Stored `label_data`, `split`, `assignment_hash`, `work_group`, `material_group`,
`parent_series_group`, `chemical_system_group`, `duplicate_group` and stored
availability are ignored as decision authority. Labels are reconstructed from
the exact claim. New split hashes bind task, example, label-row hash, component
and partition. Frozen pending declarations are not promoted during compilation.

The source resolver independently rechecks the existing
`source-occurrence-review/1.0.0` payload against claim/Work/revision/capture,
locator and actual source/review bytes. A 0054 row hash and a 0052 source record
hash have different serialization semantics; UTC timestamps and SQL float
values are restored only when recomputing the latter. Neither hash substitutes
for the other.

The exact source version's verified public date determines known-by status,
not the Work's earliest year, paper date, row creation date or another sample's
measurement. Operational-capture mode additionally requires local capture by
cutoff. Same Work/sample/Tc does not move a later version's result backward in
time. Missing/uncertain provenance and post-cutoff dependencies are excluded.
This establishes neither first appearance nor absence of LLM contamination.

## Formula features and condition safety

Features come from formula strings in the **exact claim's `raw_record`**, whose
complete value is bound by the source-occurrence review. A contemporary catalog
formula alone cannot establish historical feature availability. Both top-level
and nested original/extracted formula fields are checked. Conflicting formulas,
variable formulas, unsupported isotopes, unresolved interfaces/mixtures and
unresolved family shorthand cannot be normalized into exact training inputs.
Equivalent accepted notation may agree; contradictory simultaneous inputs
cause exclusion. A computable catalog formula that disagrees with the claim
also causes exclusion. Raw/source evidence is never rewritten.

The API vendors the existing audited, standard-library formula parser unchanged
except for its import namespace. Full-source parity is tested against ingestion.
The fixed feature order is 118 alphabetically ordered elemental fractions,
number of elements, atoms per formula unit and molar mass. The parser reduces
integer stoichiometries; fractional occupancies retain its declared formula-unit
scale. Standard/conventional elemental masses are not isotope-specific masses.
Exact parsing is not proof of sample purity, occupancy or material identity.

The conditional budget adds only the claim's reported pressure and field.
Pressure must agree with the same frozen state; a declared state field must be
numeric (not boolean) and agree with the claim. No state temperature, Tmin,
Tc, inferred Tc-dependent parameter or published score is a feature. Tmin
remains acquisition metadata only. A joint measurement condition is not proof
that it was independently controllable before the measurement.

Every declared `ml_example_inputs` entry is audited, including exact multi-hop
claim/property dependencies. A renamed feature whose ancestry contains the
target or a same-material/state Tc claim is explicitly marked `target_dependency`.
All external property/structure/artifact/event-context feature bindings are
unsupported and exclude that candidate in v1; they are not silently ignored
while the output claims full physics-feature support. Existing 0052 tables do
not supply exact property-source occurrences. A property's own availability
therefore remains unknown, even if an upstream claim is dated.

## Grouping and splits

Grouping uses the complete frozen identity graph **before exclusions**:
Work/paper/version/capture/occurrence, material and parent ancestry, exact parsed
composition, state, sample, structure ancestry and event links. Noncandidate
and subsequently excluded nodes remain bridges. An event-only, cross-state or
cross-material link can merge leakage components while remaining scientifically
unresolved. Context/support/refute links do not thereby become causal derivation
edges. Printed sample labels are never treated as global specimen IDs.

For additional declared sample trajectories or structural near duplicates,
`grouping_links` must reference captured endpoints and an actual captured review
artifact. `ml-grouping-declaration/1.0.0` binds both endpoint row hashes, the link
kind and `merge_for_leakage_control: true`. This new declaration only adds a
conservative merge; it does not authenticate a review or prove omitted links
absent. Its byte-exact fields are assembled in `_declared_links`. No arbitrary
legacy duplicate-group string is trusted.

The hash-ranked split is deterministic for fixed capture, task and seed. Group
quotas—not row quotas—are allocated; rounding and a minimum of one group in
each partition are explicit. Insufficient components/quotas produce no-go.
Chemical-system extrapolation additionally joins every identical element set.
Family holdout uses exact frozen family declarations with explicit validation
and test label sets. Components spanning incompatible partitions or containing
unknown-family bridge nodes are held out of the dataset; a row is never moved
alone to repair a split. Shared families entirely outside named holdouts are
training data. Catalog family labels are not an authenticated taxonomy.

Component-crossing checks prove a property of the captured/declaratively merged
graph only. They do not prove independent experiments, complete trajectories or
complete structure-near-duplicate detection. Coverage therefore reports
`leakage_components`, distinct Work/state/sample/material counts, row counts,
family/chemical-system balance, Tc ranges and feature missingness separately.

## Train-only transformations and artifacts

Training rows alone determine medians, mean and population standard deviation.
An all-missing training column is explicitly dropped even when test values are
present; constant columns use scale one. Missingness is retained in the original
feature inventory, while transformed rows use the retained inventory. The
helper accepts no label argument. A test-only extreme cannot alter fitted
parameters. Nonfinite arithmetic is rejected atomically.

The report includes the full task, independent input pins, packaged compiler
and parser source hashes, runtime requirement, per-column names/types/units/
source/nullability, exact labels, raw/transformed features, missingness, fitted
parameters, assignments/hashes, every exclusion, balance, dependency edges,
source audits, temporal report and authority/data-card limitations. Recompute
using the same archived implementation, not a later compiler under an old
version claim. It uses no network, database, external model or package-dependent
scientific descriptor. Runtime is the repository's locked API interpreter;
the compiler path itself uses CPython >=3.11 standard-library modules only.

## Offline use

First capture the existing approved-for-restricted-processing 0054 capsule by
its existing freezer/export workflow. This compiler does not query a live API
or create that approval. The directory must contain only canonical
`manifest.json` and its exact declared `<sha256>.bin` artifact leaves.

Prepare a reviewed task using `default_task()`, adjust its explicit policy,
then call `validate_task(task)` and serialize with the project's `canonical`
function. For example, an operator Python session with `api` on its module path
can use `scripts.ml_task_dataset.write_new_json` to create a new private task
file. Pins must be retained independently; a hash printed beside untrusted
content is not authenticity or approval.

```bash
api/.venv/bin/python scripts/ml_task_dataset.py build \
  --manifest /absolute/private/capsule/manifest.json \
  --manifest-sha256 INDEPENDENT_CAPSULE_SHA256 \
  --task /absolute/private/task.json \
  --task-sha256 INDEPENDENT_TASK_SHA256 \
  --output /absolute/private/new-dataset.json

api/.venv/bin/python scripts/ml_task_dataset.py verify \
  --manifest /absolute/private/capsule/manifest.json \
  --manifest-sha256 INDEPENDENT_CAPSULE_SHA256 \
  --task /absolute/private/task.json \
  --task-sha256 INDEPENDENT_TASK_SHA256 \
  --bundle /absolute/private/new-dataset.json \
  --bundle-sha256 INDEPENDENT_COMPILED_SHA256
```

The CLI requires an existing absolute, non-symlink parent directory. Use real
paths (for example, resolve macOS temporary-directory aliases). Files must be
bounded regular files without aliases; duplicate-key/nonfinite/noncanonical
JSON is rejected. Inputs and identity witnesses are rechecked after compilation.
No-go returns code 3 and does not create an output dataset. Invalid pins,
content or paths return code 2 with a redacted error. Success returns code 0
and retains false scientific/ML/public authority flags. New output is private
mode 0600 and atomically linked without overwriting an existing path.

## Remaining research and integration work

This baseline does not close #70. Next technical work is task/rights approval
and current lifecycle integration with ML07; typed exact source occurrences for
physical features; audited structure/trajectory matching and fair nested subset
comparisons; real task-specific evaluation data and independently adjudicated
scientific acceptance. Censored/Computed tasks and trained adapters require
their own validation. Only after an appropriate release is actually approved
should ML09 train and compare baselines or AL01 claim discovery/replay utility.
