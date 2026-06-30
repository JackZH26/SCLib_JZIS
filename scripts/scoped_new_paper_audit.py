#!/usr/bin/env python3
"""Audit data produced by papers ingested after the latest data audit.

Default mode is read-only and writes CSV/Markdown reports under
``audit/new_paper_scoped_audit_<timestamp>/``. Pass ``--apply`` to flag
critical rows in ``materials`` and insert one scoped run into
``audit_reports``.

The scope is:
  * papers with ``indexed_at`` after the latest ``audit_reports.started_at``
  * material rows whose ``records[*].paper_id`` points at one of those papers
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "api"))

from services.audit_rules import RULES, AuditRule  # noqa: E402


# Mirrors api/main.py::_FORMULA_* used by _periodic_formula_audit.
_FORMULA_BLACKLIST_REGEX = (
    r"\m("
    r"interface|bilayer|trilayer|multilayer|monolayer|superlattice|"
    r"superlattices|homobilayer|homobilayers|heterostructure|graphene|"
    r"diamond|molecule|molecules|organic|compound|compounds|system|"
    r"systems|doped|undoped|intercalated|hybrid|twisted|valley|bulk|"
    r"ladder|mirror|surface|surfaces|nanoparticle|nanoparticles|film|"
    r"films|wire|wires|polycrystal|polycrystals|tube|tubes|composition|"
    r"compositions|underdoped|overdoped|optimal|optimally|holes?|"
    r"electrons?|cells?|samples?|layers?|chiral|kagome|nanotube|"
    r"nanotubes|nanowire|nanowires"
    r")\M"
)
_FORMULA_CONDITION_REGEX = r"\(?\s*[xyzn]\s*=\s*[0-9]|[≤≥]|<=|>="
_FORMULA_CONCAT_DESCRIPTOR_REGEX = (
    r"(monolayer|bilayer|trilayer|tetralayer|fewlayer|multilayer"
    r"|heterostructure|heterostructures|superlattice|superlattices"
    r"|nanotube|nanotubes|nanowire|nanowires|nanoparticle|nanoparticles"
    r"|nanosheet|nanosheets|nanoribbon|nanoribbons|nanostructure"
    r"|nanostructures|graphene|graphite|fullerene|thinfilm|epitaxial"
    r"|amorphous|polycrystalline|substrate|doped|undoped|intercalated)"
)


@dataclass(frozen=True)
class LocalRule:
    name: str
    severity: str
    predicate: str
    setup: str = ""
    suggested_fix: str = ""


FORMULA_RULES: list[LocalRule] = [
    LocalRule(
        "ner_extracted_descriptive_text",
        "critical",
        f"formula ~* '{_FORMULA_BLACKLIST_REGEX}' "
        f"OR formula ~* '{_FORMULA_CONCAT_DESCRIPTOR_REGEX}' "
        f"OR formula ~  '{_FORMULA_CONDITION_REGEX}' "
        f"OR formula !~ '[A-Z]'",
        suggested_fix="Review formula text; likely descriptor or non-compound NER output.",
    ),
    LocalRule(
        "system_designator_not_compound",
        "critical",
        r"formula ~ '^([A-Z][a-z]?-){2,}[A-Z][a-z]?$'",
        suggested_fix="Remove crystallographic/system designator from material formula.",
    ),
    LocalRule(
        "phase_prefix_in_formula",
        "critical",
        r"formula ~ '^(Fd-?3m|Fm-?3m|Im-?3m|Pm-?3m|Pnma|"
        r"P6_?3?/?mmc?|P6/mmm|R-?3m|R-?3c|I4/mmm|I4/mcm|"
        r"Pn-?3m|P6_?3mc|C2/m|Cmcm|P-?1|P21/c|P-43m|"
        r"P4/nmm|Pm-3n)-'",
        suggested_fix="Remove space-group/phase prefix from formula.",
    ),
    LocalRule(
        "incomplete_or_charged_formula",
        "critical",
        r"formula ~ '[A-Za-z0-9][+\-]$'",
        suggested_fix="Repair incomplete or charged formula text.",
    ),
]


def sql_literal(value: str | None) -> str:
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


def scope_temp_sql(since: str | None) -> str:
    if since:
        last_audit = f"SELECT TIMESTAMPTZ {sql_literal(since)} AS started_at"
    else:
        last_audit = """
            SELECT started_at
            FROM audit_reports
            GROUP BY started_at
            ORDER BY started_at DESC
            LIMIT 1
        """
    return f"""
