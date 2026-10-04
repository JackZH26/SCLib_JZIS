# Native QE output fixtures

These are outputs of SCLib QA runs, not published physical predictions or
approved Materials observations. `capture.json` records exact hashes. Original
preparation manifests contain pseudopotential metadata and hashes, not UPF data.
The original UPFs are not redistributed. Files contain no private absolute paths.

- `scf`: three-atom AlB2 proposal, bounded SCF, 11 electronic iterations.
- `relax`: same proposal, fixed-cell optimization, zero geometry steps.
- `initialization`: charged 24-atom co-substitution, no SCF execution.
- `relax-initialization`: neutral 23-atom vacancy, spin-polarized preparation,
  no SCF/ionic execution.

Raw `.xml` and `.out` files are native captures. `.json` files are original
browser-generated preparation manifests. See `docs/discovery_qe_output_reading.md`
for the settings, scope, unit references and validation method. Component tests
that regenerate a preparation use synthetic UPF headers and change only the XML
prefix accordingly; these synthetic fixtures do not claim native execution.
