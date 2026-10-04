# Discovery source study comparison

The condition-design workspace can describe hypothetical pressure and temperature
targets, but those targets are not a response series. This addition makes a real
published study usable in Discovery: the full Table I from Jiang, Zhong and Liu,
*Underlying mechanism for high-temperature superconductivity in ternary hydride
AB2H24*, Physical Review Research 7, 023296 (2025),
DOI [10.1103/7lg7-l3x8](https://journals.aps.org/prresearch/pdf/10.1103/7lg7-l3x8).

## Real input and scientific scope

The captured APS published PDF is seven pages, dated 23 June 2025. Its SHA-256 is
`d601beae68163ed8e423fca34cbf6513330a9a8b12cdff75b1d5f30d623d5a81`.
The frozen pypdf page text, joined in page order with LF, FF, LF and no text
normalization, has SHA-256
`a31918c668f46c46f37683c1828bc3b64fce84b1de7d526918e38ca45cab63df`.

Table I on PDF page 3 contains 21 computational compounds in the reported
P6/mmm-AB2H24 substitution framework. The caption specifies 300 GPa, the isotropic
Eliashberg equation and assumed Coulomb pseudopotential μ* = 0.1. Paper-wide
computational methods identify direct solution using Elk. These statements do not
assign a retained run ID, validate its convergence or establish identical atomic
coordinate models for different compounds.

The source table supplies EPC λ, ωlog and predicted Tc. Tc explicitly has K in the
column header. EPC λ is dimensionless by its scientific definition. The table
prints no unit for ωlog, so the resource keeps its original digit string with
`value: null`, `unit: null`, and `unit_status: not_printed_in_table`. It never
silently becomes K, THz or an energy. λ and Tc are parsed only to plot the reported
source scalars; no unit conversion, uncertainty estimate, extra precision or new
calculation is introduced.

The complete table window is Unicode offsets `[9717, 10368)` in that frozen
text, with SHA-256
`23aa969de4a64f7ea3238167cf2a39c44ae0c9c47f2682be5ee1e925eccf0711`.
The new finite JSON resource retains each original row, all 84 field-token
locators and hashes, the shared method/caption locators and source-qualified
interpretation windows. It contains no full PDF, full manuscript text, private
file paths or copied native calculation files. The PDF's CC BY 4.0 attribution
statement is preserved in the bibliography and source metadata.

Three distinctions stay visible:

- The table caption calls its selected compounds dynamically stable at 300 GPa.
  This is an author-reported selection claim, not independent stability
  validation in SCLib.
- The discussion says **most** compounds lack thermodynamic stability at
  300 GPa and become dynamically unstable when pressure decreases to 250 GPa.
  This class-level statement is not assigned to a particular row. No ambient
  survival or 300 K stable-host designation follows from the table.
- The source fits its CS descriptor against Tc. The interface performs no CS
  regression, descriptor inference, new prediction, causal fit or independent
  calibration. The abstract's maximum of 276 K and Table I's 300 K value for
  ThY2H24 remain an unresolved internal source difference; the table is
  transcribed as printed.

This is a different-compound comparison at one pressure. It advances use of
actual physical quantities in the Discovery methodology, while D4's comparable
multi-pressure results and D5's stability/electronic design space remain
incomplete. Source rows are not independent experiments, catalogue associations,
scientific acceptance, ML training permission or newly executed computations.

## Data and implementation

- `frontend/public/research-pilots/discovery-ab2h24-source-table-2026-10-04.json`
  uses independent version `discovery-ab2h24-source-table/1.0.0`; its SHA-256 is
  `e63ab6df2fd73daf92cb75f0c7efda804cfda595a302f63e8b99fb55eaa9f362`.
  The adjacent sidecar describes the exact static resource bytes.
- `frontend/lib/discovery-source-comparison.ts` reads only that exact finite
  snapshot. Caller edits to source values, units, assumptions, order, locators,
  extra keys or scientific authority are rejected. It provides original-order
  A/B element filtering, finite publisher links and qualified source CSV.
- `frontend/components/DiscoverySourceComparison.tsx` exposes the public section
  `#discovery-source-comparisons`. It makes no API/provider/auth requests or
  database writes and consumes no scientific publication, private design or
  catalogue-result row.

The component follows the existing SCLib sage scientific interface. The
`design-taste-frontend` guide is applied to its relevant brand-preservation,
spacing, accessibility and plain-copy principles, with design variance 3, motion
intensity 1 and visual density 6. A complete 21-row scientific source table is
justified by the researcher task; landing-page density and decorative-motion
patterns are not applied to this study reader. Native controls and scientific
SVG require no new dependency.

## Researcher interaction

The common pressure, solver and μ* assumption appear once near the title. The
original table remains complete and in its published order. A/B filters never
sort, aggregate, infer missing zeroes or combine rows. A filter combination with
no source row has an explicit empty state, without a fallback point.

Researchers use native, labelled 16 px checkboxes within 44 px targets to select
up to two compounds. Their source values appear together above the plot and
table; a native jump link from below the table returns to that comparison.
Changing element filters clears prior selections, and selected markers highlight
the corresponding source rows. The SVG itself is a read-only chart; point-click
selection is not implemented or claimed.

The chart uses physical axes: dimensionless EPC λ and computed Tc in K. It keeps
the same axes across filters, uses individual markers without lines/fits and
preserves near-overlapping rows independently in the full table. It excludes
ωlog because its unit is unresolved. Table and plot overflow are contained in
named, keyboard-focusable regions on narrow screens. The table remains the
complete keyboard-accessible equivalent of the chart.

Source interpretation, bibliographic/currentness scope and metadata are folded
by default. Bounded JSON is inspectable in a focusable wrapping region. Static
JSON and SHA-256 links are available independently of the CSV browser-download
action. CSV exports all 21 rows regardless of display filters and repeats the
shared pressure/model assumptions, ωlog unit status, authority limits and source
locators on each row. CSV failures leave the static JSON resource available.

## Required validation

Source-fidelity verification must inspect the actual PDF page and frozen text
against every row/field locator. UI unit tests cover all original values and
order, exact static-file bytes, changed-source/model/unit/authority rejection,
true physical plot coordinates, two-row selection, contained reading regions,
empty filters, unreviewed class-scope boundaries, qualified CSV and JSON exports,
and English-default copy.

Root-owned acceptance must also verify the final normal build, actual
320/390/1280 px layout, native keyboard selection and horizontal scrolling,
disclosures, all-row downloads and downloaded contents. Independent source
inspection, automated UI tests, actual browser behavior, exact-head CI and
public deployment are separate evidence; none of them supplies formal
scientific approval. Native contracts, existing source assets, retained
catalogue quantities and RPS releases remain unchanged by this component.

## Local acceptance, 4 October 2026

The frontend source suite passed 46 checks; the full unit run passed 2,666 tests
in 114 files. After the final chart sizing, anchor spacing and unit typography
changes, the three source-comparison suites passed all 29 tests again. TypeScript
checking and the normal production build succeeded with the existing Next
configuration and fonts. The build used a byte-matched copy of 277 source/config
files; no alternative build configuration or new dependency was introduced.

Actual browser checks at 1280, 390 and 320 px verified the full source table,
two-row selection, disabled extra selections, A/B filtering, explicit empty
results and filter reset. The chart and table scroll within their own focusable
regions without widening the page. Keyboard activation of the comparison jump
link positions its heading below the fixed navigation. The SVG remains a static
chart, and native checkboxes provide the selection interface.

Browser downloads of both static source JSON files and their SHA-256 sidecars
matched the shipped bytes. The AB2H24 CSV downloaded through the interface
contains all 21 rows, including original values, unresolved omega-log units,
shared computational assumptions, locator pins and unchanged authority limits.
The experimental annealing link leads to the distinct NbScTiZr reading. These
are local production-build results; exact-commit CI, signed deployment and
public-site acceptance remain separate release work.
