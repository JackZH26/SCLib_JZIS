# Nb0.07-CVS pressure-series source readings

`/materials/source-observations/nb-cvs-pressure` exposes all four pressure
columns of [arXiv:2411.18744v1 Table 1](https://arxiv.org/html/2411.18744v1#S3.T1.2)
(PDF Table I on page 8). The source-observation hub and the existing zero-GPa
window both link to it. The original 15-observation artifact is unchanged.

The table contains 21 numerical property-fit parameters, 8 numerical fit
statistics and 3 printed dashes. Three zero-GPa quantities were already shown;
the increment is **18 property-fit parameters plus 8 fit statistics**, not 26
experiments, new materials or approved scientific properties. Pressure headers
and model labels are conditions, excluded from this numerical-cell count.

The source-defined subject is Cs(V0.93Nb0.07)3Sb5, alias Nb0.07-CVS. These are
fits to measured transverse-field muon data at 10 mT. The separate AC data use
zero-field conditions. Tc remains a gap-analysis fit parameter; no resistive
onset/midpoint/zero criterion is assigned. The paper's single-crystal default
is retained as a source-wide statement, not a unique physical specimen ID.
Pressure labels remain the printed applied hydrostatic pressures, without
inventing an absolute/gauge convention or converting ambient wording to zero.

λ denotes London penetration depth. The table's λ(T > 0) in nm is retained
separately from λ⁻²(T = 0) in μm⁻², including the unusual source temperature
label. No reciprocal recalculation is performed. ω is the authors' phase
fraction in the gap model, not a measured superconducting volume fraction.
The three Δ₂ dashes remain unlisted source cells, not zeros or measurements of
absence. Parenthetical uncertainties retain their printed digits; no confidence
level or standard-uncertainty interpretation is supplied. χ² and χ²/NDF remain
fit diagnostics, not scientific acceptance scores.

The 0.8 GPa column uses a double nodeless s-wave fit; the other three use single
nodeless s-wave fits. The ambient prose's Tc = 4.70(3) K, λ = 316(5) nm and gap
0.590(5) meV stay distinct from the table's 0 GPa column. Their dataset/specimen
correspondence remains unresolved. No result from another pressure or method
is used to fill that discrepancy.

## Source reconstruction

Official HTML and v1 PDF were captured on 5 October 2026. HTML SHA-256 is
`b5f1bc07212429562d977e9def108dbbc075e86977ab6d54e5ea597cd3bacf53`;
PDF SHA-256 is
`bddff2c5fbac870cbebdadec91d4fc14687081b97cc72aa10f80834eb2c94f99`.
The original PDF page was rendered and all 32 table cells, labels, units and
caption model assignments visually compared to the HTML. This is AI-assisted
source inspection, not independent human review or publication validation.

The public JSON carries raw values, uncertainty strings, field roles, pressure
binding, source DOM IDs and exact original-HTML Unicode character ranges with
substring hashes. End positions are exclusive. Unit provenance points to the
source row labels; fields with no printed unit retain null. The λ⁻² label's
HTML math conversion is malformed internally, so its unit typography was also
checked directly in the PDF. No manuscript text or binary is redistributed.

Reproduce from the retained original captures using the stdlib-only script:

```bash
python scripts/build_material_nb_cvs_pressure.py \
  --html /path/to/retained/source.html \
  --pdf /path/to/retained/source.pdf \
  --output-dir frontend/public/research-pilots
```

The script fails if either source hash differs. It verifies each source value,
pressure column, row label and location before generating metadata and its
SHA-256 sidecar. A changed capture requires a new inspected snapshot rather
than replacing this artifact. The frontend accepts only the exact finite
snapshot; changed values, pressure bindings, units, roles or authority are
rejected. This is not a general source importer.

## Display and validation scope

Six property rows and their four pressure conditions are visible together;
the two fit-statistic rows and technical provenance are separate native
keyboard-accessible disclosures. Wide tables use contained focusable scrolling.
The source context and uncertainty convention appear once per table.

Component checks cover all original tokens, data counts, source boundaries,
English UI, links, distinct ambient fit and invalid projections. Offline checks
cover serialized checksums, unique cell pins and rejection of changed originals;
a separate original-byte replay verifies every locator against the capture.
Browser integration and release verification are performed by the parent task.

No API contract, schema, production database, Materials filtering or Discovery
code changes. Retained-record association, scientific approval, human gold,
ML permission, formal field promotion and live deployment remain separate.
