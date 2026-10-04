# Structure references and uniform lattice proposals

`/discovery/structures` adds concrete source coordinates to the host-design workflow.
Materials source references and Discovery both link to the workspace. Researchers
can inspect original fractional sites, compare a uniform lattice change, and
download the captured CIF or an explicitly unrelaxed proposal.

## Initial source inventory (2026-10-04)

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
Later stages add site substitutions, vacancies, ordered supercells, combined
changes and Quantum ESPRESSO input/output workflows; see the implementation plan.
This initial stage alone does not complete the host library, physical calculations,
state associations or authenticated scientific execution receipts. The sources are not human-reviewed training gold.


## Expanded host coordinate library (2026-10-05)

The workspace now contains **24 captured structures**, preserving the original
three reference objects exactly. The 21 additions cover all 22 formulas explicitly
named in the methodology (MgB2 was already present). The document refers to 50 hosts
but does not supply a complete 50-item inventory. This implementation makes no
claim to have validated 50 stable hosts or superconducting candidates.

The sources below were selected by phase and study context, not by taking the first
formula search hit. CIFs are unchanged download assets. The public capture manifest
`docs/data/discovery-host-source-captures-2026-10-05.json` records selected official
COD search metadata, selection rationale, successful request URL, capture time,
HTTP status, byte count and SHA-256. The private audit also retains failed revision
requests and complete formula query responses. Ga2O3 and GaN revision requests
returned HTTP 500; their successful mutable-current-file captures are labelled as
such. All other new captures used revision URLs. Header revisions remain explicit.

