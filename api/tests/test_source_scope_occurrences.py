"""SC08 exact container-source checks over guarded synthetic SQL and HTTP."""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

from models.db import Chunk, Material, MaterialClaim, Paper, SourceSnapshot, get_session_factory
from services import provider_resilience, rag, retrieval, retrieval_currentness
from services.history_evidence import current_history_evidence
from services.material_source_scope import scoped_material_visibility
from services.material_visibility_adapter import MaterialReadContext, prepare_material_views
from services.source_lifecycle import resolve_paper_lifecycle
from services.source_visibility import (
    linked_material_visibility,
    occurrence_visibility,
    project_source_occurrences,
    resolve_explicit_materials,
    source_visibility,
)


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    async with get_session_factory()() as session:
        yield session


def scoped_context():
    raw = {"id": "mat:scope:occurrence", "formula": "MgB2", "family": "mgb2", "needs_review": False,
           "status": "active_research", "records": [
               {"paper_id": "scope:held", "formula": "MgB2", "tc_kelvin": 900, "aggregate_note": "retained"},
               {"paper_id": "scope:good", "formula": "MgB2", "tc_kelvin": 39, "aggregate_note": "retained"},
               {"paper_id": "scope:other-good", "formula": "MgB2", "tc_kelvin": 38},
           ]}
    statuses = {"scope:held": "retracted", "scope:good": "published", "scope:other-good": "published"}
    visibility, scope = scoped_material_visibility(raw, source_statuses=statuses)
    assert scope is not None and visibility["version"] == "material-visibility/2.0.0"
    return MaterialReadContext(raw, visibility, statuses, scope)


def occurrence(context, *, record=None, container="scope:good", status="published", linked=None):
    return occurrence_visibility(record if record is not None else {"material_id": context.id, "formula": "MgB2"},
        paper_status=status, container_paper_id=container,
        linked_visibility=linked_material_visibility(context) if linked is None else linked)


def assert_withheld(value, reason):
    assert value["version"] == "material-visibility/1.0.0"
    assert not value["public_catalogue_eligible"] and not value["reported_claim_filter_eligible"]
    assert value["state"] != "catalogue"  # Existing frontend occurrence v1 invariant.
    assert value["archive_available"] and value["scientific_acceptance"] is False
    assert reason in value["reason_codes"]
    assert "source_scoped_occurrence_withheld" in value["warning_codes"]


@pytest.mark.parametrize("explicit_paper", [False, True])
def test_exact_container_scope_does_not_compare_unrelated_aggregate_arrays(explicit_paper):
    context = scoped_context()
    record = {"material_id": context.id, "formula": "MgB2", "tc_kelvin": "39 K"}
    if explicit_paper:
        record["paper_id"] = "scope:good"
    before = deepcopy(context.records)
    actual = occurrence(context, record=record)
    assert actual["public_catalogue_eligible"] and actual["reported_claim_filter_eligible"]
    assert actual["state"] == "catalogue" and actual["scientific_acceptance"] is False
    assert context.records == before
    linked = linked_material_visibility(context)
    # The private object is never serialized as part of the public envelope.
    assert json.loads(json.dumps(linked)) == context.visibility
    assert "scope:good" not in json.dumps(actual)


@pytest.mark.parametrize("container,status,record_paper,reason", [
    (None, "published", "scope:good", "occurrence_container_source_unresolved"),
    ("", "published", None, "occurrence_container_source_unresolved"),
    (" scope:good", "published", None, "occurrence_container_source_unresolved"),
    ("scope:outside", "published", None, "occurrence_source_outside_eligible_scope"),
    ("scope:held", "published", None, "occurrence_source_outside_eligible_scope"),
    ("scope:good", None, None, "occurrence_source_not_currently_eligible"),
    ("scope:good", "disputed", None, "occurrence_source_not_currently_eligible"),
    ("scope:good", "published", "scope:other-good", "occurrence_container_source_conflict"),
    ("scope:good", "published", True, "occurrence_container_source_conflict"),
])
def test_source_identity_and_live_status_are_required(container, status, record_paper, reason):
    context = scoped_context()
    record = {"material_id": context.id, "formula": "MgB2"}
    if record_paper is not None:
        record["paper_id"] = record_paper
    assert_withheld(occurrence(context, record=record, container=container, status=status), reason)