SET client_min_messages TO warning;
CREATE TEMP TABLE _scope_last_audit AS {last_audit};

CREATE TEMP TABLE _scope_new_papers AS
SELECT p.*
FROM papers p, _scope_last_audit la
WHERE p.indexed_at > la.started_at;
CREATE INDEX ON _scope_new_papers (id);

CREATE TEMP TABLE _scope_new_records AS
SELECT p.id AS paper_id,
       p.source,
       p.indexed_at,
       elem.value AS record,
       elem.value->>'formula' AS formula
FROM _scope_new_papers p
CROSS JOIN LATERAL jsonb_array_elements(
    COALESCE(p.materials_extracted, '[]'::jsonb)
) AS elem(value);

CREATE TEMP TABLE _scope_affected_materials AS
SELECT DISTINCT m.id
FROM materials m
CROSS JOIN LATERAL jsonb_array_elements(
    COALESCE(m.records, '[]'::jsonb)
) AS r(value)
JOIN _scope_new_papers p ON p.id = r.value->>'paper_id';
CREATE INDEX ON _scope_affected_materials (id);
"""


def psql_cmd(args: argparse.Namespace) -> list[str]:
    remote = (
        f"docker exec -i {args.container} "
        f"psql -v ON_ERROR_STOP=1 -q --csv -U {args.db_user} -d {args.db_name}"
    )
    if args.ssh:
        return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", args.ssh, remote]
    return ["bash", "-lc", remote]


def run_psql(args: argparse.Namespace, sql: str) -> str:
    proc = subprocess.run(
        psql_cmd(args),
        input=sql,
        text=True,
        capture_output=True,
        cwd=REPO,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"psql failed with exit {proc.returncode}\nSTDERR:\n{proc.stderr}\nSTDOUT:\n{proc.stdout}"
        )
    return proc.stdout


def write_query(args: argparse.Namespace, out_dir: Path, name: str, sql: str) -> list[dict[str, str]]:
    csv_text = run_psql(args, scope_temp_sql(args.since) + "\n" + sql)
    path = out_dir / f"{name}.csv"
    path.write_text(csv_text, encoding="utf-8")
    rows = list(csv.DictReader(csv_text.splitlines()))
    print(f"wrote {path.relative_to(REPO)} ({len(rows)} rows)")
    return rows


def rule_count_sql(rules: list[LocalRule | AuditRule]) -> str:
    inserts: list[str] = [
        """
CREATE TEMP TABLE _scoped_rule_counts (
  rule_name text,
  severity text,
  would_count bigint
);
"""
    ]
    for rule in rules:
        admin_guard = "AND admin_decision IS NULL" if rule.severity == "critical" else ""
        inserts.append(f"""
{(rule.setup or '').strip()}
INSERT INTO _scoped_rule_counts(rule_name, severity, would_count)
SELECT {sql_literal(rule.name)}, {sql_literal(rule.severity)}, COUNT(*)
FROM materials
WHERE id IN (SELECT id FROM _scope_affected_materials)
  AND needs_review = FALSE
  {admin_guard}
  AND ({rule.predicate});
""")
    inserts.append("""
SELECT rule_name, severity, would_count
FROM _scoped_rule_counts
ORDER BY
  CASE severity WHEN 'critical' THEN 0 WHEN 'warn' THEN 1 ELSE 2 END,
  rule_name;
""")
    return "\n".join(inserts)


def rule_sample_sql(rules: list[LocalRule | AuditRule]) -> str:
    inserts: list[str] = [
        """
CREATE TEMP TABLE _scoped_rule_samples (
  rule_name text,
  severity text,
  material_id text,
  formula text,
  family text,
  tc_max double precision,
  total_papers integer,
  current_review_reason text,
  sample_paper_ids jsonb
);
"""
    ]
    for rule in rules:
        admin_guard = "AND admin_decision IS NULL" if rule.severity == "critical" else ""
        inserts.append(f"""
{(rule.setup or '').strip()}
INSERT INTO _scoped_rule_samples
SELECT {sql_literal(rule.name)}, {sql_literal(rule.severity)},
       materials.id, materials.formula, materials.family, materials.tc_max,
       materials.total_papers, materials.review_reason,
       (
         SELECT COALESCE(jsonb_agg(DISTINCT r.value->>'paper_id'), '[]'::jsonb)
         FROM jsonb_array_elements(COALESCE(materials.records, '[]'::jsonb)) AS r(value)
         WHERE r.value->>'paper_id' IN (SELECT id FROM _scope_new_papers)
       ) AS sample_paper_ids
