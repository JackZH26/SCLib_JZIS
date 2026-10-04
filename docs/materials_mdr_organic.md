# Versioned Organic source references

The Materials catalogue, source-reference page and MDR details panel link to
`/materials/source-references/organic`. This adds the complete Organic table from
MDR SuperCon version 240322 as a searchable reading and export surface. The
existing oxide/metallic composition-matching API and its immutable v1 semantics
remain unchanged; Organic molecular names are not sent through that matcher.

## Source and inventory

- Dataset: [NIMS MDR SuperCon Ver.240322](https://doi.org/10.48505/nims.4487), CC BY 4.0.
- Original file: [240322_MDR_Organic.txt](https://mdr.nims.go.jp/filesets/1a18e447-8ec2-4316-be12-b4acdc885fb8/download), 263,372 bytes, SHA-256 `d116848a90d01e48356ed6cf0bb69035fa863a3a559deac1ef188025bdb3b423`.
- [Official English guide](https://mdr.nims.go.jp/filesets/dd00e931-e7b7-4bc5-bde2-ba0ff1e9adaf/download), page 9; SHA-256 `89096c1f006a5d5c256d14394880b31684ad2ce0b4f7ea0d37175256ea6a029d`.

The actual file has two header rows and 49 columns. Its 569 subsequent CSV
records include one entirely empty trailing record: 568 nonempty source rows
remain. Earlier audit counts of 569 referred to the raw data-record count and
must not be read as 569 populated scientific records. All 49 original cells,
including empty strings, whitespace, names, bibliography and remarks, survive
in source order. Physical line spans and complete raw-row hashes are retained;
quoted multiline cells are parsed with CSV rules. The excluded empty row also
has a span and hash. Original bytes and a lossless JSON projection are available
for download, with NIMS attribution, version, licence and a JSON checksum.

Nonempty counts include 517 `tc`, 83 `tcmax`, 484 `pcrit`, 74 `pmax`, 23 `tcn`,
70 `hc2zero`, 73 `cohere`, 41 `penet` and 31 `gamma` cells. These counts describe
source cells, not independent experiments, unique materials or formal catalogue
field promotions. All 568 rows are accessible through 29 pages of 20 rows.

## Meaning and units

The source `tc` header says “Tc at pcrit or Tc at atmospheric pressure”; the guide
shortens this to “Tc at pcrit”. Both facts are retained. A missing `pcrit` cell
does not establish ambient pressure. A reported zero remains the raw source zero.

Organic `tcmax` is maximum Tc under pressure, with `pmax` as its associated
applied pressure. This differs from the oxide/metallic maximum-applied-pressure
definition. `tcn` is a lowest measurement temperature in a non-SC report and is
never relabelled as Tc. `pcrit` explicitly supplies GPa in the source header.
The remaining numeric columns have no unit fields: the reader labels them raw
and does not infer K, Å, degrees, tesla or other units. Comments can supply
additional conditions/units but remain original text, not automatic normalized
values or corrections to table cells. The source's `debyet` symbol is retained
despite the guide's `Z` entry for Debye temperature.

Full material names, common-name fragments, structure labels, isotopes, sample
labels and remarks remain separate. Rows 2 and 3 have the same full name but
different hydrogenated/deuterated remarks and pressure cells; they are not
deduplicated. The exact labels `Picene` and `picene` also remain separate filter
options. Case-insensitive text search helps discover names/remarks without
establishing a chemical, phase or sample identity. Guide codebooks decode sample
form and measurement methods; unknown codes remain unresolved and all raw
codes remain available.

## Interface and exports

The default table shows full name, transition values, pressure context, source
year/reference and method. Per-row disclosures show source remarks and available
properties, with all 49 original cells under a second disclosure. Details wrap
within the mobile viewport even when the comparison table scrolls horizontally.
Coverage and interpretation appear once, under dataset details.

Native GET filters cover source text, exact source structure label and a nonempty
property field. URLs preserve pagination and support exact source-row links;
invalid/repeated filters produce an explicit recoverable error. Empty results
and out-of-range pages do not silently show unrelated data. The keyboard-focusable
comparison table contains its own horizontal overflow.

The export endpoint uses the same filter function and returns **all matching
rows**, independent of the displayed page. It includes all original cells,
source metadata and snapshot hash. Its `X-Content-SHA256` header hashes the actual
UTF-8 response bytes; the filename uses the hash prefix. The full immutable JSON
has a separate SHA-256 download. No CSV export reinterprets leading source text
as spreadsheet formulas.

No API/database write, catalogue association, scientific acceptance or ML
approval is created. Original-paper publication status and figure/data files
are not reviewed by this import. The reader improves access to the source and
supports subsequent per-record review; it does not certify source conclusions.

## Reproduction

```sh
python scripts/build_mdr_organic_reference.py --source /path/to/240322_MDR_Organic.txt
python -m pytest -q scripts/tests/test_mdr_organic_reference.py
```

The builder accepts only the exact pinned source bytes, verifies headers, IDs,
row count and physical boundaries, then reproduces the JSON/checksum and original
table asset. Tests independently compare every source cell and all row spans,
plus pressure roles, isotope distinctions, missing/zero cells, pagination,
filters, exports, hash headers, invalid input, source-prefix URLs and English UI.
Local verification does not substitute for required PR CI and deployed acceptance.

## Local acceptance, 2026-10-05

The final production build passed, together with 46 frontend source checks,
2,745 unit/component tests across 124 files, the two independent Python source
tests, and Ruff on the builder/test files. The Organic route adds 169 B of route
JavaScript; the source table is rendered on the server.

Actual production-preview browser checks covered the full-table final page
(561–568 of 568), TMTSF final page (41–46 of 46), clearing filters and browser
Back restoring the selected filter/result pair, a row-3 deep link with its
deuterated source remark, and an empty search. At 1,280 px and 320 px there was
no outer horizontal overflow. The narrow table scrolls independently by keyboard;
expanded source remarks wrap within the viewport. No browser console errors
were observed. The default table shows supplied values; empty original cells
remain available in the full disclosure and downloads.

An actual browser download from the TMTSF final page contained all 46 matching
rows, not just the six visible rows. Every exported raw cell matched the pinned
source. Its 56,652 UTF-8 bytes matched the local export response exactly, with
SHA-256 `e0806aaceea46c38ad25e52f1d640a92b73a1fef9edf3ae4bc31b9ce2ccc0eb0`.
The download route did not change in the final layout-only refinement.
