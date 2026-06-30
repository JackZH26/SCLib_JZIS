# APS Data Freeze Protocol

Date: 2026-06-29

## Freeze Objective

Create a reproducible APS-only superconductivity data freeze for a
1986--2026 peer-reviewed-corpus scoping review. The freeze should be
deterministic from database exports and archived manifests. It must not
contain APS licensed full text, PDFs, OCR, or extracted article prose.

## Freeze Name

Recommended freeze identifier:

`aps_scope_2026_06_29`

If the production ingest is still actively running, use the date of the
actual final export instead, for example `aps_scope_2026_07_02`.

## Freeze Boundary

### Include

- `papers.source='aps'`
- `papers.status != 'retracted'`
- `papers.date_published` or `papers.year` in 1986--2026
- `papers.credibility_tier='T1'`
- APS metadata and abstract only
- `papers.materials_extracted` structured NER output
- `materials.records` derived structured facts
- `v_tc_geo` rows joined to `papers.source='aps'`
- `tdm_audit_log` metadata proving deletion, with file names/sizes only
- manifest/checkpoint/report files

### Exclude

- APS BagIt ZIPs
- APS PDFs
- APS full-text XML
- APS OCR/text payloads
- any `chunks.text` derived from full-text prose
- live Crossref or APS query results not archived in this freeze
- candidate DOI rows not successfully ingested, except in manifest
  coverage reports

## Pre-Freeze Stop Condition

Before exporting, pause APS ingest jobs and aggregation jobs long enough
to get a stable database snapshot. On VPS2:

```bash
cd /opt/SCLib_JZIS
docker compose ps
```

If timers exist, stop the APS yearly ingest timer and any aggregate timer
for the duration of the export. Record the exact UTC timestamp.

## Mandatory Compliance Checks

Run these before accepting the freeze:

```sql
SELECT status, deletion_confirmed, count(*)
FROM tdm_audit_log
WHERE source='aps'
GROUP BY 1,2
ORDER BY 1,2;

SELECT section, count(*)
FROM chunks
WHERE paper_id LIKE 'aps:%'
GROUP BY 1
ORDER BY 1;

SELECT count(*) AS bad_aps_chunks
FROM chunks
WHERE paper_id LIKE 'aps:%'
  AND section NOT IN ('Abstract', 'Facts');

SELECT credibility_tier, count(*)
FROM papers
WHERE source='aps'
GROUP BY 1
ORDER BY 1;
```

Acceptance criteria:

- all successful APS rows have `deletion_confirmed=true`
- `bad_aps_chunks = 0`
- APS chunks contain only `Abstract` and/or `Facts`
- manuscript-analysis rows are all `T1`

Also verify no temp directories remain:

```bash
find /dev/shm /tmp -maxdepth 3 -name 'aps-*' -type d 2>/dev/null
```

The expected result is no residual APS temp directories.

## Export Files

Place outputs under:

`ASP_SC_ScopeReview/data_freeze/snapshots/<freeze_id>/`

Required exports:

| File | Content |
|---|---|
| `papers_aps.csv.gz` | APS paper metadata, abstract, journal fields, status, related arXiv link |
| `paper_geo_aps.csv.gz` | APS paper-level geography, including country/city sets and geo status |
| `country_family_year_aps.csv.gz` | derived non-mutually-exclusive country/region x family x year table |
| `country_journal_year_aps.csv.gz` | derived country/region x journal x year table |
| `geo_country_normalization_v1.csv.gz` | archived country/region alias normalization table |
| `materials_extracted_aps.jsonl.gz` | one APS paper per line with structured NER records |
| `v_tc_geo_aps_strict.csv.gz` | strict APS material--Tc records joined to papers |
| `v_tc_geo_aps_full.csv.gz` | full APS material--Tc records before strict `Tc` filter |
| `tdm_audit_log_aps.csv.gz` | compliance/deletion audit metadata |
| `chunks_aps_authorized.csv.gz` | only abstract/fact chunks; no full text |
| `manifest_authorized_19860101_20261231.jsonl.gz` | candidate DOI universe |
| `manifest_harvest_ready.jsonl.gz` | harvest-ready DOI universe, if generated |
| `row_counts.csv` | invariant counts |
| `checksums.sha256` | SHA-256 for every exported file |
| `freeze_manifest.json` | freeze metadata, git commit, schema head, commands |

