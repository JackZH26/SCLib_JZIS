# Quantum ESPRESSO input preparation

The selected candidate in `/discovery/structures/combinations` can now be
prepared for `pw.x`. The coordinate batch contract remains unchanged. A separate
`discovery-qe-input/1.0.0` manifest records the chosen electronic setup and exact
input hashes. Preparation does not execute or submit a calculation.

## Reproducible inputs

The preparer copies the batch, settings and original pseudopotential bytes
before asynchronous work, regenerates the complete coordinate batch from the
pinned source and construction request, and rejects any mismatch. A candidate
must belong to this regenerated batch. Atom species, count, fractional positions
and all six lattice parameters come from that exact candidate. The explicit
Cartesian basis uses a along x and b in the xy plane. Deck numbers use 15
significant digits with negligible basis components below 1e-15 set to zero.

Users select actual local UPF 2 XML files, one per resulting element. Files are
read in the browser only. UTF-8 decoding, XML structure, element, PBE functional,
relativistic scope, valence electrons, unique safe filenames and exact species
coverage are checked. DTDs/entities, unsupported functional/SOC/Coulomb models,
extra/missing elements and files exceeding 8 MiB are rejected. At most eight
files can be selected. SHA-256 covers the complete original bytes, not just the
header. The manifest does not include pseudopotential contents or infer provider
identity/licensing from filenames. Header inspection does not validate radial
data or scientific transferability; the native engine must read the files.

Wavefunction/density cutoffs, k mesh and offsets, masses, charge, spin model,
occupation smearing, electronic thresholds, mixing and resource stopping limit
are visible inputs. Wavefunction/density cutoffs, masses and k mesh are initially
blank. Other visible defaults are starting choices requiring convergence tests.
An input below a positive UPF header cutoff suggestion receives a warning;
exceeding that suggestion is not a convergence certificate. UI numeric bounds
are software scope, not universal physical limits.

## Supported calculations and physical scope

- Single-point SCF, or BFGS ionic relaxation with fixed lattice vectors.
- PBE inferred from consistent UPF headers, without an `input_dft` override.
- Scalar-relativistic/nonrelativistic NC, US/USPP or PAW files without SOC.
- Spin-unpolarized, or collinear spin with one starting fraction per element.
  Fractions must be strictly between -1 and 1, avoiding the QE 7.5 ambiguity
  where magnitude >=1 denotes a magnetic moment. At least one nonzero seed is
  required for the spin-polarized option. Seeds are not converged moments.
- A single atomic type per element; same-element AFM sublattices, noncollinear
  spin, SOC, DFT+U, hybrid functionals, constrained magnetization, variable-cell
  pressure relaxation, interfaces, 2D electrostatics and DFPT require other
  method-specific setups and are not claimed by this implementation.

Positive charge removes electrons. The periodic non-neutral cell uses QE's
compensating homogeneous background. The number of valence electrons is checked
against the actual pseudopotentials and atom counts. No target pressure or
physical temperature is assigned. Smearing is numerical occupation broadening.
Unlisted solver options use installed-engine defaults; runtime version and
stdout are required for a reproducible execution record.

## Downloads and execution boundary

Four downloads are available: calculation input, separate initialization input,
JSON manifest, and SHA-256 checksums for all three plus the selected UPFs. Put
the original UPFs under `pseudo/` next to the inputs. Decks use `out/` for solver
output and distinct hash-derived prefixes for initialization and calculation.
The initialization deck uses `nstep=0`. It can check that the engine accepts the
files and print the system summary, but produces no converged SCF or relaxation
result. The CPU limit in the input is not a strict wall-clock watchdog; execution
infrastructure must enforce its own resource limits.

Changing a setting discards prepared downloads. Changing the selected candidate
remounts the entire setup, clearing masses, settings and local files. Delayed
file reads and preparation cannot restore stale results after edits/unmount.
Download failure is recoverable and does not erase prepared inputs.

The manifest's `calculation_executed`, `initialization_checked`,
`numerical_convergence_established`, `relaxed`, `energy_calculated`,
`stability_validated`, `tc_calculated`, scientific acceptance and database-write
flags remain false. External execution evidence belongs in a subsequent record,
not in a retroactively altered preparation manifest. Native initialization of a
QA example does not validate every user-generated deck or physical hypothesis.

## Validation and sources

Component/unit checks cover co-substitution and vacancies, general cell angles,
species ordering and electron counts, byte/deck hashes, source tampering,
unsupported files/settings, charge/spin edge cases, delayed caller mutation,
local file selection, downloads and stale-result cleanup. Synthetic UPF headers
in unit tests are explicitly not solver-valid pseudopotentials.

The [official QE input reference](https://www.quantum-espresso.org/Doc/INPUT_PW.html)
defines units, card/namelist syntax, initialization mode, charge convention and
starting magnetization. The private native acceptance environment uses conda-forge
QE 7.5 for osx-64 under existing Rosetta, isolated from the website runtime and
shell profile. Real PS Library UPFs are obtained from the
[official pseudopotential library](https://pseudopotentials.quantum-espresso.org/legacy_tables/ps-library).
They are QA inputs, not redistributed site assets. Acquisition receipts preserve
URLs, bytes, full SHA-256 and UPF headers.

Native acceptance on 2026-10-05 used the actual browser-downloaded inputs with
original Mg/B/Al/C PS Library 1.0.0 PBE PAW files. The charged co-substitution
case was 24 atoms, four species and 121 valence electrons; the neutral vacancy
case was 23 atoms, three species and 118 electrons, with collinear seeds and
fixed-cell relaxation declared. Both separate initialization inputs finished
with `JOB DONE` and exit 0 on QE 7.5. Independent parsing of the engine XML
matched every species, Cartesian cell vector and fractional position (maximum
fractional discrepancy 4.45e-16). All actual download and UPF hashes matched.
Each run used one thread and an external 180-second wall timeout. These were
initialization checks only; neither executed self-consistency or relaxation.
