"""Add papers.paper_geo + author-geography analysis views.

Revision ID: 0035_paper_geo
Down revision: 0034_concat_descriptor

Backend-only author / institution geography. Nothing here is exposed by
an API router, so geography never reaches the frontend.

* ``papers.paper_geo`` (JSONB) — per-paper de-duplicated city / country
  summary plus provenance, written by the new ``affiliation_ner``
  geo-NER flow. ``papers.affiliations`` (declared in 0001 but never
  populated) finally gets used for the raw per-institution detail.
* ``idx_papers_geo`` — GIN index for jsonb containment queries
  (e.g. ``paper_geo @> '{"countries":["Japan"]}'``).
* ``v_tc_geo`` — read-only view: one row per (material, Tc record),
  joined to the source paper's geography via the ``paper_id`` already
  stamped on every ``materials.records`` entry. This is the Tc-timeline
  data mapped to city / country.
* ``v_material_geo`` — read-only view: one row per material, with the
  de-duplicated union of all its papers' cities / countries.

The material-NER pipeline (material_ner.py, materials_aggregator.py) is
untouched — the mapping is purely relational over the existing
``paper_id`` link.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0035_paper_geo"
down_revision = "0034_concat_descriptor"
branch_labels = None
depends_on = None


# One row per (material, Tc record). jsonb_typeof guards the numeric
# casts so a single malformed record cannot fail the whole view query.
_V_TC_GEO = """
CREATE VIEW v_tc_geo AS
SELECT
    m.id                       AS material_id,
    m.formula                  AS formula,
    m.family                   AS family,
    r.value->>'paper_id'       AS paper_id,
    CASE WHEN jsonb_typeof(r.value->'tc_kelvin') = 'number'
         THEN (r.value->>'tc_kelvin')::double precision END   AS tc_kelvin,
    CASE WHEN jsonb_typeof(r.value->'year') = 'number'
         THEN (r.value->>'year')::int END                     AS year,
    CASE WHEN jsonb_typeof(r.value->'pressure_gpa') = 'number'
         THEN (r.value->>'pressure_gpa')::double precision END AS pressure_gpa,
    r.value->>'evidence_type'  AS evidence_type,
    p.paper_geo->'cities'      AS cities,
    p.paper_geo->'countries'   AS countries,
    p.paper_geo->>'confidence' AS geo_confidence,
    p.paper_geo->>'status'     AS geo_status
FROM materials m
CROSS JOIN LATERAL jsonb_array_elements(m.records) AS r(value)
LEFT JOIN papers p ON p.id = r.value->>'paper_id'
WHERE m.needs_review = false;
"""

# One row per material: the de-duplicated union of its papers' geography.
_V_MATERIAL_GEO = """
CREATE VIEW v_material_geo AS
WITH mp AS (
    SELECT DISTINCT
        m.id                  AS material_id,
        m.formula             AS formula,
        m.family              AS family,
        r.value->>'paper_id'  AS paper_id
    FROM materials m
    CROSS JOIN LATERAL jsonb_array_elements(m.records) AS r(value)
    WHERE m.needs_review = false
      AND r.value->>'paper_id' IS NOT NULL
),
mc AS (
    SELECT mp.material_id, mp.formula, mp.family,
           c.country, ci.city
    FROM mp
    LEFT JOIN papers p ON p.id = mp.paper_id
    LEFT JOIN LATERAL jsonb_array_elements_text(
        COALESCE(p.paper_geo->'countries', '[]'::jsonb)) AS c(country) ON true
    LEFT JOIN LATERAL jsonb_array_elements_text(
        COALESCE(p.paper_geo->'cities', '[]'::jsonb)) AS ci(city) ON true
)
SELECT
    material_id,
    max(formula)            AS formula,
    max(family)             AS family,
    count(DISTINCT country) AS country_count,
    count(DISTINCT city)    AS city_count,
    COALESCE(jsonb_agg(DISTINCT country ORDER BY country)
             FILTER (WHERE country IS NOT NULL), '[]'::jsonb) AS countries,
    COALESCE(jsonb_agg(DISTINCT city ORDER BY city)
             FILTER (WHERE city IS NOT NULL), '[]'::jsonb)    AS cities
FROM mc
GROUP BY material_id;
"""


def upgrade() -> None:
    op.add_column(
        "papers",
        sa.Column(
            "paper_geo", postgresql.JSONB(), nullable=True,
            comment="Per-paper de-duped author geography: "
                    "{cities,countries,regions,confidence,source,"
                    "method,status,extracted_at}",
        ),
    )
    op.create_index(
        "idx_papers_geo", "papers", ["paper_geo"], postgresql_using="gin",
    )
    op.execute(_V_TC_GEO)
    op.execute(_V_MATERIAL_GEO)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_material_geo;")
    op.execute("DROP VIEW IF EXISTS v_tc_geo;")
    op.drop_index("idx_papers_geo", table_name="papers")
    op.drop_column("papers", "paper_geo")
