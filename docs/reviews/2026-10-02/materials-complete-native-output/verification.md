# Complete CrB2 native output reference

The computational reference page previously exposed an inspected 2 MiB prefix and could not show the final native structure. A separately versioned metadata resource now adds the reported `finalpos` basis and three B, B, Cr sites from the complete captured XML. The finalpos coordinate lexemes match the last of three calculation blocks. The earlier archive/prefix JSON and checksum remain byte-identical and are labeled as an earlier snapshot in the page.

## Captured source and projection

- NOMAD entry `0dTJ0oCkwgt1xEV8EcXKIV8k9Zjq`, upload `5IvJz3uWTeu7Sgf197BSnw`; original mainfile `oqmd/icsd/30416/relaxation/vasprun.xml`.
- Complete native source: 3,835,451 bytes; SHA-256 `09b0088b66057f364ae436c6e6d15621572408aede91e19ae0b5ce1594f99d5e`. The capture observed HTTP EOF; the whole XML parsed, and its first 2,097,152 bytes equal the previously frozen prefix.
- New selected metadata: 27,497 bytes; SHA-256 `c75feec9feb891322eb007604f02d121d1d8a2ce72d010cc9d1ae94e37b14906`. Its 120-byte checksum resource has SHA-256 `dd355e47a468ac74e117237d606aa71caba0a68e4651bfccfe5ac3cba187cb6f`.
- Earlier metadata SHA-256 remains `c42acb658f255e020c65266a3da891a7acd05426ccb71b052f38c0e13406837d`; earlier checksum bytes remain unchanged.
- Independent source comparisons checked 38 scalar XPath/type/lexeme occurrences (26 parameters, six generator fields, six total-energy channels), 18 coordinate lexemes and three element labels against the captured XML. This is one computed entry, not a count of independent experiments or distinct material properties.

The original successful full capture made three provider GETs: indexed metadata before, native XML, indexed metadata after. A preceding attempt made one indexed metadata GET and stopped because that projection has no `entry_hash`; it did not obtain a native file. The indexed metadata before/after is byte-identical and reports a 2021 processing time. The earlier archive projection reports a 2023 processing time and an entry hash that this full capture did not reverify. These projections are separate; cross-projection atomic currentness and whole historical-file equivalence are not established.

## Scientific meaning

The [current VASP format documentation](https://vasp.at/wiki/Vasprun.xml), revision 37162, describes angstrom basis vectors and fractional/direct positions. This is a documentary convention annotation. The captured basis/positions have no explicit XML unit attributes, and the original VASP 5.3.2 documentation edition was not checked. The current page contains newer examples/layout; it does not repair earlier NOMAD archive units.

Seventeen populated input tags have 26 separately retained occurrences. INCAR ISTART 1 and electronic-startup ISTART 0 remain distinct, as do electronic NELM 60 and response-functions NELM 1. ENCUT was not observed in the complete captured XML; ENMAX is preserved as a different tag, without a default substitution. The last ionic summary and last electronic iteration retain different source channels and exact energy lexemes. Parser correction and a corrected final energy are deferred. XML closure, structural consistency and step counts establish no numerical convergence conclusion.

The entry remains a fixed-composition independent model. Experimental sample/state/phase and selected superconducting-result associations, POTCAR file identity and reproducibility, Tc and EPC remain unresolved. No new calculation, canonical property promotion, database import, human review, scientific acceptance or ML approval is performed by this change. Selected metadata is published; raw XML, indexed JSON and documentation bodies remain outside the repository.

## Validation and display

- Two existing component suites: 21 tests passed; TypeScript check passed. Cases cover native coordinate precision, conflicting parameter contexts, separate energy channels, documentary units, source paths, completeness and scientific-authority mutations, English UI and download controls.
- The production build passed with 52/52 static pages on the exact `ab2760b8be501318b290ec5a81a3718b9daa8b8a` base plus these frontend changes. PR101's separate private pages are not part of this branch base.
- Actual browser desktop 1280 px and mobile 320 px: document width matched viewport width. Open input/path/energy/JSON disclosures remained contained; matrix keyboard scrolling worked. Earlier input settings are folded by default when the complete projection is present.
- Initial browser JSON-click inspection correctly opened the resource rather than downloading it. The new-only link now has an explicit download attribute. The final production build and 21 tests were rerun after this correction. Actual native downloads of the new JSON, new checksum and retained old checksum matched their exact byte counts and hashes. The page stayed open after the corrected downloads; no console errors were recorded.
- Temporary viewport was reset, the owned tab was closed and the local server listener was removed. Screenshots were inspected inline; no saved screenshot artifact is claimed.
- Standalone secret scan of the new public metadata passed with zero findings and unchanged default scanner rules. Exact-commit CI and release/deployment/public acceptance remain separate work after publication.

The default page shows the reported geometry before method metadata. Full input contexts, energy differences, source identity and JSON are expandable. The existing route, navigation, English locale, source links and old metadata/checksum links are retained.