@pytest.mark.parametrize("fault", ["public_dict", "missing_scope", "fake_scope", "changed_records", "changed_membership", "summary", "other_material"])
def test_missing_or_forged_private_scope_never_downgrades_to_v1(fault):
    context = scoped_context()
    if fault == "missing_scope":
        context = replace(context, source_scope=None)
    elif fault == "fake_scope":
        context = replace(context, source_scope=SimpleNamespace(**context.visibility["source_scope"]))
    elif fault == "changed_records":
        context.material["records"][1]["tc_kelvin"] = 40
    elif fault == "changed_membership":
        context = replace(context, source_scope=replace(context.source_scope, eligible_indices=(0, 1, 2)))
    linked = linked_material_visibility(context)
    if fault == "public_dict":
        linked = dict(linked)
    elif fault == "summary":
        linked["source_scope"]["fingerprint"] = "0" * 64
    elif fault == "other_material":
        linked.material_id = "mat:other"
    assert_withheld(occurrence(context, linked=linked), "occurrence_source_scope_unavailable")


def test_scope_exclusion_preserves_archive_and_warns_existing_summary():
    context = scoped_context()
    raw = {"material_id": context.id, "formula": "MgB2", "tc_kelvin": 39}
    projected, summary = project_source_occurrences([raw], paper_status="published",
        linked_materials={context.id: linked_material_visibility(context)}, container_paper_id="scope:outside")
    assert projected[0]["tc_kelvin"] == 39 and summary["omitted_occurrences"] == 0
    assert summary["state_counts"] == {"pending": 1}
    assert summary["warning_codes"] == ["source_scoped_occurrence_withheld"]
    assert "visibility" not in raw
    # No exact material identity: the unchanged legacy unlinked policy applies.
    unlinked = occurrence_visibility({"formula": "MgB2"}, paper_status="published")
    assert unlinked["reported_claim_filter_eligible"] and not unlinked["public_catalogue_eligible"]


@pytest.mark.parametrize("custom_threshold", [False, True])
def test_same_paper_good_record_cannot_clear_a_sibling_anomaly(custom_threshold):
    context = scoped_context()
    material = deepcopy(context.material)
    bad_value = 38 if custom_threshold else 900
    if custom_threshold:
        material["anomaly_context"] = {"compound_thresholds": [{"field": "tc_max", "threshold": 35,
            "reference_id": "private-material-threshold", "mode": "upper_reference"}]}
        material["records"][1]["tc_kelvin"] = 30
        material["records"][2]["tc_kelvin"] = 30
    material["records"].append({"paper_id": "scope:good", "tc_kelvin": bad_value})
    visibility, scope = scoped_material_visibility(material, source_statuses=context.source_statuses)
    context = MaterialReadContext(material, visibility, context.source_statuses, scope)
    assert scope is not None and "scope:good" in scope.eligible_paper_ids
    good = {"material_id": context.id, "formula": "MgB2", "tc_kelvin": 30}
    assert occurrence(context, record=good)["reported_claim_filter_eligible"]
    bad = {**good, "tc_kelvin": bad_value, "anomaly_context": {"compound_thresholds": []},
           "anomaly_review": {"needs_review": False}, "visibility": {"public_catalogue_eligible": True}}
    assert_withheld(occurrence(context, record=bad), "occurrence_anomaly_review_required")
    assert "private-material-threshold" not in json.dumps(occurrence(context, record=bad))
    assert "private-material-threshold" not in json.dumps(linked_material_visibility(context))
    # Scoped replay adds no new policy to the frozen v1 unlinked behavior.
    assert occurrence_visibility({"tc_kelvin": 900}, paper_status="published")["reported_claim_filter_eligible"]


