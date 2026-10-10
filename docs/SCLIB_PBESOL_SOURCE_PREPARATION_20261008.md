# Source-pinned PBEsol preparation

2026-10-08. Owner: Jian Zhou, JZ Institute of Science.

This command prepares source-linked Quantum ESPRESSO inputs for two candidate
compositions and their structure controls. It does not run QE, submit a job,
reserve compute capacity or update Discovery evidence levels, Source Tc or scores.
The preparation manifest explicitly records `execution_supported=false` and
`queue_authorization=false`. The installed native worker does not support this
new preparation schema.

## Fixed source scope

| Composition | Source state | Role | Original QE | Bravais code | Coarse mesh | Cutoffs (Ry) | Valence electrons / bands |
|---|---|---|---|---:|---|---|---|
| TiNb2Mo | agm001228974 | Target | 7.1 | 6 | 6×6×10 | 98 / 392 | 52 / 31 |
| TiNb2Mo | agm002322068 | Same-composition structure control | 7.1 | 2 | 8×8×8 | 98 / 392 | 52 / 31 |
| NbTa3 | agm001828806 | Target | 6.8 | 6 | 6×6×10 | 144 / 576 | 94 / 56 |
| NbTa3 | agm001416090 | Same-composition structure control | 6.8 | 2 | 8×8×8 | 144 / 576 | 94 / 56 |

The small [source profile](data/discovery-batches-20261008/pbesol-source-profile-v1.json)
pins the four original coarse inputs and the exact Ti/Nb/Mo/Ta PBEsol NC scalar
UPFs. Full UPF files are supplied locally, rather than replaced with header-only
fixtures or downloaded by this command. Source data comes from the
[Materials Cloud archive](https://archive.materialscloud.org/records/3kbt5-r3n56);
UPF attribution and notices are retained in the profile and original files.

Both compositions are transition-metal systems. Preparing these inputs does not
establish cross-family generalization, experimental superconductivity, novelty
or room-temperature ambient stability. Valence-electron accounting is separate
from a mobile-carrier-density measurement.

## Command and artifacts

Run from the repository root with Python 3 and the standard library:

```sh
python3 scripts/build_sclib_pbesol_preparation.py \
  --source-root /absolute/source-inputs \
  --upf-root /absolute/full-upfs \
  --output /absolute/new-preparation
```

`source-inputs` contains the four `Formula_agm.../scf_coarse.in` files named in
the profile. `full-upfs` contains `Ti.upf`, `Nb.upf`, `Mo.upf` and `Ta.upf` with
their exact pinned bytes. Supply a new output path with an existing parent
directory; existing preparations are immutable. Unknown or changed inputs are
rejected rather than repaired.

On supported macOS/Linux libc implementations, the command publishes the complete
bundle atomically without replacing an existing directory, including one created
concurrently. Output directories use mode 0700 and files use mode 0600. This is an
atomic visibility guarantee, not a guarantee of durability across power loss.

The bundle preserves original source decks under `source/<state-id>/` and UPFs
under `source/upf/`. For each state it creates separate
`prepared/<state-id>/initialize/` and `prepared/<state-id>/scf/` directories,
each containing `input.in`, complete selected UPFs in `pseudo/`, a
`preparation-manifest.json` and a `delta.json`. Root `bundle-manifest.json` and
`SHA256SUMS` bind the exported files. No `native.json`, JobSpec, execution result
or synthetic result XML is generated.

The distinct manifest version is `sclib-pbesol-source-preparation/1`.
Preparation success means that the source and derived files passed the command's
checks; it does not mean that QE accepted or executed them.

## Recorded method changes

The original source files remain byte-identical. Derived inputs preserve source
`ibrav/celldm`, fractional-coordinate literals, atom/species order, masses,
cutoffs, coarse k meshes, MP smearing, smearing width and electronic settings.
Coordinates outside the primitive cell are retained without wrapping or
idealization. A rounded CIF is not substituted for the SCF geometry.

Each derived input has an explicit delta record for safe relative directories and
prefix, the initialization/SCF `nstep=0/1` distinction, and the new 600-second
engine limit. Source-effective `ecutrho` and `nbnd` are made explicit, together
with a declared neutral, non-spin-polarized, no-SOC probe model. TiNb2Mo target
`electron_maxstep=100` is a new QE 7.5 bound because its source deck omitted the
field; the other three states retain their explicit source value of 200.

The fixed-geometry port removes the historical IONS/CELL blocks and unused ionic
thresholds with line-level records. In the
[pinned QE implementation](https://github.com/QEF/q-e/tree/770a0b2d12928a67048e2f3da8d10d057e52179e),
SCF can retain IONS metadata without enabling BFGS, and it skips CELL parsing.
The port therefore changes some metadata/defaults as documented; it does not
claim that the source performed a relaxation. Electronic convergence still uses
the preserved `conv_thr`.

All prepared decks retain `la2f=false`. Source fine decks use `la2f=true` and are
outside this preparation profile. That option can write an additional
`<prefix>.a2Fsave` file; its name is not evidence of a computed alpha2F or Tc.

## Validation and next integration stage

The isolated compute workflow exercises the preparation checks alongside the
existing transport, native-worker and MgB2 preparation tests. The tests distinguish
synthetic format fixtures from a separately recorded preparation with real source
files and full UPFs. Neither category is a solver run.

Execution still requires a separately versioned native profile and canonical
PBEsol result reader, including general 3×3 cell readback, XC/UPF binding,
bands/electron counts, units, initialization-only versus SCF outcomes, actual
runtime pins and complete result custody. A real initialization must precede an
SCF admission. The resource envelope and queue grant are reviewed separately;
creating this bundle does not increase the current campaign budget.

The proposed QE 7.5 execution is a cross-version reproduction of source QE
6.8/7.1 calculations. Historical compiler, MPI/BLAS and binary identities have
not been recovered. Agreement, if later observed, must retain that limitation;
missing output or a failed comparison must remain visible.
