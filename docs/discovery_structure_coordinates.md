# Structure references and uniform lattice proposals

`/discovery/structures` adds concrete source coordinates to the host-design workflow.
Materials source references and Discovery both link to the workspace. Researchers
can inspect original fractional sites, compare a uniform lattice change, and
download the captured CIF or an explicitly unrelaxed proposal.

## Source inventory

| Reference | Captured header revision | Listed sites | Displayed cell sites | Source conditions |
| --- | --- | --- | --- | --- |
| CrB2, COD 1510641 | 176435 | B1, Cr1 | 3 | T and P absent |
| MgB2, COD 1526507 | 176429 | Mg1, B1 | 3 | T and P absent |
| FeSe, COD 4002152 | 176432 | Fe1, Se1 | 4 | cell/diffraction T 295 K; P absent |

Hashes, provider URLs, capture times and bibliography come from the existing
`materials-source-references-2026-10-02.json`. Original CIFs now ship under
`frontend/public/research-pilots/structure-cifs/`, with full SHA-256 in the manifest.
The FeSe provider revision URL failed at capture; the current-file URL returned the
recorded header revision. The shipped copy preserves those exact bytes. Original
CIFs, including FeSe diffraction data, are download assets, not client JS imports.

COD data are CC0, with attribution to original authors. Primary references:
[COD](https://www.crystallography.net/cod/),
[Gemmi small structures](https://gemmi.readthedocs.io/en/stable/chemistry.html).

## Scientific interpretation

Raw site tokens retain Fe occupancy `0.996(3)` and Se fractional z `0.26526(14)`.
Occupancy is an average refined value, not an explicit vacancy arrangement.
The diagram expands declared CIF operations in source order, separately for each
listed site. Periodic images within 0.001 Å are merged, retaining the first image
without snapping or averaging. Rounded boron coordinates thus give three displayed
cell sites. Representative and merged operation indices are recorded. The builder's
adjacent-image search applies only to these orthogonal/hexagonal pilot cells, not
general triclinic inputs. No independent symmetry inference or refinement occurs.

Orthographic views follow a, b and c; an isometric view is also available. Markers
have arbitrary size, projections can overlap, and no bond topology is inferred.
Source and preview use the same fixed scale over the supported range.

Uniform linear change ε gives `a′=a(1+ε)`, likewise b/c, with fixed angles, fractional
sites and occupancy; `V′=V(1+ε)^3`. At +2% length, volume increases by 6.1208%.
The ±10% interface bound does not establish a stability interval or pressure.

Proposal JSON includes the full source, transformation, cell and unresolved checks.
Proposal CIF retains original site/occupancy tokens and declared operations; new
lengths use source central values rounded to 12 significant digits. It omits source
measurement temperature/pressure, refinement and diffraction tags. Source lattice
uncertainties remain in JSON; proposal uncertainties are not estimated. Neither
format is a solver input deck, relaxed structure or execution receipt.

No source is promoted to a catalogue sample. Historical MgB2/FeSe held/archive
status is unchanged. No host stability, scientific acceptance, ML permission,
pressure, energy, phonon result or Tc is inferred. The workspace makes no API
writes. Current publication lifecycle/status remains unverified.

## Reproduction and validation

With an isolated Python runtime containing `gemmi==0.7.5`:

```sh
python scripts/build_discovery_structure_references.py
```

This checks and parses only the three local pinned CIFs, with no network calls,
and reproduces the coordinate JSON and SHA-256. Gemmi is an offline artifact-builder
dependency, not a new production dependency. Frontend tests cover source identity,
operation inventory, raw occupancy/coordinates, hexagonal metrics, cubic scaling,
missing conditions, invalid input, base paths, English UI and download errors.
Browser exports are additionally parsed with Gemmi during release acceptance.

Local acceptance: 46 frontend source checks and 2,728 unit tests pass, as does the
production build. Browser checks at 1280, 390 and 320 px found no document overflow;
the source-site table scrolls with the keyboard and shows its focus outline.
Actual FeSe +2% JSON/CIF downloads were inspected, and Gemmi independently parsed
the exported cell and retained site tokens. The captured-source download matched
its SHA-256. An SVG title hydration mismatch was reproduced in a new regression
test and fixed; final production reloads had no console errors. These checks do
not replace upstream CI, publication review or production deployment acceptance.

This implements a D1 coordinate-reference pilot and one D2/D3 geometric operation.
It does not complete the 50-host library, substitutions/vacancy enumeration, ordered
supercells, relaxation, DFPT, magnetic pairing, physical state associations or
scientific execution receipts. The sources are not human-reviewed training gold.
