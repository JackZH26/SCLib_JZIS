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
