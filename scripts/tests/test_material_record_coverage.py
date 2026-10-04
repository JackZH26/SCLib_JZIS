"""Independent retained-record denominators; no database or scientific approval."""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))

from services import material_enrichment as enrichment  # noqa: E402
from services import material_enrichment_seed, material_classification_seed  # noqa: E402
from services.property_evidence import legacy_result_id  # noqa: E402


def field(dto, name):
    return next(row for row in dto["fields"] if row["field"] == name)


def record_field(dto, offset, name):
    record = next(row for row in dto["records"] if row["record_offset"] == offset)
    return next(row for row in record["fields"] if row["field"] == name)


def assert_denominators(dto):
    for row in dto["fields"]:
        assert sum(row["counts"].values()) == dto["records_total"]
        assert row["counts"]["unchecked"] == dto["records_unchecked"]
        assert 0 <= row["applicability_unknown"] <= row["counts"]["missing"]


def test_partial_pressure_zero_and_separate_method_roles_are_not_material_completeness():
    records = [
        {"paper_id": "paper:computed", "knowledge_origin": "Computed", "tc_kelvin": 0,
         "measurement": "unknown"},
        {"paper_id": "paper:measured", "knowledge_origin": "Observed", "tc_kelvin": 1.2,
         "pressure_gpa": 0, "measurement": "resistivity"},
        {"paper_id": "paper:measured", "knowledge_origin": "Observed", "tc_kelvin": 1.08,
         "pressure_gpa": 0, "measurement": "resistivity"},
        {"paper_id": "paper:measured", "knowledge_origin": "Observed", "tc_kelvin": .95,
         "pressure_gpa": 0, "measurement": "susceptibility"},
        {"paper_id": "paper:measured", "knowledge_origin": "Observed", "tc_kelvin": .9,
         "pressure_gpa": 0, "measurement": "specific_heat"},
    ]
    original = deepcopy(records)
    dto = enrichment.build_record_field_coverage("mat:synthetic", records)
    assert field(dto, "pressure_gpa")["counts"] == dict(present=4, missing=1, unchecked=0, not_applicable=0)
    assert field(dto, "measurement_method")["counts"] == dict(present=4, missing=0, unchecked=0, not_applicable=1)
    assert field(dto, "calculation_method")["counts"] == dict(present=0, missing=1, unchecked=0, not_applicable=4)
    assert record_field(dto, 0, "tc_kelvin")["status"] == "present"
    assert record_field(dto, 0, "pressure_gpa")["status"] == "missing"
    # Computed results can have a numerical Tc criterion; never blanket N/A.
    assert record_field(dto, 0, "tc_criterion")["status"] == "missing"
    assert records == original
    assert_denominators(dto)


@pytest.mark.parametrize("record", [
    {"paper_type": "theoretical"},
    {"knowledge_origin": "Unknown"},
    {"knowledge_origin": "Inferred"},
    {"knowledge_origin": "AI-Proposed"},
    {"knowledge_origin": "Computed", "result_origin": "Observed"},
    {"knowledge_origin": "Computed", "source_role": "primary", "evidence_role": "cited"},
    {"result_classification": {"knowledge_origin": "Computed", "classification_status": "resolved"}},
])
def test_unresolved_or_conflicting_origin_never_becomes_not_applicable(record):
    dto = enrichment.build_record_field_coverage("mat:test", [record])
    for name in ("measurement_method", "calculation_method"):
        assert record_field(dto, 0, name)["status"] == "missing"
        assert field(dto, name)["counts"]["not_applicable"] == 0
        assert field(dto, name)["applicability_unknown"] == 1


@pytest.mark.parametrize(("record", "name"), [
    ({"knowledge_origin": "Observed", "calculation_method": "Eliashberg"}, "calculation_method"),
    ({"knowledge_origin": "Computed", "measurement_method": "resistivity"}, "measurement_method"),
])
def test_retained_role_values_survive_opposite_origin_without_overwriting(record, name):
    dto = enrichment.build_record_field_coverage("mat:test", [record])
    assert record_field(dto, 0, name)["status"] == "present"
    assert field(dto, name)["counts"]["not_applicable"] == 0


