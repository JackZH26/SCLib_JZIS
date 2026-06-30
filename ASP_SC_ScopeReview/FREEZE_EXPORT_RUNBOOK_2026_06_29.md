# APS Freeze Export Runbook

Date: 2026-06-29

This is the operational runbook for preparing and exporting the APS
scoping-review freeze from VPS2. It assumes the scripts in
`ASP_SC_ScopeReview/scripts/` have been copied to or committed in the
production SCLib repository on VPS2.

## 0. Choose Freeze ID

Use the actual export date:

```bash
export FREEZE_ID=aps_scope_$(date -u +%Y_%m_%d)
```

If the freeze is exported on 2026-06-29, this becomes
`aps_scope_2026_06_29`.

## 1. Enter Repository

The docs use `/opt/SCLib_JZIS`; older docs sometimes use `/opt/sclib`.
Use the path that exists on VPS2:

```bash
cd /opt/SCLib_JZIS
git rev-parse --short HEAD
docker compose ps
```

## 2. Pause Mutating Jobs

Pause APS ingest and aggregate jobs before exporting. Use whichever units
exist on VPS2:

```bash
systemctl list-timers | grep -E 'sclib|aps|aggregate' || true
sudo systemctl stop sclib-aps-yearly-ingest.timer 2>/dev/null || true
sudo systemctl stop sclib-aggregate.timer 2>/dev/null || true
```

Do not stop Postgres/API unless there is a separate operational reason.

## 3. Run Aggregate Once

Make sure latest APS paper NER outputs have been folded into `materials`
and `v_tc_geo`:

```bash
docker compose run --rm ingestion sclib-ingest --mode aggregate-materials
```

## 4. Backfill APS Geography

Run a small APS geography pilot first. This downloads APS BagIt packages
through the approved transient TDM path, parses only JATS affiliation
front matter, writes `papers.affiliations` / `papers.paper_geo`, deletes
the temp files, and appends `tdm_audit_log` rows.

```bash
docker compose run --rm \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -v /opt/SCLib_JZIS/ASP_SC_ScopeReview:/app/ASP_SC_ScopeReview \
  ingestion \
  python /app/ASP_SC_ScopeReview/scripts/backfill_aps_paper_geo.py --limit 100
```

If the pilot shows acceptable `ok` and country coverage, run the full
backfill:

```bash
docker compose run --rm \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -v /opt/SCLib_JZIS/ASP_SC_ScopeReview:/app/ASP_SC_ScopeReview \
  ingestion \
  python /app/ASP_SC_ScopeReview/scripts/backfill_aps_paper_geo.py --retry-failed
```

For a long full run, use a detached container and monitor with
`docker logs`:

```bash
docker rm -f sclib-aps-geo-backfill-20260629 2>/dev/null || true
docker compose run -d \
  --name sclib-aps-geo-backfill-20260629 \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -v /opt/SCLib_JZIS/ASP_SC_ScopeReview:/app/ASP_SC_ScopeReview \
  ingestion \
  python /app/ASP_SC_ScopeReview/scripts/backfill_aps_paper_geo.py --retry-failed

docker logs --tail 80 sclib-aps-geo-backfill-20260629
```

Because APS BagIt downloads are rate-limited, the full run may take many
hours. Do not export a final geography-capable freeze until this step has
completed or the remaining missing coverage has been explicitly accepted.

## 5. Run Read-Only Preflight

```bash
bash ASP_SC_ScopeReview/scripts/preflight_aps_scope_freeze.sh "$FREEZE_ID"
```

The preflight must report:

- `Bad APS chunks = 0`
- `Unconfirmed deleted audit rows = 0`
- nonzero APS paper geography rows
- nonzero non-empty APS country sets
- nonzero APS paper count
- nonzero strict Tc record count if the corpus has been ingested beyond
  metadata-only smoke tests

Review the generated report in `ASP_SC_ScopeReview/reports/`.

## 6. Export Freeze

If the authorized manifest lives in `/opt/sclib_aps_manifests`, pass it
explicitly:

```bash
AUTHORIZED_MANIFEST_DIR=/opt/sclib_aps_manifests \
bash ASP_SC_ScopeReview/scripts/export_aps_scope_freeze.sh "$FREEZE_ID"
```

If a single harvest-ready manifest has been generated, include it:

```bash
AUTHORIZED_MANIFEST_DIR=/opt/sclib_aps_manifests \
HARVEST_READY_MANIFEST=/opt/sclib_aps_manifests/aps_superconductivity_harvest_ready.jsonl \
bash ASP_SC_ScopeReview/scripts/export_aps_scope_freeze.sh "$FREEZE_ID"
```

The export will fail if:

- APS chunks include sections other than `Abstract` or `Facts`
- any `status='deleted'` audit rows have `deletion_confirmed=false`
- APS `paper_geo` coverage is zero, unless `ALLOW_MISSING_GEO=1` is set
  for a non-final, non-geography pilot export
- residual APS temp directories exist under `/dev/shm` or `/tmp`
- forbidden APS licensed file types appear in the freeze output

## 7. Verify Output

```bash
OUT="ASP_SC_ScopeReview/data_freeze/snapshots/$FREEZE_ID"
ls -lh "$OUT"
cat "$OUT/row_counts.csv"
shasum -a 256 -c "ASP_SC_ScopeReview/data_freeze/checksums/${FREEZE_ID}.sha256"
```

Confirm there are no licensed-material files:

```bash
find "$OUT" -type f \( -iname '*.zip' -o -iname '*.pdf' -o -iname '*.xml' -o -iname '*.ocr' \) -print
```

Expected: no output.

## 8. Resume Jobs

Only after the snapshot is complete:

```bash
sudo systemctl start sclib-aggregate.timer 2>/dev/null || true
sudo systemctl start sclib-aps-yearly-ingest.timer 2>/dev/null || true
systemctl list-timers | grep -E 'sclib|aps|aggregate' || true
```

## 9. Copy Freeze Back For Analysis

From the local machine, after confirming the export path:

```bash
rsync -avz root@72.62.251.29:/opt/SCLib_JZIS/ASP_SC_ScopeReview/data_freeze/snapshots/$FREEZE_ID/ \
  /Users/jackzhou/Documents/JZIS/SCLib/ASP_SC_ScopeReview/data_freeze/snapshots/$FREEZE_ID/

rsync -avz root@72.62.251.29:/opt/SCLib_JZIS/ASP_SC_ScopeReview/data_freeze/checksums/${FREEZE_ID}.sha256 \
  /Users/jackzhou/Documents/JZIS/SCLib/ASP_SC_ScopeReview/data_freeze/checksums/
```

Then verify locally:

```bash
cd /Users/jackzhou/Documents/JZIS/SCLib
shasum -a 256 -c ASP_SC_ScopeReview/data_freeze/checksums/${FREEZE_ID}.sha256
```

## 10. Minimum Handoff Summary

Record in `ASP_SC_ScopeReview/reports/`:

- freeze id
- git commit
- export UTC timestamp
- APS paper count
- APS strict Tc record count
- APS paper_geo coverage
- bad chunk count
- unconfirmed deletion count
- checksum file path
