"""Frozen additive 0057 reverse indexes for read-only source impact inspection.

These indexes improve exact-ID catalogue lookup. They are not a dependency
ledger, a refresh queue, or evidence that propagation has completed. Reuse the
existing claim, chunk, accepted-map, parent and release-pin indexes elsewhere.
"""
from __future__ import annotations

import sqlalchemy as sa

INDEX_SPECS = (
    ("idx_si57_material_records", "materials", "records", "gin", "jsonb_path_ops"),
    ("idx_si57_timeline_paper", "timeline_projection_points", "paper_id", "btree", None),
    ("idx_si57_timeline_material", "timeline_projection_points", "material_id", "btree", None),
    ("idx_si57_example_claim", "ml_examples", "claim_id", "btree", None),
    ("idx_si57_example_work", "ml_examples", "work_id", "btree", None),
    ("idx_si57_example_material", "ml_examples", "material_id", "btree", None),
)


def register(metadata: sa.MetaData) -> dict[str, sa.Index]:
    """Attach only frozen indexes, without new columns, tables or DML hooks."""
    indexes = {}
    for name, table_name, column, method, operator_class in INDEX_SPECS:
        table = metadata.tables[table_name]
        options = {"postgresql_using": method}
        if operator_class:
            options["postgresql_ops"] = {column: operator_class}
        indexes[name] = sa.Index(name, table.c[column], **options)
    return indexes
