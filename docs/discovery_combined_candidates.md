# Combined atomic-site and lattice proposals

`/discovery/structures/combinations` extends the existing single-site workspace
with a concrete co-substitution/vacancy/lattice-change product. The single-site
contract stays unchanged. Both use the same source-pinned parent supercell IDs.

## Input and enumeration

Researchers select the captured CrB2 or MgB2 coordinates, integer repeats, one
to three distinct atomic sites, explicit replacement symbols and optional
vacancy/unchanged choices at each site. FeSe's partial occupancy still requires
an explicit disorder model and cannot silently become an ordered model. Source
operations, the 0.001 Å source expansion tolerance and nominal atom positions
are inherited from the documented coordinate reader.

One option is selected at each listed site. Up to eight distinct uniform linear
changes form an additional axis. Percentages accept at most six decimal places
between −10 and +10. Equivalent decimal spellings and repeated element symbols
deduplicate exactly; there is no fuzzy strain tolerance. Canonical order follows
the original atom inventory, then sorted choices and percentages. A duplicate
target ID is rejected before generation, rather than applying two incompatible
changes to the same atom. Same-element replacement requires choosing the explicit
unchanged option instead.

The interface shows raw combinations, distinct combinations and generated
candidates before preparation. At most 64 distinct combinations and 96 original
sites are supported. Excess input is rejected, never silently truncated. A
zero-change/zero-strain baseline and any atom-free crystal are explicitly
excluded with their complete choices and reasons retained in JSON. No atom is
removed for any other reason. Distinct arrangements are not claimed to be
inequivalent under symmetry.

Example: in MgB2 2×2×2, choose Mg→Al/original, B→C/vacancy/original and linear
changes −2%, 0%, +2%. This gives 18 distinct combinations, one unchanged baseline
and 17 candidates. Mg→Al plus B→C yields Mg7AlB15C; Mg→Al plus a B vacancy yields
Mg7AlB15. Two changed sites are 2/24 original total sites. Original-species
denominators remain independent: 1/8 Mg and 1/16 B. Two Mg substitutions instead
mean 2/8 original Mg sites, not repeated denominators after the first edit.

## Geometry and provenance

Substitutions/removals act on the original supercell, then every lattice vector
is multiplied by `1 + percent / 100`. Angles and fractional positions stay fixed.
Volume changes by the cube of that factor; +2% length means +6.1208% geometric
volume. This does not assign a pressure, strain energy or stable strain interval.

Every candidate contains the resulting full atom inventory, actual changes with
original target identity, cell, nominal composition, denominator-aware change
fractions, volume ratio, P1 CIF and its SHA-256. CIF numeric tokens use 14
significant digits. Source uncertainty tokens stay in the original reference;
proposal uncertainties are not estimated. Candidate IDs hash the contract,
parent and emitted CIF hash; choice/row order does not change them. The full
batch also retains original user input, baseline, source metadata and excluded
combinations, with a checksum of its exact UTF-8 JSON bytes. Pagination shows
eight candidates at a time but the batch download contains them all.

Caller input is copied and expanded before the first asynchronous hash. Editing
any proposal input or leaving the component discards delayed preparation.
Preparation/download failures have separate recovery states; failed downloads
do not discard generated candidates. Table overflow is confined to keyboard
focusable regions.

## Scientific limits and acceptance

The selected candidate also exposes a separate
[Quantum ESPRESSO preparation workflow](discovery_qe_input_preparation.md).
It requires actual UPF files and explicit electronic settings, and exports
independent input/initialization decks and a provenance manifest. It does not
change the coordinate batch's unrelaxed status or claim executed results.

Outputs are unrelaxed ordered coordinate proposals. Charge, magnetic state,
target temperature and pressure remain unresolved. Concentrations refer to
nominal changes in the original supercell, not measured doping or carrier
density. No electronic, formation-energy, phonon, pairing or coherence result
is generated. Numerical/supercell convergence, disorder, relaxation and scientific
validation remain necessary. No catalogue, training or database write occurs.

Meaningful regression coverage checks actual cross-product inventories, mixed
substitutions/vacancies, species denominators, unchanged atoms, volume scaling,
parent/candidate identity, caller mutation during a delayed hash, invalid and
excessive requests, complete-cell removal, server hydration, pagination, edit
invalidation and download failure. Browser acceptance must additionally inspect
downloaded JSON/CIF, including independent CIF parsing. Local success does not
substitute for required PR CI, normal deployment or scientific validation.

Local acceptance on 2026-10-05 passed all 46 frontend source checks, 2,753
unit/component tests across 125 files and the production build. Actual browser
checks generated the 17-candidate MgB2 example, inspected three result pages,
downloaded the complete batch from its one-row final page, and downloaded a
selected +2% co-substitution CIF and JSON checksum. The 239,178-byte JSON has
SHA-256 `6e52be02d9dd41ae58847a51a5e3f0ed38d6149ebdd4624dbba8c87f7ebb838c`.

Gemmi 0.7.5 independently parsed every one of the 17 CIFs in that actual download.
The full combinatorial inventory, atom counts/elements/fractional positions,
crystal volumes, original-species denominators, P1 operations and file hashes
matched. The separately downloaded CIF exactly matched the selected manifest
entry. Desktop controls were consistently 44 px high. At 1,280, 390 and 320 px
there was no outer horizontal overflow; keyboard table scrolling and expanded
coordinate/provenance content remained contained. Switching to FeSe cleared
the previous candidates and disabled generation. No browser console errors
were observed. This is production-preview acceptance, not a deployed release.
