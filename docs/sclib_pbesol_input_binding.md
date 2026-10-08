# Closed PBEsol preparation binding

`scripts/sclib_compute/pbesol_profile.py` adds an offline identity check for the
four frozen source models prepared by `build_sclib_pbesol_preparation.py`. Each
has two **preparation stages**, `initialize` and `scf`; the serialized field
`preparation_phase` follows the preparer's terminology. It does not describe or
approve a material's crystal or thermodynamic phase.

The binding is `sclib-pbesol-input-binding/1`, with method profile
`pbesol-source-coarse-qe75/1`. It is not a native worker descriptor. The current
worker cannot dispatch it, and the existing PBE `sclib-native-qe/1` rules remain
unchanged. No job, runtime capability, budget, result or candidate score is
created by this module.

## Accepted input and source authority

The Python interfaces are:

```python
build_input_binding(source_id, phase, files) -> PbesolInputBinding
validate_input_binding(binding_json, files) -> PbesolInputBinding
```

`files` is a dictionary of immutable bytes with the exact flat names `source.in`,
`preparation.json`, `delta.json`, `input.in` and the two or three expected UPF
basenames. File names are never opened. Source/deck/JSON inputs are limited to
64 KiB each, UPFs to 1 MiB each and the full set to 4 MiB. The interfaces only read
fixed installed trust metadata and the preparer's installed source file; they do
not read caller paths, write files, connect to a service or invoke a solver.

The installed source profile and historical preparer code are checked against
their actual byte hashes. `pbesol-prepared-pins-v1.json` is itself hash-pinned and
binds the eight previously frozen preparation manifests, source/derived decks,
line deltas and geometry hashes. This table contains public source identifiers
and hashes, not historical filesystem contents. A caller cannot select a custom
profile or replace source authority with self-declared checksums.

| Source ID | Composition | Role | Source representation | Electrons / bands |
|---|---|---|---|---|
| agm001228974 | TiNb2Mo | Target | ibrav 6 | 52 / 31 |
| agm002322068 | TiNb2Mo | Same-composition structure control | ibrav 2 | 52 / 31 |
| agm001828806 | NbTa3 | Target | ibrav 6 | 94 / 56 |
| agm001416090 | NbTa3 | Same-composition structure control | ibrav 2 | 94 / 56 |

The source is parsed with the unchanged preparer; UPF bytes and their PBESOL,
norm-conserving, scalar-relativistic headers are bound to species and valence
inventory. The derived input and complete line delta must exactly match a fresh
in-memory derivation. Every preparation manifest also matches its external pin
and independently checked source/deck/UPF/geometry claims.

This is a finite canonical input subset, not a general QE parser. It retains
original species order, fractional literals (including negative/out-of-cell
values), ibrav 2/6 geometry, source coarse mesh and MP smearing. It requires the
frozen explicit `nbnd`/`ecutrho`, neutral nonmagnetic assumptions,
`from_scratch`, isolated paths, `la2f=false`, and the declared preparation stage.
IONS/CELL and inactive ionic thresholds are removed only through the existing
explicit line delta. Alternate whitespace, additional directives, changed
source method, new meshes or fine `la2f=true` inputs require another reviewed
profile version. PBE substitution is not normalized into PBEsol.

## Custody and scientific boundary

All bindings explicitly carry `execution_enabled=false`,
`queue_authorization=false` and `scientific_acceptance=false`. `job_spec`,
`runtime_observation` and `attempt_receipt` are required null values. False flags
must be JSON booleans, and sizes/electron/band counts must be integers; numerical
zero, strings and float coercions cannot grant authority. Duplicate JSON keys,
nonfinite numbers and extra binding fields are rejected.

`qe_version_expected` and `qe_source_commit_expected` name the intended engine,
not an observed binary or process. There is no actual PBEsol runtime evidence in
this increment. Future execution requires distinct reviewed dispatch, exact
binary/resource pins, job/attempt/fence custody, complete output pins and an
independently checked PBEsol result reader. Initialization cannot supply SCF
scientific values, EPC, Tc or candidate ranking evidence.

## Offline verification

Ordinary CI runs synthetic fixtures and rejection tests, with explicit test-only
substitution of installed trust. Those fixtures are not scientific UPFs. CI does
not download source files, call QE or run a calculation. Eight private frozen-real
checks are explicitly skipped unless `SCLIB_PBESOL_FORMAL_BUNDLE` is set to the
retained formal-v2 bundle. Once set, missing/changed files fail rather than skip.

```sh
python -m pytest scripts/tests/test_sclib_pbesol_profile.py -q
SCLIB_PBESOL_FORMAL_BUNDLE=/absolute/private/formal-v2 \
  python -m pytest scripts/tests/test_sclib_pbesol_profile.py -q
```

Tests include source/phase swaps, semantic mutations after fixture pins are
updated, manifest/UPF/geometry relationships, strict authority types and bounded
input. Both stages are rejected by unchanged native-v1 validation, including a
forged valid v1 source envelope wrapped around the exact PBEsol deck. Existing
transport, native-fault, calibration and preparation tests remain in compute CI.
