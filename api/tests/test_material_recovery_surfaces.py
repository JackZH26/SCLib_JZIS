import hashlib
from uuid import uuid4

import pytest

from models.db import Chunk, Material, Paper, get_session_factory


async def seed(*, status="active_research"):
    suffix = uuid4().hex[:12]
    material_id, paper_id = f"mat:recovery:{suffix}", f"arxiv:recovery:{suffix}"
    records = [
        {"paper_id": paper_id, "formula": "NbN", "tc_kelvin": 200, "pressure_gpa": 300,
         "knowledge_origin": "Computed", "method": "DFT", "year": 2026},
        {"paper_id": paper_id, "formula": "NbN", "tc_kelvin": 23, "pressure_gpa": 2,
         "knowledge_origin": "Observed", "measurement": "resistivity", "tc_criterion": "onset", "year": 2024},
    ]
    async with get_session_factory()() as session:
        session.add(Paper(id=paper_id, source="arxiv", title="Synthetic recovery test",
                          authors=[], abstract="Synthetic fixture", status="published"))
        session.add(Material(id=material_id, formula="NbN", formula_normalized=suffix, family=suffix,
                             records=records, tc_max=200, tc_max_theoretical=200, total_papers=1,
                             needs_review=False, status=status))
        await session.commit()
        session.add_all([
            Chunk(id=f"{paper_id}:0", paper_id=paper_id, chunk_index=0, section="Results",
                  text="NbN has a superconducting transition temperature of 23 K at 2 GPa, measured by resistivity."),
            Chunk(id=f"{paper_id}:1", paper_id=paper_id, chunk_index=1, section="Facts",
                  text="NbN has a superconducting transition temperature of 999 K at 888 GPa."),
        ])
        await session.commit()
    return material_id, suffix, records


async def seed_source_inventory(inventories):
    """Persist real indexed sources in the invocation's disposable database."""
    suffix = uuid4().hex[:12]
    identifier = f"mat:recovery:{suffix}"
    paper_ids = {label: f"arxiv:recovery:{suffix}:{label}" for label in inventories}
    records = [{"paper_id": paper_id, "formula": "NbN", "tc_kelvin": 23,
                "knowledge_origin": "Observed", "measurement": "resistivity", "year": 2024}
               for paper_id in paper_ids.values()]
    async with get_session_factory()() as session:
        session.add_all([Paper(id=paper_id, source="arxiv", title="Synthetic bounded-source fixture",
                              authors=[], abstract="Synthetic fixture", status="published")
                         for paper_id in paper_ids.values()])
        session.add(Material(id=identifier, formula="NbN", formula_normalized=suffix, family=suffix,
                             records=records, tc_max=23, total_papers=len(paper_ids),
                             needs_review=False, status="active_research"))
        await session.commit()
        session.add_all([Chunk(id=f"{paper_ids[label]}:{index}", paper_id=paper_ids[label],
                               chunk_index=index, text=text, section=section, has_table=has_table)
                         for label, chunks in inventories.items()
                         for index, (text, section, has_table) in enumerate(chunks)])
        await session.commit()
    return identifier, paper_ids


@pytest.mark.asyncio
async def test_matched_tc_is_atomic_and_does_not_borrow_catalogue_maximum(client):
    _, family, _ = await seed()
    response = await client.get("/v1/materials", params={"family": family, "pressure_max": 3, "tc_min": 20})
    assert response.status_code == 200
    body = response.json()["results"][0]
    assert body["tc_max"] == 200
    match = body["matching_results"][0]
    assert match["tc_evidence"]["result_id"] == match["result_id"]
    assert match["tc_evidence"]["value"] == 23
    assert match["tc_evidence"]["state"]["pressure_semantics"]["pressure_gpa"] == 2
    assert match["tc_evidence"]["source"]["year"] == 2024
    assert match["tc_evidence"]["conditions"]["tc_criterion"] == "onset"


