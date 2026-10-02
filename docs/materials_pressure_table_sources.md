# Pressure and table source records

`/materials/source-observations/pressure-and-tables` presents 18 finite source-expression records from two captured papers and three source subjects. They are not 18 experiments or approved catalogue properties. The existing 15 initial observations and 34 follow-up records remain byte-identical.

The metadata resource retains parent PDF and supplied text SHA-256 hashes, original package hashes, exact subject/window/value/unit/condition character spans and original table columns. The original bound source capture IDs and expression keys remain unchanged; a public reference label is separate from that identity. A capture ID is provenance metadata, not a filesystem path or an access credential. The original PDFs, source fulltext, base64 packages and private file paths are not redistributed. Whole-batch downloads have a SHA-256 sidecar. Each source-subject resource contains exactly its six expressions and its source snapshot, with pending status, unestablished sample/state/result association, zero canonical promotions and no scientific or ML approval.

## Scientific scope

- BiTeCl's main-text 7 K / 15 GPa report stays separate from the Figure 2 caption's 90% resistivity criteria at 24.1 and 50.8 GPa. The original inset prints 50.1 GPa while its caption/body print 50.8 GPa. That conflict is visible and unresolved. The frozen parser leaves the sentence-pressure numerical normalization unresolved, while retaining the raw `15` / `GPa` expression.
- Two nominal Table I samples, `Mo5P0.9B2.1` (original column 2) and `Mo5PB2` (column 3), both report refined `Mo5P1.07(4)B1.93(4)`. Their resistive-zero and susceptibility-onset Tc values, lattice parameters and source windows remain separate. The third, more P-rich column is excluded. All eight parenthetical Tc/lattice quantities retain their full raw uncertainty notation and the decomposed `A` plus combining ring unit. Numeric and uncertainty normalization remains pending.
- Room-temperature powder XRD describes the crystallographic window only. Unreported Tc pressure is not converted to ambient pressure, and preparation pressure is not assigned to Tc.
- The Bi PDF's observed v1 label, its internal July 7, 2018 date and official January 25, 2015 v1 submission are preserved without claiming version equivalence. Current publisher/arXiv files, publication currentness and original-fulltext redistribution rights remain unresolved for both sources.

The source expression projections were compiled with the unchanged v2 Python contract and checked against the independently prepared projections. Independent parent-PDF re-extraction and read-only native SQL/Python semantic parity are separately identified by receipt hashes in the source metadata. These checks establish the captured expression chain, not physical sample identity or scientific validation.

## Presentation and validation

Values and relevant missing states remain visible; publication versions, capture hashes and field locators use native keyboard-accessible disclosures. The original Mo columns are compared in a contained, focusable horizontal-scroll table on narrow screens. Three native disclosures render the exact six-entry JSON resources for the BiTeCl subject and the two original Mo columns in bounded, keyboard-focusable reading areas. Viewing a subject requires no download permission, navigation or client JavaScript. Same-origin static-resource links and the whole 18-entry download with SHA-256 sidecar remain available for programmatic use and browser downloads where permitted.

Targeted component tests cover counts and authority boundaries, main/caption separation, both original columns, every uncertainty string and unresolved unit, missing Tc pressure, source-label conflicts, original locators, English copy and three exact static subject resources. No API contract, backend compiler, SQL function, model, migration, production import or private-curation setting is changed.
