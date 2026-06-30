#!/usr/bin/env bash
set -euo pipefail

# Export a derived/authorized APS-only freeze from VPS2.
#
# Run from the SCLib repo root on VPS2:
#
#   bash ASP_SC_ScopeReview/scripts/export_aps_scope_freeze.sh aps_scope_2026_06_29
#
# This script writes only metadata, abstract/fact chunks, structured NER
# outputs, material records, and TDM audit metadata. It must never copy APS
# BagIt ZIPs, PDFs, XML, OCR, or full-text article prose.

FREEZE_ID="${1:-aps_scope_2026_06_29}"
OUT_DIR="ASP_SC_ScopeReview/data_freeze/snapshots/${FREEZE_ID}"
CHECKSUM_DIR="ASP_SC_ScopeReview/data_freeze/checksums"
AUTHORIZED_MANIFEST_DIR="${AUTHORIZED_MANIFEST_DIR:-audit/aps_manifest_20260616T065908Z_authorized_19860101_20261231}"
HARVEST_READY_MANIFEST="${HARVEST_READY_MANIFEST:-}"

mkdir -p "${OUT_DIR}" "${CHECKSUM_DIR}"

psql_raw() {
  local sql="$1"
  docker compose exec -T postgres psql -U sclib -d sclib -At -c "${sql}"
}

psql_csv() {
  local name="$1"
  local sql="$2"
  docker compose exec -T postgres psql -U sclib -d sclib \
    -c "\copy (${sql}) TO STDOUT WITH CSV HEADER" \
    | gzip -c > "${OUT_DIR}/${name}.csv.gz"
}

echo "[1/12] Recording git/schema metadata"
{
  echo "{"
  echo "  \"freeze_id\": \"${FREEZE_ID}\","
  echo "  \"created_utc\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\","
  echo "  \"git_commit\": \"$(git rev-parse HEAD)\","
  echo "  \"git_commit_short\": \"$(git rev-parse --short HEAD)\","
  echo "  \"authorized_manifest_dir\": \"${AUTHORIZED_MANIFEST_DIR}\","
  echo "  \"harvest_ready_manifest\": \"${HARVEST_READY_MANIFEST}\""
  echo "}"
} > "${OUT_DIR}/freeze_manifest.json"

echo "[2/12] Compliance checks"
docker compose exec -T postgres psql -U sclib -d sclib -c "
SELECT status, deletion_confirmed, count(*)
FROM tdm_audit_log
WHERE source='aps'
GROUP BY 1,2
ORDER BY 1,2;"

docker compose exec -T postgres psql -U sclib -d sclib -c "
SELECT section, count(*)
FROM chunks
WHERE paper_id LIKE 'aps:%'
GROUP BY 1
ORDER BY 1;"

docker compose exec -T postgres psql -U sclib -d sclib -c "
SELECT count(*) AS bad_aps_chunks
FROM chunks
WHERE paper_id LIKE 'aps:%'
  AND section NOT IN ('Abstract', 'Facts');"

BAD_CHUNKS="$(psql_raw "SELECT count(*) FROM chunks WHERE paper_id LIKE 'aps:%' AND section NOT IN ('Abstract', 'Facts');")"
if [[ "${BAD_CHUNKS}" != "0" ]]; then
  echo "ERROR: APS chunks include non-authorized sections: ${BAD_CHUNKS}" >&2
  exit 2
fi

UNCONFIRMED_DELETIONS="$(psql_raw "SELECT count(*) FROM tdm_audit_log WHERE source='aps' AND status='deleted' AND deletion_confirmed=false;")"
if [[ "${UNCONFIRMED_DELETIONS}" != "0" ]]; then
  echo "ERROR: APS deleted audit rows with deletion_confirmed=false: ${UNCONFIRMED_DELETIONS}" >&2
  exit 3
fi

GEO_ROWS="$(psql_raw "SELECT count(*) FROM (SELECT COALESCE(EXTRACT(YEAR FROM p.date_published)::int, CASE WHEN p.publication_ref->>'published_date' ~ '^[0-9]{4}' THEN substring(p.publication_ref->>'published_date' from 1 for 4)::int END) AS paper_year, paper_geo FROM papers p WHERE p.source='aps') q WHERE paper_year BETWEEN 1986 AND 2026 AND paper_geo IS NOT NULL;")"
if [[ "${GEO_ROWS}" == "0" && "${ALLOW_MISSING_GEO:-0}" != "1" ]]; then
  echo "ERROR: APS paper_geo coverage is zero; final geography-capable freeze is not ready." >&2
  echo "Set ALLOW_MISSING_GEO=1 only for a non-final, non-geography pilot export." >&2
  exit 6
fi

