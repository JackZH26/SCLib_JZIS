"""Composition, provenance, bounded transport and cache fidelity of NOMAD reads."""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))
from services import material_calculation_references as nomad  # noqa: E402


def row(entry="task_1", formula="B2Mg", *, method="DFT", program="VASP"):
    # Synthetic provider metadata, not a published source quotation or claim.
    return {"entry_id": entry, "upload_id": "upload_1", "parser_name": "parsers/vasp",
            "mainfile": "mp-1580/vasprun.xml", "references": ["http://dx.doi.org/10.1234/example"],
            "results": {"material": {"chemical_formula_hill": formula, "chemical_formula_reduced": formula,
                                    "material_id": "structure_1", "structural_type": "bulk",
                                    "symmetry": {"space_group_symbol": "P6/mmm", "space_group_number": 191,
                                                 "crystal_system": "hexagonal"}},
                        "method": {"method_name": method, "simulation": {"program_name": program}}}}


def payload(rows=None, total=None):
    rows = [row()] if rows is None else rows
    return {"data": rows, "pagination": {"total": len(rows) if total is None else total}}


def project(body=None, formula="MgB2"):
    return nomad.project_calculation_references(formula, payload() if body is None else body,
                                                retrieved_at="2026-10-02T00:00:00+00:00")


@pytest.mark.parametrize(("formula", "hill"), [("MgB2", "B2Mg"), ("NbN", "NNb"), ("FeSe", "FeSe"), ("C2H6O", "C2H6O"), ("BaFe1.906Pt0.094As2", "As2BaFe1.906Pt0.094")])
def test_hill_query_preserves_exact_reduced_composition(formula, hill):
    assert nomad.hill_query_formula(formula) == hill


@pytest.mark.parametrize(("formula", "query"), [
    ("Al2O3", "Al2O3"), ("Al4O6", "Al2O3"), ("Nb2N2", "NNb"),
    ("B2C", "B2C"), ("CHB", "BCH"), ("H2", "H"),
    ("Fe0.5Se0.5", "FeSe"), ("La1.85Sr0.15CuO4", "Cu20La37O80Sr3"),
    ("BaFe1.906Pt0.094As2", "As1000Ba500Fe953Pt47"),
])
def test_reduced_query_uses_alphabetical_integer_proportions(formula, query):
    assert nomad.reduced_query_formula(formula) == query


@pytest.mark.parametrize("formula", ["MgB2-x", "NbN₁₋ₓ", "¹¹B2Mg", "LaFeAsO1-xFx", "FeSe/SrTiO3", "NbN:Ti"])
def test_unresolved_identity_never_becomes_parent_query(formula):
    assert nomad.hill_query_formula(formula) is None
    assert nomad.reduced_query_formula(formula) is None


def test_larger_cells_are_references_without_phase_or_sample_promotion():
    first = row("cell_10", formula="Al4O6")
    first["results"]["material"]["chemical_formula_reduced"] = "Al2O3"
    second = row("cell_30", formula="Al12O18")
    second["results"]["material"]["chemical_formula_reduced"] = "Al2O3"
    conflicting = row("conflict", formula="Al4O6")
    conflicting["results"]["material"]["chemical_formula_reduced"] = "AlO2"
    result = project(payload([first, second, conflicting], total=387), formula="Al2O3")
    assert result["query_formula"] == "Al2O3"
    assert [ref["formula"] for ref in result["references"]] == ["Al4O6", "Al12O18"]
    assert result["truncated"] and result["matches_total"] == 387
    assert result["scientific_acceptance"] is False
    assert all(ref["phase_identity_established"] is False and ref["sample_identity_established"] is False
               for ref in result["references"])


def test_multistructure_tasks_and_unknown_method_remain_distinct():
    first, second = row("a"), row("b", method=None, program="LOBSTER")
    second["results"]["material"]["material_id"] = "structure_2"
    second["results"]["material"]["symmetry"]["space_group_symbol"] = "Fm-3m"
    result = project(payload([second, first], total=89))
    assert result["status"] == "available" and result["matches_total"] == 89 and result["truncated"]
    assert [ref["id"] for ref in result["references"]] == ["a", "b"]
    assert result["references"][1]["method_status"] == "unresolved"
    assert result["references"][1]["knowledge_origin"] == "Unresolved"
    assert result["references"][1]["method"] is None
    assert all(ref["conditions_status"] == "not_inspected" for ref in result["references"])
    assert all(ref["sample_identity_established"] is False and ref["phase_identity_established"] is False for ref in result["references"])
    assert result["scientific_acceptance"] is False


