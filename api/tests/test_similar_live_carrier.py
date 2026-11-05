"""Candidate transport boundaries; no corpus enumeration or provider calls."""

import asyncio
import json
from contextlib import ExitStack
from copy import deepcopy
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from services import similar_live_carrier as live
from services.pgvector_query import PgvectorQueries, PgvectorQueryError, PgvectorUnavailable, ProjectionSpec


def fixture():
    build = "10000000-0000-4000-8000-000000000001"
    standby = "10000000-0000-4000-8000-000000000002"
    content = "10000000-0000-4000-8000-000000000003"
    pin = SimpleNamespace(logical_index="fixture", build_id=build, content_id=content,
        manifest_sha256="1" * 64, policy_artifact_sha256="2" * 64, profile_json="{}",
        projection=ProjectionSpec(build, content, "1" * 64))
    witness = SimpleNamespace(pin=pin, table_oid=10, graph_oid=11, table_filenode=12,
        graph_filenode=13, member_count=1001, graph_bytes=8192)
    approved = {build: {"scope": live.graph_scope(witness), "graph_bytes": 8192,
        "segments": [{"part": 0, "size": 8192, "source_stream_sha256": "3" * 64}],
        "reader_sha256": "4" * 64, "postgres_image_digest": "sha256:" + "5" * 64}}
    approved[standby] = deepcopy(approved[build])
    approved[standby]["scope"]["build"] = standby
    authority = MagicMock()
    authority.execute = AsyncMock()
    authority.scalar = AsyncMock(return_value=1001)
    engine = MagicMock()
    engine.connect.return_value.__aenter__.return_value = authority
    transport = PgvectorQueries(engine)
    transport._global_slot = AsyncMock()
    transport._configure = AsyncMock()
    reader = live.LiveSimilarCarrier(transport, approved)
    scratch = MagicMock()
    scratch.execute = AsyncMock()
    scratch.fetch = AsyncMock()
    pool = MagicMock()
    pool.acquire.return_value.__aenter__.return_value = scratch
    reader._pool = AsyncMock(return_value=pool)
    reader._binding = AsyncMock()
    return reader, witness, authority, scratch


