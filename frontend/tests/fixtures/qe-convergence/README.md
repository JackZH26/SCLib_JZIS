# Native numerical-refinement fixtures

Three actual PWSCF 7.5 executions on 2026-10-05 vary only the automatic mesh:
2×2×2, 4×4×4 and 6×6×6, with shifts 0 0 0. Inputs were produced by the existing
SCLib generator using the original source-linked three-atom AlB₂ proposal:
Mg at S1 of the MgB₂ reference replaced by Al, with +2% isotropic lattice scaling.
This constructed geometry has not been validated as a stable material.

All runs use identical PBE PAW pseudopotentials, 60/480 Ry cutoffs,
Marzari–Vanderbilt smearing 0.02 Ry, 1e-8 Ry SCF threshold, neutral charge and
spin-unpolarized fixed-geometry SCF. Every prepared input, manifest, stdout,
native XML, parsed reading and local execution receipt is retained unchanged.
`capture.json` pins their exact bytes. The full UPF files remain in the private
execution audit; their identities are preserved in the manifests. The fixture
does not redistribute those files or substitute header-only UPFs for execution.

The engine is the existing isolated conda-forge osx-64 QE 7.5 runtime under
Rosetta on macOS. Each run is bounded to one thread, 120 s input CPU limit and
180 s external wall timeout. Execution receipts record the binary/input hashes,
actual elapsed times and zero process exits. All three native reports reached
electronic convergence, but the sampled energy range is
0.016918366228363624 Hartree/atom, exceeding the deliberately requested
1e-4 Hartree/atom comparison tolerance. That tolerance is an example research
request, not a universal physical acceptance limit.

These are parser/comparison acceptance inputs, not authenticated cloud jobs,
published predictions, proof of cutoff or mesh convergence, formation energies,
stable-host certification or superconductivity calculations. Tests that alter
their settings are explicitly synthetic control tests and do not claim new runs.