async def seed_occurrences(db):
    suffix = uuid4().hex
    material_id = "mat:occurrence:" + suffix
    papers, chunks = [], []
    for tag in ("good", "held", "outside"):
        paper_id = f"scope:{tag}:{suffix}"
        record = {"material_id": material_id, "formula": "MgB2", "tc_kelvin": 39, "knowledge_origin": "Observed"}
        paper = Paper(id=paper_id, source="arxiv", title="Synthetic scoped source", authors=[],
            abstract="Synthetic preserved bibliography.", status="published", materials_extracted=[record])
        chunk = Chunk(id=paper_id + "_chunk", paper_id=paper_id, title=paper.title, section="Results",
            text="The synthetic source reports MgB2. This fixture is not scientific evidence.",
            materials_mentioned=deepcopy([record]))
        papers.append(paper)
        chunks.append(chunk)
    material = Material(id=material_id, formula="MgB2", formula_normalized="scope-" + suffix, family="mgb2",
        total_papers=2, needs_review=False, records=[
            {"paper_id": papers[0].id, "formula": "MgB2", "tc_kelvin": 39, "aggregate_note": "different metadata"},
            {"paper_id": papers[1].id, "formula": "MgB2", "tc_kelvin": 900},
        ])
    db.add_all([material, *papers, *chunks])
    await db.commit()
    papers[1].status = "retracted"
    await db.commit()
    return material, papers, chunks


@pytest.mark.asyncio
async def test_actual_papers_keep_archive_but_cannot_launder_other_paper_scope(client, db_session):
    material, papers, _ = await seed_occurrences(db_session)
    original_records = deepcopy(material.records)
    for index, paper in enumerate(papers):
        response = await client.get(f"/v1/paper/{paper.id}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["abstract"] == paper.abstract and body["source_visibility"]["bibliography_available"]
        value = body["materials_extracted"][0]["visibility"]
        assert value["version"] == "material-visibility/1.0.0"
        assert value["public_catalogue_eligible"] is (index == 0)
        assert value["reported_claim_filter_eligible"] is (index == 0)
        assert value["archive_available"] and value["scientific_acceptance"] is False
        if index == 2:
            assert_withheld(value, "occurrence_source_outside_eligible_scope")
            assert body["occurrence_visibility_summary"]["state_counts"] == {"pending": 1}
    await db_session.refresh(material)
    assert material.records == original_records


@pytest.mark.asyncio
@pytest.mark.parametrize("custom_threshold", [False, True])
async def test_actual_same_paper_sibling_anomaly_preserves_archive_without_current_badge(client, db_session, custom_threshold):
    material, papers, _ = await seed_occurrences(db_session)
    bad_value = 38 if custom_threshold else 900
    good = {**papers[0].materials_extracted[0], "tc_kelvin": 30}
    bad = {**good, "tc_kelvin": bad_value, "anomaly_context": {"compound_thresholds": []}}
    papers[0].materials_extracted = [good, bad]
    material.records = [{**material.records[0], "tc_kelvin": 30}, material.records[1],
                        {"paper_id": papers[0].id, "formula": "MgB2", "tc_kelvin": bad_value}]
    if custom_threshold:
        material.anomaly_context = {"compound_thresholds": [{"field": "tc_max", "threshold": 35,
            "reference_id": "private-material-threshold", "mode": "upper_reference"}]}
    await db_session.commit()
    response = await client.get(f"/v1/paper/{papers[0].id}")
    assert response.status_code == 200, response.text
    rows = response.json()["materials_extracted"]
    assert [row["tc_kelvin"] for row in rows] == [30, bad_value]
    assert rows[0]["visibility"]["reported_claim_filter_eligible"]
    assert_withheld(rows[1]["visibility"], "occurrence_anomaly_review_required")
    assert "private-material-threshold" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["search", "ask"])
@pytest.mark.parametrize("index", [0, 2])
async def test_actual_lexical_consumers_use_chunk_container_without_changing_wire(client, db_session, monkeypatch, route, index):
    _, papers, chunks = await seed_occurrences(db_session)
    provider_resilience.reset()
    async def lexical(*args, **kwargs):
        return [retrieval.LexicalHit(chunks[index].id, 1.0)]
    def forbidden(*args, **kwargs):
        raise AssertionError("The synthetic legacy lexical path must not use ANN")
    monkeypatch.setattr(f"routers.{route}.retrieval.lexical_search", lexical)
    monkeypatch.setattr(f"routers.{route}.index_vector_adapter.query", forbidden)
    captured = []
    def generate(question, sources, **kwargs):
        captured.append(rag.build_user_prompt(question, sources))
        return rag.RagResult("The source reports a synthetic result [1].", 2, True, [])
    monkeypatch.setattr("routers.ask.rag.generate_answer", generate)
    response = await client.post(f"/v1/{route}", json={"question" if route == "ask" else "query": "MgB2 report"})
    assert response.status_code == 200, response.text
    source = response.json()["sources" if route == "ask" else "results"][0]
    assert source["paper_id"] == papers[index].id
    value = source["material_evidence" if route == "ask" else "materials"][0]["visibility"]
    assert value["public_catalogue_eligible"] is (index == 0)
    if index == 2:
        assert_withheld(value, "occurrence_source_outside_eligible_scope")
        if route == "ask":
            assert "source_scoped_occurrence_withheld" in captured[0]
    provider_resilience.reset()


