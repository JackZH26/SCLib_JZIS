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
    async def test_semantic_candidates_keep_the_original_search_budget_and_authority_ranking(self):
        reader, witness, authority, scratch = fixture()
        rows = [dict(vector_id='v1', paper_id='p1', content_sha256='1'*64,
            vector_sha256='2'*64, chunk_revision_sha256='3'*64, year=2005, distance=.25)]
        selected = MagicMock()
        selected.mappings.return_value.all.return_value = rows
        authority.execute.return_value = selected
        with ExitStack() as patches:
            patches.enter_context(patch.object(live, 'current_read_pin', AsyncMock()))
            patches.enter_context(patch.object(live, 'physical_witness', AsyncMock(return_value=witness)))
            roots = patches.enter_context(patch.object(live, 'eligible_source_roots',
                AsyncMock(return_value=[['(1,1)']])))
            result = await reader.query(witness, [1.0]+[0.0]*767, top_k=1)
        self.assertEqual(result.neighbors[0].vector_id, 'v1')
        self.assertEqual(result.neighbors[0].distance, .25)
        self.assertEqual(result.strategy, 'hnsw')
        self.assertFalse(result.exhaustive)
        reader._transport._configure.assert_awaited_once_with(authority, 1000)
        self.assertEqual(roots.await_args.args[-1], 1024)
        self.assertEqual(authority.execute.await_args.args[1]['roots'], ['(1,1)'])
        self.assertIn('hnsw.ef_search=1000', str(scratch.execute.await_args.args[0]))
        self.assertEqual(reader._transport._slots._value, 4)

    async def test_semantic_rare_year_cohort_remains_exact_without_opening_carrier(self):
        reader, witness, authority, _ = fixture()
        authority.scalar.return_value = 0
        selected = MagicMock()
        selected.mappings.return_value.all.return_value = []
        authority.execute.return_value = selected
        with ExitStack() as patches:
            patches.enter_context(patch.object(live, 'current_read_pin', AsyncMock()))
            patches.enter_context(patch.object(live, 'physical_witness', AsyncMock(return_value=witness)))
            result = await reader.query(witness, [1.0]+[0.0]*767, top_k=20,
                year_min=2000, year_max=2005, excluded_revisions=['4'*64])
        self.assertTrue(result.exhaustive)
        self.assertEqual(result.neighbors, ())
        reader._pool.assert_not_awaited()
        self.assertEqual(authority.scalar.await_args.args[1]['cap'], 200001)
        self.assertEqual(authority.execute.await_args.args[1]['year_min'], 2000)
        self.assertEqual(authority.execute.await_args.args[1]['excluded'], ['4'*64])

    async def test_year_filtered_frontier_refills_and_rejects_null_years(self):
        scratch = AsyncMock()
        scratch.fetch.side_effect = [[('(1,1)',), ('(1,2)',)], [('(1,3)',)]]
        authority = AsyncMock()
        first, second = MagicMock(), MagicMock()
        first.all.return_value = [('(1,1)', False), ('(1,2)', True)]
        second.all.return_value = [('(1,3)', True)]
        authority.execute.side_effect = [first, second]
        roots = await live.eligible_source_roots(scratch, authority, 'fixture', ['query'], [], 2,
            year_min=2000, year_max=2005)
        self.assertEqual(roots, [['(1,2)', '(1,3)']])
        sql, params = authority.execute.await_args_list[0].args
        self.assertIn('COALESCE', str(sql))
        self.assertEqual((params['year_min'], params['year_max']), (2000, 2005))

    async def test_semantic_cancellation_releases_native_and_authority_and_sql_slot(self):
        reader, witness, authority, scratch = fixture()
        entered = asyncio.Event()
        async def waiting(*args):
            entered.set()
            await asyncio.Future()
        scratch.fetch.side_effect = waiting
        with ExitStack() as patches:
            patches.enter_context(patch.object(live, 'current_read_pin', AsyncMock()))
            patches.enter_context(patch.object(live, 'physical_witness', AsyncMock(return_value=witness)))
            task = asyncio.create_task(reader.query(witness, [1.0]+[0.0]*767, top_k=20))
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(reader._transport._slots._value, 4)
        authority.begin.return_value.__aexit__.assert_awaited_once()
        scratch.transaction.return_value.__aexit__.assert_awaited_once()

    async def test_semantic_invalid_year_or_changed_graph_executes_no_sql(self):
        reader, witness, authority, _ = fixture()
        with self.assertRaises(PgvectorQueryError):
            await reader.query(witness, [1.0]+[0.0]*767, top_k=20, year_min=2005, year_max=2000)
        witness.graph_filenode += 1
        with self.assertRaises(PgvectorQueryError):
            await reader.query(witness, [1.0]+[0.0]*767, top_k=20)
        authority.execute.assert_not_awaited()
        reader._pool.assert_not_awaited()

    async def test_search_and_ask_semantic_coordinator_uses_prepared_carrier(self):
        from services import content_retrieval
        carrier, witness, _, _ = fixture()
        reader = content_retrieval.ContentRetriever(MagicMock(), carrier._transport)
        reader._readiness = MagicMock()
        reader._readiness.prepared_witness.return_value = witness
        batch = object()
        reader.similar_carrier = SimpleNamespace(query=AsyncMock(return_value=batch), close=AsyncMock())
        reader._transport.query = AsyncMock()
        vector = [1.0]+[0.0]*767
        try:
            settings = SimpleNamespace(provider_circuit_failure_threshold=3, provider_circuit_cooldown_seconds=20)
            with patch.object(content_retrieval, 'get_settings', return_value=settings), \
                    patch.object(content_retrieval.provider_resilience, 'run_blocking', AsyncMock(return_value=vector)):
                result = await reader._semantic(witness.pin, 'superconductivity', top_k=60,
                    year_min=2000, year_max=2005)
            self.assertIs(result, batch)
            reader.similar_carrier.query.assert_awaited_once_with(witness, vector,
                top_k=60, year_min=2000, year_max=2005)
            reader._transport.query.assert_not_awaited()
        finally:
            await reader.close()

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
        second = MagicMock()
        second.execute = AsyncMock()
        contexts = [MagicMock(), MagicMock()]
        for context, connection in zip(contexts, (scratch, second)):
            context.__aenter__.return_value = connection
        pool = reader._pool.return_value
        pool.acquire.side_effect = contexts
        calls = completed = 0
        async def execute(statement, params=None):
            # The same authority connection scans five source prefixes during
            # the first native FETCH. Keep this operation in flight at deadline.
            if "AS roots" in str(statement):
                await asyncio.sleep(4)
            return MagicMock()
        authority.execute.side_effect = execute
        async def slow_fetch(*args):
            nonlocal calls, completed
            calls += 1
            ordinal = calls
            await asyncio.sleep(.32)
            completed += 1
            return [(f"({ordinal},1)",)]
        scratch.fetch.side_effect = slow_fetch
        second.fetch = AsyncMock(side_effect=slow_fetch)
        with ExitStack() as patches:
            patches.enter_context(patch.object(live, "current_read_pin", AsyncMock()))
            patches.enter_context(patch.object(live, "physical_witness", AsyncMock(return_value=witness)))
            started = asyncio.get_running_loop().time()
            with self.assertRaises(PgvectorUnavailable):
                await reader.query_many(witness, [[1.0] + [0.0] * 767 for _ in range(20)],
                    top_k=15, excluded_revisions=[])
        self.assertLess(asyncio.get_running_loop().time() - started, 2.8)
        # In-flight native and authority work must stop before ranking.
        self.assertLessEqual(calls, 20)
        self.assertLess(completed, calls)
        self.assertEqual(reader._transport._slots._value, 4)
        authority.begin.return_value.__aexit__.assert_awaited_once()
        scratch.transaction.return_value.__aexit__.assert_awaited_once()
        second.transaction.return_value.__aexit__.assert_awaited_once()
        self.assertFalse(any("CROSS JOIN LATERAL" in str(call.args[0])
            for call in authority.execute.await_args_list))

    async def test_authority_and_native_prefixes_are_reassembled_in_source_order(self):
        authority = MagicMock()
        authority.execute = AsyncMock(return_value=MagicMock())
        authority.execute.return_value.all.return_value = [(1, ["(4,1)"]), (2, ["(8,1)"])]
        queries = [str(i) for i in range(1, 9)]

        async def native(scratch, connection, table, inputs, exclusions, limit, *, during_first_fetch):
            self.assertIs(connection, authority)
            self.assertEqual(inputs, ["1", "2", "3", "5", "6", "7"])
            await during_first_fetch()
            return [[f"({i},1)"] for i in inputs]

        with patch.object(live, "eligible_source_roots", new=native):
            groups = await live.similar_source_roots((), authority, "fixture", queries, ["x"], 257)
        self.assertEqual(groups, [[f"({i},1)"] for i in queries])
        sql, params = authority.execute.await_args.args
        self.assertIn("ORDER BY embedding <=>", str(sql))
        self.assertEqual(params, {"queries": ["4", "8"], "excluded": ["x"], "pool_limit": 257})

        authority.execute.return_value.all.return_value = [(1, ["(4,1)"])]
        with patch.object(live, "eligible_source_roots", new=native):
            with self.assertRaises(PgvectorQueryError):
                await live.similar_source_roots((), authority, "fixture", queries, ["x"], 257)

    async def test_two_native_partitions_preserve_prefixes_and_resolve_each_round_once(self):
        first, second = AsyncMock(), AsyncMock()
        first.fetch.side_effect = [[("(1,1)",), ("(1,2)",)], [("(3,1)",), ("(3,2)",)], [("(1,3)",)]]
        second.fetch.side_effect = [[("(1,2)",), ("(2,1)",)], [("(4,1)",)]]
        authority = AsyncMock()
        initial, refill = MagicMock(), MagicMock()
        initial.all.return_value = [(root, root != "(1,1)") for root in
            ["(4,1)", "(3,2)", "(3,1)", "(2,1)", "(1,2)", "(1,1)"]]
        refill.all.return_value = [("(1,3)", True)]
        authority.execute.side_effect = [initial, refill]
        result = await live.eligible_source_roots((first, second), authority, "fixture",
            ["a", "b", "c", "d"], [], 2)
        self.assertEqual(result, [["(1,2)", "(1,3)"], ["(1,2)", "(2,1)"],
            ["(3,1)", "(3,2)"], ["(4,1)"]])
        self.assertEqual(authority.execute.await_count, 2)
        self.assertEqual([call.args[0] for call in first.fetch.await_args_list],
            ["FETCH FORWARD 2 FROM source_0", "FETCH FORWARD 2 FROM source_2", "FETCH FORWARD 1 FROM source_0"])
        self.assertEqual([call.args[0] for call in second.fetch.await_args_list],
            ["FETCH FORWARD 2 FROM source_1", "FETCH FORWARD 2 FROM source_3"])

    async def test_partition_failure_cancels_sibling_before_authority_resolution(self):
        first, second, authority = AsyncMock(), AsyncMock(), AsyncMock()
        entered, cancelled = asyncio.Event(), asyncio.Event()
        async def waiting(*args):
            entered.set()
            try:
                await asyncio.Future()
            finally:
                cancelled.set()
        async def broken(*args):
            await entered.wait()
            raise RuntimeError("native disconnected")
        first.fetch.side_effect = waiting
        second.fetch.side_effect = broken
        with self.assertRaises(ExceptionGroup):
            await live.eligible_source_roots((first, second), authority, "fixture", ["a", "b"], [], 257)
        self.assertTrue(cancelled.is_set())
        authority.execute.assert_not_awaited()

    async def test_partial_pair_checkout_cancellation_returns_first_connection(self):
        reader, witness, _, scratch = fixture()
        entered = asyncio.Event()
        first, second = MagicMock(), MagicMock()
        first.__aenter__.return_value = scratch
        async def waiting(*unused):
            entered.set()
            await asyncio.Future()
        second.__aenter__.side_effect = waiting
        reader._pool.return_value.acquire.side_effect = [first, second]
        async def run():
            async with reader._source_connections(witness, 20):
                self.fail("partial pair admitted")
        task = asyncio.create_task(run())
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        first.__aexit__.assert_awaited_once()
        self.assertFalse(reader._batch_checkout_lock.locked())
        scratch.transaction.assert_not_called()

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
