"""Versioned integrity additions for 0047; freeze this contract after release.

No imports of live ORM classes: old migrations must retain their own schema.
The runtime registry appends these constraints only after the 0045 tables exist.
Preflight is SELECT-only and reports IDs/counts, never source text or secrets.
"""
from __future__ import annotations

import sqlalchemy as sa

REVISION = "0047_claim_integrity"
NEW_CHECKS = {
    "ck_ci47_claim_pressure_required": (
        "pressure_state NOT IN ('explicit_ambient','reported') OR pressure_gpa IS NOT NULL"
    ),
    "ck_ci47_claim_accepted_outcome": (
        "validity_status <> 'accepted' OR "
        "(result_status IN ('unknown','inconclusive') AND property_type = 'tc') OR "
        "(result_status = 'observed' AND property_type = 'tc' AND value_relation <> 'unreported') OR "
        "(result_status = 'not_detected' AND property_type = 'non_transition' "
        "AND evidence_role <> 'primary_theoretical' "
        "AND coalesce(lower(extraction_metadata #>> '{result_classification,knowledge_origin}'), 'unknown') "
        "NOT IN ('computed','inferred','ai-proposed','ai_proposed') "
        "AND value_relation IN ('unreported','lt','le') "
        "AND minimum_temperature_k IS NOT NULL "
        "AND measurement_method IS NOT NULL "
        "AND lower(regexp_replace(measurement_method, '^[[:space:]]+|[[:space:]]+$', '', 'g')) NOT IN "
        "('', 'unknown', 'none', 'n/a', 'not_reported', 'not_measured'))"
    ),
}
TARGET_UNIQUE = "uq_ci47_claim_material"
TARGET_FOREIGN_KEY = "fk_ci47_example_claim_material"


def register(metadata: sa.MetaData) -> None:
    """Apply current metadata without rewriting the historical v2 registrar."""
    claims = metadata.tables["material_claims"]
    existing = {item.name for item in claims.constraints}
    for name, expression in NEW_CHECKS.items():
        if name not in existing:
            claims.append_constraint(sa.CheckConstraint(expression, name=name))
    if TARGET_UNIQUE not in existing:
        claims.append_constraint(sa.UniqueConstraint("id", "material_id", name=TARGET_UNIQUE))
    examples = metadata.tables["ml_examples"]
    if TARGET_FOREIGN_KEY not in {item.name for item in examples.constraints}:
        examples.append_constraint(sa.ForeignKeyConstraint(
            ["claim_id", "material_id"], ["material_claims.id", "material_claims.material_id"],
            name=TARGET_FOREIGN_KEY, ondelete="RESTRICT", onupdate="RESTRICT", match="FULL",
        ))


def audit_incompatible_rows(connection, *, sample_limit: int = 20) -> dict:
    """Read a consistent transaction; callers decide whether to lock writes.

Audit both newly strengthened rules and existing finite/value-shape constraints
on v1 claims and v2 state/property tables. IS NOT TRUE catches SQL NULL holes,
including a legacy CHECK that PostgreSQL would otherwise treat as satisfied.
"""
    if isinstance(sample_limit, bool) or not isinstance(sample_limit, int) or not 0 <= sample_limit <= 100:
        raise ValueError("sample_limit must be between 0 and 100")
    tables = ("material_claims", "material_states", "event_properties")
    reports = []
    for table in tables:
        # Obtain the complete PostgreSQL expression directly. Some SQLAlchemy
        # reflection versions strip an unmatched pair from pg_get_constraintdef
        # around ALL/OR expressions; re-wrapping that text can change precedence.
        # pg_get_expr preserves the original parse-tree semantics and NULL arms.
        checks = dict(connection.execute(sa.text(
            "SELECT conname, pg_get_expr(conbin, conrelid) "
            "FROM pg_constraint WHERE conrelid = to_regclass(:table) AND contype = 'c'"
        ), {"table": table}).all())
        if not checks:
            raise RuntimeError(f"Integrity preflight requires the existing constrained table: {table}")
        if table == "material_claims":
            checks.update(NEW_CHECKS)
        for rule, expression in sorted(checks.items()):
            # Identifiers are fixed above; catalog expressions originate from
            # database DDL, not user input or NER. No raw record values are logged.
            where = f"({expression}) IS NOT TRUE"
            count = connection.execute(sa.text(f'SELECT count(*) FROM "{table}" WHERE {where}')).scalar_one()
            if count:
                ids = connection.execute(sa.text(
                    f'SELECT id FROM "{table}" WHERE {where} ORDER BY id LIMIT :limit'
                ), {"limit": sample_limit}).scalars().all()
                reports.append({"table": table, "rule": rule, "count": count,
                                "sample_ids": [str(value) for value in ids]})
    mismatch = (
        "NOT EXISTS (SELECT 1 FROM material_claims c "
        "WHERE c.id=e.claim_id AND c.material_id=e.material_id)"
    )
    count = connection.execute(sa.text(f"SELECT count(*) FROM ml_examples e WHERE {mismatch}")).scalar_one()
    if count:
        ids = connection.execute(sa.text(
            f"SELECT e.id FROM ml_examples e WHERE {mismatch} ORDER BY e.id LIMIT :limit"
        ), {"limit": sample_limit}).scalars().all()
        reports.append({"table": "ml_examples", "rule": TARGET_FOREIGN_KEY, "count": count,
                        "sample_ids": [str(value) for value in ids]})
    return {"schema": "sclib-claim-integrity-audit/v1", "target_revision": REVISION,
            "compatible": not reports, "violations": reports,
            "note": "Counts are per-rule and must not be summed as distinct row counts."}