def test_raw_underlying_dft_metadata_preserves_order_false_and_main_gw_method():
    item = row(method="G0W0", program="exciting")
    item["results"]["method"]["simulation"]["dft"] = {
        "xc_functional_names": ["GGA_X_PBE", "GGA_C_PBE"],
        "xc_functional_type": "GGA", "spin_polarized": False,
    }
    result = project(payload([item]))
    ref = result["references"][0]
    assert ref["method"] == "G0W0" and ref["knowledge_origin"] == "Computed"
    assert ref["xc_functional_names"] == ["GGA_X_PBE", "GGA_C_PBE"]
    assert ref["xc_functional_type"] == "GGA" and ref["spin_polarized"] is False
    assert ref["dft_metadata_status"] == "reported"
    assert ref["dft_metadata_scope"] == "reported_underlying_dft_metadata_not_complete_method"
    assert ref["conditions_status"] == "not_inspected"
    assert nomad._valid_cache(result, "MgB2", "B2Mg")


@pytest.mark.parametrize("names", [None, [], [None], [True], [1], ["a"] * 17, ["a" * 81], [" GGA_X_PBE"], ["GGA_X_PBE\n"], "GGA_X_PBE", {"name": "GGA_X_PBE"}])
def test_dft_name_array_is_nullable_strict_bounded_and_not_truncated(names):
    item = row()
    item["results"]["method"]["simulation"]["dft"] = {"xc_functional_names": names}
    ref = project(payload([item]))["references"][0]
    assert ref["xc_functional_names"] is None
    assert ref["dft_metadata_status"] == ("not_supplied" if names is None or names == [] else "requires_review")


@pytest.mark.parametrize("spin", [0, 1, "false", "true", [], {}])
def test_numeric_or_text_spin_values_do_not_become_reported_booleans(spin):
    metadata = nomad._dft_metadata({"dft": {"spin_polarized": spin}})
    assert metadata["spin_polarized"] is None and metadata["dft_metadata_status"] == "requires_review"


def test_missing_dft_metadata_never_infers_functional_from_method_or_program():
    ref = project()["references"][0]
    assert ref["method"] == "DFT" and ref["program"] == "VASP"
    assert all(ref[key] is None for key in ("xc_functional_names", "xc_functional_type", "spin_polarized"))
    assert ref["dft_metadata_status"] == "not_supplied"
    assert nomad._dft_metadata({"dft": {"xc_functional_type": " GGA"}})["xc_functional_type"] is None


def test_malformed_supplied_metadata_is_not_absence_and_valid_false_is_retained():
    item = row()
    item["results"]["method"]["simulation"]["dft"] = {"xc_functional_names": [None], "spin_polarized": False}
    result = project(payload([item]))
    ref = result["references"][0]
    assert ref["xc_functional_names"] is None and ref["spin_polarized"] is False
    assert ref["dft_metadata_status"] == "requires_review"
    assert nomad._valid_cache(result, "MgB2", "B2Mg")
    absent = project()["references"][0]
    assert absent["dft_metadata_status"] == "not_supplied"


def test_cache_rejects_bad_dft_names_spin_promotions_and_old_missing_scope():
    result = project()
    for patch in ({"xc_functional_names": [None]}, {"spin_polarized": 0}, {"dft_metadata_scope": "full_method_verified"}, {"dft_metadata_status": "reported"}):
        changed = deepcopy(result)
        changed["references"][0].update(patch)
        assert not nomad._valid_cache(changed, "MgB2", "B2Mg")
    for key in ("dft_metadata_scope", "xc_functional_names"):
        changed = deepcopy(result)
        changed["references"][0].pop(key)
        assert not nomad._valid_cache(changed, "MgB2", "B2Mg")


@pytest.mark.parametrize("changed", ["B", "B2Mg1-x", "¹¹B2Mg", "B2Mg:Fe", "B2Mg/O"])
def test_each_returned_composition_label_must_match_exactly(changed):
    item = row()
    item["results"]["material"]["chemical_formula_reduced"] = changed
    result = project(payload([item]))
    assert result["status"] == "unavailable" and result["references"] == []
    assert result["matches_total"] == 1  # provider task count, not validated match count


def test_no_match_requires_a_successful_empty_provider_result():
    assert project(payload([], 0))["status"] == "no_match"
    for body in ({}, {"data": [], "pagination": {}}, payload([], 8), payload([], True), payload([None], 0)):
        assert project(body)["status"] == "unavailable"


def test_hard_candidate_and_inspection_limits_and_duplicate_task_identity():
    result = project(payload([row(f"task_{i:03}") for i in range(60)], 200))
    assert len(result["references"]) == 20 and result["inspected_entries"] == 21 and result["truncated"]
    assert [ref["id"] for ref in result["references"]] == [f"task_{i:03}" for i in range(20)]
    assert len(project(payload([row("same"), row("same")]))["references"]) == 1


