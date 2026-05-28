#!/usr/bin/env bash
# scripts/refresh_corpus_stats.sh
#
# Refresh all corpus statistics for a given snapshot date.
# Runs against VPS2 PostgreSQL via SSH; output lives in audit/refresh_${SNAPSHOT}/
#
# Usage:
#   scripts/refresh_corpus_stats.sh                  # use today's UTC date
#   scripts/refresh_corpus_stats.sh 2026-05-28       # explicit snapshot date
#
# Requires:
#   - SSH key auth to root@72.62.251.29
#   - docker compose up on VPS2 (sclib-postgres container)
#
# Produces (in audit/refresh_${SNAPSHOT}/):
#   q0_corpus.csv                  # Headline strict-filter totals
#   q_evidence_breakdown.csv       # primary_experimental / primary / theoretical / NULL
#   q1_family_succession.csv       # 5-year family succession (top-3 per bucket)
#   q2_2008_shock.csv              # 2007/08/09 iron-based + cuprate counts
#   q2b_annual_submissions.csv     # Annual paper-submission counts (SCLib-side)
#   q2c_2008_multi_family.csv      # Multi-family labeling check for 2008
#   q3_hp_ratio.csv                # HP vs ambient Tc ratio per 5-year bucket
#   q4_high_tc_records.csv         # Top-30 Tc records (>=200K)
#   q5_us_china_all_papers.csv     # Annual USA vs China (all papers)
#   q5b_us_china_tcgeo.csv         # Annual USA vs China (Tc-bearing subset)
#   q6_family_leadership.csv       # Leading country per material family
#   q7_multi_country.csv           # n_countries-per-paper distribution
#   q7b_us_china_joint.csv         # US-China joint papers per 5-year bucket
#   q8_pareto.csv                  # Material Pareto (papers-per-formula buckets)
#   q8b_top_materials.csv          # Top-15 materials by paper count
#   q8c_powerlaw_raw.csv           # Raw papers-vs-materials for power-law fit
#   q8d_top25_materials.csv        # Top-25 materials by paper count
#   q9_watershed.csv               # 100K watershed under 4 filter conventions
#   q10_above100k.csv              # >100K records by family
#   q10b_above100k_bins.csv        # >100K Tc bands (100-130/130-140/140-200/>200)
#   q10c_material_scarcity.csv     # % of materials with max(Tc) > 100K / > 200K
#   q10d_above100k_temporal.csv    # >100K records by 5-year bucket
#   q11_tc_histogram.csv           # 10K Tc histogram (0..300)
#   q11b_tc_5k_bins.csv            # 5K Tc histogram (0..110) — valley source
#   q11c_family_band_decomp.csv    # Family decomposition of 0-50/50-80/80-120K
#   q12_mean_tc_bucket.csv         # Mean Tc per 5-year bucket
#   q13_rocket_materials.csv       # "Rocket-launch" formulas (MgB2, LaH10, ...)
#   q14_fulleride_above100k.csv    # Fulleride records above 100K (retracted-filter test)
#   q14b_fulleride_papers.csv      # Underlying fulleride papers (status check)
#   q15_country_top25.csv          # Top-25 countries (post-normalization)
#   v_tc_geo_strict.csv            # Full strict-filter view export
#   v_tc_geo_full.csv              # Pre-retraction-filter view (figure 2 source)
#   timeline_data.csv              # Mirror of v_tc_geo_full, supports timeline_plot.py
#
# All queries use the canonical strict filter:
#   tc_kelvin > 0 AND tc_kelvin <= 300 AND papers.status != 'retracted'
#
# Country normalization is NOT re-applied here — it is assumed to be already
# stored in papers.paper_geo (idempotent UPDATE in scripts/normalize_countries.sh).

set -euo pipefail

