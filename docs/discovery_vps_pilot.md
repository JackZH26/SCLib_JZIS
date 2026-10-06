# Bounded Mg7AlB16 Quantum ESPRESSO pilot

This recipe prepares actual source-linked inputs for a coordinator-operated pilot.
The preparation tool runs no solver, remote command or job scheduler. UPFs and
the resulting bundle stay in the private audit directory and are not website assets.

## Fixed question and inputs

For the retained Mg7AlB16 coordinate states with uniform linear lattice changes
−2%, 0% and +2%, measure **finite k-mesh sensitivity of fixed-geometry SCF energy**.
Each state has 24 atoms and receives meshes 2×2×2, 4×4×4 and 6×6×6, zero shifts:
nine SCF inputs in total. This is a numerical pilot, not a ranking of superconducting
potential or a result of the high-bandwidth/carrier-density strategies.

All nine use the real PS Library 1.0.0 PBE PAW Mg/Al/B UPFs, charge 0, nspin 1,
60/480 Ry wavefunction/charge-density cutoffs, MV smearing 0.02 Ry, conv_thr=1e-10 Ry
and max_seconds=300. Masses are Mg 24.305, Al 26.9815385 and B 10.81 u.
Electronic maxstep=100 and mixing_beta=0.3 are explicit pilot settings. The chosen
PAW valences total 121 electrons; spin-unpolarized fractional occupations are a
declared model, not an established physical magnetic ground state. Original
catalogue conditions stay null. Smearing does not assign temperature, and lattice
scaling does not assign pressure. Fixed-cell SCF does not relax the coordinates.

## Predeclared comparison

Use the existing native result reader and `discovery-qe-sampled-convergence/1.0.0`
comparator separately for each state. The tolerance is **1e-4 Hartree/atom**.
All three runs must report electronic SCF convergence with the same actual engine,
UPFs and other settings. Evaluate `(max(E) - min(E)) / 24` over the three meshes;
the maximum native SCF error per atom must also be strictly below the tolerance.
The comparator's observed finite-window result is retained as such. It does not
establish an infinite-mesh, cutoff or zero-smearing limit. A failed/missing run
leaves its study incomplete; no replacement zero or success receipt is created.
No absolute-energy ranking across composition or geometry is produced by this pilot.

## Prepare with existing real files

```sh
python scripts/prepare_discovery_qe_pilot.py \
  --mg-upf /absolute/path/Mg.pbe-spnl-kjpaw_psl.1.0.0.UPF \
  --al-upf /absolute/path/Al.pbe-n-kjpaw_psl.1.0.0.UPF \
  --b-upf /absolute/path/B.pbe-n-kjpaw_psl.1.0.0.UPF \
  --source-receipt /absolute/path/actual-capture-receipt.json \
  --output /absolute/path/new-private-bundle
```

The helper invokes an opt-in Vitest/jsdom preparation harness, reusing the actual
`prepareResearchModel` and `prepareQeInput` implementations. Ordinary CI skips
this preparation test when its explicit input variable is absent. It requires
the captured real UPF byte hashes and an unused output directory, validates all
nine decks, copies exact recipe/CIF/UPF bytes with hashes and emits a private
`pilot-plan.json`, file manifest and `SHA256SUMS`. No synthetic UPF can satisfy the
capture hashes. Every generated manifest remains `prepared_input`, with execution
and convergence flags false. Each job directory includes its own `pseudo/` and
separate execution and nstep=0 initialization decks.

## Execution and return boundary

The coordinator's assigned envelope is at most 4 CPU cores, 12 GiB memory and
3,600 seconds total wall time, with sequential jobs and a 450-second external
per-job ceiling. Initializations and overhead count toward the total. The engine's
300-second setting is not a substitute for the external watchdog. These assigned
pilot bounds are not an RPS campaign budget or evidence that execution occurred.

The operator must retain engine version, exact command and resource enforcement,
per-job start/finish/exit status, actual input/UPF hashes, stdout, native XML and
their hashes. Original preparation files remain immutable. Subsequent native-file
readings and comparison reports are separate artifacts bound to the same state.
Success would establish only the actual reported SCF/finite-mesh observations.
No stability, Tc, ambient-pressure, room-temperature, ML or formal scientific
publication claim follows from this pilot.

