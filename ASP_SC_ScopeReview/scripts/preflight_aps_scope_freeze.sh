#!/usr/bin/env bash
set -euo pipefail

# Read-only preflight for an APS scope-review freeze.
#
# Run from the SCLib repo root on VPS2:
#
#   bash ASP_SC_ScopeReview/scripts/preflight_aps_scope_freeze.sh aps_scope_2026_06_29
#
# This script does not export data. It writes a short report with row
# counts and compliance gates so the actual freeze export can fail less
# dramatically.

FREEZE_ID="${1:-aps_scope_2026_06_29}"
REPORT_DIR="ASP_SC_ScopeReview/reports"
REPORT="${REPORT_DIR}/${FREEZE_ID}_preflight_$(date -u +%Y%m%dT%H%M%SZ).md"

mkdir -p "${REPORT_DIR}"

psql_table() {
  local sql="$1"
  docker compose exec -T postgres psql -U sclib -d sclib -P pager=off -c "${sql}"
}

psql_scalar() {
  local sql="$1"
  docker compose exec -T postgres psql -U sclib -d sclib -At -c "${sql}"
}

append_sql() {
  local title="$1"
  local sql="$2"
  {
    echo
    echo "## ${title}"
    echo
    echo '```text'
    psql_table "${sql}"
    echo '```'
  } >> "${REPORT}"
}

echo "# APS Freeze Preflight" > "${REPORT}"
{
  echo
  echo "- Freeze id: \`${FREEZE_ID}\`"
  echo "- UTC: \`$(date -u +%Y-%m-%dT%H:%M:%SZ)\`"
  echo "- Git commit: \`$(git rev-parse HEAD)\`"
  echo "- Git short: \`$(git rev-parse --short HEAD)\`"
} >> "${REPORT}"

append_sql "APS Paper Counts" "
SELECT source, credibility_tier, status, count(*)
FROM papers
WHERE source='aps'
GROUP BY 1,2,3
ORDER BY 1,2,3;"

append_sql "APS Year Coverage" "
WITH aps_papers AS (
  SELECT COALESCE(
           EXTRACT(YEAR FROM p.date_published)::int,
           CASE WHEN p.publication_ref->>'published_date' ~ '^[0-9]{4}'
                THEN substring(p.publication_ref->>'published_date' from 1 for 4)::int
           END
         ) AS paper_year
  FROM papers p
  WHERE p.source='aps'
)
SELECT paper_year AS year, count(*) AS papers
FROM aps_papers
WHERE paper_year BETWEEN 1986 AND 2026
GROUP BY paper_year
ORDER BY paper_year;"

append_sql "APS Journal Coverage" "
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
SELECT COALESCE(journal_abbrev, '(missing)') AS journal_abbrev, count(*) AS papers
FROM aps_papers
WHERE paper_year BETWEEN 1986 AND 2026
GROUP BY 1
ORDER BY papers DESC, journal_abbrev;"

append_sql "TDM Deletion Audit" "
SELECT status, deletion_confirmed, count(*)
FROM tdm_audit_log
WHERE source='aps'
GROUP BY 1,2
ORDER BY 1,2;"

append_sql "APS Chunk Sections" "
SELECT section, count(*)
FROM chunks
WHERE paper_id LIKE 'aps:%'
GROUP BY 1
ORDER BY 1;"

append_sql "APS Strict Tc Denominators" "
WITH aps_records AS (
  SELECT v.*, p.id AS aps_paper_id,
         COALESCE(
           EXTRACT(YEAR FROM p.date_published)::int,
           CASE WHEN p.publication_ref->>'published_date' ~ '^[0-9]{4}'
                THEN substring(p.publication_ref->>'published_date' from 1 for 4)::int
           END
         ) AS paper_year
  FROM v_tc_geo v
  JOIN papers p ON p.id=v.paper_id
  WHERE p.source='aps' AND p.status!='retracted' AND p.credibility_tier='T1'
    AND v.tc_kelvin > 0 AND v.tc_kelvin <= 300
)
SELECT 'strict_tc_records' AS metric, count(*)::text AS value
FROM aps_records
WHERE paper_year BETWEEN 1986 AND 2026
UNION ALL
SELECT 'strict_tc_papers', count(DISTINCT aps_paper_id)::text
FROM aps_records
WHERE paper_year BETWEEN 1986 AND 2026
UNION ALL
SELECT 'strict_formulas', count(DISTINCT formula)::text
FROM aps_records
WHERE paper_year BETWEEN 1986 AND 2026;"

append_sql "APS Geography Coverage" "
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
FROM aps_papers
WHERE paper_year BETWEEN 1986 AND 2026
UNION ALL
SELECT 'paper_geo_rows', count(*)::text
FROM aps_papers
WHERE paper_year BETWEEN 1986 AND 2026
  AND paper_geo IS NOT NULL
