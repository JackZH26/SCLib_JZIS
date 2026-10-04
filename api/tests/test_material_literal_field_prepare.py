"""Synthetic prepare inputs; source text is reread, never browser metadata."""
import hashlib
from copy import deepcopy
from uuid import uuid4

import pytest
import sqlalchemy as sa

from models.db import Base
from services import material_enrichment as enrichment
from services import material_enrichment_read as recovery
from services import material_literal_field_prepare as service
from services import rag_evidence
from services import source_expression_intake_v2 as expressions
from services.rag_evidence_contract import VERSION as EVIDENCE_VERSION
from services.source_property_pending import SourcePropertyError
from tests.test_material_literal_field_contract import synthetic_literal_package
from tests.test_research_freeze import add
from tests.test_research_freeze import db_session as frozen_db_session

db_session = frozen_db_session


def request():
    return {"version": service.VERSION, "material_id": "synthetic-material", "target": {
        "kind": "retained_result", "material_id": "synthetic-material", "record_index": 0,
        "entity_id": None, "expected_context_sha256": "a"*64},
        "candidate_id": "enrichment:"+"b"*64, "extractor_version": enrichment.EXTRACTOR_VERSION,
        "chunk_id": "synthetic-chunk", "source_content_sha256": "c"*64,
        "retained_result_id": "legacy-result:"+"d"*64, "retained_record_sha256": "e"*64}


def test_closed_pin_request_has_no_browser_source_payload():
    assert service.validate_request(request()) == request()
    for key in ("source_text", "candidate", "metadata", "package", "scientific_acceptance"):
        forged = request()
        forged[key] = "forged"
        with pytest.raises(ValueError):
            service.validate_request(forged)


@pytest.mark.parametrize("change", [
    lambda r: r.update(version="unregistered"),
    lambda r: r.update(candidate_id="enrichment:"+"A"*64),
    lambda r: r.update(extractor_version="unregistered"),
    lambda r: r["target"].update(record_index=True),
    lambda r: r["target"].update(material_id="different"),
])
def test_prepare_unknown_or_cross_target_pins_rejected(change):
    r = request()
    change(r)
    with pytest.raises(ValueError):
        service.validate_request(r)


def pure_source():
    raw = "NbN lower critical field above 12.4(3) mT."
    record = {"paper_id": "synthetic-paper", "tc_kelvin": 15}
    material = {"id": "synthetic-material", "formula": "NbN", "records": [record]}
    source = {"id": "synthetic-chunk", "paper_id": "synthetic-paper", "text": raw,
              "content_sha256": hashlib.sha256(raw.encode()).hexdigest(), "source_revision": "synthetic-source/1",
              "kind": "original_passage", "source_status": "unknown", "locator": {"section": "Synthetic"},
              "source_url": "https://example.org/synthetic"}
    report = enrichment.build_enrichment_report([material], [source])
    candidate = next(c for c in report["candidates"] if c["field"] == "hc1_source_value")
    metadata = synthetic_literal_package()["source"]
    return raw, candidate, metadata


def test_prepare_keeps_original_bound_uncertainty_spans_and_null_quantity():
    raw, candidate, metadata = pure_source()
    package, prepared = service.package_from_candidate(candidate, formula="NbN", source_text=raw, source_metadata=metadata)
    value = prepared.projections[0]["value"]
    assert value["raw_value"] == "above 12.4(3) mT"
    assert value["raw_uncertainty"] == "(3)" and value["quantity"] is None
    assert value["value_span"] == candidate["source_value"]["value_span"]
    assert package["expressions"][0]["conditions"] == []
    assert prepared.projections[0]["field_interpretation_reviewed"] is False
    with pytest.raises(ValueError):
        service.package_from_candidate(candidate, formula="NbN", source_text=raw.replace("12.4", "12.5"), source_metadata=metadata)


def test_prepare_never_prepends_missing_target_or_accepts_rehashed_alias_candidate():
    raw, candidate, metadata = pure_source()
    with pytest.raises(ValueError):
        service.package_from_candidate(candidate, formula="MgB2", source_text=raw, source_metadata=metadata)
    altered = deepcopy(candidate)
    altered["subject"]["identity_basis"] = "nominal_refined_composition_proposal"
    altered["candidate_id"] = "enrichment:" + enrichment.digest({k:v for k,v in altered.items() if k not in {"candidate_id", "evidence_text"}})
    with pytest.raises(ValueError):
        service.package_from_candidate(altered, formula="NbN", source_text=raw, source_metadata=metadata)