@pytest.mark.asyncio
async def test_recovery_omits_facts_and_excerpts_and_never_changes_retained_records(client):
    identifier, _, records = await seed()
    response = await client.get(f"/v1/materials/{identifier}/enrichment")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scientific_acceptance"] is False and body["database_changed"] is False
    assert body["counts"]["promoted_facts"] == 0
    assert body["candidates"]
    for candidate in body["candidates"]:
        assert "evidence_text" not in candidate
        assert candidate["value"] not in {999, 888}
        assert candidate["source"]["kind"] == "legacy_unknown"
        assert candidate["source"]["publication_revision_verified"] is False
        assert candidate["source_content_checked"] is False
    async with get_session_factory()() as session:
        assert (await session.get(Material, identifier)).records == records


@pytest.mark.asyncio
async def test_primary_classification_seed_is_source_scoped_and_stops_after_record_change(client, monkeypatch):
    identifier, _, records = await seed()
    from services import material_classification_seed
    from services.material_enrichment import build_enrichment_report, text_digest

    statement = "NbN exhibits CDW measured by neutron diffraction."
    source = {"id": "capture:synthetic-primary", "paper_id": records[0]["paper_id"], "text": statement,
              "content_sha256": text_digest(statement), "source_revision": "synthetic-primary/v1",
              "kind": "original_passage", "locator": {"section": "Synthetic benchmark"}}
    full = build_enrichment_report([{"id": identifier, "formula": "NbN", "records": records}], [source],
                                   include_evidence_text=False)
    assert len(full["classification_candidates"]) == 1
    resource = {"version": material_classification_seed.VERSION, "seed_id": "synthetic-native-primary",
                "seed_sha256": "0" * 64, "candidates": full["classification_candidates"]}
    monkeypatch.setattr(material_classification_seed, "load_seed", lambda: resource)
    response = await client.get(f"/v1/materials/{identifier}/enrichment")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    body = response.json()
    candidate, = body["classification_candidates"]
    assert candidate["claim"]["normalized_value"] == "CDW" and candidate["claim"]["stance"] == "reported"
    assert candidate["retained_reference_count"] == 2
    assert candidate["scientific_acceptance"] is False and candidate["material_state_reviewed"] is False
    assert body["classification_counts"]["promoted_facts"] == body["counts"]["promoted_facts"] == 0
    assert body["classification_primary_source_seed"]["candidate_facts_added"] == 1
    assert "evidence_text" not in candidate and "source_excerpt" not in response.text
    async with get_session_factory()() as session:
        material = await session.get(Material, identifier)
        assert material.records == records
        changed = [dict(record) for record in records]
        changed[0]["tc_kelvin"] = 201
        material.records = changed
        await session.commit()
    replacement = await client.get(f"/v1/materials/{identifier}/enrichment")
    assert replacement.status_code == 200, replacement.text
    assert replacement.json()["classification_candidates"] == []
    assert replacement.json()["classification_primary_source_seed"]["candidate_facts_added"] == 0


@pytest.mark.asyncio
async def test_external_reference_and_recovery_routes_cannot_bypass_hold(client, monkeypatch):
    identifier, _, _ = await seed(status="pending")
    from routers import materials
    async def unexpected(*args, **kwargs):
        raise AssertionError("Upstream must not be queried for an ineligible material")
    monkeypatch.setattr(materials, "fetch_external_references", unexpected)
    assert (await client.get(f"/v1/materials/{identifier}/external_references")).status_code == 404
    assert (await client.get(f"/v1/materials/{identifier}/enrichment")).status_code == 404


@pytest.mark.asyncio
async def test_recovery_discards_snapshot_if_source_withdraws_during_read(client, monkeypatch):
    identifier, _, records = await seed()
    from services import material_enrichment_read
    original = material_enrichment_read.read_material_enrichment

    async def withdrawing(db, material):
        report = await original(db, material)
        async with get_session_factory()() as session:
            paper = await session.get(Paper, records[0]["paper_id"])
            paper.status = "withdrawn"
            await session.commit()
        return report

    monkeypatch.setattr(material_enrichment_read, "read_material_enrichment", withdrawing)
    response = await client.get(f"/v1/materials/{identifier}/enrichment")
    assert response.status_code == 503
    assert "no-store" in response.headers["cache-control"]
    assert response.headers["retry-after"] == "1"
    assert "candidates" not in response.json()