def test_projection_excludes_coordinates_tc_source_text_and_private_fields():
    item = row()
    item.update(secret="synthetic-private-placeholder", evidence_text="synthetic-text", coordinates=[1, 2], Tc=99)
    item["results"]["material"]["symmetry"]["space_group_number"] = True
    item["references"] += ["https://doi.org@evil.example/10.1234/a", "javascript:bad", "https://doi.org/10.1234/a?token=x", "https://example.com/fulltext"]
    result = project(payload([item]))
    encoded = json.dumps(result)
    for name in ("secret", "evidence_text", "coordinates", "Tc", "mainfile", "vasprun.xml", "evil.example", "example.com/fulltext"):
        assert name not in encoded
    ref = result["references"][0]
    assert ref["space_group_number"] is None
    assert ref["source_references"] == [{"provider": "DOI", "url": "https://doi.org/10.1234/example"}, {"provider": "Materials Project", "url": "https://next-gen.materialsproject.org/materials/mp-1580"}]
    assert len(ref["source_snapshot_sha256"]) == 64


class FakeRedis:
    def __init__(self, cached=None, budget=1):
        self.cached, self.budget = cached, budget
        self.reads = self.writes = 0
        self.ttl = None

    async def get(self, key):
        self.reads += 1
        return self.cached

    async def set(self, key, value, ex):
        self.writes += 1
        self.cached, self.ttl = value, ex

    def pipeline(self, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def incr(self, key):
        return self

    def expire(self, key, ttl):
        return self

    async def execute(self):
        return [self.budget, True]


@pytest.mark.asyncio
async def test_original_isotope_and_dopant_guard_precedes_cache(monkeypatch):
    cache = FakeRedis(json.dumps(project()))
    monkeypatch.setattr(nomad, "get_redis", lambda: cache)
    for records in ([{"formula_raw": "¹¹B2Mg"}], [{"raw_extraction": {"formula": "MgB2-x"}}], [{"formula": "MgB1.9C0.1"}]):
        result = await nomad.fetch_material_calculation_references("MgB2", current_records=records)
        assert result["status"] == "not_applicable"
    assert cache.reads == 0


@pytest.mark.asyncio
async def test_cache_hit_budget_and_24h_cache_for_success_only(monkeypatch):
    cache = FakeRedis()
    monkeypatch.setattr(nomad, "get_redis", lambda: cache)
    calls = []

    async def provider(query):
        calls.append(query)
        return payload()

    monkeypatch.setattr(nomad, "_provider_payload", provider)
    first = await nomad.fetch_material_calculation_references("MgB2")
    assert first["status"] == "available" and calls == ["B2Mg"] and cache.ttl == 86400
    assert await nomad.fetch_material_calculation_references("MgB2") == first
    assert calls == ["B2Mg"] and not nomad._locks
    cache.cached, cache.budget = None, 6
    assert (await nomad.fetch_material_calculation_references("MgB2"))["reason"] == "provider_request_budget"
    assert calls == ["B2Mg"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("formula", "legacy_query", "cell_formula"), [
    ("B2C", "CB2", "C2B4"), ("Al2O3", "Al2O3", "Al4O6"),
])
@pytest.mark.parametrize("generation", [2, 3])
async def test_reduced_lookup_does_not_reuse_old_hill_no_match_cache(monkeypatch, formula, legacy_query, cell_formula, generation):
    digest = hashlib.sha256(formula.encode()).hexdigest()
    legacy_key, current_key = f"materials:nomad:{generation}:" + digest, "materials:nomad:4:" + digest
    legacy = project(payload([], 0), formula=formula)
    # Earlier lookups were incomplete even when the query spelling was identical.
    legacy["query_formula"] = legacy_query
    values = {legacy_key: json.dumps(legacy)}
    reads = []

    class KeyedCache(FakeRedis):
        async def get(self, key):
            reads.append(key)
            return values.get(key)

        async def set(self, key, value, ex):
            assert ex == 86400
            values[key] = value

    cache, calls = KeyedCache(), []
    monkeypatch.setattr(nomad, "get_redis", lambda: cache)

    async def provider(query):
        calls.append(query)
        item = row(formula=cell_formula)
        item["results"]["material"]["chemical_formula_reduced"] = formula
        return payload([item])

    monkeypatch.setattr(nomad, "_provider_payload", provider)
    first = await nomad.fetch_material_calculation_references(formula, current_records=[{"formula_raw": cell_formula}])
    assert first["status"] == "available" and first["query_formula"] == formula
    assert await nomad.fetch_material_calculation_references(formula) == first
    assert calls == [formula] and reads == [current_key, current_key]
    assert json.loads(values[legacy_key]) == legacy


@pytest.mark.parametrize("mutator", [
    lambda value: value.update(evidence_text="synthetic-private-text"),
    lambda value: value["references"][0].update(url="https://evil.example"),
    lambda value: value["references"][0].update(knowledge_origin="Observed"),
    lambda value: value["references"][0].update(source_references=[{"provider": "DOI", "url": "https://evil.example"}]),
    lambda value: value["references"][0].update(formula="MgB2-x"),
])
def test_cached_public_projection_rejects_extra_fields_urls_and_promotions(mutator):
    value = deepcopy(project())
    assert nomad._valid_cache(value, "MgB2", "B2Mg")
    mutator(value)
    assert not nomad._valid_cache(value, "MgB2", "B2Mg")


@pytest.mark.asyncio
async def test_unexpected_compression_is_rejected_before_reading_body(monkeypatch):
    original = httpx.AsyncClient

    class UnreadStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise AssertionError("Unexpected compressed body must not be inspected")
            yield b""  # pragma: no cover

    def response(request):
        assert request.headers["Accept-Encoding"] == "identity"
        return httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=UnreadStream())

    monkeypatch.setattr(nomad.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(response), **kwargs))
    with pytest.raises(nomad._ProviderFailure, match="provider_unexpected_content_encoding"):
        await nomad._provider_payload("B2Mg")