FROM materials
WHERE id IN (SELECT id FROM _scope_affected_materials)
  AND needs_review = FALSE
  {admin_guard}
  AND ({rule.predicate})
ORDER BY tc_max DESC NULLS LAST, id
LIMIT 25;
""")
    inserts.append("""
SELECT *
FROM _scoped_rule_samples
ORDER BY
  CASE severity WHEN 'critical' THEN 0 WHEN 'warn' THEN 1 ELSE 2 END,
  rule_name,
  tc_max DESC NULLS LAST,
  material_id;
""")
    return "\n".join(inserts)


def apply_sql(rules: list[LocalRule | AuditRule], since: str | None) -> str:
    started = datetime.now(timezone.utc).isoformat()
    sql: list[str] = [
        "BEGIN;",
        scope_temp_sql(since),
        """
CREATE TEMP TABLE _scoped_apply_results (
  rule_name text,
  severity text,
  rows_flagged bigint,
  sample_ids jsonb,
  suggested_fix text
);
CREATE TEMP TABLE _scoped_rule_ids (id text);
CREATE TEMP TABLE _updated_ids (id text);
""",
    ]
    for rule in rules:
        suggestion = getattr(rule, "suggested_fix", "") or ""
        admin_guard = "AND admin_decision IS NULL" if rule.severity == "critical" else ""
        if rule.severity == "critical":
            sql.append(f"""
TRUNCATE _scoped_rule_ids;
{(rule.setup or '').strip()}
INSERT INTO _scoped_rule_ids(id)
SELECT id
FROM materials
WHERE id IN (SELECT id FROM _scope_affected_materials)
  AND needs_review = FALSE
  {admin_guard}
  AND ({rule.predicate});

TRUNCATE _updated_ids;
WITH updated AS (
  UPDATE materials m
  SET needs_review = TRUE,
      review_reason = {sql_literal(rule.name)}
  FROM _scoped_rule_ids s
  WHERE m.id = s.id
  RETURNING m.id
)
INSERT INTO _updated_ids(id)
SELECT id FROM updated;

INSERT INTO _scoped_apply_results
SELECT {sql_literal(rule.name)},
       {sql_literal(rule.severity)},
       COUNT(*)::bigint,
       (
         SELECT COALESCE(jsonb_agg(id ORDER BY id), '[]'::jsonb)
         FROM (SELECT id FROM _updated_ids ORDER BY id LIMIT 10) s
       ),
       {sql_literal(suggestion)}
FROM _updated_ids;
""")
        else:
            sql.append(f"""
TRUNCATE _scoped_rule_ids;
{(rule.setup or '').strip()}
INSERT INTO _scoped_rule_ids(id)
SELECT id
FROM materials
WHERE id IN (SELECT id FROM _scope_affected_materials)
  AND needs_review = FALSE
  {admin_guard}
  AND ({rule.predicate});

INSERT INTO _scoped_apply_results
SELECT {sql_literal(rule.name)},
       {sql_literal(rule.severity)},
       COUNT(*)::bigint,
       (
         SELECT COALESCE(jsonb_agg(id ORDER BY id), '[]'::jsonb)
         FROM (SELECT id FROM _scoped_rule_ids ORDER BY id LIMIT 10) s
       ),
       {sql_literal(suggestion)}
FROM _scoped_rule_ids;
""")
    sql.append(f"""
INSERT INTO audit_reports
  (started_at, completed_at, rule_name, severity, rows_flagged,
   delta_vs_previous, sample_ids, suggested_fix, suggested_fixes)
SELECT TIMESTAMPTZ {sql_literal(started)},
       now(),
       r.rule_name,
       r.severity,
       r.rows_flagged::integer,
       CASE
         WHEN prev.rows_flagged IS NULL THEN NULL
         ELSE r.rows_flagged::integer - prev.rows_flagged
       END,
       r.sample_ids,
       NULLIF(r.suggested_fix, ''),
       '[]'::jsonb
