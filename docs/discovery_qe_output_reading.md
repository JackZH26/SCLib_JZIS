# Local Quantum ESPRESSO output reading

`/discovery/calculations` connects native output to the exact candidate prepared
by the combined-coordinate workspace. It accepts five groups of local files:
the original preparation JSON, exact `.in` deck used, native
`data-file-schema.xml`, complete stdout log, and original UPFs. Files remain in
the browser. No execution, job submission, backend feedback write or catalogue
promotion occurs. The preparation manifest stays unchanged.

## Supported scope

This reader targets **PWSCF 7.5 / QEXSD 25.05.21**, including SCF and fixed-cell
BFGS relaxation, or their separate `nstep=0` initialization inputs. Other engine
versions and schema versions need matching readers. A complete XML document and
one completed stdout envelope are required; interrupted/truncated files are
rejected. A complete file envelope can still report nonconvergence or an
incomplete engine exit. The reader does not validate the entire XSD or attest
execution authenticity.

The UI shows the file-reported state, electronic iteration count, optional ionic
step count, total energy, Fermi energy, valence electrons and maximum atomic
force norm. Initialization yields no physical observations. A zero-step ionic
optimization is explicitly identified. Full source identity, settings, original
scalar tokens, forces, stress tensor, final atom coordinates and file hashes are
available in the expandable JSON and downloadable reading/checksum.

## Reproducible consistency checks

All original bytes are copied before asynchronous work. Manifest and input are
limited to 1 MiB each, XML/stdout to 8 MiB each, and 1–8 UPFs to 8 MiB each.
Strict UTF-8 and bounded file checks precede parsing. XML DTDs/entities,
duplicate required path nodes and non-finite numeric tokens are rejected.

The original preparation is regenerated from its pinned coordinate reference,
construction request, candidate identity, settings and selected UPF bytes.
The full manifest hash must match the reconstructed manifest exactly. Reformatting
the original JSON therefore invalidates this comparison. The selected input hash
must match either the execution or initialization deck in that manifest.

XML checks include run prefix, calculation, restart and step limit, input
positions, atom/species order and masses, UPF filenames, fixed lattice,
functional, spin scope, cutoffs, charge, occupation smearing, k mesh/offsets,
electronic controls and ionic method/thresholds. Extra DFT corrections are
rejected. Output species, lattice, functional, magnetization model and cutoffs
are cross-checked. SCF output positions must match; relaxation positions may
change. Converged electronic reports require a positive iteration count and an
estimated error within the prepared threshold. The final stdout energy and
iteration count must match XML; stdout atom/species/electron counts are checked
even for initialization. Reported BFGS convergence also checks the
optimization step count. Tensor dimensions are checked before deriving norms.

These checks cover the declared method subset, not all unlisted QE defaults.
Local file consistency does not prove that the engine actually executed those
bytes. XML contains UPF filenames, not a cryptographic runtime attestation of the
loaded pseudopotentials. Both `execution_authenticated` and
`pseudopotential_execution_bytes_attested` therefore remain false. The reading
retains full input/XML/stdout/manifest hashes and the original UPF hashes for
subsequent authenticated execution capture and review.

## Units and interpretation

Native XML declares Hartree atomic units. QE input cutoffs, smearing and
electronic/ionic energy thresholds use Ry, so comparisons apply **1 Hartree =
2 Ry**. Stdout total energy is printed in Ry; XML `etot` is Hartree per
computational cell. Forces are Hartree/bohr and stress is Hartree/bohr³.
Coordinates are native Cartesian bohr and derived fractional coordinates in the
fixed candidate lattice. Numeric tokens are retained for the scalar readings;
full source-file hashes preserve traceability for all values.

`etot` includes the selected numerical smearing contribution. It is not formation
energy, energy above hull or measured free energy at 300 K. Electronic or ionic
stopping thresholds do not establish cutoff, k-point, smearing or cell-size
convergence. The pressure default in a fixed-cell engine input is not assigned
as a target physical pressure. No target temperature, ambient-pressure stability,
phonon calculation, Tc, scientific acceptance or ML approval is inferred.

Initialization can terminate with process exit 0 and `JOB DONE` while native XML
reports exit status 255. It remains `initialization_only` when the exact
initialization deck matches, there are zero SCF steps, no convergence and no
final energy. It is never displayed as a successful physical calculation.

## Validation evidence

Native fixtures were captured on 2026-10-05 with an isolated conda-forge QE 7.5
osx-64 runtime under Rosetta. The browser generated the exact inputs. Real
PS Library 1.0.0 PBE PAW files stayed in private QA storage; UPF contents are not
redistributed in the repository or website bundle.

- A three-atom AlB2 proposal derived by replacing the Mg site in COD 1526507 and
  uniformly expanding lattice lengths by 2% completed a bounded SCF run. Neutral,
  spin-unpolarized, 60/480 Ry cutoffs, 4×4×4 k mesh, cold smearing 0.02 Ry,
  electronic threshold 1e-8 Ry. It reported 11 SCF iterations and
  `etot = -31.19334546679567 Hartree/cell`.
- The same proposal with fixed-cell relaxation reported convergence after one
  SCF cycle and zero BFGS steps. The geometry was already within the selected
  stopping threshold; this is not evidence of a displaced relaxed geometry.
- Earlier native initialization outputs cover a charged 24-atom co-substitution
  and a neutral spin-polarized 23-atom vacancy preparation. Both are retained as
  initialization only, with XML exit 255 and no energy.

Runs used one thread, a 120-second input CPU limit for the three-atom cases and
an external 180-second wall timeout. These are integration examples, not a
materials prediction campaign or convergence/stability study. Fixture hashes
are recorded under `frontend/tests/fixtures/qe-output/capture.json`. Unit tests
use captured native reports plus explicitly synthetic header-only UPFs for
file-chain tests. Synthetic headers are never passed off as solver-valid files.

## Primary references

- [QE input reference](https://www.quantum-espresso.org/Doc/INPUT_PW.html): input
  units, initialization, electronic thresholds and fixed-cell BFGS controls.
- [QE data files](https://www.quantum-espresso.org/Doc/pw_user_guide/node9.html):
  native XML location, intermediate steps and initialization behavior.
- [QE 7.5 native output writer](https://github.com/QEF/q-e/blob/qe-7.5/PW/src/pw_restart_new.f90):
  electronic error and energy conversions to Hartree.
- [QE 7.5 XML initialization](https://github.com/QEF/q-e/blob/qe-7.5/Modules/qexsd_init.f90):
  force/stress conversion and native array dimensions.
- [Pinned QEXSD 25.05.21 schema](https://github.com/QEF/qeschemas/blob/02afc7df576658492a9b2f1aa47218a3b153ebd9/PW_CPV/previous_schemas/qes_250521.xsd).

Authenticated execution records, persistent computational feedback, convergence
series, competing-state comparison, DFPT and scientific review remain subsequent
work. This local reader does not change the existing archival source-feedback
contract.
