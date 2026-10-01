"""COD projection and request bounds without any database or service credentials."""
from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))
from services import material_crystal_references as cod


def row(identifier="1000026", **extra):
    return {"file": identifier, "formula": "- B2 Mg -", "calcformula": "- B2 Mg -",
            "a": "3.0823", "siga": "0.0001", "gamma": "120", "sg": "P 6/m m m",
            "sgNumber": "191", "flags": "has coordinates", "svnrevision": "176435",
            "doi": "10.1000/synthetic", "year": "2001", **extra}


class ProjectionTests(unittest.TestCase):
    def test_composition_query_preserves_dopants_and_hill_order(self):
        self.assertEqual(cod.hill_formula("MgB2"), "B2 Mg")
        self.assertEqual(cod.hill_formula("NbN"), "N Nb")
        self.assertEqual(cod.hill_formula("BaFe1.906Pt0.094As2"), "As2 Ba Fe1.906 Pt0.094")

    def test_missing_pressure_and_method_are_unresolved_and_files_unvalidated(self):
        result = cod.project_crystal_references("MgB2", [row()], retrieved_at="now")
        r = result["references"][0]
        self.assertEqual(r["knowledge_origin"], "Unresolved")
        self.assertIsNone(r["measurement_conditions"]["cell_pressure"])
        self.assertIsNone(r["measurement_conditions"]["diffraction_pressure"])
        self.assertFalse(r["coordinate_model_validated"])
        self.assertTrue(r["provider_has_coordinates"])
        self.assertEqual(r["cif_url"], "https://www.crystallography.net/cod/1000026.cif@176435")
        self.assertEqual(r["source_revision"], "svn:176435")
        self.assertEqual(len(r["source_snapshot_sha256"]), 64)
        self.assertFalse(result["database_changed"])

    def test_schema_units_and_standard_uncertainties_are_preserved(self):
        r = cod.project_crystal_references("MgB2", [row(method="powder diffraction", cellpressure="101.3", sigcellpressure="2", celltemp="293", sigcelltemp="0")], retrieved_at="now")["references"][0]
        self.assertEqual(r["knowledge_origin"], "Observed")
        self.assertEqual(r["lattice"]["a"]["unit"], "Å")
        self.assertEqual(r["lattice"]["a"]["uncertainty"], 0.0001)
        p = r["measurement_conditions"]["cell_pressure"]
        self.assertEqual((p["value"], p["uncertainty"], p["unit"]), (101.3, 2, "kPa"))
        self.assertEqual(r["measurement_conditions"]["cell_temperature"]["uncertainty"], 0)
        self.assertEqual(r["measurement_conditions"]["cell_temperature"]["unit"], "K")

    def test_simulated_predicted_and_negated_diffraction_are_not_observed(self):
        for method in ("simulated powder diffraction", "predicted neutron diffraction", "calculated X-ray diffraction", "computational powder diffraction", "not powder diffraction", "non-diffraction", "no experimental diffraction"):
            with self.subTest(method=method):
                result = cod.project_crystal_references("MgB2", [row(method=method)], retrieved_at="now")
                self.assertEqual(result["status"], "unavailable")
                self.assertEqual(result["references"], [])

    def test_declared_fe_se_and_cell_content_deviation_are_not_equated(self):
        r = cod.project_crystal_references("FeSe", [row(formula="- Fe Se -", calcformula="- Fe0.996 Se -")], retrieved_at="now")["references"][0]
        self.assertEqual(r["composition_relation"], "different_composition")
        self.assertEqual(r["match_level"], "declared_composition_only_refined_differs")
        self.assertEqual(r["cell_content_formula"], "Fe0.996Se")
        self.assertFalse(r["sample_identity_established"])

    def test_nonmatch_and_invalid_metadata_differ_from_empty_provider_result(self):
        self.assertEqual(cod.project_crystal_references("NbN", [], retrieved_at="now")["status"], "no_match")
        for r in [row(), row(file="bad"), row(formula="- N Nb -", calcformula="- N Nb -", status="retracted"), row(formula="- N Nb -", calcformula="- N Nb -", flags="theoretical"), row(formula="- N Nb -", calcformula="- N Nb -", onhold="2030-01-01")]:
            self.assertEqual(cod.project_crystal_references("NbN", [r], retrieved_at="now")["status"], "unavailable")

    def test_polymorphs_are_sorted_and_bounded_not_selected_by_energy(self):
        rows = [row(str(1000000 + i)) for i in reversed(range(21))]
        result = cod.project_crystal_references("MgB2", rows, retrieved_at="now")
        self.assertEqual(len(result["references"]), 20)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["matches_total"], 21)
        self.assertEqual(result["references"][0]["id"], "1000000")
        self.assertEqual(cod.project_crystal_references("MgB2", rows + [row("2000000")], retrieved_at="now")["status"], "unavailable")

    def test_unsafe_bibliography_and_coordinates_are_not_published(self):
        r = cod.project_crystal_references("MgB2", [row(doi="javascript:alert(1)", coordinates=["PRIVATE"], secret="PRIVATE")], retrieved_at="now")["references"][0]
        self.assertIsNone(r["bibliography"]["doi_url"])
        self.assertNotIn("PRIVATE", json.dumps(r))

    def test_overlong_doi_is_rejected_instead_of_linking_a_truncated_identifier(self):
        r = cod.project_crystal_references("MgB2", [row(doi="10.1000/" + "x" * 300)], retrieved_at="now")["references"][0]
        self.assertIsNone(r["bibliography"]["doi"])
        self.assertIsNone(r["bibliography"]["doi_url"])

    def test_overlong_formula_is_rejected_instead_of_parsing_its_prefix(self):
        raw = "B2Mg" + " " * 252 + "O"
        self.assertGreater(len(raw), 256)
        self.assertIsNone(cod._cod_formula(raw))
        r = cod.project_crystal_references("MgB2", [row(formula=raw)], retrieved_at="now")["references"][0]
        self.assertIsNone(r["declared_formula"])
        self.assertEqual(r["match_level"], "cell_content_composition_only_declared_unresolved")

    def test_cell_contents_match_with_unresolved_declaration_is_not_a_known_difference(self):
        r = cod.project_crystal_references("MgB2", [row(formula="- Bx Mg -")], retrieved_at="now")["references"][0]
        self.assertEqual(r["match_level"], "cell_content_composition_only_declared_unresolved")
        self.assertEqual(r["composition_relation"], "unresolved")

    def test_huge_json_integer_cannot_escape_numeric_projection(self):
        r = cod.project_crystal_references("MgB2", [row(a=10**400)], retrieved_at="now")["references"][0]
        self.assertNotIn("a", r["lattice"])


