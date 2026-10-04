# Material detail layout and recovery-table keyboard access

The material heading and guest bookmark prompt shared a non-wrapping flex row. At 320 px, the public La4Ni3O9.99 page measured 335 px wide and the prompt extended to x=334.77. The same layout remained in parent commit `133fb6728cf9483f5e2f4ef1511ae2be800fc8ed`.

The heading row now wraps and the formula heading stays within the available width. At 320 px the guest prompt moves below the formula; at 390 px it remains beside it. The field-coverage table now has a named, focusable scroll region and a visible focus outline. A 40 rem minimum table width preserves readable columns while horizontal scrolling stays inside that region.

## Verification

An actual in-app browser opened the changed page using an isolated development workspace and a loopback-only replay of captured public GET responses. The replay served only the captured nickelate detail and enrichment responses; authentication reads returned an anonymous 401 and writes were refused. No production CORS, authentication, CSP or database settings changed. The production build was checked separately in another isolated workspace with the normal public API URL and an inert server API URL.

- 46 source tests passed.
- 51 component tests in three relevant suites passed, including a new disclosure, accessible-name, focus and field-text regression.
- Production build and type validation passed; 55 static pages generated.
- Actual 320 px and 390 px document widths matched their viewports. Formula and bookmark bounds stayed inside both viewports. The default 1280 px viewport also had no page overflow.
- Enter opened the coverage disclosure. Tab reached the named scroll region. Three right-arrow presses moved its scroll position from 0 to 120 px; three left-arrow presses returned it to 0. Page width remained 320 px throughout.
- All 39 returned coverage rows rendered. The selected headline remained 23 K. The browser recorded no console errors. The temporary viewport override was reset, the temporary tab closed, and both owned loopback servers stopped.

The captured detail response was 93,252 bytes, SHA-256 `40447330c937cff6578db220af0dc8b51c917ce87a0eebb863b854927762c335`. The enrichment response was 59,078 bytes, SHA-256 `8e7bad64e090d19f0ff561644dba9de1a762be030a2e514251354b1a1ce76b15`. These are replay inputs, not new scientific facts or current production acceptance of this change.

## Source-recovery availability diagnosis

The public page separately returned 39 field states, 13 pending literal candidates and three source statements requiring closer inspection, after inspecting 28 chunks across two linked papers and three retained records. Its actual JSON download matched the returned coverage and candidate identities, with all approval and database-change flags false. Version responses before and after the public browser check were byte-identical and reported `ab2760b`.

The same public enrichment GET returned the same bytes for the public and local Origin headers. The response permitted the public origin but did not permit the local preview origin. This explains the earlier local browser failure; it does not establish missing source information. The download-event wait timed out after the click, but the completed file was found and verified without repeating the click.

This patch changes presentation and keyboard access only. Scientific values, extraction states, sample associations, review decisions, source assets and downloads retain their existing semantics. Latest exact-head CI, signed release and deployed-page acceptance remain separate publication gates.
