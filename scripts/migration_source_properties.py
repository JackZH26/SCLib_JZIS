"""Empty 0082 inventory for older owned migration round trips.

Importing this helper opens no connections or clients. Callers verify their
owned database before passing a connection. Populated/refusal snapshots must
continue to include these tables; only old-head comparisons exclude them.
"""

TABLES = (
    "source_property_import_receipts",
    "source_property_observation_revisions",
    "source_property_review_appends",
)


def assert_empty(connection):
    from sqlalchemy import text

    for name in TABLES:
        assert connection.execute(text(f'SELECT count(*) FROM public."{name}"')).scalar_one() == 0