COUNTRY_ROWS="$(psql_raw "SELECT count(*) FROM (SELECT COALESCE(EXTRACT(YEAR FROM p.date_published)::int, CASE WHEN p.publication_ref->>'published_date' ~ '^[0-9]{4}' THEN substring(p.publication_ref->>'published_date' from 1 for 4)::int END) AS paper_year, paper_geo FROM papers p WHERE p.source='aps') q WHERE paper_year BETWEEN 1986 AND 2026 AND jsonb_array_length(COALESCE(paper_geo->'countries', '[]'::jsonb)) > 0;")"
if [[ "${COUNTRY_ROWS}" == "0" && "${ALLOW_MISSING_GEO:-0}" != "1" ]]; then
  echo "ERROR: APS non-empty country coverage is zero; final geography-capable freeze is not ready." >&2
  echo "Set ALLOW_MISSING_GEO=1 only for a non-final, non-geography pilot export." >&2
  exit 7
fi

if find /dev/shm /tmp -maxdepth 3 -name 'aps-*' -type d 2>/dev/null | grep -q .; then
  echo "ERROR: residual APS temp dirs found under /dev/shm or /tmp" >&2
  find /dev/shm /tmp -maxdepth 3 -name 'aps-*' -type d 2>/dev/null >&2
  exit 4
fi

echo "[3/12] Archive manifest inputs"
if [[ -d "${AUTHORIZED_MANIFEST_DIR}" ]]; then
  for src in \
    "${AUTHORIZED_MANIFEST_DIR}/aps_superconductivity_dois.txt" \
    "${AUTHORIZED_MANIFEST_DIR}/aps_superconductivity_manifest.jsonl" \
    "${AUTHORIZED_MANIFEST_DIR}/aps_superconductivity_manifest.csv" \
    "${AUTHORIZED_MANIFEST_DIR}/APS_SUPERCONDUCTIVITY_COVERAGE.md" \
    "${AUTHORIZED_MANIFEST_DIR}/aps_superconductivity_authorized_19860101_20261231_dois.txt" \
    "${AUTHORIZED_MANIFEST_DIR}/aps_superconductivity_authorized_19860101_20261231_manifest.jsonl"; do
    if [[ -f "${src}" ]]; then
      base="$(basename "${src}")"
      gzip -c "${src}" > "${OUT_DIR}/manifest_authorized_${base}.gz"
    fi
  done
else
  echo "WARNING: authorized manifest dir not found: ${AUTHORIZED_MANIFEST_DIR}" >&2
fi

if [[ -n "${HARVEST_READY_MANIFEST}" && -f "${HARVEST_READY_MANIFEST}" ]]; then
  gzip -c "${HARVEST_READY_MANIFEST}" > "${OUT_DIR}/manifest_harvest_ready.jsonl.gz"
fi

GEO_NORMALIZATION="ASP_SC_ScopeReview/data_freeze/manifest_inputs/aps_geo_country_normalization_v1.csv"
if [[ -f "${GEO_NORMALIZATION}" ]]; then
  gzip -c "${GEO_NORMALIZATION}" > "${OUT_DIR}/geo_country_normalization_v1.csv.gz"
fi

echo "[4/12] Export APS papers"
psql_csv "papers_aps" "
WITH aps_papers AS (
  SELECT p.*,
         COALESCE(
           EXTRACT(YEAR FROM p.date_published)::int,
           CASE WHEN p.publication_ref->>'published_date' ~ '^[0-9]{4}'
                THEN substring(p.publication_ref->>'published_date' from 1 for 4)::int
           END
         ) AS paper_year
  FROM papers p
  WHERE p.source='aps'
)
SELECT id, source, doi, external_id, id_scheme, title, abstract, authors,
       journal, journal_abbrev, publication_ref, date_published, year,
       status, credibility_tier, related_paper_id, indexed_at,
       chunk_count, paper_geo
FROM (
  SELECT *, paper_year AS year FROM aps_papers
) q
WHERE year BETWEEN 1986 AND 2026
ORDER BY year, doi"

echo "[5/12] Export APS geography tables"
psql_csv "paper_geo_aps" "
WITH aps_papers AS (
  SELECT p.*,
         COALESCE(
           EXTRACT(YEAR FROM p.date_published)::int,
           CASE WHEN p.publication_ref->>'published_date' ~ '^[0-9]{4}'
                THEN substring(p.publication_ref->>'published_date' from 1 for 4)::int
           END
         ) AS paper_year
  FROM papers p
  WHERE p.source='aps'
)
SELECT id AS paper_id, doi, journal_abbrev, year, date_published,
       paper_geo->'countries' AS countries,
       paper_geo->'cities' AS cities,
       paper_geo->>'status' AS geo_status,
       paper_geo->>'confidence' AS geo_confidence
FROM (
  SELECT *, paper_year AS year FROM aps_papers
) q
WHERE year BETWEEN 1986 AND 2026
ORDER BY year, doi"

