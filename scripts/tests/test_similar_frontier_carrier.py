"""The private AM stream must preserve native ordering across revision exclusions."""

from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from similar_frontier_carrier import eligible_roots


class CarrierRoots(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.scratch = AsyncMock()
        self.db = AsyncMock()
        self.args = {"query": "synthetic", "excluded": ["revision"]}

    @staticmethod
    def resolved(*items):
        result = MagicMock()
        result.all.return_value = list(items)
        return result

    async def test_refill_preserves_am_order_when_heap_returns_in_other_order(self):
        self.scratch.fetch.side_effect = [
            [("(1,2)",), ("(1,3)",), ("(1,5)",)],
            [("(8,1)",)],
        ]
        self.db.execute.side_effect = [
            self.resolved(("(1,5)", True), ("(1,3)", True), ("(1,2)", False)),
            self.resolved(("(8,1)", True)),
        ]
        roots = await eligible_roots(self.scratch, self.db, "fixture", self.args, 3)
        self.assertEqual(roots, ["(1,3)", "(1,5)", "(8,1)"])
        self.assertEqual(
            [call.args[0] for call in self.scratch.fetch.await_args_list],
            [
                "FETCH FORWARD 3 FROM frontier_roots",
                "FETCH FORWARD 1 FROM frontier_roots",
            ],
        )

    async def test_unresolved_root_rejects_the_whole_pool(self):
        self.scratch.fetch.return_value = [("(1,2)",), ("(2,4)",)]
        self.db.execute.return_value = self.resolved(("(1,2)", True))
        with self.assertRaisesRegex(ValueError, "Unresolved physical candidate"):
            await eligible_roots(self.scratch, self.db, "fixture", self.args, 2)