@pytest.mark.asyncio
async def test_actual_chunk_prepare_positive_and_origin_url_pin_holds(db_session):
    from tests.research_access_helpers import research_operator
    from tests.test_material_field_cases import retained
    operator = await research_operator()
    material, paper = await retained(db_session)
    await db_session.execute(sa.update(Base.metadata.tables["materials"]).where(Base.metadata.tables["materials"].c.id == material).values(formula="NbN", formula_normalized="NbN"))
    await db_session.execute(sa.update(Base.metadata.tables["papers"]).where(Base.metadata.tables["papers"].c.id == paper).values(arxiv_id="2401.00001"))
    raw = "NbN lower critical field above 12.4(3) mT."
    chunk = "literal-prepare:" + uuid4().hex
    await add(db_session, "chunks", id=chunk, paper_id=paper, text=raw, materials_mentioned=[], section="Synthetic original window", chunk_index=0)
    context = await service.cases.context(db_session, actor_user_id=operator["id"], material_id=material, record_index=0)
    view = await service.material_view(db_session, await db_session.get(service.Material, material))
    # An unresolved legacy origin is explicitly withheld; it is not repaired.
    report = await recovery.read_material_enrichment(db_session, view)
    candidate = next(c for c in report["candidates"] if c["field"] == "hc1_source_value")
    r = {**request(), "material_id": material, "target": context["target"], "candidate_id": candidate["candidate_id"],
         "chunk_id": chunk, "source_content_sha256": hashlib.sha256(raw.encode()).hexdigest(),
         "retained_result_id": context["closure"]["legacy_result_id"], "retained_record_sha256": context["closure"]["retained_record_sha256"]}
    with pytest.raises(SourcePropertyError, match="origin_held"):
        await service.prepare(db_session, actor_user_id=operator["id"], request=r)
    evidence = await rag_evidence.register_chunk_evidence(db_session, chunk_id=chunk,
        candidate={"version": EVIDENCE_VERSION, "chunk_kind": "original_passage", "permission_status": "unresolved",
                   "source_locator": {"section": "Synthetic original window"}}, dry_run=False)
    await rag_evidence.bind_chunk_evidence(db_session, chunk_id=chunk, evidence_revision_id=evidence["evidence_revision_id"], dry_run=False)
    # Descriptor version pins deliberately change the candidate identity.
    report = await recovery.read_material_enrichment(db_session, view)
    r["candidate_id"] = next(c for c in report["candidates"] if c["field"] == "hc1_source_value")["candidate_id"]
    before = await db_session.scalar(sa.select(sa.func.count()).select_from(expressions._table(1)))
    prepared = await service.prepare(db_session, actor_user_id=operator["id"], request=r)
    assert prepared["pending_ledger_written"] is False
    assert prepared["source_origin"]["publication_revision_verified"] is False
    assert prepared["package"]["source"]["rights_status"] == "unresolved"
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(expressions._table(1))) == before
    assert service.expression_contract.compile_package(prepared["package"]).projections[0]["value"]["raw_value"] == "above 12.4(3) mT"
    changed = {**r, "source_content_sha256": "f"*64}
    with pytest.raises(SourcePropertyError, match="source_changed"):
        await service.prepare(db_session, actor_user_id=operator["id"], request=changed)
    await db_session.execute(sa.update(Base.metadata.tables["papers"]).where(Base.metadata.tables["papers"].c.id == paper).values(arxiv_id=None))
    refreshed = await rag_evidence.register_chunk_evidence(db_session, chunk_id=chunk,
        candidate={"version": EVIDENCE_VERSION, "chunk_kind": "original_passage", "permission_status": "unresolved",
                   "source_locator": {"section": "Synthetic original window"}}, dry_run=False)
    await rag_evidence.bind_chunk_evidence(db_session, chunk_id=chunk, evidence_revision_id=refreshed["evidence_revision_id"], dry_run=False)
    with pytest.raises(SourcePropertyError, match="url_unavailable"):
        await service.prepare(db_session, actor_user_id=operator["id"], request=r)


@pytest.mark.asyncio
async def test_private_prepare_http_disabled_access_and_closed_request(client, monkeypatch):
    from config import get_settings
    from tests.research_access_helpers import research_operator, research_user

    prefix = "/v1/research/material-literal-fields"
    get_settings.cache_clear()
    assert (await client.get(prefix + "/capabilities")).status_code == 404
    monkeypatch.setenv("SOURCE_PROPERTY_PENDING_ENABLED", "true")
    get_settings.cache_clear()
    try:
        operator = await research_operator()
        reviewer = await research_operator(role="reviewer")
        ungranted = await research_user(is_admin=True)
        for headers, expected in (({}, 401), (ungranted["headers"], 403),
                                  (operator["headers"], 200), (reviewer["headers"], 200)):
            response = await client.get(prefix + "/capabilities", headers=headers)
            assert response.status_code == expected
            assert response.headers["cache-control"] == "private, no-store"
        caps = (await client.get(prefix + "/capabilities", headers=operator["headers"])).json()
        assert caps["profile"] == service.PROFILE
        assert caps["field_cases"]["version"] == "material-field-case/1.1.0"
        forged = {**request(), "source_text": "NbN fabricated source"}
        response = await client.post(prefix + "/prepare", headers=operator["headers"], json=forged)
        assert response.status_code == 400
        assert "fabricated source" not in response.text
    finally:
        get_settings.cache_clear()