@pytest.mark.asyncio
async def test_unavailable_responses_are_not_cached_and_timeout_is_distinct(monkeypatch):
    cache = FakeRedis()
    monkeypatch.setattr(nomad, "get_redis", lambda: cache)

    async def invalid(query):
        return {"data": [], "pagination": {"total": 5}}

    monkeypatch.setattr(nomad, "_provider_payload", invalid)
    assert (await nomad.fetch_material_calculation_references("MgB2"))["status"] == "unavailable"
    assert cache.writes == 0

    async def stalled(query):
        await asyncio.Event().wait()

    monkeypatch.setattr(nomad, "REQUEST_SECONDS", 0.01)
    monkeypatch.setattr(nomad, "_provider_payload", stalled)
    assert (await nomad.fetch_material_calculation_references("MgB2"))["reason"] == "provider_request_timeout"
    assert cache.writes == 0 and not nomad._locks


@pytest.mark.asyncio
async def test_concurrent_same_formula_uses_one_provider_call_and_cancellation_keeps_waiter_slot(monkeypatch):
    cache, entered, release = FakeRedis(), asyncio.Event(), asyncio.Event()
    monkeypatch.setattr(nomad, "get_redis", lambda: cache)
    calls = []

    async def provider(query):
        calls.append(query)
        entered.set()
        await release.wait()
        return payload()

    monkeypatch.setattr(nomad, "_provider_payload", provider)
    first = asyncio.create_task(nomad.fetch_material_calculation_references("MgB2"))
    await entered.wait()
    second = asyncio.create_task(nomad.fetch_material_calculation_references("MgB2"))
    await asyncio.sleep(0)
    assert next(iter(nomad._locks.values())).users == 2
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert len(nomad._locks) == 1
    release.set()
    assert (await second)["status"] == "available"
    assert len(calls) == 2 and not nomad._locks
    calls.clear()
    cache.cached = None
    assert all(result["status"] == "available" for result in await asyncio.gather(*(nomad.fetch_material_calculation_references("MgB2") for _ in range(4))))
    assert len(calls) == 1 and not nomad._locks


@pytest.mark.asyncio
async def test_leaf_query_is_public_and_http_422_is_not_absence(monkeypatch):
    original = httpx.AsyncClient
    observed = []

    def respond(request):
        observed.append(json.loads(request.content))
        return httpx.Response(422, json={"detail": "synthetic unsupported quantity"})

    monkeypatch.setattr(nomad.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    with pytest.raises(nomad._ProviderFailure, match="provider_rejected_query"):
        await nomad._provider_payload("B2Mg")
    assert observed[0]["owner"] == "public" and observed[0]["pagination"]["page_size"] == 21
    assert observed[0]["query"] == {"results.material.chemical_formula_reduced": "B2Mg"}
    assert {"results.method.simulation.dft.xc_functional_names", "results.method.simulation.dft.xc_functional_type", "results.method.simulation.dft.spin_polarized"} <= set(observed[0]["required"]["include"])
    assert all(field not in {"results.material.symmetry", "results.method.simulation"} for field in observed[0]["required"]["include"])


@pytest.mark.asyncio
async def test_streamed_upstream_bytes_are_bounded_before_json_projection(monkeypatch):
    original = httpx.AsyncClient

    class HugeStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b" " * (nomad.MAX_BYTES // 2)
            yield b" " * (nomad.MAX_BYTES // 2 + 1)
            raise AssertionError("A bounded reader must stop before another chunk")

    monkeypatch.setattr(nomad.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=HugeStream())), **kwargs))
    with pytest.raises(nomad._ProviderFailure, match="provider_response_too_large"):
        await nomad._provider_payload("B2Mg")