@pytest.mark.asyncio
async def test_scope_membership_change_invalidates_selected_input_and_updates_only_current_history(db_session):
    material, papers, chunks = await seed_occurrences(db_session)
    chunk = chunks[0]
    statuses = await resolve_paper_lifecycle(db_session, [chunk.paper_id])
    linked = await resolve_explicit_materials(db_session, [chunk.materials_mentioned])
    occurrences, summary = project_source_occurrences(chunk.materials_mentioned, paper_status=statuses[chunk.paper_id],
        linked_materials=linked, container_paper_id=chunk.paper_id)
    review = source_visibility(statuses[chunk.paper_id])
    review["warning_codes"] = sorted(set(review["warning_codes"] + summary["warning_codes"]))
    pin = retrieval_currentness.selection_pin(chunk, material_evidence=occurrences, source_review=review)
    assert (await retrieval_currentness.check_selected_sources([pin])).status == "unchanged"
    material.records = [{**material.records[0], "paper_id": papers[2].id}, material.records[1]]
    await db_session.commit()
    changed = await retrieval_currentness.check_selected_sources([pin])
    assert changed.status == "changed" and changed.reason_code == "retrieval_source_changed"
    # Same counts and active containing Paper: the scope's identities, not just
    # public summary counts, affect the current selection fingerprint.
    await db_session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
    history = SimpleNamespace(id=uuid4(), sources=[{"paper_id": chunk.paper_id}])
    original_sources = deepcopy(history.sources)
    overlay = (await current_history_evidence(db_session, [history]))[history.id]
    assert overlay["scientific_acceptance"] is False
    assert "source_scoped_occurrence_withheld" in json.dumps(overlay)
    assert "pending" in json.dumps(overlay)
    assert history.sources == original_sources


@pytest.mark.asyncio
async def test_actual_claim_projection_retains_private_scope_but_not_scientific_approval(db_session):
    from routers.ml_foundation import _claim_response

    material, papers, _ = await seed_occurrences(db_session)
    now = datetime.now(UTC)
    snapshot = SourceSnapshot(dataset_version="source-scope-" + uuid4().hex, site_git_sha="a" * 40,
        database_watermark=now, paper_count=3, material_count=1, chunk_count=3,
        schema_version="synthetic-scoped-claim/1", manifest_sha256=uuid4().hex * 2,
        license_manifest_sha256="c" * 64, status="frozen", frozen_at=now)
    db_session.add(snapshot)
    await db_session.flush()
    claims = [MaterialClaim(material_id=material.id, paper_id=papers[index].id, source_snapshot_id=snapshot.id,
        property_type="tc", evidence_role="primary_experimental", result_status="observed",
        value_relation="exact", value_kelvin=39, tc_definition="onset", pressure_state="not_reported",
        source_kind="legacy", validity_status="accepted", raw_record={"formula": "MgB2", "tc_kelvin": 39},
        source_record_hash=uuid4().hex * 2, extractor_version="synthetic-scope/1") for index in (0, 2)]
    db_session.add_all(claims)
    await db_session.commit()
    context = (await prepare_material_views(db_session, [material]))[0]
    assert context.source_scope is not None
    for index, claim in enumerate(claims):
        value = _claim_response(claim, context, "published", None).claim_visibility
        assert value["public_claim_eligible"] is (index == 0)
        assert value["scientific_acceptance"] is False and value["ml_training_eligibility_established"] is False
        assert value["archive_available"]
        if index == 1:
            assert value["state"] == "pending"
            assert "occurrence_source_outside_eligible_scope" in value["reason_codes"]