psql_csv "country_family_year_aps" "
WITH aps_records AS (
  SELECT v.*, p.id AS aps_paper_id, p.paper_geo,
         COALESCE(
           EXTRACT(YEAR FROM p.date_published)::int,
           CASE WHEN p.publication_ref->>'published_date' ~ '^[0-9]{4}'
                THEN substring(p.publication_ref->>'published_date' from 1 for 4)::int
           END
         ) AS paper_year
  FROM v_tc_geo v
  JOIN papers p ON p.id = v.paper_id
  WHERE p.source='aps'
    AND p.status != 'retracted'
    AND p.credibility_tier='T1'
    AND v.tc_kelvin > 0
    AND v.tc_kelvin <= 300
)
SELECT a.paper_year AS year,
       COALESCE(c.country, '(missing)') AS country,
       COALESCE(a.family, '(missing)') AS family,
       count(*) AS strict_tc_records,
       count(DISTINCT a.aps_paper_id) AS papers
FROM aps_records a
LEFT JOIN LATERAL jsonb_array_elements_text(
    COALESCE(a.paper_geo->'countries', '[]'::jsonb)
) AS c(country) ON true
WHERE a.paper_year BETWEEN 1986 AND 2026
GROUP BY a.paper_year, COALESCE(c.country, '(missing)'), COALESCE(a.family, '(missing)')
ORDER BY year, country, family"

psql_csv "country_journal_year_aps" "
WITH aps_papers AS (
  SELECT p.*,
         COALESCE(
           EXTRACT(YEAR FROM p.date_published)::int,
           CASE WHEN p.publication_ref->>'published_date' ~ '^[0-9]{4}'
                THEN substring(p.publication_ref->>'published_date' from 1 for 4)::int
           END
         ) AS paper_year
  FROM papers p
  WHERE p.source='aps'
    AND p.status != 'retracted'
    AND p.credibility_tier='T1'
)
SELECT p.paper_year AS year,
       COALESCE(c.country, '(missing)') AS country,
       COALESCE(p.journal_abbrev, '(missing)') AS journal_abbrev,
       count(DISTINCT p.id) AS papers
FROM aps_papers p
LEFT JOIN LATERAL jsonb_array_elements_text(
    COALESCE(p.paper_geo->'countries', '[]'::jsonb)
) AS c(country) ON true
WHERE p.paper_year BETWEEN 1986 AND 2026
GROUP BY p.paper_year, COALESCE(c.country, '(missing)'), COALESCE(p.journal_abbrev, '(missing)')
ORDER BY year, country, journal_abbrev"

echo "[6/12] Export APS material NER payloads"
docker compose exec -T postgres psql -U sclib -d sclib -At \
  -c "
WITH aps_papers AS (
  SELECT p.*,
         COALESCE(
           EXTRACT(YEAR FROM p.date_published)::int,
           CASE WHEN p.publication_ref->>'published_date' ~ '^[0-9]{4}'
                THEN substring(p.publication_ref->>'published_date' from 1 for 4)::int
           END
         ) AS paper_year
  FROM papers p
  WHERE p.source='aps'
)
SELECT jsonb_build_object(
  'paper_id', id,
  'doi', doi,
  'journal_abbrev', journal_abbrev,
  'year', paper_year,
  'materials_extracted', materials_extracted
)::text
FROM aps_papers
WHERE paper_year BETWEEN 1986 AND 2026
ORDER BY paper_year, doi
" | gzip -c > "${OUT_DIR}/materials_extracted_aps.jsonl.gz"

echo "[7/12] Export APS strict Tc view"
psql_csv "v_tc_geo_aps_strict" "
WITH aps_records AS (
  SELECT v.*, p.doi, p.journal_abbrev, p.date_published,
         COALESCE(
           EXTRACT(YEAR FROM p.date_published)::int,
           CASE WHEN p.publication_ref->>'published_date' ~ '^[0-9]{4}'
                THEN substring(p.publication_ref->>'published_date' from 1 for 4)::int
           END
         ) AS paper_year
  FROM v_tc_geo v
  JOIN papers p ON p.id = v.paper_id
  WHERE p.source='aps'
    AND p.status != 'retracted'
    AND p.credibility_tier='T1'
    AND v.tc_kelvin > 0
    AND v.tc_kelvin <= 300
)
SELECT material_id, formula, family, paper_id, doi,
       journal_abbrev, paper_year AS year, date_published,
       tc_kelvin, pressure_gpa, evidence_type,
       cities, countries, geo_confidence, geo_status
FROM aps_records
WHERE paper_year BETWEEN 1986 AND 2026
ORDER BY year, doi, formula"