@pytest.mark.asyncio
async def test_recovery_round_robin_reaches_second_paper_beyond_forty_table_hits(client):
    identifier, papers = await seed_source_inventory({
        "a": [("NbN has Tc=23 K at 2 GPa, measured by resistivity.", "Results", True)] * 45,
        "b": [("NbN has Tc=17.5 K, measured by resistivity.", "Results", False)],
    })
    response = await client.get(f"/v1/materials/{identifier}/enrichment")
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["inspection_scope"]["chunks_considered"] == 40
    assert report["inspection_scope"]["chunks_inspected"] == 40
    assert report["counts"]["source_captures"] == 40
    assert any(candidate["field"] == "tc_kelvin" and candidate["value"] == 17.5
               and candidate["source"]["paper_id"] == papers["b"] for candidate in report["candidates"])
    coverage = report["coverage"][0]["source_coverage"]
    assert coverage[papers["a"]]["chunks_supplied"] == 39
    assert coverage[papers["a"]]["omitted_chunk_reasons"] == {"chunk_inspection_limit": 6}
    assert coverage[papers["b"]]["chunks_supplied"] == 1
    assert coverage[papers["b"]]["omitted_chunks_total"] == 0
    assert coverage[papers["b"]]["truncated"] is False


@pytest.mark.asyncio
async def test_recovery_character_budget_skips_big_chunk_and_keeps_later_complete_source(client):
    def passage(value, length):
        prefix = f"NbN has Tc={value} K, measured by resistivity. "
        return prefix + "x" * (length - len(prefix))

    first, nonfitting, later = passage(23, 19900), passage(999, 1000), passage(17.5, 400)
    identifier, papers = await seed_source_inventory({
        "a": [(first, "Results", True)] * 6 + [(nonfitting, "Results", True), (later, "Results", True)],
    })
    response = await client.get(f"/v1/materials/{identifier}/enrichment")
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["inspection_scope"]["chunks_considered"] == 8
    assert report["inspection_scope"]["chunks_inspected"] == 7
    assert report["inspection_scope"]["characters_inspected"] == 119800
    row = report["coverage"][0]["source_coverage"][papers["a"]]
    assert row["omitted_chunk_reasons"] == {"character_inspection_limit": 1}
    assert row["chunks_supplied"] == 7 and row["excluded_chunks_total"] == 0
    candidate = next(candidate for candidate in report["candidates"] if candidate["value"] == 17.5)
    assert candidate["source"]["content_sha256"] == hashlib.sha256(later.encode()).hexdigest()
    assert candidate["source"]["locator"]["chunk_id"] == f"{papers['a']}:7"
    assert all(candidate["value"] != 999 for candidate in report["candidates"])
    assert row["fulltext_checked"] is False and row["supplement_checked"] is False


