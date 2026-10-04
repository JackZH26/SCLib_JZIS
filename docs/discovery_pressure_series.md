# Discovery pressure study comparison

This implementation adds a real, source-qualified computational pressure series from
Errea et al., *Quantum Crystal Structure in the 250 K Superconducting Lanthanum
Hydride*. The captured input is the official
[arXiv:1907.11916v1 author preprint](https://arxiv.org/abs/1907.11916v1), submitted
27 July 2019; its PDF is dated 30 July 2019. The related
[Nature 578, 66–69 (2020) article](https://www.nature.com/articles/s41586-020-1955-z),
DOI 10.1038/s41586-020-1955-z, is identified as a separate version of record.
Equivalence of its table to the captured preprint and current publication or
retraction status were not verified.

This advances D4 with actual quantities at multiple pressures for a single
compound and source-defined phase family. It does not complete translation to
ambient pressure, provide identical coordinate models or establish a stable
host at 300 K and 1 atm. The earlier AB₂H₂₄ comparison remains a different-compound
study at one pressure; it cannot substitute for this series.

## Captured source facts

Extended Data Table I on PDF page 11 has seven complete computational rows:
four LaH₁₀ pressures and three LaD₁₀ pressures. The original table has 49 numeric
cells, seven compound tokens and no missing printed numeric cells. Printed
precision is retained, including the LaD₁₀ λ string `1.80`.

| Compound | Pressure (GPa) | EPC λ | ωlog (meV) | McMillan Tc (K), μ*=0.1 | Allen–Dynes Tc (K), μ*=0.1 | Anisotropic ME Tc (K) | Isotropic SCDFT Tc (K) |
|---|---:|---:|---:|---:|---:|---:|---:|
| LaH10 | 129 | 3.62 | 76.4 | 171.8 | 252.6 | 255.3 | 230 |
| LaH10 | 163 | 2.67 | 96.4 | 197.1 | 247.0 | 242.8 | 225 |
| LaH10 | 214 | 2.06 | 115.5 | 196.3 | 235.9 | 237.9 | 210 |
| LaH10 | 264 | 1.73 | 126.6 | 189.5 | 219.2 | 216.9 | 201 |
| LaD10 | 159 | 3.14 | 63.5 | 135.0 | 184.2 | 180.4 | 171 |
| LaD10 | 210 | 2.21 | 81.7 | 145.5 | 176.5 | 172.9 | 158 |
| LaD10 | 260 | 1.80 | 92.2 | 142.2 | 164.6 | 157.9 | 151 |

GPa, meV and K are printed in the table headers. EPC λ is dimensionless by its
physical definition, with the source definition located separately. All numeric
parsing uses the existing source units; no meV-to-K conversion or additional
precision is introduced. Uncertainties are `null`, not zero. The cell schema
also defines explicit nulls for genuinely missing printed cells; this particular
snapshot contains none. Its exact loader rejects attempts to replace a reported
cell with a missing value or zero.

The 20-page, 3,667,042-byte source PDF has SHA-256
`5ec05581e7ea71074a80afee8b4c4dafdc524938e830b849143ec35e7726c07f`.
The derived UTF-8 text uses `pdftotext -layout`, retaining page form feeds with
no post-extraction normalization, and has SHA-256
`383697d172df6415084fe68491307c93308519d1b4047357e359e1e9e89007ef`.
Offsets count zero-based Python Unicode code points and are end exclusive.
The full table occupies `[64900, 66714)`, with window SHA-256
`cb9d8e141eb008e11c67dcac3c0e33617df1b9a60575550756734a5df51d0469`.

The finite metadata includes ten source windows, seven row-window pins and all
56 field-token spans and hashes. These cover table headers and values, the
pressure definition, phase claims, PBE/DFPT/SSCHA assumptions, each Coulomb
treatment, quantity definitions and the preprint title/authors/printed date.
The full PDF, extracted manuscript and rendered source page remain in the
private capture audit; none is rehosted in the public resource. Private audit
directories have mode 700 and files mode 600.

## Comparability and limits

The source defines the pressure axis through the quantum energy E(R), including
quantum effects. It is not an external-stress request or a room-temperature
experimental pressure calibration. A pressure point, its λ and its ωlog are
bound to their own original table row.

The reported phase family is cubic Fm-3m. This supports a qualified comparison
within each compound's author computational study. It does not establish
identical lattice/atomic coordinates across pressures, a native retained run,
independent convergence verification or a physical specimen series. Row-specific
structural calculation temperature is unestablished and remains null; computed
Tc is not the temperature at which a host is validated as stable.

The relevant computational chain is PBE GGA with Quantum ESPRESSO DFPT, combined
with SSCHA phonon frequencies and polarization vectors from the quantum E(R)
Hessian. The superconductivity calculations neglect the Φ(4) Hessian term.
The source reports a 3×3×3 Fm-3m Hessian supercell and EPC 6×6×6 q and 40×40×40 k
grids. These are reported settings, not SCLib execution or convergence receipts.
The separate VASP phase-search/enthalpy calculation is not substituted for the
DFPT/Tc chain.

Four Tc channels remain distinct:

- McMillan and Allen–Dynes use the stated assumed scalar μ* = 0.1.
- Anisotropic Migdal–Éliashberg retains EPC anisotropy and uses a k-averaged
  static RPA screened Coulomb treatment. No scalar μ* = 0.1 is assigned to it.
- Isotropic SCDFT uses RPA Coulomb matrix elements averaged over iso-energy
  surfaces with energy-dependent DOS; the source explicitly introduces no
  empirical scalar μ* parameter.

The authors report anharmonic dynamic stabilization in the high-pressure
experimental range and a LaH₁₀ quantum-energy minimum down to about 129 GPa.
They also report a LaD₁₀ instability at 126 GPa and loss of LaH₁₀ thermodynamic
stability at lower pressure. Harmonic instabilities, anharmonic stabilization
and thermodynamic stability stay distinct. These claims remain source
interpretation with locators; they do not independently approve any row or
establish an ambient stable host. No numerical lower-pressure thermodynamic
threshold is inferred from the paragraph's contextual wording.

The LaH₁₀ and LaD₁₀ pressure grids differ. The reader neither joins their points
into one series nor pairs nearby pressures to derive an isotope coefficient.
It does not fit Tc, compute a pressure derivative, infer a causal pressure law,
digitize a figure or extrapolate to 0 GPa or 1 atm.

## Finite data layer

- `frontend/public/research-pilots/discovery-lah10-pressure-series-2026-10-04.json`
  uses the independent version `discovery-lah10-pressure-series/1.0.0`; its
  SHA-256 is
  `f80b7b855c154163dc4a18d02489fc8c97882154abc735ff6582fddaf0804e9c`.
  The adjacent `.sha256` sidecar pins exact resource bytes.
- `frontend/lib/discovery-pressure-series.ts` accepts only the exact finite
  snapshot, with original rows, field order, source edition, units, assumptions,
  source windows and unchanged false scientific authority. Edited values,
  source/model meanings, ordering, extra keys or promoted associations are
  rejected. Successful loads return independent copies.
- `discoveryPressurePoints` selects exactly one compound and one quantity,
  retains source order and supplies source scalars to the plot. It never
  concatenates solver channels or isotope series. The default is LaH₁₀'s four
  anisotropic ME values; SCDFT remains an independently selectable channel.
- `discoveryPressureSeriesCsv` exports all seven original rows and all four
  solver columns, regardless of the visible selection. Raw precision, units,
  unknown structural temperature, separate μ* roles, method/pressure scopes,
  unchanged authority and source/text/resource hashes accompany each row.

This resource has no material/result ID, membership test, native publication
selector or catalogue write path. It does not reinstate catalogue eligibility,
replace a selected Tc or promote a source to canonical science or ML use.
Conversely, a material-level catalogue dispute flag cannot by itself establish
that this particular paper or its printed table is invalid. Catalogue status,
source reading, native association review and scientific acceptance remain
separate evidence.

## Reader and acceptance

The root-owned `DiscoveryPressureSeries` component appears at
`#discovery-pressure-response`. Native selectors choose LaH₁₀ or LaD₁₀ and one
actual quantity/solver. The corresponding compound's table retains every
reported solver column in original order; selecting a plotted quantity does
not hide or rewrite the other table cells. Downloads retain the complete
seven-row source table.

The chart uses markers only, with pressure in GPa and a single vertical
quantity. The compounds share fixed axis ranges when switched, and all Tc
solvers share a K axis. The selected solver's Coulomb treatment is readable
near the chart. Methods, source-qualified interpretations, bibliography and
finite JSON are available through disclosures. Table and plot have named,
keyboard-focusable horizontal scrolling regions. The full table provides the
keyboard-readable equivalent of the chart; point-click selection is not claimed.

Eight data-layer tests cover exact source tuples, all numeric/token pins,
static-byte hashes, distinct solver assumptions, null-temperature and authority
limits, changed-source/model/unit/order rejection, isolated pressure points,
copy safety, complete CSV and version-specific reading URLs. They use finite
source facts rather than a synthetic pressure response. Actual test execution,
normal build, browser layout/keyboard/download acceptance and final metadata
bytes must be recorded by the root against the finished implementation.

Source transcription was checked against the real rendered table and frozen
text: ten metadata windows, seven row windows and 56 field-token pins match,
with 49 numeric cells, no blanks and no mismatches. This is source fidelity
evidence, not independent domain review, model validation or scientific
approval. Exact-commit CI, signed release and public-site acceptance remain
separate release work.

## Root execution evidence

The finished branch passed 15 pressure-specific tests, 171 focused material
tests, all 2,695 unit tests in 117 files, 46 source checks, TypeScript checking
and the normal production build. An owned build copy matched all 284 production
input files; configuration, fonts and dependency versions were unchanged.

The actual production-build browser showed all six quantity/solver selections
with their original values, physical units and separate Coulomb assumptions.
LaD10 displayed its three independent pressures and preserved `1.80` in the
table. Desktop 1280 px, 390 px and 320 px had no outer horizontal overflow;
the 320 px table accepted keyboard scrolling. The pressure anchor landed
below the fixed navigation. Methods and source disclosures were closed by
default. These observations concern this local build, not the public website.

Actual JSON and SHA downloads matched the shipped resources byte for byte.
With the display on LaD10/SCDFT, the browser CSV still contained all seven
rows and 76 columns. Its 14,338 bytes have SHA-256
`458f0ed87986d481c1e2cbee2e9e230dcea72268df173820e93b184cdfdf6b47`.
An independent AI literal audit compared all 532 CSV fields directly with the
fixed JSON, without calling the TypeScript exporter, and found no difference.
The source audit independently reproduced the PDF text and checked all source
windows and tokens with no difference. Neither audit is human scientific review.

The owned browser tab and service were closed, the viewport reset, and the
temporary build removed after final input matching. User downloads remain.
Exact-commit CI, normal signed release and public-site acceptance are still
required. No scientific fields, catalogue eligibility or source-state
associations were promoted.