FROM _scoped_apply_results r
LEFT JOIN LATERAL (
  SELECT ar.rows_flagged
  FROM audit_reports ar
  WHERE ar.rule_name = r.rule_name
  ORDER BY ar.started_at DESC
  LIMIT 1
) prev ON TRUE;

COMMIT;

SELECT rule_name, severity, rows_flagged, sample_ids
FROM _scoped_apply_results
ORDER BY
  CASE severity WHEN 'critical' THEN 0 WHEN 'warn' THEN 1 ELSE 2 END,
  rule_name;
""")
    return "\n".join(sql)


def build_report(out_dir: Path, tables: dict[str, list[dict[str, str]]], mode: str) -> None:
    summary = {row["metric"]: row["value"] for row in tables.get("summary", [])}
    formula_total = sum(int(r["would_count"]) for r in tables.get("formula_rule_dry_run", []))
    broad_rows = tables.get("material_rule_dry_run", [])
    broad_critical = sum(
        int(r["would_count"]) for r in broad_rows if r["severity"] == "critical"
    )
    broad_warn_info = sum(
        int(r["would_count"]) for r in broad_rows if r["severity"] != "critical"
    )
    lines = [
        "# Scoped New-Paper Audit",
        "",
        f"Mode: `{mode}`",
        f"Latest prior audit: `{summary.get('latest_prior_audit_started_utc', 'unknown')}`",
        "",
        "## Scope",
        "",
        f"- New papers: `{summary.get('new_papers', '0')}`",
        f"- New papers with extracted materials: `{summary.get('new_papers_with_materials', '0')}`",
        f"- Material extraction records: `{summary.get('new_material_records', '0')}`",
        f"- Affected material rows: `{summary.get('affected_materials', '0')}`",
        "",
        "## Dry-Run Rule Totals",
        "",
        f"- Formula-shape critical flags: `{formula_total}`",
        f"- Broad-rule critical flags: `{broad_critical}`",
        f"- Broad-rule warn/info report counts: `{broad_warn_info}`",
        "",
        "See CSV files in this directory for source/day breakdowns, anomalies,",
        "rule counts, and sample material rows.",
        "",
    ]
    (out_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ssh", default="root@72.62.251.29")
    parser.add_argument("--container", default="sclib-postgres")
    parser.add_argument("--db-user", default="sclib")
    parser.add_argument("--db-name", default="sclib")
    parser.add_argument("--since", help="Override prior audit timestamp")
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out_dir or REPO / "audit" / f"new_paper_scoped_audit_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    all_rules: list[LocalRule | AuditRule] = [*FORMULA_RULES, *RULES]
    tables: dict[str, list[dict[str, str]]] = {}

    tables["summary"] = write_query(args, out_dir, "summary", """
WITH latest AS (
  SELECT la.started_at,
         (SELECT max(completed_at) FROM audit_reports ar WHERE ar.started_at = la.started_at) AS completed_at,
         (SELECT sum(rows_flagged) FROM audit_reports ar WHERE ar.started_at = la.started_at) AS rows_flagged
  FROM _scope_last_audit la
)
SELECT 'latest_prior_audit_started_utc' AS metric, started_at::text AS value FROM latest
UNION ALL SELECT 'latest_prior_audit_completed_utc', completed_at::text FROM latest
UNION ALL SELECT 'latest_prior_audit_rows_flagged', rows_flagged::text FROM latest
UNION ALL SELECT 'new_papers', COUNT(*)::text FROM _scope_new_papers
UNION ALL SELECT 'new_papers_with_materials', COUNT(*)::text FROM _scope_new_papers WHERE jsonb_array_length(materials_extracted) > 0
UNION ALL SELECT 'new_material_records', COUNT(*)::text FROM _scope_new_records
UNION ALL SELECT 'distinct_raw_formulas', COUNT(DISTINCT formula)::text FROM _scope_new_records WHERE formula IS NOT NULL
UNION ALL SELECT 'affected_materials', COUNT(*)::text FROM _scope_affected_materials
UNION ALL SELECT 'affected_materials_unflagged', COUNT(*)::text FROM materials WHERE id IN (SELECT id FROM _scope_affected_materials) AND needs_review = FALSE
UNION ALL SELECT 'affected_materials_flagged', COUNT(*)::text FROM materials WHERE id IN (SELECT id FROM _scope_affected_materials) AND needs_review = TRUE
UNION ALL SELECT 'chunks_for_new_papers', COUNT(c.*)::text FROM chunks c JOIN _scope_new_papers p ON p.id = c.paper_id
UNION ALL SELECT 'max_new_paper_indexed_at_utc', max(indexed_at)::text FROM _scope_new_papers
UNION ALL SELECT 'max_affected_material_updated_at_utc', max(updated_at)::text FROM materials WHERE id IN (SELECT id FROM _scope_affected_materials)
ORDER BY metric;
""")
    tables["papers_by_source"] = write_query(args, out_dir, "papers_by_source", """
