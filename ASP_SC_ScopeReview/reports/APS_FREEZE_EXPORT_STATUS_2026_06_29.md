# APS Freeze Export Status

UTC status time: 2026-06-30T11:17Z

## Current State

- APS geography backfill completed successfully on VPS2.
- Detached container `sclib-aps-geo-backfill-20260629` exited `0` after
  finishing `28,277 / 28,277` queued rows.
- Freeze preflight passed for `aps_scope_2026_06_30`.
- Freeze export completed successfully for `aps_scope_2026_06_30`.
- Remote and local checksum verification both passed.

## Last Observed Counts

- APS papers: 28,307.
- APS strict Tc records: 17,846.
- APS `paper_geo` rows: 28,307.
- APS non-empty country sets: 24,696.
- APS `paper_geo IS NULL`: 0.
- Bad APS chunks: 0.
- Unconfirmed deleted audit rows: 0.

## Last Observed Progress

- Backfill completion time: `2026-06-30T08:58:32Z`.
- Backfill summary: `ok=25,023`, `no_affiliations=3,254`.
- Preflight report:
  `ASP_SC_ScopeReview/reports/aps_scope_2026_06_30_preflight_20260630T111509Z.md`.
- Freeze snapshot:
  `ASP_SC_ScopeReview/data_freeze/snapshots/aps_scope_2026_06_30/`.
- Freeze checksum file:
  `ASP_SC_ScopeReview/data_freeze/checksums/aps_scope_2026_06_30.sha256`.

## Current Geography Status Mix

- `aps_jats_aff`, `ok`: 18,256 papers.
- `aps_ocr_front_country_scan`, `ok`: 6,560 papers.
- `aps_ocr_front_country_scan`, `no_affiliations`: 2,984 papers.
- `aps_jats_aff`, `no_affiliations`: 275 papers.

## Current Tail Years

- `2026`: 532 / 532 papers have `paper_geo`.
- `2025`: 1,053 / 1,053 papers have `paper_geo`.
- `2024`: 1,039 / 1,039 papers have `paper_geo`.
- `2023`: 918 / 918 papers have `paper_geo`.

## Monitor Commands

```bash
docker logs --tail 80 sclib-aps-geo-backfill-20260629
docker ps --filter name=sclib-aps-geo-backfill-20260629 --format "{{.Names}} {{.Status}}"
```

```bash
docker compose exec -T postgres psql -U sclib -d sclib -Atc "
SELECT
  count(*) FILTER (WHERE paper_geo IS NOT NULL) AS geo_rows,
  count(*) FILTER (
    WHERE jsonb_array_length(COALESCE(paper_geo->'countries','[]'::jsonb)) > 0
  ) AS country_rows,
  count(*) FILTER (WHERE paper_geo IS NULL) AS missing_geo,
  count(*) AS aps_papers
FROM papers
WHERE source='aps';"
```

## Next Gates

1. Start APS 1986--2026 scoping analysis from the frozen snapshot.
2. Build Golden-400 and geography timelines from `v_tc_geo_aps_strict.csv.gz`,
   `paper_geo_aps.csv.gz`, and `country_family_year_aps.csv.gz`.
3. Draft the APS manuscript in the new study directory with APS/RevTeX
   authorship blocks for Jian Zhou.