echo "[8/12] Export APS full Tc view"
psql_csv "v_tc_geo_aps_full" "
WITH aps_records AS (
  SELECT v.*, p.doi, p.journal_abbrev, p.date_published,
         COALESCE(
           EXTRACT(YEAR FROM p.date_published)::int,
           CASE WHEN p.publication_ref->>'published_date' ~ '^[0-9]{4}'
                THEN substring(p.publication_ref->>'published_date' from 1 for 4)::int
           END
         ) AS paper_year
  FROM v_tc_geo v
  JOIN papers p ON p.id = v.paper_id
  WHERE p.source='aps'
)
SELECT material_id, formula, family, paper_id, doi,
       journal_abbrev, paper_year AS year, date_published,
       tc_kelvin, pressure_gpa, evidence_type,
       cities, countries, geo_confidence, geo_status
FROM aps_records
WHERE paper_year BETWEEN 1986 AND 2026
ORDER BY year, doi, formula"

echo "[9/12] Export APS TDM audit and authorized chunks"
psql_csv "tdm_audit_log_aps" "
SELECT source, doi, paper_id, harvested_at, processed_at, bagit_bytes,
       files_processed, ner_record_count, deleted_at, deletion_confirmed,
       temp_path, status, error, created_at
FROM tdm_audit_log
WHERE source='aps'
ORDER BY created_at, doi"

psql_csv "chunks_aps_authorized" "
SELECT id, paper_id, chunk_index, section, text
FROM chunks
WHERE paper_id LIKE 'aps:%'
  AND section IN ('Abstract', 'Facts')
ORDER BY paper_id, chunk_index"

echo "[10/12] Row counts"
docker compose exec -T postgres psql -U sclib -d sclib \
  -c "\copy (
WITH aps_papers AS (
  SELECT p.*,
         COALESCE(
           EXTRACT(YEAR FROM p.date_published)::int,
           CASE WHEN p.publication_ref->>'published_date' ~ '^[0-9]{4}'
                THEN substring(p.publication_ref->>'published_date' from 1 for 4)::int
           END
         ) AS paper_year
  FROM papers p
  WHERE p.source='aps'
)
SELECT 'aps_papers' AS metric, count(*)::text AS value
FROM aps_papers WHERE paper_year BETWEEN 1986 AND 2026
UNION ALL
SELECT 'aps_t1_active_papers', count(*)::text
FROM aps_papers
WHERE status!='retracted' AND credibility_tier='T1'
  AND paper_year BETWEEN 1986 AND 2026
UNION ALL
SELECT 'aps_strict_tc_records', count(*)::text
FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id
WHERE p.source='aps' AND p.status!='retracted' AND p.credibility_tier='T1'
  AND COALESCE(
        EXTRACT(YEAR FROM p.date_published)::int,
        CASE WHEN p.publication_ref->>'published_date' ~ '^[0-9]{4}'
             THEN substring(p.publication_ref->>'published_date' from 1 for 4)::int
        END
      ) BETWEEN 1986 AND 2026
  AND v.tc_kelvin > 0 AND v.tc_kelvin <= 300
UNION ALL
SELECT 'aps_bad_chunks', count(*)::text
FROM chunks
WHERE paper_id LIKE 'aps:%'
  AND section NOT IN ('Abstract', 'Facts')
UNION ALL
SELECT 'aps_tdm_unconfirmed', count(*)::text
FROM tdm_audit_log
WHERE source='aps' AND status='deleted' AND deletion_confirmed=false
UNION ALL
SELECT 'aps_geo_rows', count(*)::text
FROM aps_papers
WHERE paper_year BETWEEN 1986 AND 2026
  AND paper_geo IS NOT NULL
UNION ALL
SELECT 'aps_nonempty_country_sets', count(*)::text
FROM aps_papers
WHERE paper_year BETWEEN 1986 AND 2026
  AND jsonb_array_length(COALESCE(paper_geo->'countries', '[]'::jsonb)) > 0
) TO STDOUT WITH CSV HEADER" > "${OUT_DIR}/row_counts.csv"

echo "[11/12] Guard against forbidden APS licensed files in freeze tree"
if find "${OUT_DIR}" -type f \( -iname '*.zip' -o -iname '*.pdf' -o -iname '*.xml' -o -iname '*.ocr' \) | grep -q .; then
  echo "ERROR: forbidden APS licensed file type found in freeze output" >&2
  find "${OUT_DIR}" -type f \( -iname '*.zip' -o -iname '*.pdf' -o -iname '*.xml' -o -iname '*.ocr' \) >&2
  exit 5
fi

echo "[12/12] Checksums"
find "${OUT_DIR}" -maxdepth 1 -type f -print0 \
  | sort -z \
  | xargs -0 shasum -a 256 > "${CHECKSUM_DIR}/${FREEZE_ID}.sha256"

echo "Freeze export complete: ${OUT_DIR}"
echo "Checksums: ${CHECKSUM_DIR}/${FREEZE_ID}.sha256"