SELECT source,
       COUNT(*) AS papers,
       COUNT(*) FILTER (WHERE jsonb_array_length(materials_extracted) > 0) AS papers_with_materials,
       COALESCE(sum(jsonb_array_length(materials_extracted)), 0) AS material_records,
       min(indexed_at) AS first_indexed_at,
       max(indexed_at) AS last_indexed_at
FROM _scope_new_papers
GROUP BY source
ORDER BY source;
""")
    tables["papers_by_day"] = write_query(args, out_dir, "papers_by_day", """
SELECT indexed_at::date AS day,
       source,
       COUNT(*) AS papers,
       COUNT(*) FILTER (WHERE jsonb_array_length(materials_extracted) > 0) AS papers_with_materials,
       COALESCE(sum(jsonb_array_length(materials_extracted)), 0) AS material_records
FROM _scope_new_papers
GROUP BY day, source
ORDER BY day, source;
""")
    tables["extraction_anomalies"] = write_query(args, out_dir, "extraction_anomalies", """
WITH candidates AS (
  SELECT 'no_chunks' AS anomaly, p.id, p.indexed_at
  FROM _scope_new_papers p
  WHERE NOT EXISTS (SELECT 1 FROM chunks c WHERE c.paper_id = p.id)
  UNION ALL
  SELECT 'no_materials_extracted', p.id, p.indexed_at
  FROM _scope_new_papers p
  WHERE jsonb_array_length(p.materials_extracted) = 0
  UNION ALL
  SELECT 'high_material_record_count_ge_20', p.id, p.indexed_at
  FROM _scope_new_papers p
  WHERE jsonb_array_length(p.materials_extracted) >= 20
  UNION ALL
  SELECT 'high_chunk_count_ge_100', p.id, p.indexed_at
  FROM _scope_new_papers p
  JOIN chunks c ON c.paper_id = p.id
  GROUP BY p.id, p.indexed_at
  HAVING COUNT(c.*) >= 100
),
ranked AS (
  SELECT *, row_number() OVER (PARTITION BY anomaly ORDER BY indexed_at DESC, id) AS rn
  FROM candidates
)
SELECT anomaly, COUNT(*) AS n,
       COALESCE(jsonb_agg(id ORDER BY indexed_at DESC, id) FILTER (WHERE rn <= 20), '[]'::jsonb) AS sample_ids
FROM ranked
GROUP BY anomaly
ORDER BY anomaly;
""")
    tables["raw_record_checks"] = write_query(args, out_dir, "raw_record_checks", f"""
