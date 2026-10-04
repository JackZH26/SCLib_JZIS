# NbScTiZr annealing and source parameter comparison

This finite source reading exposes preparation-dependent reports from two captured manuscripts. It answers which preparation label belongs to a Tc report, how magnetization and resistivity fits differ, and which quantities are source-derived. It does not overlay selected catalogue values or establish the same physical specimen across the studies.

The sources are [arXiv:2311.00195v1](https://arxiv.org/pdf/2311.00195v1), 18 PDF pages, and [arXiv:2406.19553v1](https://arxiv.org/pdf/2406.19553v1), 28 pages. Original PDF and complete extracted text remain private. Public metadata contains factual cells, paraphrased methods and 19 hash-only page/character windows. `pdftotext -layout` UTF-8 output retains page separators; offsets are Unicode character positions with an exclusive end. Each nonempty cell has its own literal span and SHA-256 inside the appropriate source window. Two additional windows bind the refined-Tc Hc2 analysis and the mixed-phase γel/β statement; all five source tables remain unchanged.

PDF SHA-256:

- 2023: `5ada9ca574ae87d4cb4f8004a77a1504ce483b26642fe93d941e2c5d28ebd257`.
- 2024: `2640697191af7398cbd39cd16cf5bf5b89514ccfbe56b40ce9c79103b5415119`.

The public JSON has 210 nonempty source cells and nine explicitly unlisted cells. It contains 2024 Table 1's ten phase rows, 2023 Table 1's eight phase rows with SEM volume fractions and VEC, 75 cells from 2024 Table 2, four original 2023 Tc values, and 16 calorimetric fit/ratio values for four annealed samples. These are source-cell counts, not new materials, independent measurements, approved fields or a precision/recall benchmark. Shared values and preceding-study attribution remain visible.

## Scientific reading boundaries

The 2023 Table 1 Tc sequence is 7.9, 8.4, 9.0 and 8.7 K for as-cast, 400, 800 and 1000 °C groups. Its Figure 3(a) discussion defines ac-susceptibility diamagnetic onset; the methods describe 5 Oe, 800 Hz and 3–20 K. The 2024 Table 2 sequence is 8.11, 8.71, 9.36, 9.13 and 9.03 K with an additional 600 °C group. Its text describes refined Tc from upper-critical-field analysis. Calorimetric midpoint is stated in the later heat-jump normalization analysis and is not assigned to the whole Table 2 Tc row. Values from the two editions are not reconciled or recomputed.

Annealing temperatures and the four-day hold describe processing. The as-cast state has no annealing temperature or hold duration in the metadata; the paper's 0 °C plotting convention is not a physical preparation temperature. The captured 2023 v1 has no 600 °C row. Nominal 1:1:1:1 starting proportions do not replace phase-resolved chemistry.

The phase-composition columns print coefficients with parenthetical uncertainty notation without an explicit composition unit. They retain null raw units, rather than silently becoming atomic percentages or normalized formulae. Lattice values retain their printed angstrom unit; the 2023 extracted token is decomposed `Å` and the 2024 token is `Å`. The 2024 text attributes bcc chemical compositions to the preceding study [46]; the table is not an independent repeat, and the additional 600 °C row is not found in the captured 2023 v1 table. Source phase volume fractions are not superconducting Meissner or shielding fractions. Source-derived VEC remains separate from composition and lattice measurements.

M and ρ mark distinct magnetization and resistivity WHH-fit channels. Hc1(0) retains mT, Hc2(0) retains T. Ginzburg–Landau coherence and penetration lengths and κ are source-derived; they are not direct length measurements or new calculations. Penetration depth λGL in nm and the WHH spin-orbit-scattering parameter λSO are not electron–phonon coupling λ.

Normal-state γel and β include both bcc and hcp contributions. The four annealed-sample electronic-specific-heat fits retain the gap and residual γ term, plus the original dimensionless gap and normalized-jump ratios. The source attributes residual γ to hcp and discusses possible strong coupling; the reading grants no global pairing classification. As-cast estimates remain absent because the source excludes that broadened transition from this analysis. Ratios are not recalculated using the independently tabulated Tc values.

## Display and catalogue links

`loadNbsctizrAnnealing` accepts only the finite shipped snapshot and returns an independent copy. Altered numerical tokens, units, roles, source editions, normalized values, missing-cell meanings, extra manuscript text or authority are rejected. Source links are restricted to the two exact PDF editions and in-range one-based pages.

`nbsctizrAnnealingReading` matches the exact inspected `mat:nbsctizr` result/source tuples. It produces a related-paper reading entry only; formula equality, paper membership and the helper do not establish physical sample, state, structure or selected-result associations. The surrounding page remains responsible for current catalogue eligibility. The source asset includes no catalogue IDs, reviewer identities or fulltext.

The inspected historical/fresh DTOs also contain a legacy `cuprate_123` phase label in records despite the papers' bcc/hcp discussion. This is a later extraction/association review opportunity. This source reading preserves retained records and creates no automatic correction or global warning.

## Verification and authority

Preparation replay matched every public cell token and window hash to the unchanged PDF-derived text. Independent AI-assisted source inspection also compared the original table cells, phases, units and fit roles. Such checks are source-fidelity evidence, not independent human scientific adjudication. Component/unit, production build, browser downloads, exact-head CI and public deployment are separate validations recorded by the integrating task.

All canonical update, scientific acceptance, formal human review, ML-training permission and calculation-execution flags remain false or zero. Current publication/retraction status, publisher/retained-ingestion byte equivalence, full supplement coverage and physical associations remain unestablished.

## Local display acceptance, 4 October 2026

The final display renders γel and residual γel′ as `mJ/(mol·K²)` and β as
`mJ/(mol·K⁴)`. This denominator grouping is supported by the source equations;
the public JSON retains its original unit tokens and unchanged SHA-256
`e7422f5af6df9113db17c593b37bbe1509fe4bcb64cadf20ccafc2fa29133f27`.
The page explicitly distinguishes formatted unit typography from source tokens.

The full frontend unit run passed 2,666 tests in 114 files. Following final
display changes, all 29 tests in the three comparison suites passed, including
all eight annealing UI tests. Type checking and the normal production build
succeeded. Browser checks at 1280, 390 and 320 px verified closed default
disclosures, separate transition criteria, parameter/gap tables, keyboard
scrolling and contained horizontal overflow. JSON and SHA sidecar downloads
matched the exact shipped files.

The actual public DTO was version-fenced before inspection. Filtering the
catalogue for NbScTiZr still selected the retained 9 K observed result from the
2023 source. Its evidence dialog and full material page both exposed the
qualified related-reading link; navigating that link reached this source page.
The 2024 9.36 K source value did not replace the catalogue result, and no phase
or physical-specimen association was added. These are local acceptance results;
deployment and scientific property review remain separate.