@pytest.mark.asyncio
async def test_actual_saved_answer_receipt_is_unchanged_when_current_scope_changes(client, db_session, monkeypatch, registered_user):
    material, papers, chunks = await seed_occurrences(db_session)
    _, token = registered_user
    headers = {"Authorization": "Bearer " + token}
    async def lexical(*args, **kwargs):
        return [retrieval.LexicalHit(chunks[0].id, 1.0)]
    def forbidden(*args, **kwargs):
        raise AssertionError("Synthetic lexical fixture does not need ANN")
    monkeypatch.setattr("routers.ask.retrieval.lexical_search", lexical)
    monkeypatch.setattr("routers.ask.index_vector_adapter.query", forbidden)
    monkeypatch.setattr("routers.ask.rag.generate_answer", lambda *args, **kwargs:
        rag.RagResult("A synthetic source report [1].", 2, True, []))
    response = await client.post("/v1/ask", headers=headers, json={"question": "MgB2 report"})
    assert response.status_code == 200, response.text
    saved = response.json()["history"]
    assert saved["status"] == "saved"
    url = "/v1/history/" + saved["history_id"]
    before = await client.get(url, headers=headers)
    assert before.status_code == 200, before.text
    original = before.json()
    assert original["evidence"]["status"] == "verified"
    material.records = [{**material.records[0], "paper_id": papers[2].id}, material.records[1]]
    await db_session.commit()
    after = await client.get(url, headers=headers)
    assert after.status_code == 200, after.text
    current = after.json()
    assert current["evidence"] == original["evidence"]
    assert current["entry"]["sources"] == original["entry"]["sources"]
    assert current["entry"]["answer"] == original["entry"]["answer"]
    assert "source_scoped_occurrence_withheld" in json.dumps(current["entry"]["current_evidence"])
    assert current["evidence"]["currentness_revalidated"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("eligible", [True, False])
async def test_actual_generation_numerical_lookup_requires_exact_scoped_source(client, db_session, monkeypatch, eligible):
    from config import get_settings
    from services import index_vector_adapter
    from tests.index_generation_fixtures import RESOURCE, publish_and_activate
    from tests.test_scientific_query_http import forbid_providers, record, stage_records

    logical = "scope-numerical-" + uuid4().hex
    monkeypatch.setattr(get_settings(), "retrieval_logical_index", logical)
    index_vector_adapter.clear_disposable()
    index_vector_adapter.register_disposable(RESOURCE)
    try:
        material_id = "mat:scoped-query:" + uuid4().hex
        meta, _, staged = await stage_records(monkeypatch, db_session, logical, [record(material_id=material_id)])
        selected_paper = meta.paper_id
        other = Paper(id="scope:independent:" + uuid4().hex, source="arxiv", title="Independent synthetic source",
            authors=[], abstract="Synthetic only.", status="published", materials_extracted=[])
        held = Paper(id="scope:held:" + uuid4().hex, source="arxiv", title="Held synthetic source",
            authors=[], abstract="Synthetic only.", status="retracted", materials_extracted=[])
        material = Material(id=material_id, formula="MgB2", formula_normalized=material_id, family="mgb2",
            total_papers=2, needs_review=False, records=[
                {"paper_id": selected_paper if eligible else other.id, "formula": "MgB2", "tc_kelvin": 39,
                 "aggregate_note": "Not the exact extraction object; container identity is the bridge"},
                {"paper_id": held.id, "formula": "MgB2", "tc_kelvin": 900},
            ])
        db_session.add_all([other, held, material])
        await db_session.commit()
        await publish_and_activate(db_session, staged)
        forbid_providers(monkeypatch)
        response = await client.post("/v1/ask", json={"question": "What is the Tc of MgB2 at ambient pressure?"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["scientific_lookup"]["status"] == "completed"
        assert len(body["scientific_results"]) == (1 if eligible else 0)
        if eligible:
            item = body["scientific_results"][0]
            assert item["binding"]["paper_id"] == selected_paper
            assert item["result"]["tc"]["value"] == 39
            assert not item["result"]["scientific_acceptance"] and not item["result"]["ml_training_eligible"]
        assert body["tokens_used"] == 0
    finally:
        index_vector_adapter.clear_disposable()