UNION ALL
SELECT 'nonempty_country_sets', count(*)::text
FROM aps_papers
WHERE paper_year BETWEEN 1986 AND 2026
  AND jsonb_array_length(COALESCE(paper_geo->'countries', '[]'::jsonb)) > 0
UNION ALL
SELECT 'multi_country_papers', count(*)::text
FROM aps_papers
WHERE paper_year BETWEEN 1986 AND 2026
  AND jsonb_array_length(COALESCE(paper_geo->'countries', '[]'::jsonb)) >= 2;"

BAD_CHUNKS="$(psql_scalar "SELECT count(*) FROM chunks WHERE paper_id LIKE 'aps:%' AND section NOT IN ('Abstract', 'Facts');")"
UNCONFIRMED="$(psql_scalar "SELECT count(*) FROM tdm_audit_log WHERE source='aps' AND status='deleted' AND deletion_confirmed=false;")"
APS_PAPERS="$(psql_scalar "SELECT count(*) FROM (SELECT COALESCE(EXTRACT(YEAR FROM p.date_published)::int, CASE WHEN p.publication_ref->>'published_date' ~ '^[0-9]{4}' THEN substring(p.publication_ref->>'published_date' from 1 for 4)::int END) AS paper_year FROM papers p WHERE p.source='aps') q WHERE paper_year BETWEEN 1986 AND 2026;")"
STRICT_RECORDS="$(psql_scalar "SELECT count(*) FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id WHERE p.source='aps' AND p.status!='retracted' AND p.credibility_tier='T1' AND COALESCE(EXTRACT(YEAR FROM p.date_published)::int, CASE WHEN p.publication_ref->>'published_date' ~ '^[0-9]{4}' THEN substring(p.publication_ref->>'published_date' from 1 for 4)::int END) BETWEEN 1986 AND 2026 AND v.tc_kelvin > 0 AND v.tc_kelvin <= 300;")"
GEO_ROWS="$(psql_scalar "SELECT count(*) FROM (SELECT COALESCE(EXTRACT(YEAR FROM p.date_published)::int, CASE WHEN p.publication_ref->>'published_date' ~ '^[0-9]{4}' THEN substring(p.publication_ref->>'published_date' from 1 for 4)::int END) AS paper_year, paper_geo FROM papers p WHERE p.source='aps') q WHERE paper_year BETWEEN 1986 AND 2026 AND paper_geo IS NOT NULL;")"
COUNTRY_ROWS="$(psql_scalar "SELECT count(*) FROM (SELECT COALESCE(EXTRACT(YEAR FROM p.date_published)::int, CASE WHEN p.publication_ref->>'published_date' ~ '^[0-9]{4}' THEN substring(p.publication_ref->>'published_date' from 1 for 4)::int END) AS paper_year, paper_geo FROM papers p WHERE p.source='aps') q WHERE paper_year BETWEEN 1986 AND 2026 AND jsonb_array_length(COALESCE(paper_geo->'countries', '[]'::jsonb)) > 0;")"

{
  echo
  echo "## Gate Summary"
  echo
  echo "- APS papers in 1986--2026: \`${APS_PAPERS}\`"
  echo "- APS strict Tc records: \`${STRICT_RECORDS}\`"
  echo "- APS paper_geo rows: \`${GEO_ROWS}\`"
  echo "- APS non-empty country sets: \`${COUNTRY_ROWS}\`"
  echo "- Bad APS chunks: \`${BAD_CHUNKS}\`"
  echo "- Unconfirmed deleted audit rows: \`${UNCONFIRMED}\`"
} >> "${REPORT}"

if [[ "${BAD_CHUNKS}" != "0" || "${UNCONFIRMED}" != "0" ]]; then
  echo "Preflight failed compliance gates. See ${REPORT}" >&2
  exit 2
fi

if [[ "${GEO_ROWS}" == "0" && "${ALLOW_MISSING_GEO:-0}" != "1" ]]; then
  echo "Preflight failed geography gate: APS paper_geo coverage is zero. See ${REPORT}" >&2
  echo "Set ALLOW_MISSING_GEO=1 only for a non-final, non-geography pilot export." >&2
  exit 6
fi

if [[ "${COUNTRY_ROWS}" == "0" && "${ALLOW_MISSING_GEO:-0}" != "1" ]]; then
  echo "Preflight failed geography gate: APS non-empty country coverage is zero. See ${REPORT}" >&2
  echo "Set ALLOW_MISSING_GEO=1 only for a non-final, non-geography pilot export." >&2
  exit 7
fi

echo "Preflight report written: ${REPORT}"
