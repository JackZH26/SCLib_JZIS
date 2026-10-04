"""Empty 0082–0085 inventories for older owned migration round trips.

Importing this helper opens no connections or clients. Callers verify their
owned database before passing a connection. Populated/refusal snapshots must
continue to include these tables; only old-head comparisons exclude them.
"""

from migration_discovery_designs import assert_empty as assert_empty_discovery_designs
from migration_discovery_condition_batches import assert_empty as assert_empty_condition_batches

V1_TABLES = (
    "source_property_import_receipts",
    "source_property_observation_revisions",
    "source_property_review_appends",
)
INTAKE_V2_TABLES = (
    "source_expression_captures_v2",
    "source_expression_imports_v2",
    "source_expression_revisions_v2",
)
FIELD_CASE_TABLES = (
    "material_field_targets_v1",
    "material_field_associations_v1",
    "material_field_attempts_v1",
)
FIELD_REVIEW_TABLES = (
    "material_field_review_requests_v1",
    "material_field_review_decisions_v1",
)
TABLES = (*V1_TABLES, *INTAKE_V2_TABLES, *FIELD_CASE_TABLES, *FIELD_REVIEW_TABLES)


def assert_empty(connection):
    from sqlalchemy import text

    assert_empty_discovery_designs(connection)
    assert_empty_condition_batches(connection)
    for name in TABLES:
        assert connection.execute(text(f'SELECT count(*) FROM public."{name}"')).scalar_one() == 0
