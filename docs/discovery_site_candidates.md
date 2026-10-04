# Explicit site modification candidates

`/discovery/structures/candidates` extends the captured-coordinate workspace with
an ordered supercell and an explicit single-site modification. Researchers choose
the source, three integer repeats, one enumerated atom and replacement elements
or a vacancy, then inspect and download each unrelaxed coordinate model.

## Construction and scientific scope

Only the pinned CrB2 (COD 1510641) and MgB2 (COD 1526507) references currently have
all original occupancy tokens exactly `1`. FeSe remains inspectable as a source,
but its `0.996(3)` occupancy blocks ordered candidate generation: an explicit
disorder model is needed. No occupancy is rounded to create an atomistic model.

For repeats `(na, nb, nc)`, the lattice vectors become `(na*a, nb*b, nc*c)` and
each source fractional position `f` is translated by cell index `t` and mapped to
`(f+t)/n`. Source angles and retained symmetry-expanded positions remain unchanged.
The inherited expansion uses the documented 0.001 Å periodic merge tolerance;
coordinates are not idealized. Repeats range from 1 to 4, with at most 96 original
sites. These are interface bounds, not a claim of defect convergence.

One substitution changes the selected atom's element; one vacancy removes it.
All other sites and the cell remain fixed. Exact replacement symbols are
deduplicated in input order; a same-element no-op is rejected. A batch holds at
most eight proposals, optionally including one vacancy. Distinct choices of atom
are not claimed to be symmetry-inequivalent. No energy ranking is produced.

Nominal concentration has two explicit denominators: the original sites of the
selected chemical species, and all original sites in the supercell. For MgB2
2×2×2, the baseline is Mg8B16: replacing one Mg with Al gives Mg7AlB16 and a
vacancy gives Mg7B16. Both change 1/8 Mg sites (12.5%) and 1/24 original total
sites (4.1667%). Neither ratio is a measured concentration or carrier density.

## Output and lineage

The CIF enumerates every resulting atom with occupancy one and only the identity
operation in P1. It does not assign the source space group to the modified model.
Lengths and fractional coordinates are serialized to 14 significant digits.
Source measurement temperature/pressure and uncertainty are not assigned to the
proposal; the original reference and raw tokens remain in the batch JSON.

Parent IDs hash the source CIF hash, repeats, baseline cell and sites. Candidate
IDs additionally hash the target, operation and emitted CIF hash. JSON contains
both coordinate sets, original site label, source expansion index, cell
translation, transformation, nominal concentrations and complete source metadata.
The JSON download has a SHA-256 sidecar; every candidate includes its CIF hash.
IDs are deterministic for this version and input. Content identity does not
establish scientific validity or uniqueness under crystallographic symmetry.

Charge, magnetic state, intended temperature and pressure are unresolved. The
workspace does not run relaxation, electronic-structure, energy, phonon, pairing
or coherence calculations. Researchers must select physical/calculation settings,
check size and numerical convergence, and validate stability before interpreting
any superconducting quantities. No API, catalogue, training or production-data
write occurs. Source references are not certified stable hosts or physical
associations with catalogue measurements. Existing held/archive status remains.

## Interaction and verification

Any source, cell, target or operation edit removes old results. Sequence checks
discard preparation that finishes after an edit or unmount. Invalid input,
partial occupancy, oversized cells, hashing failure and download failure have
explicit English states. A failure to download does not discard generated data.
Tables provide keyboard-focusable horizontal scrolling on small screens.

Regression tests verify translated Cartesian coordinates in the hexagonal
metric, exact site changes, both concentration denominators, immutable baseline
and sources, deterministic hashes, P1 serialization, invalid-input boundaries,
server hydration, stale asynchronous work and failed downloads. Actual browser
downloads are separately parsed with Gemmi during local acceptance. Local checks
do not substitute for the stacked PR's required CI or deployment acceptance.

Local acceptance passed 46 source checks, 2,737 unit tests and the production
build. The browser generated Al/Ca substitutions and one Mg vacancy in MgB2
2×2×2; actual JSON/sidecar and Al/vacancy CIF downloads matched their hashes.
Gemmi 0.7.5 parsed all three CIF strings from the downloaded batch, independently
confirming atom inventories, fractional coordinates, cell volume and P1 identity
operations. The FeSe selection removed old results and disabled generation.
Final 1280/320 px layouts had no outer horizontal overflow, keyboard inspection
worked, input bottoms aligned and the production page emitted no console errors.

This advances the methodology's host-plus-modification step. A 50-host library,
disorder enumeration, symmetry-reduced candidates, solver-ready input decks,
executed calculations and validated superconducting-state results remain work.
