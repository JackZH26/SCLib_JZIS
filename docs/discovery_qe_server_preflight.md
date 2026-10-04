# Native QE preflight in the API runtime

The local Discovery output reader now has an independent Python counterpart:
`services.qe_pw_import.preflight_pw`. This is the first server-side step toward
persistent computational feedback. It reads original bytes, without accepting
the browser's calculated values or treating a preparation JSON as evidence that
a calculation ran. There is no HTTP endpoint, SQL write or new migration in this
change. The existing matdyn import and archival feedback contracts are unchanged.

## Supported reading

The adapter consumes the explicit input subset emitted by Discovery: periodic
PBE, 1–96 atoms, 1–8 elements, collinear or unpolarized spin, automatic k-point
mesh, smearing, and either SCF or fixed-cell BFGS ionic relaxation. The separate
`nstep=0` initialization deck is recognized. PWSCF must report version 7.5 and
QEXSD 25.05.21 in Hartree atomic units. Other namelist keys, cards, coordinate
units, methods and versions need a corresponding adapter. Additional input
options are rejected instead of silently discarded.

Original input assignments, composition, species masses, geometry, mesh,
cutoffs, charge and electronic/ionic stopping settings are parsed directly.
XML input/output and stdout must be consistent with that deck. The supplied
UPF files must match its exact filename inventory, elements, supported PBE
headers and resulting valence-electron count. Every original file is hashed.
Filenames are labels; the adapter never opens a path named inside an input or
UPF file, fetches a URL, invokes QE, or executes source comments.

Native total energy, Fermi energy, electron count, force/stress arrays and final
coordinates retain their native units. Scalar raw numeric tokens and XML paths
are retained alongside the complete file hash. The original file is needed for
replay; the JSON report is not a substitute for it. Input and XML energy settings
are compared using 1 Hartree = 2 Ry. No formation/hull energy is derived from
total energy. Smearing does not supply a physical temperature, and the fixed-cell
input does not assign an ambient-pressure target.

Initialization supplies no physical observations, including when the console
says `JOB DONE` but the native XML exit status is 255. Unconverged and incomplete
runs keep their explicit provisional status. A relaxation reporting zero ionic
steps must retain the original geometry. Electronic stopping tolerance is not
cutoff, k-point, smearing or multi-state convergence.

This performs bounded XML parsing and checks the supported method subset, not
full XSD validation, UPF radial-data validation or authentication of the runtime
that generated the files. It does not establish that those UPF bytes were loaded
by the engine. Candidate labels in comments do not establish source-coordinate,
catalogue-material, saved-design or physical-state associations. All execution
authentication, scientific acceptance, ML approval and public-release flags
remain false.

## Local use

Run with the project's locked Python runtime:

```bash
python scripts/qe_pw_preflight.py \
  --input run.in \
  --xml run.save/data-file-schema.xml \
  --stdout pw.out \
  --upf pseudo/Al.pbe-n-kjpaw_psl.1.0.0.UPF \
  --upf pseudo/B.pbe-n-kjpaw_psl.1.0.0.UPF \
  --output private-reading.json
```

The command reads explicit regular files, refuses symlinks and files that change
during capture, and creates an owner-only report atomically without overwriting
an existing path. Standard output contains the reading status and SHA-256 of the
exact report bytes. It never submits a job, uploads a file or changes a database.
The input is bounded to 1 MiB, XML/stdout to 8 MiB each, and each of up to eight
UPFs to 8 MiB. XML depth is at most 64 and each XML document has at most 200,000
elements. These are parser bounds, not an HTTP upload budget or an approved
server concurrency policy.

## Evidence and remaining integration

The four original input decks under `api/tests/fixtures/qe-pw` are byte-for-byte
copies of the earlier local SCF, relaxation and two initialization captures.
Their hashes are checked against the already frozen preparation manifests in
`frontend/tests/fixtures/qe-output`. XML/stdout stay in the original fixture
location. Existing 2³, 4³ and 6³ mesh captures provide independent comparison
against their frozen browser readings.

Repository tests use explicitly synthetic, header-only UPFs for parser tests;
they are never described as solver-valid pseudopotentials. Private replay uses
the original manifest-pinned PS Library files. This replay checks parser
consistency and file integrity; it does not repeat a solver execution or validate
material stability or superconductivity.

Persistent feedback still needs an owner-private file inventory, exact saved
design/action association, preview/commit and uncertain-outcome recovery,
authenticated retrieval, current-access checks, and browser replay from saved
bytes. A future service must call this parser itself and compare its findings
with the browser's reading. It must separately verify the source-coordinate
construction and distinguish user-declared execution from authenticated runtime
receipts. Formal scientific field review remains a separate operation.

## Primary format references

- [PWSCF 7.5 input reference](https://www.quantum-espresso.org/Doc/INPUT_PW.html)
  defines the input namelists, energy units and zero-step initialization.
- [Pinned QEXSD 25.05.21 schema](https://github.com/QEF/qeschemas/blob/02afc7df576658492a9b2f1aa47218a3b153ebd9/PW_CPV/previous_schemas/qes_250521.xsd)
  describes the native XML structure. This adapter does not execute that schema.
