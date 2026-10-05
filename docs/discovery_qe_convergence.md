# Local numerical-refinement comparison

`/discovery/calculations` now lets a researcher add each successfully read native
SCF run to a local study. The workflow connects a source-linked candidate to an
observable sensitivity check before further calculations. It does not execute
jobs, persist user files, write Materials records or change scientific approval.

## Compared quantities and conditions

Choose 3–16 readings and enter an explicit tolerance in Hartree/atom. The UI
compares one parameter: wavefunction cutoff, charge-density cutoff, k mesh or
smearing width. Each cutoff is varied separately with the other fixed. Meshes
are ordered by refinement with no decreasing direction; shifts remain fixed.
Smearing widths are ordered decreasingly. No coordinate, volume, composition,
mass, charge, pseudopotential, engine, SCF-control or other setting may change.

Only electronically converged spin-unpolarized fixed-geometry SCF readings are
accepted. Relaxation can change geometry, and the current reader lacks enough
magnetic-state information to compare spin-polarized branches. The existing
reader still reads these other runs individually; this study does not certify
their comparability. Current file changes do not erase readings the researcher
explicitly added. Editing the study invalidates previous results; leaving the
page clears the in-memory queue. Late asynchronous work cannot restore a cleared
comparison. No localStorage or network request is used.

For each run, the table reports its native cell energy, energy difference from
the last supplied refinement point divided by the common atom count, and native
SCF error divided by that count. The final three points define a sampled window:
`(max(E) - min(E)) / N`. Its range is compared with the user tolerance. When the
reported SCF error in that window reaches or exceeds the tolerance, the result
requests tighter electronic convergence first. The SCF error remains an engine
estimate, not a rigorous error bound. Duplicate parameter values are rejected,
not averaged or counted as independent refinement points.

A sampled window within tolerance is explicitly a finite-data observation, not
a proof of the infinite-basis, dense-mesh or zero-smearing limit. Forces and
stress are not assessed by this energy test. Mesh and smearing require joint
examination before wider conclusions. See the official QE
[metal convergence exercise](https://www.quantum-espresso.org/wp-content/uploads/2022/03/exercise2_instructions.pdf)
and [input reference](https://www.quantum-espresso.org/Doc/INPUT_PW.html).
Numerical occupation broadening is not an assigned experimental temperature.

## Provenance and export

The queue accepts readings produced by the native-file reader, not imported
free-form result JSON. That reader reconstructs the source candidate and exact
input preparation from the selected original UPF bytes, manifest and native
files. Comparison copies inputs before asynchronous work and verifies each
reading's exact JSON and checksum. These checks establish file consistency;
execution authenticity remains false.

The independent `discovery-qe-sampled-convergence/1.0.0` export contains all
original reading reports and their hashes, candidate/source/UPF pins, sorted
points, reference point, user tolerance, finite-window calculation and explicit
scientific scope. Its sidecar hashes the actual JSON file bytes. No frozen input
or reading version was redefined.

## Actual native validation

Three bounded local PWSCF 7.5 runs used the same three-atom AlB₂ coordinate
proposal at 2³, 4³ and 6³ meshes. All reached electronic convergence, yet their
sampled range was 0.016918366228363624 Hartree/atom. At the example user tolerance
of 1e-4 Hartree/atom the comparator correctly requests further refinement. This
does not validate the proposed phase or predict superconductivity.

Exact inputs, native output and execution-receipt fixtures are retained under
`frontend/tests/fixtures/qe-convergence`. Tests re-read the native XML/stdout,
verify byte hashes, check atom normalization, order independence, mismatched
physical settings, duplicates, anisotropic mesh ordering, unsupported run kinds,
stale bytes, delayed-result clearing and UI/export behavior. Synthetic changed
settings test controls only. The original UPFs are retained privately, not
redistributed in these fixtures.

Local acceptance passed 46 source checks, 2,829 unit/component checks and a
production build. Real browser file selection replayed all three runs using
their full original UPFs. Desktop, 390 px and 320 px layouts were checked; the
320 px document stays 320 px wide while the reading table scrolls locally by
keyboard. Changing the comparison axis removes the stale result and rejects
incompatible settings. The actual 64,192-byte downloaded study exactly matches
an independent native-file reconstruction and its SHA-256 sidecar. These are
local acceptance results; current-head CI and production release remain separate.

## Joint mesh–smearing study

The same reading queue now offers **Mesh and smearing** mode. It lays out the
cross-product of parameter values actually supplied, keeping uncalculated cells
explicitly empty. Duplicate combinations are rejected. All remaining settings,
including smearing method, offsets, cutoffs, charge, masses, SCF controls, engine,
source candidate and UPF bytes must agree. Anisotropic meshes must form a
componentwise refinement sequence.

A joint assessment requires a complete observed grid with at least three meshes
and three widths, within the existing 16-reading limit. The finite window uses
the three finest supplied meshes and three smallest widths. Its energy envelope
is `(max(etot) - min(etot)) / N` across those nine runs. The largest reported SCF
error in that window must be below the user's tolerance before the envelope is
compared. Separate row ranges and the smallest-three-width range at the finest
mesh help distinguish mesh sensitivity from width sensitivity. Missing cells or
insufficient axis coverage withhold the joint statistic, including when a missing
cell lies outside the final window. No value is interpolated or replaced by zero.

The quantity is native QE `etot` with its selected smearing contribution. No
entropy correction, zero-width extrapolation, physical-temperature assignment,
phase-stability assessment or Tc prediction is made. A sampled window within
tolerance still does not establish the numerical limit. The original one-axis
export remains unchanged; joint studies use independent
`discovery-qe-mesh-smearing-study/1.0.0` JSON with all original reading reports,
missing combinations, units, checksums and the exact finite-window calculation.

Native acceptance added six bounded, one-thread QE 7.5 runs to the earlier three:
2³/4³/6³ meshes at 0.04/0.02/0.01 Ry cold smearing, with every other prepared
setting and the three-atom AlB₂ proposal fixed. All nine SCF cycles converged.
The width range at the finest mesh is approximately 9.58717e-5 Hartree/atom,
whereas the joint envelope is 0.016965894419036214 Hartree/atom, exceeding the
example 1e-4 tolerance. This demonstrates why one small width range cannot stand
in for a joint assessment; it is workflow validation, not a material prediction.
New native inputs, manifests, XML, stdout, readings and bounded execution records
are retained in `frontend/tests/fixtures/qe-joint-refinement`; original UPFs stay
private. Regression tests re-read the native files and verify their hashes.

Actual browser selection read all nine sets of native files. The eight-run view
correctly withheld the joint assessment; adding the missing run produced the full
grid. The downloaded 172,498-byte study matched an independent native-file
reconstruction and its sidecar SHA-256:
`f9ccc21eadd4cea09394df6b483bc840b1d7867d05ab3e13c8f420ed7ba4e74d`.