WITH candidates AS (
  SELECT 'missing_formula' AS check_name, paper_id, formula, indexed_at
  FROM _scope_new_records
  WHERE formula IS NULL OR btrim(formula) = ''
  UNION ALL
  SELECT 'formula_shape_descriptive', paper_id, formula, indexed_at
  FROM _scope_new_records
  WHERE formula ~* '{_FORMULA_BLACKLIST_REGEX}'
     OR formula ~* '{_FORMULA_CONCAT_DESCRIPTOR_REGEX}'
     OR formula ~  '{_FORMULA_CONDITION_REGEX}'
     OR formula !~ '[A-Z]'
  UNION ALL
  SELECT 'system_designator_not_compound', paper_id, formula, indexed_at
  FROM _scope_new_records
  WHERE formula ~ '^([A-Z][a-z]?-){2,}[A-Z][a-z]?$'
  UNION ALL
  SELECT 'phase_prefix_in_formula', paper_id, formula, indexed_at
  FROM _scope_new_records
  WHERE formula ~ '^(Fd-?3m|Fm-?3m|Im-?3m|Pm-?3m|Pnma|P6_?3?/?mmc?|P6/mmm|R-?3m|R-?3c|I4/mmm|I4/mcm|Pn-?3m|P6_?3mc|C2/m|Cmcm|P-?1|P21/c|P-43m|P4/nmm|Pm-3n)-'
  UNION ALL
  SELECT 'incomplete_or_charged_formula', paper_id, formula, indexed_at
  FROM _scope_new_records
  WHERE formula ~ '[A-Za-z0-9][+\\-]$'
  UNION ALL
  SELECT 'tc_out_of_range', paper_id, formula, indexed_at
  FROM _scope_new_records
  WHERE jsonb_typeof(record->'tc_kelvin') = 'number'
    AND ((record->>'tc_kelvin')::float < 0.01 OR (record->>'tc_kelvin')::float > 300)
  UNION ALL
  SELECT 'pressure_out_of_range', paper_id, formula, indexed_at
  FROM _scope_new_records
  WHERE jsonb_typeof(record->'pressure_gpa') = 'number'
    AND ((record->>'pressure_gpa')::float < 0 OR (record->>'pressure_gpa')::float > 500)
  UNION ALL
  SELECT 'record_year_out_of_range', paper_id, formula, indexed_at
  FROM _scope_new_records
  WHERE jsonb_typeof(record->'year') = 'number'
    AND ((record->>'year')::int < 1980 OR (record->>'year')::int > EXTRACT(YEAR FROM now())::int + 1)
  UNION ALL
  SELECT 'cited_evidence_records', paper_id, formula, indexed_at
  FROM _scope_new_records
  WHERE record->>'evidence_type' = 'cited'
),
ranked AS (
  SELECT *, row_number() OVER (PARTITION BY check_name ORDER BY indexed_at DESC, paper_id, formula) AS rn
  FROM candidates
)
SELECT check_name, COUNT(*) AS n,
       COALESCE(jsonb_agg(jsonb_build_object('paper_id', paper_id, 'formula', formula)
                ORDER BY indexed_at DESC, paper_id, formula) FILTER (WHERE rn <= 20), '[]'::jsonb) AS samples
FROM ranked
GROUP BY check_name
ORDER BY check_name;
""")
    tables["affected_materials_by_review_state"] = write_query(args, out_dir, "affected_materials_by_review_state", """
SELECT needs_review,
       COALESCE(review_reason, 'none') AS review_reason,
       COUNT(*) AS n
FROM materials
WHERE id IN (SELECT id FROM _scope_affected_materials)
GROUP BY needs_review, review_reason
ORDER BY needs_review DESC, n DESC, review_reason;
""")
    tables["affected_material_samples"] = write_query(args, out_dir, "affected_material_samples", """
SELECT id, formula, family, tc_max, total_papers, needs_review, review_reason,
       (
         SELECT COALESCE(jsonb_agg(DISTINCT r.value->>'paper_id'), '[]'::jsonb)
         FROM jsonb_array_elements(COALESCE(materials.records, '[]'::jsonb)) AS r(value)
         WHERE r.value->>'paper_id' IN (SELECT id FROM _scope_new_papers)
       ) AS new_paper_ids
FROM materials
WHERE id IN (SELECT id FROM _scope_affected_materials)
ORDER BY tc_max DESC NULLS LAST, id
LIMIT 100;
""")
    tables["formula_rule_dry_run"] = write_query(
        args, out_dir, "formula_rule_dry_run", rule_count_sql(FORMULA_RULES),
    )
    tables["material_rule_dry_run"] = write_query(
        args, out_dir, "material_rule_dry_run", rule_count_sql(RULES),
    )
    tables["rule_samples"] = write_query(
        args, out_dir, "rule_samples", rule_sample_sql(all_rules),
    )

    if args.apply:
        apply_out = run_psql(args, apply_sql(all_rules, args.since))
        (out_dir / "apply_results.csv").write_text(apply_out, encoding="utf-8")
        print(f"wrote {(out_dir / 'apply_results.csv').relative_to(REPO)}")

    build_report(out_dir, tables, "apply" if args.apply else "dry-run")
    print(f"wrote {(out_dir / 'REPORT.md').relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