def test_sample_offsets_distinguish_repeated_identical_occurrences_and_bind_original_hashes():
    record = {"paper_id": "paper:a", "tc_kelvin": 0, "private_context": "not exported"}
    dto = enrichment.build_record_field_coverage("mat:test", [record, record], records_total=9,
                                                  record_offsets=[0, 8])
    assert [row["record_offset"] for row in dto["records"]] == [0, 8]
    assert {row["result_id"] for row in dto["records"]} == {legacy_result_id(record, scope_id="mat:test")}
    assert {row["record_sha256"] for row in dto["records"]} == {enrichment.digest(record)}
    assert field(dto, "tc_kelvin")["counts"] == dict(present=2, missing=0, unchecked=7, not_applicable=0)
    assert "not exported" not in json.dumps(dto)
    assert dto["coverage_sha256"] == enrichment.digest({k: v for k, v in dto.items() if k != "coverage_sha256"})
    assert all(dto[key] is False for key in enrichment.AUTHORITY)
    assert_denominators(dto)


@pytest.mark.parametrize("paper_id", ["", " paper:a", "a" * 101, "paper:\nsecret", "paper:\x7fsecret", 7])
def test_invalid_paper_identifiers_are_not_exported(paper_id):
    dto = enrichment.build_record_field_coverage("mat:test", [{"paper_id": paper_id}])
    assert dto["records"][0]["paper_id"] is None


@pytest.mark.parametrize("options", [
    {"records_total": True}, {"records_total": -1}, {"records_total": 1_000_001},
    {"record_offsets": [False]}, {"record_offsets": [-1]}, {"record_offsets": [1]},
    {"record_offsets": []},
])
def test_invalid_denominators_or_offsets_fail_closed(options):
    with pytest.raises(enrichment.EnrichmentError):
        enrichment.build_record_field_coverage("mat:test", [{}], **options)


def test_bounded_rows_duplicate_offsets_and_noncanonical_records_fail_closed():
    for records, options in [([{}] * 33, {}), ([{}, {}], {"record_offsets": [0, 0]}),
                             ([{"tc_kelvin": float("nan")}], {})]:
        with pytest.raises(enrichment.EnrichmentError):
            enrichment.build_record_field_coverage("mat:test", records, **options)
    with pytest.raises(enrichment.EnrichmentError):
        enrichment.build_record_field_coverage("mat:\nsecret", [])


def test_empty_inventory_has_zero_denominators_without_fake_completion():
    dto = enrichment.build_record_field_coverage("mat:test", [])
    assert dto["records"] == []
    assert dto["records_total"] == dto["records_inspected"] == 0
    assert_denominators(dto)


def test_route_registry_iteration_order_cannot_change_independent_coverage_identity(monkeypatch):
    records = [{"tc_kelvin": 0, "knowledge_origin": "Observed"}]
    before = enrichment.build_record_field_coverage("mat:test", records)
    monkeypatch.setattr(enrichment, "FIELD_ROUTES", dict(reversed(list(enrichment.FIELD_ROUTES.items()))))
    assert enrichment.build_record_field_coverage("mat:test", records) == before


class EmptyReadSession:
    async def execute(self, _statement):
        return SimpleNamespace(all=lambda: [], scalars=lambda: SimpleNamespace(all=lambda: []))


