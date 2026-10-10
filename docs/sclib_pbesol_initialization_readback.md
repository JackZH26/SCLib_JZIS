# PBEsol initialization-only readback

This inert Python reader checks a bounded initialization capture against the
existing source-input binding. It does not dispatch work, validate result custody,
accept a runtime, or calculate superconducting properties.

`read_initialization(binding_bytes, files, *, xml, stdout, stderr,
process_exit_code)` first snapshots the bounded exact input map of immutable bytes,
then revalidates the actual source/deck/UPF bytes using the installed PBEsol binding
validator. Subsequent parsing uses only that snapshot. A caller-supplied binding
object or expected-number dictionary is not an authority shortcut.

The supported domain is the four fixed source states, initialize stage, PBESOL,
PWSCF 7.5 and QEXSD 25.05.21. It checks source geometry with a full 3×3 inverse,
ordered atoms/species, cutoffs, bands, charge, spin, mesh and fixed cell/ion
settings. Ry→Ha conversion occurs once. The electron count is labelled an input
UPF expectation; physical initialization outputs remain null.

The source `only_init` jump bypasses ten output families: total_energy,
band_structure, forces, stress, electric_field, fcp_force, fcp_tot_charge, rism3d,
rismlaue and two_chem. Their presence, even nested, rejects initialization.
Atomic structure must contain exactly one Cartesian atomic_positions representation;
crystal/wyckoff alternatives cannot coexist or replace it in this profile. Numeric
input/output subtrees cannot override the root Hartree unit convention through
unqualified or namespaced unit attributes. This is a supported-domain check,
not a claim of full XSD validation or a conversion of unexpected units.

XML status 0/255 remains distinct from the supplied raw OS exit. OS exit 255 retains a
solver_failure classification and requires review even when XML is semantically
initialization_only. Custody is false, capture/current-attempt/verified transport
outcome are unknown, readiness is false and scientific acceptance is false. SCF
reading, runtime admission, process execution and returned-result custody remain
separate work. Missing or malformed XML is not repaired or replaced.

## Tests and provenance

Default CI uses normal Python fixture code and the existing PR #160 test-only
synthetic source/UPF/preparation setup. It needs no private input paths and ships
no UPF archive, large XML collection or full schema dump. The production validator
has no test-trust override API; monkeypatching exists only in the fixture.

Four optional actual-input checks are selected by `SCLIB_PBESOL_FORMAL_BUNDLE`.
Unset means an explicit skip. An empty, missing or corrupt supplied path fails;
it never falls back to synthetic input. Each check verifies the pinned bundle and
preparation manifest before following its paths, then calls the same input
validator. Their output XML/stdout remains synthetic, so passing them establishes
actual input binding coverage, not a real PBEsol run.

Run `python -m pytest tests/test_sclib_pbesol_init_reader.py -q` in the configured
compute test environment. The dedicated compute workflow includes this suite and
its helper in lint/path selection. Source/schema and historical prototype hashes
are recorded in `docs/data/discovery-batches-20261008/pbesol-init-reader-provenance-v1.json`.
Official mappings use QE commit 770a0b2d12928a67048e2f3da8d10d057e52179e and the
separately archived QEXSD commit 02afc7df576658492a9b2f1aa47218a3b153ebd9. Neither
source pin proves the identity of a running binary.
