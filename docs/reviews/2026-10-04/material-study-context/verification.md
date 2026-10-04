# Related paper context for three material records

Several retained Tc records lacked a readable route to preparation, original sample columns and source method attribution. This change adds six reading contexts from three inspected studies, exposing 19 literal field projections with the exact source windows, original uncertainty notation, source revisions and hashes. It also adds a compact related-paper entry to the three inspected material details when material ID, selected-result ID and paper ID all match.

| Captured study | Reading context |
|---|---|
| BiTeCl, arXiv:1501.06203 | Self-flux growth, Daphne oil 7373 for transport, separate Neon Raman medium, 488 nm wavelength and room-temperature pressure calibration. Calibration temperature is not a Tc measurement condition. |
| Mo borophosphide, arXiv:1603.02892 | Original Table I columns 2 and 3 retain different nominal preparations, despite their identical printed refined composition. Both refined-composition occurrences retain their original row/column and occurrence identifiers. Existing Tc and lattice rows stay separate. |
| Pt substituted BaFe₂As₂, arXiv:0912.2752v2 | Figure 4 attributes 23 K to resistivity and magnetic susceptibility. Its approximately 20 K heat-capacity feature and below-21 K discussion are separate contexts. XRD correspondence preserves parenthetical composition uncertainties and its 250 K measurement temperature. |

These are AI-assisted captured-paper readings with pending context status. The related links match actual returned record identities, but do not establish a common physical specimen, the originally ingested fulltext edition or a new formal calorimetric Tc. There are no canonical property overlays, database operations, source imports, new calculations or human/scientific/ML approval changes. The selected catalogue values remain separate.

The public metadata is `materials-study-context-2026-10-04.json` (27,284 bytes; SHA-256 `75f628dfd479b1d0512caa7ccbc81202ce4b2e4136cbf093e86e2f7fa0607481`). Its sidecar is 106 bytes. All 15 pre-existing public research-pilot members remain byte-identical. Source PDFs/HTML and full derived texts are retained privately; the new public asset contains bounded field projections and source locators. Unversioned PDF links explicitly distinguish the mutable URL from the captured file hash. The original Pt HTML capture time was not retained and is not invented.

Local validation on merged-main `0a35c5dfccfd03c5f15d8ed5e56f8b58309648f5`:

- 91 preparation checks and 85 independent field-replay checks passed, including native HTML element derivation, 19 literal hashes and the two original Mo table columns.
- 62 component/behavior tests in nine suites passed; TypeScript validation and the production build passed with all 54 static pages.
- Actual browser checks at 1280 and 320 pixels verified all three material-detail entries, source locator folds, contained JSON reading, preserved XRD composition notation and keyboard horizontal scrolling. Mo and Pt tables remain inside their horizontal regions; document width stayed at the viewport width.
- Actual Bi/Pt cross-page entry clicks now open only the target's ancestor disclosures and position the content below fixed navigation. No-hash visits retain closed disclosures. Four finite Bi/Pt hashes are handled by a client leaf with listener/frame cleanup; mounted base paths are retained by native links. The Mo heading has the same 96-pixel scroll offset.
- Actual browser JSON and SHA-256 downloads were rehashed and matched the shipped bytes. No browser error logs were observed on the inspected source pages. Temporary tabs, viewport overrides and the local server were cleaned up.

The initial two test-selector failures, the initial closed-fragment browser observation and the Mo heading obstruction were preserved before repair. These local checks do not prove a new public deployment; exact-head CI and signed production release have their own gates. The separate dependency security update is PR #103.
