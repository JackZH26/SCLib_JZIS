"""Frozen0066 physical lookup paths; no new scientific schema or authority.

The reader's ML query uses input_event_id because the existing composite FK
already binds property inputs to that exact event. Event derivations are one
hop and only derives_from links. Distribution object identity and all eight
nullable capsule FK slots need reverse paths; omitting one OR branch prevents
a complete BitmapOr path. Partial indexes omit rows outside these predicates.
"""
from __future__ import annotations

import sqlalchemy as sa

INDEX_SPECS = (
    ("idx_sri66_ml_input_event", "ml_example_inputs", ("input_event_id",), "input_event_id IS NOT NULL"),
    ("idx_sri66_derivation_input_event", "event_evidence", ("input_event_id",), "link_type = 'derives_from'"),
    ("idx_sri66_distribution_object", "research_distribution_dependencies", ("table_name", "row_id"), None),
    *((f"idx_sri66_distribution_capsule_{index}", "research_distribution_dependencies",
       (f"capsule_release_{index}",), f"capsule_release_{index} IS NOT NULL") for index in range(8)),
)


def register(metadata: sa.MetaData) -> dict[str, sa.Index]:
    """Attach only nonunique btree indexes to already registered tables."""
    result = {}
    for name, table, columns, predicate in INDEX_SPECS:
        options = {"postgresql_using": "btree"}
        if predicate is not None:
            options["postgresql_where"] = sa.text(predicate)
        result[name] = sa.Index(name, *(metadata.tables[table].c[column] for column in columns), **options)
    return result