class Cache:
    def __init__(self): self.values, self.used = {}, 0
    async def get(self, key): return self.values.get(key)
    async def set(self, key, body, **_kwargs): self.values[key] = body
    def pipeline(self, **_kwargs): return self
    async def __aenter__(self): return self
    async def __aexit__(self, *_args): pass
    def incr(self, _key): self.used += 1
    def expire(self, *_args): pass
    async def execute(self): return [self.used, True]


class RequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_corrupt_nested_cache_json_is_unavailable(self):
        cache = Cache()
        with patch.object(cache, "get", AsyncMock(return_value="[" * 5000 + "]" * 5000)), patch.object(cod, "get_redis", return_value=cache):
            self.assertEqual((await cod.fetch_material_crystal_references("MgB2"))["status"], "unavailable")

    async def test_cached_metadata_is_reprojected_and_cannot_supply_authority_or_extra_fields(self):
        cache = Cache()
        provider = AsyncMock(return_value=([row()], "1" * 64))
        with patch.object(cod, "get_redis", return_value=cache), patch.object(cod, "_provider_rows", provider):
            await cod.fetch_material_crystal_references("MgB2")
            key = next(iter(cache.values))
            saved = json.loads(cache.values[key])
            saved["references"] = [{"scientific_acceptance": True, "coordinate_model_validated": True}]
            saved["rows"][0].update(coordinate_model_validated=True, scientific_acceptance=True, PRIVATE="SECRET", unit="GPa")
            cache.values[key] = json.dumps(saved)
            r = await cod.fetch_material_crystal_references("MgB2")
            self.assertFalse(r["scientific_acceptance"])
            self.assertFalse(r["references"][0]["coordinate_model_validated"])
            self.assertEqual(r["references"][0]["lattice"]["a"]["unit"], "Å")
            self.assertNotIn("SECRET", json.dumps(r))
            saved["rows"][0]["status"] = "retracted"
            cache.values[key] = json.dumps(saved)
            self.assertEqual((await cod.fetch_material_crystal_references("MgB2"))["status"], "unavailable")
            provider.assert_awaited_once()

    async def test_queued_waiter_keeps_same_lock_until_last_user_finishes(self):
        provider_ready, provider_release = asyncio.Event(), asyncio.Event()
        cache_ready, cache_release = asyncio.Event(), asyncio.Event()
        class SlowCache(Cache):
            calls = 0
            async def get(self, key):
                self.calls += 1
                if self.calls == 2:
                    cache_ready.set()
                    await cache_release.wait()
                return await super().get(key)
        cache = SlowCache()
        async def provider(_query):
            provider_ready.set()
            await provider_release.wait()
            return [row()], "1" * 64
        with patch.object(cod, "get_redis", return_value=cache), patch.object(cod, "_provider_rows", AsyncMock(side_effect=provider)) as fetch:
            a = asyncio.create_task(cod.fetch_material_crystal_references("MgB2"))
            await provider_ready.wait()
            key = next(iter(cod._locks))
            slot = cod._locks[key]
            b = asyncio.create_task(cod.fetch_material_crystal_references("MgB2"))
            await asyncio.sleep(0)
            self.assertEqual(slot.users, 2)
            provider_release.set()
            await asyncio.wait_for(cache_ready.wait(), 1)
            await a
            self.assertIs(cod._locks[key], slot)
            c = asyncio.create_task(cod.fetch_material_crystal_references("MgB2"))
            await asyncio.sleep(0)
            self.assertIs(cod._locks[key], slot)
            cache_release.set()
            await asyncio.wait_for(asyncio.gather(b, c), 1)
            fetch.assert_awaited_once()
            self.assertNotIn(key, cod._locks)

    async def test_source_identity_guard_precedes_cache_and_provider(self):
        with patch.object(cod, "get_redis", side_effect=AssertionError("must not access cache")):
            for formula, records in [("FeSe", [{"formula_raw": "FeSe/SrTiO3"}]), ("La2Cu18O4", [{"formula_raw": "La₂Cu¹⁸O₄"}]), ("YBCO", []), ("MgB2", [{"formula_raw": "MgB2^+"}])]:
                self.assertEqual((await cod.fetch_material_crystal_references(formula, current_records=records))["status"], "not_applicable")

    async def test_success_is_cached_but_errors_are_not_false_no_match(self):
        cache = Cache()
        provider = AsyncMock(return_value=([row()], "1" * 64))
        with patch.object(cod, "get_redis", return_value=cache), patch.object(cod, "_provider_rows", provider):
            a = await cod.fetch_material_crystal_references("MgB2")
            b = await cod.fetch_material_crystal_references("MgB2")
            self.assertEqual(a, b)
            provider.assert_awaited_once_with("B2 Mg")
        with patch.object(cod, "get_redis", return_value=cache), patch.object(cod, "_provider_rows", side_effect=httpx.ConnectError("PRIVATE")):
            r = await cod.fetch_material_crystal_references("NbN")
        self.assertEqual(r["status"], "unavailable")
        self.assertNotIn("PRIVATE", json.dumps(r))
        self.assertEqual(len(cache.values), 1)

    async def test_provider_budget_rejects_uncached_request(self):
        cache = Cache()
        cache.used = 2
        with patch.object(cod, "get_redis", return_value=cache), patch.object(cod, "_provider_rows", side_effect=AssertionError("budget exceeded")):
            self.assertEqual((await cod.fetch_material_crystal_references("NbN"))["reason"], "provider_request_budget")

    async def test_transport_rejects_compression_format_bytes_and_row_overflow(self):
        original = httpx.AsyncClient
        cases = [(b"[]", {"content-type": "application/json", "content-encoding": "gzip"}),
                 (b"[]", {"content-type": "text/html"}),
                 (b" " * (cod.MAX_BYTES + 1), {"content-type": "application/json"}),
                 (json.dumps([row(str(1000000+i)) for i in range(22)]).encode(), {"content-type": "application/json"})]
        for body, headers in cases:
            def handler(request):
                self.assertEqual(request.headers["accept-encoding"], "identity")
                return httpx.Response(200, headers=headers, stream=httpx.ByteStream(body))
            def client(**kwargs): return original(transport=httpx.MockTransport(handler), **kwargs)
            with patch.object(cod.httpx, "AsyncClient", client), self.assertRaises(ValueError):
                await cod._provider_rows("B2 Mg")

    async def test_transport_valid_empty_response_is_not_reclassified_as_failure(self):
        original = httpx.AsyncClient
        def handler(request):
            self.assertEqual(request.url.params["formula"], "B2 Mg")
            return httpx.Response(200, headers={"content-type": "application/json"}, stream=httpx.ByteStream(b"[]"))
        def client(**kwargs): return original(transport=httpx.MockTransport(handler), **kwargs)
        with patch.object(cod.httpx, "AsyncClient", client):
            rows, digest = await cod._provider_rows("B2 Mg")
        self.assertEqual(rows, [])
        self.assertEqual(len(digest), 64)


if __name__ == "__main__":
    unittest.main()
