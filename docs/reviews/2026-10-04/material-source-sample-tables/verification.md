# Fe–Te–Se source sample tables

Materials linked to arXiv:0911.4758 previously offered a selected Tc and paper context without the paper's composition and susceptibility-fit table. The new source reference separates nominal preparation, measured EDX coefficients and fit parameters, and links it from five exact material/result/paper tuples. The existing FeTeSe context keeps its primary link and adds a companion link.

## Source and scope

- Captured edition: [arXiv:0911.4758v1, Table I, PDF page 4](https://arxiv.org/pdf/0911.4758v1#page=4).
- PDF SHA-256: `3648d27c3f7a152518c9160c95cf4fa21a2419bbb4f35dbd601c9f5a317937c4`.
- Source JSON SHA-256: `a20ebb3d98b1e460a942944fe24004d860ccb969b5c25d10c4b007f407f5d372`.
- Six source rows and 54 original table cells, including missing-cell marks. Splitting composition and fit parameters repeats six nominal labels, yielding 60 displayed cells. These counts do not establish independent experiments or completed catalogue fields.
- Original coefficients, negative fit values, source units and row order are retained. The 0.40(I) effective-moment cell is blank; 0.40(II) has a printed dash. Neither becomes zero.
- The 100–300 K and 20–50 K fit ranges have separate source locators. Weiss fit temperatures and effective moments retain their model roles; the Fe(II) attribution remains tentative.
- Table I has no measured-composition row for x = 0.45 or 0.48. The reference does not map source rows to physical samples, states or selected Tc records. Publisher and retained-ingestion edition equivalence remains unresolved.
- No canonical field, classification, scientific acceptance, formal human review or ML approval is added. Existing selected values and API responses are unchanged.

## Display and validation

The dedicated page uses two named, keyboard-focusable scroll regions, column and row headers, explicit units, one closed source/download disclosure, finite PDF page links and contained JSON. Both the new JSON viewer and adjacent paper-context viewer expose a named region. Invalid or altered table input displays an unavailable state.

Validation performed on the owned source checkout and isolated copies:

- Source checks: 46 passed.
- Four related component suites: 50 passed. After adding named metadata regions, both changed suites passed again: 15 tests. No additional scientific inference is established by these UI checks.
- Final production build, type checking and static generation passed; the dedicated sample-table route was generated.
- Independent source inspection checked all 60 displayed cells against the original PDF page, including the 54 unique cells, three source windows, units, fit roles and blank/dash distinction. All 19 pre-existing research assets remained byte-identical to the parent commit.
- Actual browser at 1280, 320 and 390 px: both tables retain six rows, document width remains the viewport width, and table overflow stays inside its region. Tab reaches the fit table; arrow keys scroll it horizontally. Source disclosure opens with Enter and provides three bounded PDF-page links.
- Actual browser JSON and sidecar downloads completed after one click each. The downloaded 14,733-byte JSON matched the source asset and the sidecar matched byte-for-byte.
- Frozen public Fe1+δTe0.80Se0.20 detail GET replay retained its selected 12 K and two source records. The actual related-paper link navigated to the new source table page without placing table cells in the selected-value surface.
- The adjacent paper-context metadata region was reached using Tab in the actual browser. No browser console errors were captured.
- Private preview served one checksum-pinned read-only detail response, refused writes and used the existing development origin policy. It changed no production CORS, CSP, credentials or service configuration.

Local previews and builds do not prove public deployment. Ordinary required CI, signed release/deployment and final public acceptance remain separate publication gates.
