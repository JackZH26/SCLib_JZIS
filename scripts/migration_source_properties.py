"""Empty 0082/0083 inventories for older owned migration round trips.

Importing this helper opens no connections or clients. Callers verify their
owned database before passing a connection. Populated/refusal snapshots must
continue to include these tables; only old-head comparisons exclude them.
"""

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
TABLES = (*V1_TABLES, *INTAKE_V2_TABLES)


def assert_empty(connection):
    from sqlalchemy import text

    for name in TABLES:
        assert connection.execute(text(f'SELECT count(*) FROM public."{name}"')).scalar_one() == 0