| Formula | COD ID | Selected phase | Expanded sites | Numeric source T (K) |
| --- | --- | --- | ---: | --- |
| Al2O3 | [9007634](https://www.crystallography.net/cod/9007634.html) | Corundum, hexagonal setting | 30 | diffraction 300 |
| MgO | [9006456](https://www.crystallography.net/cod/9006456.html) | Rocksalt | 8 | diffraction 298 |
| ZrO2 | [9016714](https://www.crystallography.net/cod/9016714.html) | Monoclinic baddeleyite | 12 | not supplied |
| HfO2 | [9013470](https://www.crystallography.net/cod/9013470.html) | Monoclinic hafnia | 12 | not supplied |
| Ga2O3 | [2004987](https://www.crystallography.net/cod/2004987.html) | Monoclinic beta phase | 20 | cell 273.2; diffraction 273 |
| AlN | [1010514](https://www.crystallography.net/cod/1010514.html) | Wurtzite | 4 | not supplied |
| BN | [9008997](https://www.crystallography.net/cod/9008997.html) | Hexagonal layered phase | 4 | not supplied |
| GaN | [1010168](https://www.crystallography.net/cod/1010168.html) | Wurtzite | 4 | not supplied |
| TiN | [1011101](https://www.crystallography.net/cod/1011101.html) | Rocksalt | 8 | not supplied |
| NbN | [1011319](https://www.crystallography.net/cod/1011319.html) | Cubic rocksalt | 8 | not supplied |
| SiC | [1010995](https://www.crystallography.net/cod/1010995.html) | Cubic 3C | 8 | not supplied |
| TiC | [9012564](https://www.crystallography.net/cod/9012564.html) | Rocksalt | 8 | not supplied |
| ZrC | [1562921](https://www.crystallography.net/cod/1562921.html) | Rocksalt | 8 | cell 298; diffraction 298 |
| HfC | [1539502](https://www.crystallography.net/cod/1539502.html) | Rocksalt | 8 | not supplied |
| NbC | [1011323](https://www.crystallography.net/cod/1011323.html) | Rocksalt | 8 | not supplied |
| TiB2 | [2002800](https://www.crystallography.net/cod/2002800.html) | Hexagonal diboride | 3 | not supplied |
| ZrB2 | [1510857](https://www.crystallography.net/cod/1510857.html) | Hexagonal diboride | 3 | not supplied |
| MgAl2O4 | [1540775](https://www.crystallography.net/cod/1540775.html) | Cubic spinel | 56 | not supplied |
| LaAlO3 | [1521190](https://www.crystallography.net/cod/1521190.html) | Rhombohedral, hexagonal setting | 30 | not supplied |
| SrTiO3 | [9006864](https://www.crystallography.net/cod/9006864.html) | Cubic perovskite | 5 | not supplied |
| BaZrO3 | [1538369](https://www.crystallography.net/cod/1538369.html) | Cubic perovskite | 5 | not supplied |

None of these 21 CIFs supplies numeric measurement pressure. A paper title or room
temperature description is not converted into an invented temperature or 1-atm value.
For example, Al2O3 uses the 300 K diffraction entry, not its companion 2170 K entry;
Ga2O3 separately retains cell T = 273.2 K and diffraction T = 273 K. This source
library does not certify ambient/300 K thermodynamic, dynamical or chemical stability.

### CIF interpretation

Eight new references omit the occupancy column. Their JSON retains `raw: null`,
`value: 1` and `basis: cif_dictionary_default`, following the
[IUCr coreCIF occupancy definition](https://www.iucr.org/__data/iucr/cifdic_html/1/cif_core.dic/Iatom_site_occupancy.html).
The UI explicitly identifies the default as unmeasured. Proposal CIFs write `1`
with a comment naming its basis. An explicit `?` or `.` is not replaced by this
default. Explicit `1`, `1.` and `1.0` are equivalent full-occupancy tokens; uncertainty
and partial occupancy continue to prevent automatic ordered-site generation. The
existing FeSe model still requires a disorder model.

Original ionic type symbols (such as Al3+ and N3-) remain `type_symbol_raw`; element
names are parsed independently and do not assign charge to a proposed electronic
state. When type symbols are omitted, the recorded basis is the CIF label element
prefix. Only declared symmetry operations are expanded, accepting both coreCIF tag
spellings. The new builder uses reciprocal-basis bounds to enumerate all periodic
images within the tolerance, including skew cells. It checks expansion against
Gemmi's unit-cell sites, weighted formula ratios, supplied Z, overlapping sites,
finite numeric tokens, source hashes and revision identity. This is structural-file
validation, not a new symmetry determination or a physical stability result.

### Interaction and reproducibility

Family, formula, phase and COD ID filters locate source references. Filtering does
not silently change the selected source or proposal. All selectors group sources by
family and include their phase. Links carry the selected reference into single-site
and combined-site generation. Larger cells start at 1×1×1 so a 30-site corundum or
56-site spinel source opens within the 96-site preview limit; this is not a converged
defect-model size. Three-element structures have a labelled three-species legend.
The a/b/c view directions now follow actual lattice vectors, including monoclinic c.

```sh
# In an isolated environment containing gemmi==0.7.5:
python scripts/build_discovery_host_references.py --check
# Rebuild only when intentionally updating the captured artifact:
python scripts/build_discovery_host_references.py
```

No network, production database write or global dependency installation is needed
for reconstruction. The original 2026-10-04 snapshot and builder remain available.
The current 2026-10-05 JSON hash is
`f558d87c57dc125e023c9ecc274348a869890cbcc0429eb61daa7e2a16414f25`.

Validation: 46 source checks, 2,807 unit/component tests in 128 files, and the
production build pass. Checks include previous native QE fixture reconstruction,
all named hosts, old reference identity, distinct source temperatures, occupancy
provenance, ionic symbols, monoclinic camera directions, filtering and selection
continuity. In the production browser build, Al2O3 O→N and O-vacancy proposals at
0%/+2% produced four candidates. Actual downloaded JSON/checksum/CIF files passed
hash and independent Gemmi checks: Al12 N O17 (30 atoms), Al12 O17 (29 atoms), and
scaled source geometry with 30 expanded atoms. Desktop 1280 and mobile 390/320 px
showed no document overflow; source tables use local scrolling. Browser console
reported no warnings or errors. These checks do not establish physical viability.