VPS="root@72.62.251.29"
SNAPSHOT_DATE="${1:-$(date -u +%Y-%m-%d)}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATE_TAG="${SNAPSHOT_DATE//-/_}"
REMOTE_OUT="/tmp/refresh_${DATE_TAG}"
LOCAL_OUT="$REPO_ROOT/audit/refresh_${DATE_TAG}"

echo "=========================================="
echo "  SCLib corpus stats refresh"
echo "=========================================="
echo "  Snapshot date : $SNAPSHOT_DATE"
echo "  Local output  : $LOCAL_OUT"
echo "  Remote work   : $VPS:$REMOTE_OUT"
echo ""

mkdir -p "$LOCAL_OUT"

# ---------------------------------------------------------------------------
# Build the remote script (executed inside VPS2 with docker exec -i)
# ---------------------------------------------------------------------------
REMOTE_SCRIPT=$(cat <<'REMOTE_EOF'
#!/bin/bash
set -e
OUT="__REMOTE_OUT__"
SNAPSHOT="__SNAPSHOT_DATE__"
mkdir -p "$OUT"
rm -f "$OUT"/*.csv

pg() { docker exec -i sclib-postgres psql -U sclib -d sclib --csv -A -F, -c "$1"; }

# Record the freeze timestamp
docker exec -i sclib-postgres psql -U sclib -d sclib -At -c "SELECT now()::text" > "$OUT/FREEZE_TIMESTAMP.txt"
echo "Freeze timestamp: $(cat $OUT/FREEZE_TIMESTAMP.txt)"

# ===========================================================================
# SECTION A — Headline corpus statistics
# ===========================================================================

echo "[Q0] Strict-filter corpus stats"
pg "SELECT 'total_papers' AS metric, count(*)::text AS value FROM papers WHERE status != 'retracted'
UNION ALL SELECT 'tc_records_filtered', count(*)::text FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id WHERE p.status != 'retracted' AND v.tc_kelvin > 0 AND v.tc_kelvin <= 300
UNION ALL SELECT 'distinct_materials_filt', count(DISTINCT v.formula)::text FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id WHERE p.status != 'retracted' AND v.tc_kelvin > 0 AND v.tc_kelvin <= 300
UNION ALL SELECT 'distinct_papers_w_tc', count(DISTINCT v.paper_id)::text FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id WHERE p.status != 'retracted' AND v.tc_kelvin > 0 AND v.tc_kelvin <= 300
UNION ALL SELECT 'retracted_papers_total', count(*)::text FROM papers WHERE status='retracted'
UNION ALL SELECT 'retracted_w_tcrecords', count(DISTINCT v.paper_id)::text FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id WHERE p.status='retracted'
UNION ALL SELECT 'v_tc_geo_unfiltered', count(*)::text FROM v_tc_geo WHERE tc_kelvin > 0 AND tc_kelvin <= 300
UNION ALL SELECT 'papers_with_geo', count(*)::text FROM papers WHERE paper_geo IS NOT NULL AND status != 'retracted'
UNION ALL SELECT 'geo_coverage_pct', round(100.0 * count(*) FILTER (WHERE paper_geo IS NOT NULL) / count(*), 2)::text FROM papers WHERE status != 'retracted'" > "$OUT/q0_corpus.csv"

echo "[Q_evidence] Evidence-type breakdown"
pg "SELECT COALESCE(v.evidence_type, 'NULL') AS evidence_type, count(*) AS n,
        round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct
    FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id
    WHERE p.status != 'retracted' AND v.tc_kelvin > 0 AND v.tc_kelvin <= 300
    GROUP BY v.evidence_type
    ORDER BY n DESC" > "$OUT/q_evidence_breakdown.csv"

# ===========================================================================
# SECTION B — Temporal patterns
# ===========================================================================

echo "[Q1] Family succession (5-year buckets, top-3)"
pg "WITH fb AS (
  SELECT ((v.year/5)*5)::int AS bucket, v.family, count(*) AS recs,
         row_number() OVER (PARTITION BY (v.year/5)*5 ORDER BY count(*) DESC) AS rk
  FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id
  WHERE v.tc_kelvin > 0 AND v.tc_kelvin <= 300 AND v.year BETWEEN 1995 AND 2025
    AND v.family IS NOT NULL AND p.status != 'retracted'
  GROUP BY bucket, v.family
) SELECT bucket, rk, family, recs FROM fb WHERE rk <= 3 ORDER BY bucket, rk" > "$OUT/q1_family_succession.csv"

echo "[Q2] 2008 iron-based shock"
pg "SELECT v.year, v.family, count(*) AS records, count(DISTINCT v.paper_id) AS papers
    FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id
    WHERE v.year IN (2007, 2008, 2009) AND v.family IN ('iron_based', 'cuprate')
      AND p.status != 'retracted'
    GROUP BY v.year, v.family ORDER BY v.year, v.family" > "$OUT/q2_2008_shock.csv"

echo "[Q2b] Annual SCLib submissions"
pg "SELECT EXTRACT(YEAR FROM COALESCE(date_published, date_submitted))::int AS year,
       count(*) AS submissions
    FROM papers
    WHERE EXTRACT(YEAR FROM COALESCE(date_published, date_submitted)) BETWEEN 1995 AND 2026
      AND status != 'retracted'
    GROUP BY year ORDER BY year" > "$OUT/q2b_annual_submissions.csv"

echo "[Q2c] 2008 multi-family papers"
pg "WITH p2008 AS (
  SELECT v.paper_id, array_agg(DISTINCT v.family) AS families
  FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id
  WHERE v.year=2008 AND v.family IS NOT NULL AND p.status != 'retracted'
  GROUP BY v.paper_id
) SELECT
  count(*) FILTER (WHERE cardinality(families)=1) AS single_family,
  count(*) FILTER (WHERE cardinality(families)>=2) AS multi_family,
  count(*) FILTER (WHERE 'cuprate'=ANY(families) AND 'iron_based'=ANY(families)) AS both_cuprate_iron,
  count(*) AS total_papers_2008
FROM p2008" > "$OUT/q2c_2008_multi_family.csv"

echo "[Q12] Mean Tc per 5-year bucket"
pg "SELECT ((v.year/5)*5)::int AS bucket,
       round(avg(v.tc_kelvin)::numeric, 1) AS mean_tc,
       count(*) AS records
    FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id
    WHERE v.tc_kelvin > 0 AND v.tc_kelvin <= 300 AND v.year BETWEEN 1995 AND 2025
      AND p.status != 'retracted'
    GROUP BY bucket ORDER BY bucket" > "$OUT/q12_mean_tc_bucket.csv"

# ===========================================================================
# SECTION C — Tc structure
# ===========================================================================

echo "[Q3] HP vs ambient ratio per 5-year bucket"
pg "SELECT ((v.year/5)*5)::int AS bucket,
       count(*) FILTER (WHERE v.pressure_gpa > 1) AS hp_n,
       count(*) FILTER (WHERE v.pressure_gpa IS NULL OR v.pressure_gpa <= 1) AS amb_n,
       round(avg(v.tc_kelvin) FILTER (WHERE v.pressure_gpa > 1)::numeric, 1) AS hp_mean_tc,
       round(avg(v.tc_kelvin) FILTER (WHERE v.pressure_gpa IS NULL OR v.pressure_gpa <= 1)::numeric, 1) AS amb_mean_tc
    FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id
    WHERE v.tc_kelvin > 0 AND v.tc_kelvin <= 300 AND v.year BETWEEN 1995 AND 2025
      AND p.status != 'retracted'
    GROUP BY bucket ORDER BY bucket" > "$OUT/q3_hp_ratio.csv"

echo "[Q4] Top-30 records (Tc >= 200K)"
pg "SELECT v.paper_id, v.formula, v.family, v.tc_kelvin, v.pressure_gpa, v.evidence_type, v.year
    FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id
    WHERE v.tc_kelvin >= 200 AND p.status != 'retracted'
    ORDER BY v.tc_kelvin DESC LIMIT 30" > "$OUT/q4_high_tc_records.csv"

echo "[Q9] 100K watershed under 4 filter conventions"
pg "WITH a AS (SELECT count(*) AS total, count(*) FILTER (WHERE v.tc_kelvin <= 100) AS under100
    FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id WHERE v.tc_kelvin > 0 AND v.tc_kelvin <= 300 AND p.status != 'retracted'),
b AS (SELECT count(*) AS total, count(*) FILTER (WHERE v.tc_kelvin <= 100) AS under100
    FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id WHERE v.tc_kelvin > 0 AND v.tc_kelvin <= 300 AND v.evidence_type='primary_experimental' AND p.status != 'retracted'),
c AS (SELECT count(*) AS total, count(*) FILTER (WHERE v.tc_kelvin <= 100) AS under100
    FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id WHERE v.tc_kelvin > 0 AND v.tc_kelvin <= 300 AND (v.pressure_gpa IS NULL OR v.pressure_gpa <= 1) AND p.status != 'retracted'),
d AS (SELECT count(*) AS total, count(*) FILTER (WHERE v.tc_kelvin <= 100) AS under100
    FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id WHERE v.tc_kelvin > 0 AND v.tc_kelvin <= 300 AND (v.pressure_gpa IS NULL OR v.pressure_gpa <= 1) AND v.evidence_type != 'primary_theoretical' AND p.status != 'retracted')
SELECT 'all_excl_retracted' AS scope, total, under100, round(100.0*under100/total, 2) AS pct FROM a
UNION ALL SELECT 'strict_experimental', total, under100, round(100.0*under100/total, 2) FROM b
UNION ALL SELECT 'ambient', total, under100, round(100.0*under100/total, 2) FROM c
UNION ALL SELECT 'ambient_no_theory', total, under100, round(100.0*under100/total, 2) FROM d" > "$OUT/q9_watershed.csv"

echo "[Q10] Above-100K records by family"
pg "SELECT v.family, count(*) AS records,
       count(*) FILTER (WHERE v.pressure_gpa IS NULL OR v.pressure_gpa <= 1) AS ambient,
       count(*) FILTER (WHERE v.pressure_gpa > 1) AS hp,
       count(*) FILTER (WHERE v.pressure_gpa > 100) AS ultra_hp,
       round(avg(v.tc_kelvin)::numeric, 1) AS mean_tc,
       round(max(v.tc_kelvin)::numeric, 1) AS max_tc
    FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id
    WHERE v.tc_kelvin > 100 AND v.tc_kelvin <= 300 AND v.family IS NOT NULL
      AND p.status != 'retracted'
    GROUP BY v.family ORDER BY records DESC" > "$OUT/q10_above100k.csv"

echo "[Q10b] Above-100K Tc bands"
pg "SELECT CASE WHEN v.tc_kelvin <= 130 THEN '100-130'
            WHEN v.tc_kelvin <= 140 THEN '130-140'
            WHEN v.tc_kelvin <= 200 THEN '140-200'
            ELSE '>200' END AS tc_band,
       count(*) AS total,
       count(*) FILTER (WHERE v.family='cuprate') AS cuprate,
       count(*) FILTER (WHERE v.family='hydride') AS hydride,
       count(*) FILTER (WHERE v.family NOT IN ('cuprate','hydride') OR v.family IS NULL) AS other
    FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id
    WHERE v.tc_kelvin > 100 AND v.tc_kelvin <= 300 AND p.status != 'retracted'
    GROUP BY tc_band ORDER BY min(v.tc_kelvin)" > "$OUT/q10b_above100k_bins.csv"

echo "[Q10c] Material-level above-100K scarcity"
pg "WITH mp AS (
  SELECT v.formula, max(v.tc_kelvin) AS max_tc
  FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id
  WHERE p.status != 'retracted'
  GROUP BY v.formula
)
SELECT count(*) AS total_materials,
       count(*) FILTER (WHERE max_tc > 100) AS above_100k,
       count(*) FILTER (WHERE max_tc > 200) AS above_200k,
       round(100.0 * count(*) FILTER (WHERE max_tc > 100) / count(*), 2) AS pct_above_100k,
       round(100.0 * count(*) FILTER (WHERE max_tc > 200) / count(*), 3) AS pct_above_200k
FROM mp" > "$OUT/q10c_material_scarcity.csv"

echo "[Q10d] Above-100K records over time"
pg "SELECT ((v.year/5)*5)::int AS bucket, count(*) AS total,
       count(*) FILTER (WHERE v.tc_kelvin > 100) AS above100,
       count(*) FILTER (WHERE v.tc_kelvin > 100 AND v.pressure_gpa > 1) AS above100_hp,
       round(100.0 * count(*) FILTER (WHERE v.tc_kelvin > 100) / count(*), 2) AS pct_above100
    FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id
    WHERE v.tc_kelvin > 0 AND v.tc_kelvin <= 300 AND v.year BETWEEN 1995 AND 2025
      AND p.status != 'retracted'
    GROUP BY bucket ORDER BY bucket" > "$OUT/q10d_above100k_temporal.csv"

echo "[Q11] Tc histogram (10K bins)"
pg "SELECT ((floor(v.tc_kelvin/10)*10))::int AS tc_low, count(*) AS records
    FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id
    WHERE v.tc_kelvin > 0 AND v.tc_kelvin <= 300 AND p.status != 'retracted'
    GROUP BY tc_low ORDER BY tc_low" > "$OUT/q11_tc_histogram.csv"

echo "[Q11b] Tc histogram 5K bins (valley source)"
pg "SELECT ((floor(v.tc_kelvin/5)*5))::int AS tc_low, count(*) AS records
    FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id
    WHERE v.tc_kelvin > 0 AND v.tc_kelvin <= 110 AND p.status != 'retracted'
    GROUP BY tc_low ORDER BY tc_low" > "$OUT/q11b_tc_5k_bins.csv"

echo "[Q11c] Family band decomposition (0-50/50-80/80-120K)"
pg "SELECT v.family,
       count(*) FILTER (WHERE v.tc_kelvin < 50) AS band_0_50,
       count(*) FILTER (WHERE v.tc_kelvin >= 50 AND v.tc_kelvin < 80) AS band_50_80,
       count(*) FILTER (WHERE v.tc_kelvin >= 80 AND v.tc_kelvin <= 120) AS band_80_120
    FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id
    WHERE v.tc_kelvin > 0 AND v.tc_kelvin <= 120 AND p.status != 'retracted'
    GROUP BY v.family
    ORDER BY (count(*) FILTER (WHERE v.tc_kelvin < 50)
            + count(*) FILTER (WHERE v.tc_kelvin >= 50 AND v.tc_kelvin < 80)
            + count(*) FILTER (WHERE v.tc_kelvin >= 80 AND v.tc_kelvin <= 120)) DESC" > "$OUT/q11c_family_band_decomp.csv"

# ===========================================================================
# SECTION D — Geography
# ===========================================================================

echo "[Q5] USA vs China annual (all papers)"
pg "WITH pp AS (
  SELECT DISTINCT p.arxiv_id AS paper_id,
         EXTRACT(YEAR FROM COALESCE(p.date_published, p.date_submitted))::int AS year,
         jsonb_array_elements_text(p.paper_geo->'countries') AS country
  FROM papers p
  WHERE EXTRACT(YEAR FROM COALESCE(p.date_published, p.date_submitted)) BETWEEN 2005 AND 2026
    AND p.paper_geo IS NOT NULL AND p.status != 'retracted'
) SELECT year,
  count(DISTINCT paper_id) FILTER (WHERE country='China') AS china,
  count(DISTINCT paper_id) FILTER (WHERE country='USA') AS usa
FROM pp GROUP BY year ORDER BY year" > "$OUT/q5_us_china_all_papers.csv"

echo "[Q5b] USA vs China annual (Tc-bearing subset)"
pg "WITH pp AS (
  SELECT DISTINCT v.paper_id, v.year, jsonb_array_elements_text(v.countries) AS country
  FROM v_tc_geo v JOIN papers p ON p.id = v.paper_id
  WHERE v.year BETWEEN 2005 AND 2026 AND p.status != 'retracted'
) SELECT year,
  count(DISTINCT paper_id) FILTER (WHERE country='China') AS china,
  count(DISTINCT paper_id) FILTER (WHERE country='USA') AS usa
FROM pp GROUP BY year ORDER BY year" > "$OUT/q5b_us_china_tcgeo.csv"

echo "[Q6] Family leadership by country"
pg "WITH ctyfam AS (
  SELECT DISTINCT v.paper_id, v.family, jsonb_array_elements_text(v.countries) AS country
  FROM v_tc_geo v JOIN papers p ON p.id = v.paper_id
  WHERE v.family IS NOT NULL AND v.countries IS NOT NULL AND p.status != 'retracted'
), counts AS (
  SELECT family, country, count(DISTINCT paper_id) AS n FROM ctyfam GROUP BY family, country
), ranked AS (
  SELECT family, country, n, row_number() OVER (PARTITION BY family ORDER BY n DESC) AS rk FROM counts
) SELECT family, rk, country, n FROM ranked WHERE rk <= 2 AND n >= 10 ORDER BY family, rk" > "$OUT/q6_family_leadership.csv"

echo "[Q7] Multi-country paper distribution"
pg "SELECT
  CASE WHEN jsonb_array_length(paper_geo->'countries')=1 THEN '1'
       WHEN jsonb_array_length(paper_geo->'countries')=2 THEN '2'
       WHEN jsonb_array_length(paper_geo->'countries')=3 THEN '3'
       ELSE '4+' END AS n_countries, count(*) AS papers
  FROM papers WHERE paper_geo IS NOT NULL AND status != 'retracted'
  GROUP BY n_countries ORDER BY n_countries" > "$OUT/q7_multi_country.csv"

echo "[Q7b] US-China joint papers per 5-year bucket"
pg "WITH pp AS (
  SELECT DISTINCT p.arxiv_id AS paper_id,
         ((EXTRACT(YEAR FROM COALESCE(p.date_published, p.date_submitted))::int / 5) * 5) AS bucket,
         jsonb_array_elements_text(p.paper_geo->'countries') AS country
  FROM papers p
  WHERE EXTRACT(YEAR FROM COALESCE(p.date_published, p.date_submitted)) BETWEEN 1995 AND 2026
    AND p.paper_geo IS NOT NULL AND p.status != 'retracted'
), agg AS (SELECT bucket, paper_id, array_agg(country) AS countries FROM pp GROUP BY bucket, paper_id)
SELECT bucket,
  count(*) FILTER (WHERE 'USA'=ANY(countries) AND 'China'=ANY(countries)) AS us_china_joint,
  count(*) AS total_papers
FROM agg GROUP BY bucket ORDER BY bucket" > "$OUT/q7b_us_china_joint.csv"

echo "[Q15] Top-25 countries (post-normalization)"
pg "SELECT country, count(*) AS papers
    FROM (SELECT jsonb_array_elements_text(paper_geo->'countries') AS country
          FROM papers WHERE paper_geo IS NOT NULL AND status != 'retracted') c
    GROUP BY country ORDER BY papers DESC LIMIT 25" > "$OUT/q15_country_top25.csv"

# ===========================================================================
# SECTION E — Materials & Pareto
# ===========================================================================

echo "[Q8] Material Pareto buckets"
pg "WITH mp AS (
  SELECT v.formula, count(DISTINCT v.paper_id) AS papers
  FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id
  WHERE p.status != 'retracted'
  GROUP BY v.formula
)
SELECT CASE WHEN papers=1 THEN '1'
            WHEN papers BETWEEN 2 AND 5 THEN '2-5'
            WHEN papers BETWEEN 6 AND 20 THEN '6-20'
            WHEN papers BETWEEN 21 AND 100 THEN '21-100'
            ELSE '101+' END AS bucket, count(*) AS materials
FROM mp GROUP BY bucket ORDER BY min(papers)" > "$OUT/q8_pareto.csv"

echo "[Q8b] Top-15 materials"
pg "SELECT v.formula, v.family, count(DISTINCT v.paper_id) AS papers, count(*) AS records,
       round(count(*)::numeric / count(DISTINCT v.paper_id), 1) AS rec_per_paper
    FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id
    WHERE v.tc_kelvin > 0 AND v.tc_kelvin <= 300 AND p.status != 'retracted'
    GROUP BY v.formula, v.family ORDER BY papers DESC LIMIT 15" > "$OUT/q8b_top_materials.csv"

echo "[Q8c] Power-law raw (papers vs material count)"
pg "WITH mp AS (
  SELECT v.formula, count(DISTINCT v.paper_id) AS papers
  FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id
  WHERE p.status != 'retracted' GROUP BY v.formula
) SELECT papers, count(*) AS material_count FROM mp GROUP BY papers ORDER BY papers" > "$OUT/q8c_powerlaw_raw.csv"

echo "[Q8d] Top-25 materials"
pg "SELECT v.formula, v.family, count(DISTINCT v.paper_id) AS papers, count(*) AS records
    FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id
    WHERE v.tc_kelvin > 0 AND v.tc_kelvin <= 300 AND p.status != 'retracted'
    GROUP BY v.formula, v.family ORDER BY papers DESC LIMIT 25" > "$OUT/q8d_top25_materials.csv"

echo "[Q13] 'Rocket-launch' materials"
pg "SELECT v.formula, min(v.year) AS first_year,
       count(DISTINCT v.paper_id) AS papers, count(*) AS records
    FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id
    WHERE (v.formula ILIKE 'UTe2' OR v.formula ILIKE 'CsV3Sb5'
        OR v.formula ILIKE 'La3Ni2O7%' OR v.formula ILIKE 'Hg-1223' OR v.formula ILIKE 'Hg-1212'
        OR v.formula ILIKE 'BSCCO' OR v.formula ILIKE 'YBCO' OR v.formula ILIKE 'MgB2'
        OR v.formula ILIKE 'LaH10' OR v.formula ILIKE 'H3S' OR v.formula ILIKE 'FeSe'
        OR v.formula ILIKE 'Nb' OR v.formula ILIKE 'Al' OR v.formula ILIKE 'NbN'
        OR v.formula ILIKE 'Sr2RuO4' OR v.formula ILIKE 'Pb' OR v.formula ILIKE 'CeCoIn5' OR v.formula ILIKE 'NbSe2')
      AND p.status != 'retracted'
    GROUP BY v.formula ORDER BY papers DESC" > "$OUT/q13_rocket_materials.csv"

echo "[Q14] Fulleride above 100K (retraction-filter test)"
pg "SELECT v.paper_id, v.formula, v.tc_kelvin, v.pressure_gpa, v.evidence_type
    FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id
    WHERE v.family='fulleride' AND v.tc_kelvin > 100 AND p.status != 'retracted'
    ORDER BY v.tc_kelvin DESC" > "$OUT/q14_fulleride_above100k.csv"

echo "[Q14b] Underlying fulleride papers (all status)"
pg "SELECT DISTINCT p.id AS paper_id, p.title, p.status, p.retraction_date
    FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id
    WHERE v.family='fulleride' AND v.tc_kelvin > 100
    ORDER BY p.retraction_date NULLS LAST, p.id" > "$OUT/q14b_fulleride_papers.csv"

# ===========================================================================
# SECTION F — Full view exports (for plotting / Zenodo deposit)
# ===========================================================================

echo "[Export] v_tc_geo strict-filter full dump"
pg "SELECT v.material_id, v.formula, v.family, v.paper_id, v.tc_kelvin, v.year,
       v.pressure_gpa, v.evidence_type, v.geo_confidence, v.geo_status,
       v.cities::text AS cities_json, v.countries::text AS countries_json
    FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id
    WHERE v.tc_kelvin > 0 AND v.tc_kelvin <= 300 AND p.status != 'retracted'
    ORDER BY v.year, v.paper_id, v.formula" > "$OUT/v_tc_geo_strict.csv"

echo "[Export] v_tc_geo full (pre-retraction-filter) — figure 2 source"
pg "SELECT v.material_id, v.formula, v.family, v.paper_id, v.tc_kelvin, v.year,
       v.pressure_gpa, v.evidence_type, v.geo_confidence, v.geo_status,
       v.cities::text AS cities_json, v.countries::text AS countries_json,
       p.status AS paper_status
    FROM v_tc_geo v JOIN papers p ON p.id=v.paper_id
    WHERE v.tc_kelvin > 0 AND v.tc_kelvin <= 300
    ORDER BY v.year, v.paper_id, v.formula" > "$OUT/v_tc_geo_full.csv"

echo "[Export] timeline_data.csv (timeline_plot.py input)"
pg "SELECT v.year, v.tc_kelvin, v.family, v.evidence_type, v.pressure_gpa
    FROM v_tc_geo v
    WHERE v.tc_kelvin > 0 AND v.tc_kelvin <= 300
    ORDER BY v.year" > "$OUT/timeline_data.csv"

# ===========================================================================
# SECTION G — Sanity check
# ===========================================================================

echo ""
echo "=== Done. Output files ==="
ls -la "$OUT/" | tail -50
echo ""
echo "=== Headline numbers (q0_corpus.csv) ==="
cat "$OUT/q0_corpus.csv"
REMOTE_EOF
)

# Substitute placeholders
REMOTE_SCRIPT="${REMOTE_SCRIPT//__REMOTE_OUT__/$REMOTE_OUT}"
REMOTE_SCRIPT="${REMOTE_SCRIPT//__SNAPSHOT_DATE__/$SNAPSHOT_DATE}"

# Ship + execute on VPS2
echo "--- Shipping script to VPS2 ---"
echo "$REMOTE_SCRIPT" | ssh "$VPS" "cat > /tmp/refresh_${DATE_TAG}.sh && chmod +x /tmp/refresh_${DATE_TAG}.sh"

echo "--- Executing on VPS2 ---"
ssh "$VPS" "bash /tmp/refresh_${DATE_TAG}.sh"

# Pull results back
echo ""
echo "--- Pulling CSVs back ---"
scp "$VPS:$REMOTE_OUT/*.csv" "$LOCAL_OUT/" 2>&1 | tail -5
scp "$VPS:$REMOTE_OUT/FREEZE_TIMESTAMP.txt" "$LOCAL_OUT/" 2>&1 | tail -2

# Write provenance file
cat > "$LOCAL_OUT/PROVENANCE.txt" <<EOF
Snapshot date:     $SNAPSHOT_DATE
Generator script:  scripts/refresh_corpus_stats.sh
Local timestamp:   $(date -u +%Y-%m-%dT%H:%M:%SZ)
VPS host:          $VPS
Remote work dir:   $REMOTE_OUT (preserved on VPS2 until next refresh)
DB freeze TS:      $(cat "$LOCAL_OUT/FREEZE_TIMESTAMP.txt" 2>/dev/null || echo 'unknown')
EOF

echo ""
echo "=========================================="
echo "  Refresh complete"
echo "=========================================="
echo ""
echo "Local output: $LOCAL_OUT"
echo ""
echo "Next steps:"
echo "  1. Run scripts/compute_reliability_v2.py   --out $LOCAL_OUT"
echo "  2. Run scripts/powerlaw_fit.py             --out $LOCAL_OUT"
echo "  3. Run scripts/valley_statistics.py        --out $LOCAL_OUT"
echo "  4. Run scripts/golden_set_stratification.py --out $LOCAL_OUT"
echo "  5. Run scripts/supermat_overlap.py         --out $LOCAL_OUT"
echo "  6. Run scripts/timeline_plot.py            (auto-reads timeline_data.csv)"
echo "  7. Run scripts/compare_snapshots.py --old <prev> --new $LOCAL_OUT"