@pytest.mark.asyncio
async def test_recovery_counts_actual_restricted_stale_derived_and_length_omissions_per_paper(client):
    from services.rag_evidence import register_chunk_evidence

    identifier, papers = await seed_source_inventory({
        "a": [("NbN has Tc=999 K.", "Facts", True),
              ("NbN has Tc=998 K.", "Results", True),
              ("NbN has Tc=23 K.", "Results", True)],
        "b": [("NbN has Tc=17.5 K.", "Results", False),
              ("NbN has Tc=997 K.", "Results", False),
              ("x" * 20001, "Results", False), ("", "Results", False)],
    })
    locator = {"page": 2, "table": "S1", "row": 3, "column": 2,
               "xml_xpath": "/article/body/sec[2]/table-wrap[1]/table/tbody/tr[3]/td[2]",
               "section": "Results", "char_start": 50, "char_end": 149}
    async with get_session_factory()() as session:
        await register_chunk_evidence(session, chunk_id=f"{papers['a']}:1", dry_run=False,
            candidate={"version": "rag-evidence/1.0.0", "chunk_kind": "original_passage",
                       "permission_status": "restricted"})
        await register_chunk_evidence(session, chunk_id=f"{papers['a']}:2", dry_run=False,
            candidate={"version": "rag-evidence/1.0.0", "chunk_kind": "original_passage",
                       "source_locator": locator})
        await register_chunk_evidence(session, chunk_id=f"{papers['b']}:1", dry_run=False,
            candidate={"version": "rag-evidence/1.0.0", "chunk_kind": "original_passage"})
        await session.commit()
        changed = await session.get(Chunk, f"{papers['b']}:1")
        changed.text += " Revised synthetic passage."
        await session.commit()
    response = await client.get(f"/v1/materials/{identifier}/enrichment")
    assert response.status_code == 200, response.text
    report = response.json()
    coverage = report["coverage"][0]["source_coverage"]
    first, second = coverage[papers["a"]], coverage[papers["b"]]
    assert first["excluded_chunks_total"] == 2
    assert first["excluded_chunk_reasons"] == {"derived_source": 1, "source_permission_restricted": 1}
    assert second["excluded_chunks_total"] == 1
    assert second["excluded_chunk_reasons"] == {"source_not_current": 1}
    assert second["omitted_chunk_reasons"] == {"indexed_chunk_length_outside_bounds": 2}
    for row in (first, second):
        assert row["chunks_supplied"] == 1
        assert row["chunks_supplied"] + row["excluded_chunks_total"] + row["omitted_chunks_total"] == row["indexed_chunks_total"]
    assert all(candidate["value"] not in {999, 998, 997} for candidate in report["candidates"])
    candidate = next(candidate for candidate in report["candidates"] if candidate["value"] == 23)
    assert candidate["source"]["locator"] == {**locator, "chunk_id": f"{papers['a']}:2"}
    assert candidate["source"]["content_sha256"] == hashlib.sha256(b"NbN has Tc=23 K.").hexdigest()


@pytest.mark.asyncio
@pytest.mark.parametrize("passage", [
    "NbN exhibits charge order below Tstar=40~K and Tco=58 K.",
    "NbN exhibits charge order at −5 K and 58 K.",
])
async def test_recovery_reviews_formatted_multiple_temperatures_as_distinct_states(client, passage):
    identifier, papers = await seed_source_inventory({"a": [(passage, "Results", False)]})
    response = await client.get(f"/v1/materials/{identifier}/enrichment")
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["classification_extractor_version"] == "materials-source-statement-extractor/1.0.1"
    assert report["classification_candidates"] == []
    finding, = report["classification_review_findings"]
    assert finding["reason_codes"] == ["multiple_local_temperature_mentions_require_state_review"]
    assert finding["source"]["paper_id"] == papers["a"]
    assert finding["source"]["content_sha256"] == hashlib.sha256(passage.encode()).hexdigest()
    assert report["classification_counts"]["promoted_facts"] == 0
    assert report["database_changed"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("passage,expected_forms", [
    ("NbN exhibits bulk superconductivity at Tc=23 K, supported by heat-capacity measurements.", set()),
    ("Bulk NbN samples were prepared for resistivity measurements.", {"bulk"}),
    ("NbN single crystals exhibit bulk superconductivity at Tc=23 K.", {"single_crystal"}),
    ("No NbN bulk samples were obtained.", set()),
    ("NbN shows bulk superconductivity while MgB2 samples are single crystals.", set()),
])
async def test_recovery_distinguishes_physical_sample_form_from_bulk_superconductivity(client, passage, expected_forms):
    identifier, papers = await seed_source_inventory({"a": [(passage, "Results", False)]})
    async with get_session_factory()() as session:
        original_records = (await session.get(Material, identifier)).records
    response = await client.get(f"/v1/materials/{identifier}/enrichment")
    assert response.status_code == 200, response.text
    report = response.json()
    forms = [candidate for candidate in report["candidates"] if candidate["field"] == "sample_form"]
    assert {candidate["value"] for candidate in forms} == expected_forms
    for candidate in forms:
        assert candidate["extractor_version"] == "materials-literal-extractor/1.0.1"
        assert candidate["source"]["paper_id"] == papers["a"]
        assert candidate["source"]["content_sha256"] == hashlib.sha256(passage.encode()).hexdigest()
        assert candidate["source_content_checked"] is False and candidate["disposition"] == "pending"
    assert report["counts"]["promoted_facts"] == 0 and report["database_changed"] is False
    async with get_session_factory()() as session:
        assert (await session.get(Material, identifier)).records == original_records
