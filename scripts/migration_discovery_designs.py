"""Independent 0087 inventory for older owned migration round trips.

This private proposal ledger is not a source-property scientific contract.
Only an explicitly empty ledger may be excluded from an old-head snapshot;
populated/refusal snapshots must retain it. Importing opens no clients.
"""

TABLES = ("discovery_design_revisions_v1",)


def assert_empty(connection):
    from sqlalchemy import text

    for name in TABLES:
        assert connection.execute(text(f'SELECT count(*) FROM public."{name}"')).scalar_one() == 0


def function_signatures():
    from models.discovery_design_v1 import FUNCTION_SIGNATURES

    return FUNCTION_SIGNATURES