@pytest.mark.asyncio
async def test_actual_read_sampling_counts_omitted_occurrences_unchecked_and_preserves_old_report_identity():
    from services import material_enrichment_read as reader

    records = [{"paper_id": "paper:a", "tc_kelvin": index, "knowledge_origin": "Observed"}
               for index in range(65)]
    material = SimpleNamespace(id="mat:sample", formula="NbN", records=records + [{}],
                               current_records=lambda: records)
    baseline = await reader.read_material_enrichment(EmptyReadSession(), material)
    result = await reader.read_material_enrichment(EmptyReadSession(), material, include_record_coverage=True)
    dto = result.pop("record_coverage")
    assert result == baseline
    assert dto["records_total"] == 65  # excludes the raw but currently ineligible occurrence
    assert dto["records_inspected"] == 32
    assert dto["records_unchecked"] == 33
    assert [row["record_offset"] for row in dto["records"]] == [i * 64 // 31 for i in range(32)]
    assert field(dto, "tc_kelvin")["counts"] == dict(present=32, missing=0, unchecked=33, not_applicable=0)
    assert field(dto, "calculation_method")["counts"] == dict(present=0, missing=0, unchecked=33, not_applicable=32)
    assert result["report_sha256"] == enrichment.digest({k: v for k, v in result.items() if k != "report_sha256"})
    assert_denominators(dto)


@pytest.mark.asyncio
async def test_registered_public_route_attaches_independent_hash_after_both_seed_reseals(monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from routers import materials

    records = [{"paper_id": "paper:fixture", "tc_kelvin": 0, "pressure_gpa": 0,
                "knowledge_origin": "Observed", "measurement": "resistivity"}]
    material = SimpleNamespace(id="mat:coverage-http-fixture", formula="NbN", records=records,
                               visibility=object(), current_records=lambda: records)

    class Session(EmptyReadSession):
        async def get(self, _model, identifier):
            assert identifier == material.id
            return material

    session = Session()

    async def database():
        yield session

    async def view(db, value):
        assert db is session and value is material
        return value

    async def revision(db):
        assert db is session
        return ("synthetic-catalogue-epoch", 1)

    # Only isolate visibility/revision/DB boundaries; the registered route,
    # real read worker, actual source seed mergers and both hashes execute.
    monkeypatch.setattr(materials, "material_view", view)
    monkeypatch.setattr(materials, "visibility_allows_view", lambda value: value is material.visibility)
    monkeypatch.setattr(materials, "_material_page_revision", revision)
    app = FastAPI()
    app.include_router(materials.router)
    app.dependency_overrides[materials.get_db] = database
    app.dependency_overrides[materials.peek_identity] = lambda: None
    async with AsyncClient(transport=ASGITransport(app), base_url="http://local-fixture") as client:
        response = await client.get("/materials/mat:coverage-http-fixture/enrichment")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    body = response.json()
    dto = body.pop("record_coverage")
    assert dto["records_total"] == dto["records_inspected"] == 1
    assert field(dto, "pressure_gpa")["counts"] == dict(present=1, missing=0, unchecked=0, not_applicable=0)
    assert body["primary_source_seed"]["candidate_facts_added"] == 0
    assert "classification_primary_source_seed" in body
    assert body["report_sha256"] == enrichment.digest({k: v for k, v in body.items() if k != "report_sha256"})
    assert dto["coverage_sha256"] == enrichment.digest({k: v for k, v in dto.items() if k != "coverage_sha256"})
    assert all(dto[key] is False for key in enrichment.AUTHORITY)
    assert records[0]["pressure_gpa"] == 0


def test_independent_dto_preserves_existing_candidate_and_packaged_seed_report_identities():
    seed = material_enrichment_seed.load_seed()
    assert seed is not None  # validates the unchanged installed seed and its candidate digests
    record = {"formula": "NbN", "paper_id": "paper:a", "tc_kelvin": 16}
    material = SimpleNamespace(id="mat:nbn", formula="NbN", current_records=lambda: [record])
    text = "NbN has Tc=16 K at 0 GPa."
    source = {"id": "capture:a", "paper_id": "paper:a", "text": text,
              "content_sha256": enrichment.text_digest(text), "source_revision": "synthetic:v1",
              "kind": "original_passage", "source_status": "active", "locator": {"section": "Results"}}
    payload = {"id": material.id, "formula": material.formula, "records": [record]}
    report = enrichment.build_enrichment_report([payload], [source], include_evidence_text=False)
    before = deepcopy(report)
    dto = enrichment.build_record_field_coverage(material.id, [record])
    for candidate in report["candidates"]:
        enrichment.validate_candidate_identity(candidate)
    merged = material_classification_seed.merge_primary_classification_seed(
        material_enrichment_seed.merge_primary_seed(report, material), material)
    independent = material_classification_seed.merge_primary_classification_seed(
        material_enrichment_seed.merge_primary_seed(before, material), material)
    merged["record_coverage"] = dto  # route attaches only after both existing reseals
    assert {k: v for k, v in merged.items() if k != "record_coverage"} == independent
    assert merged["report_sha256"] == enrichment.digest({k: v for k, v in independent.items() if k != "report_sha256"})