## Actual pilot captured on 2026-10-06

The authorized isolated CPU run used PWSCF 7.5. The frozen input-plan SHA-256 is
`1ea4ab79c7433d966f4ff393c4e8deda9adea6cc2cf7bcd42b6c65c0559da855`.
All nine initialization files were read separately as initialization-only. All
nine executions reported electronic SCF convergence in their native XML/stdout;
there were no execution timeouts. The successful capture took **1187.682 seconds**.

| Lattice-length change | Meshes | Energy range (Hartree/atom) | Largest reported SCF error (Hartree/atom) | Decision |
|---|---|---|---|---|
| −2% | 2³, 4³, 6³ | 0.0006334572564270502 | 2.0457753286758532e-12 | Redirect; refine method |
| 0% | 2³, 4³, 6³ | 0.0007494048434040224 | 4.3212316030610455e-13 | Redirect; refine method |
| +2% | 2³, 4³, 6³ | 0.0008587643862464726 | 6.790550139396558e-13 | Redirect; refine method |

Each range exceeds the predeclared `1e-4 Hartree/atom` tolerance. Electronic
stopping precision and mesh sensitivity answer different questions: the native
SCF convergence does not resolve these sampled energy windows. The linked
follow-up cases retain all six physical axes as unknown. They require an explicit
revised sampling action before interpreting physical differences. No ordering
of superconducting potential follows from the three ranges.

The public asset set contains **17 JSON files**:

- One compact summary, `discovery-qe-pilot-2026-10-06.json`, and its
  `discovery-qe-pilot-2026-10-06.pins.json` digest record.
- Three exact structured mesh-comparison exports, one per state:
  `mesh-comparison-minus02.json`, `mesh-comparison-zero.json` and
  `mesh-comparison-plus02.json`. Each retains its three structured native-file
  readings, input/model/file hashes and the sampled-window assessment. Its
  SHA-256 matches the summary's `comparison_sha256`.
- Twelve exact research-case exports: prepared action, returned result, recorded
  decision and linked child case for each of the three states. Every case was
  imported, exported byte-for-byte, and checked against its catalogue coordinate
  association. The summary supplies their download URLs and exact SHA-256 values.

The summary and pins are under `/research-pilots/`; the fifteen comparison and
case downloads are under `/research-pilots/discovery-qe-pilot-20261006/`.
Original stdout/XML text, UPF contents, execution receipts and private machine
metadata remain separate from these structured website assets.

The compact summary retains `authority.public_release: false` as a
**formal scientific publication authority** field. It does not describe whether
the JSON is publicly accessible. File availability and engineering consistency
checks do not grant scientific approval or an RPS release; those authorities
remain false, with RPS score and rank null. The reader-summary SHA-256 is
`e54e49e4cdcc7057cb0da1991fcfb4773e25c1bca54fcdb2d658aa9db2f1feeb`.

The first actual attempt failed at MPI account initialization before PWSCF
started. Its nine failed initialization outputs and receipts remain retained;
the successful retry is a separate capture with the same frozen scientific
inputs. The successful runner SHA-256 is
`527a9b3652281f4ac4c24f2a37cd94485c2d685123048a4f0f779e66c4cf07bc`.
That historical runner applied a 450-second watchdog to each phase; its actual
jobs nevertheless took 43.332–249.521 seconds including both phases. The later
runner revision has SHA-256
`c94de42a7c81cb4a6e3ea957cbc01360041342c0c84b617df63db7bf8d9b46de`.
It fixes the contract by sharing one 450-second deadline across initialization,
execution and termination, within the total-work deadline. The published pilot
results were produced by the historical `527a9b…` runner; they were not rerun
with `c94de4…`, and the later deadline fix is not applied retrospectively to
their execution receipts.

Actual startup cgroup reads confirmed the 4-core CPU quota and 12 GiB memory
limit. The post-finish systemd query had no surviving invocation identity and
provides no peak-memory or no-OOM attestation. Runtime-preparation and runtime
receipts describe micromamba and PWSCF respectively; their different binary
hashes are not evidence of a changed PWSCF run.
