# Restricted scientific-feature datasets, version 2

Status: internal technical implementation, not an approved training release.
Related issues: [ML06 #70](https://github.com/JackZH26/SCLib_JZIS/issues/70)
and [ML05 #67](https://github.com/JackZH26/SCLib_JZIS/issues/67).
The [v1 task compiler](ML_TASK_DATASETS.md), frozen 0045 property registry,
0052 claim-source contract and 0054 capsule format remain unchanged.

## What this increment enables

An operator can retain independently reviewed source occurrences for exact
physical-property or coordinate inputs in a frozen candidate dataset, capture
those occurrences into an independently pinned private companion, and compile
fair composition/physics/structure comparisons offline. The original capsule
is not rewritten to manufacture source roots it never captured.

Technical success establishes reproducible declared evidence, not the truth of
a calculation, reviewer identity, source permission, scientific acceptance,
prospective performance, or approval to train or publish. Those flags remain
false. There is no training job, external calculation, production migration,
public endpoint, automatic extraction, or public Discovery score change here.

## Exact source provenance without rewriting history

Migration `0064_ml_feature_companion` adds one append-only table,
`ml_feature_source_bindings`. A binding identifies an actual persisted 0054
release and one of its actual `ml_example_inputs`. Only a property or structure
input is supported. Composite foreign keys retain the exact 0052 revision,
capture and Work, and the actual review artifact. A source may not be attached
merely because it shares the material formula, paper title, or Tc source.

The separate `ml-feature-source-review/1.0.0` document binds:

- The complete original capsule hash and frozen input/target row hashes.
- Actual property event, state, sample, structure and producer-run hashes where
  applicable; a structure input does not acquire a fictitious event/state FK.
- The selected label claim/event/state/sample/material/structure hashes.
- Exact source revision/capture records, version/publication and capture times,
  representation, source bytes, locator and independent review bytes.
- Closed applicability declarations and the retained scientific context.

Its three source flags are strict Boolean declarations. The actual metadata and
canonical bytes must agree. A checked hash or `approved` database state is not
human authentication. A wrong target, different capture, changed locator,
re-pinned mismatched review, withdrawn source, or incompatible review is held.

`register_feature_source_binding(...)` is a trusted internal writer, not a
public API. It defaults to `dry_run=True`, requires SERIALIZABLE isolation,
uses the existing integrity lock and a bounded nonblocking advisory lock,
and owns a savepoint only. The caller retains responsibility for its outer
transaction. Its receipt says `committed: false`; a savepoint is not a durable
commit. Exact retries and previews do not advance the database guard epoch.
Raw SQL still encounters frozen-input, FK, review and append-only guards.
Updates/deletes/truncation and nonempty downgrade are rejected.

`capture_feature_companion(...)` reads every persisted binding for the exact
base release in one clean REPEATABLE READ or SERIALIZABLE snapshot. It checks
the actual release and source metadata closure, including capture conflicts,
and requires the complete exact byte inventory. There is no client-selected
subset that can quietly omit an inconvenient binding.

The private `ml-feature-companion/1.0.0` contains source rows, all binding rows,
all base bytes and the additional source/review bytes as bounded base64. Its
limits are 500 bindings, 1,000 source rows, 400 artifacts, 8 MiB per decoded
artifact, 64 MiB combined decoded bytes and 96 MiB canonical JSON wire. Existing
0054 limits still apply independently; this is a bounded canary format, not a
claim that a million-row corpus has been processed.

The internal `companion_sha256` covers the body excluding that field. Every
external `expected_companion_sha256` or CLI `--companion-sha256` instead covers
the **entire canonical file**, including its internal checksum. Obtain that
external pin independently. Offline verification checks both hashes and exact
inventories, but cannot prove that an untrusted party actually observed the
database or discover bindings omitted before a separately trusted capture.

## First physical feature profiles

`ml-task/2.0.0` wraps a validated v1 positive Observed-Tc label task and adds
explicit sorted selectors. Each selector pins actual property key, registry,
component, unit, Computed origin, semantic profile and full protocol hash.
Feature names cannot confer scientific meaning on a different result.

| Actual property | Unit | Mandatory interpretation |
| --- | --- | --- |
| `formation_energy_per_atom` | eV/atom | Stated energy/enthalpy, elemental reference ensemble and nuclear treatment |
| `energy_above_hull` | eV/atom | Stated energy/enthalpy, actual retained competing-reference ensemble and treatment |
| `band_gap` | eV | Normal-state fundamental one-electron gap; declared spin/occupation treatment, not superconducting gap |
| `dos_at_fermi` | states/eV/formula_unit | Total spin channels, explicit source formula-unit basis, Fermi reference and broadening |
| `electron_phonon_lambda` | 1 | Isotropic full-alpha-squared-F spectral definition, DFPT protocol and nuclear treatment |
| `omega_log` | K | Same kind of spectral definition, frequency/temperature convention and DFPT protocol; zero is undefined |
| `phonon_min_frequency` | THz | Signed frequency on the actual declared q sampling; imaginary modes negative, not clipped to zero |

Initial profiles are Computed DFT/DFPT profiles. Experimental optical/tunneling
proxies are not silently pooled with them. RPS, Tc, superfluid stiffness and
other superconducting-response or target-derived proxies are not inputs.
The seven quantities are not universal superconductivity mechanisms, and a
technical admission is not a positive or negative contribution to an RPS score.

Every retained value must be an exact finite point. Missing/interval/censored
values stay missing; Boolean values are not numbers. Valid zero band gaps and
hull distances remain zero, not missing. Negative formation energies and signed
imaginary phonon frequencies remain meaningful numerical inputs. No absent
value, missing source, or RPS negative control creates a non-superconductor label.

Protocol hashes are fixed by the task before admission. Method/code version,
settings schema and full actual run settings must match. Stability references,
q grids/weighted points and EPC broadening/frequency grids are actual closed
objects retained in `run.settings.scientific_protocol_data`; a bare hash with
no underlying data is insufficient. These checks bind retained numerical
declarations; they do not prove convergence, reference-energy accuracy,
functional/pseudopotential suitability or a correct phase diagram.

A different protocol is excluded from that column rather than pooled or chosen
after seeing labels. This deliberately limits initial cross-family pooling:
different reference ensembles, pressure protocols or nuclear treatments need
separate preregistered tasks or a future scientifically reviewed harmonization
contract. `protocol_template()` deliberately returns invalid unknown fields;
it does not fabricate scientifically acceptable settings.

If both lambda and omega-log columns are selected and independently present,
joint use additionally requires the same actual run, state, structure and
shared spectral protocol projection. The output manifest must contain both
exact property references. A conflict removes both values, not the base label
or other valid physical features. A scalar can still be selected independently;
an incomplete pair retains explicit missingness. Imputation does not establish
a physical pair. This verifies shared retained declarations, not independent
re-integration of a common alpha-squared-F spectrum: spectral amplitudes are
not retained by this initial contract.

## Calculation lineage and time

A completed `research_runs` row and creation timestamp are insufficient. The
compiler reads actual canonical input/output `run_manifest` bytes:

- `ml-computed-input/1.0.0`: exact run and structure ID/hash, strict normal-state
  and non-target-use flags, plus sorted exact result dependency references.
- `ml-computed-output/1.0.0`: the same run and sorted exact output property
  references, including the property being admitted.

These references extend, never replace, the SQL `derives_from` graph. Event-only
or unresolved cross-state dependencies remain held. Any Tc, RPS or excluded
superconducting-response ancestor blocks the feature, including multi-hop and
renamed results. Noncausal `context`/`supports`/`refutes` edges remain noncausal
but still merge leakage groups. Parent-run lineage without a separately
supported complete manifest contract remains unavailable.

The same target-ancestry veto includes observed non-transition/non-detection
claims; absence of detected superconductivity is an outcome, not a prospective
physical descriptor. Invalid supporting physical or coordinate declarations
also propagate to dependent features. Structure-parent relations participate
in the temporal DAG. Bounded resolvable exact result references in actual run
documents are retained for grouping even if another manifest assertion fails.

The calculation's exact coordinate input also needs its own witnessed source
time. Retain a structure `ml_example_inputs` binding even in a physical-only
task; the structure columns need not be selected. A property's paper date is
not borrowed as the coordinate source's date.

Availability uses each feature's own reviewed source version, never the Tc's
Work date, artifact `available_at`, run status or ingestion timestamp. The full
declared dependency closure must be known by the task cutoff, and the feature
must be known by the selected label's witnessed availability. Public-knowledge
mode distinguishes publication time from later capture time; operational mode
additionally requires capture by the cutoff. Publication-date equality does
not prove that a feature was experimentally available before measuring Tc.
No first-discovery or LLM-pretraining-contamination claim is made.

Published computations may use their own exact literature witnesses. Unpublished
new computations require a future operational receipt contract and are held
here; no synthetic historical-public date is invented for them.

## State applicability and normal-state surrogates

The first information regime is `pre_outcome_normal_state`. Exact property
admission requires the same actual state; exact structure admission requires
the label event's actual structure. Matching text alone is not enough.

A separate reviewed `normal_state_surrogate` supports, for example, a simulation
state at 0 K used for a finite-temperature observed specimen. The complete
review pins both sides and explicitly records scope, rationale and uncertainty.
Hard checks still require the same material and resolved source-bound
composition, equal explicit pressure and magnetic field, and equal explicit
phase. Property surrogates require a simulation state. Both structural contexts
must exist and be pinned. Different nonnull sample identities are a veto.
Missing field/phase/pressure is not equality. A review cannot override a known
contradiction or turn a computed proxy into an observed measurement.

## Coordinate features

Only two intensive bulk descriptors are added: volume per atom and conventional
mass density. They use the actual full cell and explicit fully occupied sites;
site order and an exactly repeated supercell do not change their meaning.
No raw site count, ordinal space-group number or textual structure name is used
as a universal numerical feature.

Inputs can be closed `sclib-coordinate/1.0.0` JSON or the documented bounded
`vasp-poscar/1.0.0` subset: explicit VASP5 elemental species, one positive scale,
Direct/Cartesian coordinates and optional explicit selective-dynamics flags.
Negative or three-axis scales, omitted species, MD continuation, velocities,
isotope labels, partial occupancy, duplicate periodic sites and degenerate cells
are rejected. The parser follows VASP's lattice and Cartesian scale convention;
POSCAR species labels do not attest the POTCAR actually used in a calculation.
See the [upstream POSCAR specification](https://vasp.at/wiki/POSCAR).

The source review separately declares full bulk 3D/no-vacuum applicability,
source formula, non-target origin, normal state, phase and conditions. A parser
cannot independently distinguish vacuum from empty bulk space. General CIF
symmetry expansion, disordered occupancy, 2D slabs, moiré systems and isotope
masses remain unavailable. Unsupported geometry does not become zero density.
The density conversion uses the exact SI Avogadro constant; atomic masses use
the existing pinned conventional table, not isotope-specific masses. See
[NIST's SI definition of amount of substance](https://www.nist.gov/pml/owm/si-units-amount-substance).

## Fixed splits and fair comparisons

Construct the complete leakage graph before any optional-feature exclusion:
all frozen results, source Work/version/capture, material ancestry, sample/state,
structure ancestry/exact coordinate bytes, producer runs/manifests, declared
near-duplicate/trajectory links and all candidate input relations. Shared code
or a protocol alone does not make all materials one experimental sample.

Freeze one base cohort **B** of independently eligible labels and its single
train/validation/test assignment. Invalid optional features do not delete B.
Then derive **P** (at least one selected physical quantity admitted), **S**
(exactly one admitted coordinate structure), and **PS = P intersection S**.
Multiple admitted structures are an unresolved choice, not an opportunity to
pick the best score or average different phases.

Only these comparisons share a scientifically interpretable coverage basis:

| Cohort | Required comparison views |
| --- | --- |
| B | C baseline, descriptive coverage context |
| P | C versus C+P on identical samples and assignments |
| S | C versus C+S on identical samples and assignments |
| PS | C, C+P, C+S and C+P+S on identical samples and assignments |

`C@B` versus `CPS@PS` is not reported as a fair feature-performance comparison.
There are no trained-model performance results in this implementation.

Each view fits medians, retained columns and standardization on its own training
rows only. Missingness remains explicit before imputation. An all-missing train
column is dropped even if held-out values exist. Enhanced views with no observed
added training features, or any required view lacking train/validation/test,
are `no_go`. The compiler never retries a seed, relaxes grouping, drops a hard
conflict or resplits a subset to manufacture a passing experiment.

## Executable workflow and verification

1. Build and independently review a real candidate capsule using the existing
   0054 workflow. Its label, run, coordinate and input foreign keys must already
   be real; no ad hoc manipulation of a frozen manifest is supported.
2. Obtain independent exact source/applicability reviews. Use the trusted
   default-preview registration service; an authorized caller explicitly owns
   any actual transaction commit. The code does not create genuine reviews.
3. Capture the complete private companion with `capture_feature_companion` in
   a clean stable snapshot and retain independent complete-file SHA-256 pins.
4. Fill a v2 task with exact selectors and protocols, preserve its independent
   file pin, and run the locked API interpreter with the offline CLI below.
5. Independently verify by rebuilding every view from the original capsule,
   original bytes, companion and task. Rehashing a modified dataset is not enough.

```bash
api/.venv/bin/python scripts/ml_scientific_dataset.py build \
  --manifest /private/capsule/manifest.json --manifest-sha256 MANIFEST_FILE_SHA256 \
  --companion /private/feature-companion.json --companion-sha256 COMPANION_FILE_SHA256 \
  --task /private/task-v2.json --task-sha256 TASK_FILE_SHA256 \
  --output /private/output/dataset-v2.json

api/.venv/bin/python scripts/ml_scientific_dataset.py verify \
  --manifest /private/capsule/manifest.json --manifest-sha256 MANIFEST_FILE_SHA256 \
  --companion /private/feature-companion.json --companion-sha256 COMPANION_FILE_SHA256 \
  --task /private/task-v2.json --task-sha256 TASK_FILE_SHA256 \
  --bundle /private/output/dataset-v2.json --bundle-sha256 DATASET_FILE_SHA256
```

Paths and hashes above are placeholders. No command creates source evidence.
The CLI refuses aliases, nonregular files, changing inputs, duplicate/noncanonical
JSON, mismatched pins and overwrite attempts. It never writes inside the closed
capsule inventory. Exit 0 means technical pass, exit 3 means an accounted no-go
with no dataset written, and exit 2 means invalid input with private error text
suppressed. Successful outputs are new owner-only files; all authority flags
remain false. The interpreter is the locked API runtime (package imports include
existing ORM/configuration); descriptor arithmetic itself is standard-library
code and performs no network/database connection or learned fitting beyond the
explicit training-only preprocessing described above.

## Remaining acceptance gates

Real redistribution-permitted reviewed source packages, independent physical
review, source rights/currentness, protocol suitability, actual convergence,
sampling bias, complete external dependencies, prospective acquisition time,
larger-scale evaluation and learned adapters remain open. This canary must not
be described as a universally ML-ready cross-family superconductivity dataset.
Neither #67 nor #70 is closed solely because synthetic SQL fixtures pass.