class LiveSourceBoundaries(IsolatedAsyncioTestCase):
    async def test_shutdown_cancellation_releases_both_graph_pools(self):
        reader, _, _, _ = fixture()
        entered = asyncio.Event()
        async def waiting():
            entered.set()
            await asyncio.Future()
        first, second = MagicMock(), MagicMock()
        first.close = AsyncMock(side_effect=waiting)
        second.close = AsyncMock()
        reader._pools = {'first': first, 'second': second}
        task = asyncio.create_task(reader.close())
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        first.terminate.assert_called_once()
        second.terminate.assert_called_once()
        self.assertEqual(reader._pools, {})

    async def test_native_binding_requires_the_signed_page_and_engine_manifest(self):
        reader, witness, _, scratch = fixture()
        scratch.fetchval = AsyncMock(return_value=json.dumps(live.graph_scope(witness)))
        with self.assertRaisesRegex(PgvectorQueryError, 'binding changed'):
            await live.LiveSimilarCarrier._binding(reader, scratch, witness)
        scratch.fetchval.return_value = json.dumps(live.binding_payload(reader._approved[witness.pin.build_id]))
        await live.LiveSimilarCarrier._binding(reader, scratch, witness)
        changed = deepcopy(reader._approved[witness.pin.build_id])
        changed['segments'][0]['source_stream_sha256'] = '6' * 64
        scratch.fetchval.return_value = json.dumps(live.binding_payload(changed))
        with self.assertRaisesRegex(PgvectorQueryError, 'binding changed'):
            await live.LiveSimilarCarrier._binding(reader, scratch, witness)

    async def test_refill_keeps_every_source_order_and_resolves_shared_roots_once(self):
        scratch = AsyncMock()
        # Two sources share a physical neighbor. Heap order is intentionally
        # unrelated to either source order. Both exclude the same native root.
        scratch.fetch.side_effect = [[("(1,1)",), ("(1,2)",)],
            [("(1,2)",), ("(2,1)",)], [("(1,3)",)]]
        authority = AsyncMock()
        first, second = MagicMock(), MagicMock()
        first.all.return_value = [("(2,1)", True), ("(1,2)", True), ("(1,1)", False)]
        second.all.return_value = [("(1,3)", True)]
        authority.execute.side_effect = [first, second]
        roots = await live.eligible_source_roots(scratch, authority, "fixture", ["v1", "v2"], [], 2)
        self.assertEqual(roots, [["(1,2)", "(1,3)"], ["(1,2)", "(2,1)"]])
        self.assertEqual(authority.execute.await_count, 2)
        self.assertEqual(len(authority.execute.await_args_list[0].args[1]["roots"]), 3)

    async def test_unresolved_root_rejects_all_sources_instead_of_shortening_a_frontier(self):
        scratch = AsyncMock()
        scratch.fetch.side_effect = [[("(1,1)",)], [("(2,1)",)]]
        authority = AsyncMock()
        resolved = MagicMock()
        resolved.all.return_value = [("(1,1)", True)]
        authority.execute.return_value = resolved
        with self.assertRaisesRegex(PgvectorQueryError, "Unresolved"):
            await live.eligible_source_roots(scratch, authority, "fixture", ["v1", "v2"], [], 1)

    async def test_invalid_last_vector_executes_no_valid_prefix(self):
        reader, witness, authority, _ = fixture()
        vectors = [[1.0] + [0.0] * 767 for _ in range(19)] + [[float("nan")] * 768]
        with self.assertRaises(PgvectorQueryError):
            await reader.query_many(witness, vectors, top_k=15, excluded_revisions=[])
        reader._transport.engine.connect.assert_not_called()
        reader._pool.assert_not_awaited()
        authority.execute.assert_not_awaited()

    async def test_changed_graph_never_opens_a_carrier_connection(self):
        reader, witness, authority, _ = fixture()
        witness.graph_filenode += 1
        with self.assertRaises(PgvectorQueryError):
            await reader.query_many(witness, [[1.0] + [0.0] * 767], top_k=15, excluded_revisions=[])
        reader._pool.assert_not_awaited()
        authority.execute.assert_not_awaited()

    async def test_twenty_sources_share_one_real_two_second_deadline(self):
        reader, witness, authority, scratch = fixture()
        calls = 0
        async def slow_fetch(*args):
            nonlocal calls
            calls += 1
            await asyncio.sleep(.12)
            return [(f"({calls},1)",)]
        scratch.fetch.side_effect = slow_fetch
        with ExitStack() as patches:
            patches.enter_context(patch.object(live, "current_read_pin", AsyncMock()))
            patches.enter_context(patch.object(live, "physical_witness", AsyncMock(return_value=witness)))
            started = asyncio.get_running_loop().time()
            with self.assertRaises(PgvectorUnavailable):
                await reader.query_many(witness, [[1.0] + [0.0] * 767 for _ in range(20)],
                    top_k=15, excluded_revisions=[])
        self.assertLess(asyncio.get_running_loop().time() - started, 2.8)
        self.assertLess(calls, 20)
        self.assertEqual(reader._transport._slots._value, 4)
        authority.begin.return_value.__aexit__.assert_awaited_once()
        scratch.transaction.return_value.__aexit__.assert_awaited_once()
        self.assertFalse(any("CROSS JOIN LATERAL" in str(call.args[0])
            for call in authority.execute.await_args_list))

    async def test_cancellation_unwinds_native_and_authority_transactions_and_sql_permit(self):
        reader, witness, authority, scratch = fixture()
        entered = asyncio.Event()
        async def waiting(*args):
            entered.set()
            await asyncio.Future()
        scratch.fetch.side_effect = waiting
        with ExitStack() as patches:
            patches.enter_context(patch.object(live, "current_read_pin", AsyncMock()))
            patches.enter_context(patch.object(live, "physical_witness", AsyncMock(return_value=witness)))
            task = asyncio.create_task(reader.query_many(witness, [[1.0] + [0.0] * 767],
                top_k=15, excluded_revisions=[]))
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(reader._transport._slots._value, 4)
        authority.begin.return_value.__aexit__.assert_awaited_once()
        scratch.transaction.return_value.__aexit__.assert_awaited_once()