## Core Analysis Filters

The APS manuscript denominator should be:

```sql
p.source = 'aps'
AND p.status != 'retracted'
AND p.credibility_tier = 'T1'
AND p.year BETWEEN 1986 AND 2026
```

The strict APS material--Tc view should add:

```sql
v.tc_kelvin > 0
AND v.tc_kelvin <= 300
```

Pressure interpretation must keep null pressure separate:

- `pressure_gpa <= 1`: explicit low/ambient pressure
- `pressure_gpa > 1`: high pressure
- `pressure_gpa IS NULL`: pressure not stated, not ambient

Evidence interpretation should keep:

- `primary_experimental`
- `primary_theoretical`
- ambiguous `primary`
- `cited`
- null/blank

No APS paper should be treated as ground-truth superconductivity merely
because it is peer reviewed. APS means reviewed publication status, not
post-replication confirmation.

## Freeze Readiness Gates

Gate 1: Manifest gate

- authorized manifest exists and checksum is archived
- harvest-ready subset generated or documented as intentionally not used
- invalid DOI list archived, including `10.1103/466c-8sl4`

Gate 2: Ingest gate

- APS DOI rows ingested match the intended study scope
- annual coverage report generated for 1986--2026
- each processed DOI has a TDM audit row

Gate 3: Compliance gate

- no APS full-text chunk sections
- no temp residuals
- no BagIt/PDF/XML/OCR files in the freeze tree

Gate 4: Analysis gate

- `aggregate-materials` run after final ingest
- APS-only strict and full `v_tc_geo` exports generated
- row counts reproducible from exported CSVs
- 2026 is labeled partial if the freeze date precedes 2026-12-31

Gate 5: Geography gate

- APS paper-level geography coverage measured separately as:
  - geography row exists
  - non-empty country set exists
  - non-empty city set exists
- country/region name normalization table archived
- non-mutually-exclusive country counts exported
- fractional country-count sensitivity table exported
- country/region x family x period matrix exported for the manuscript
- missing-country sample frozen for manual review

Gate 6: Validation gate

- APS Golden sample frame frozen
- validation sample rows have local source availability status recorded
- validation outputs are not used as ground truth until human adjudication
  or multi-model comparison is complete

## Recommended Golden Validation Design

Mirror the arXiv Golden-400 protocol but adapt it for APS compliance:

- Do not archive APS full text in the Golden input packet.
- Archive only metadata, abstract, derived NER records, hashes, and
  processing provenance.
- For validator reruns, validators must access APS full text only through
  the same transient TDM path and must delete it immediately after
  extraction.

Suggested sample:

- 400 APS papers total, matching the arXiv Golden-400 design
- stratified by period: 1986--1990, 1991--1995, 1996--2000,
  2001--2005, 2006--2010, 2011--2015, 2016--2020, 2021--2025,
  2026 partial
- oversample material-bearing records, high-pressure records,
  above-100 K records, hydrides, cuprates, iron-based, and no-Tc papers
- include geography strata: USA, China, Japan, Germany, UK/EU aggregate,
  South Korea, Taiwan, India, multi-country papers, and missing-country
  cases
- include journal strata: PRB, PRL, PRX/PRResearch/PRMaterials,
  RMP/PRApplied/other

Interpretation:

- multi-model agreement is an agreement diagnostic, not ground-truth
  accuracy
- formula selection, evidence type, and pressure tier remain review
  targets

## Immediate Next Action

Run APS geography backfill on VPS2, rerun the preflight, and only then run
`scripts/export_aps_scope_freeze.sh` after confirming the APS ingest has
reached the desired scope. The export script is intentionally conservative
and writes only derived/authorized outputs.
