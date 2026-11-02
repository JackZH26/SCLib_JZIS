"""Historical scope never hides populated native input/revision history."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from migration_revision_scope import pre_materials_context_tables


class Connection:
    def __init__(self, populated=()):
        self.populated = set(populated)
        self.sql = []

    def execute(self, statement):
        sql = str(statement)
        self.sql.append(sql)
        exists = any("public." + name + ")" in sql for name in self.populated)
        class Result:
            def scalar_one(self):
                return exists
        return Result()


def test_only_explicit_empty_later_namespaces_can_be_omitted():
    names = ["papers", "retrieval_input_receipts_v2", "retrieval_native_revisions_v2", "unknown_future_history"]
    connection = Connection()
    assert pre_materials_context_tables(connection, names) == ["papers", "unknown_future_history"]
    assert len(connection.sql) == 2


@pytest.mark.parametrize("table", ["retrieval_input_receipts_v2", "retrieval_native_revisions_v2"])
def test_populated_native_history_cannot_be_projected_away(table):
    with pytest.raises(AssertionError, match="Retained native retrieval"):
        pre_materials_context_tables(Connection([table]), ["papers", table])
