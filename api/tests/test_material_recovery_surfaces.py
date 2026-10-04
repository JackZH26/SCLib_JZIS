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
    from services.material_enrichment import digest
    record_coverage = body["record_coverage"]
    assert record_coverage["version"] == "materials-record-field-coverage/1.0.0"
    assert record_coverage["records_total"] == record_coverage["records_inspected"] == 2
    assert record_coverage["records_unchecked"] == 0
    assert record_coverage["coverage_sha256"] == digest(
        {key: value for key, value in record_coverage.items() if key != "coverage_sha256"})
    # The independent DTO must not rewrite either seed's existing report identity.
    assert body["report_sha256"] == digest(
        {key: value for key, value in body.items() if key not in {"report_sha256", "record_coverage"}})
    assert all(sum(row["counts"].values()) == 2 for row in record_coverage["fields"])
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

    async def withdrawing(db, material, **options):
        report = await original(db, material, **options)
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
@pytest.mark.parametrize("bad_section", [" Results", "Results ", "Results\nSynthetic label"])
async def test_recovery_excludes_invalid_locator_without_normalizing_retained_data(client, bad_section):
    from services.material_enrichment import (
        EnrichmentError,
        validate_candidate_identity,
        validate_source,
    )

    invalid_text, valid_text = "NbN has Tc=999 K.", "NbN has Tc=17.5 K."
    identifier, papers = await seed_source_inventory({
        "a": [(invalid_text, bad_section, True), (valid_text, "Results", False)],
    })
    invalid_id, valid_id = f"{papers['a']}:0", f"{papers['a']}:1"
    # The strict source contract must continue rejecting the original locator.
    with pytest.raises(EnrichmentError, match="^source_locator_invalid$"):
        validate_source({"id": invalid_id, "paper_id": papers["a"], "text": invalid_text,
                         "content_sha256": hashlib.sha256(invalid_text.encode()).hexdigest(),
                         "source_revision": "synthetic-retained-revision", "kind": "legacy_unknown",
                         "locator": {"chunk_id": invalid_id, "section": bad_section}})
    async with get_session_factory()() as session:
        original_records = (await session.get(Material, identifier)).records

    response = await client.get(f"/v1/materials/{identifier}/enrichment")
    assert response.status_code == 200, response.text
    assert "no-store" in response.headers["cache-control"]
    report = response.json()
    row = report["coverage"][0]["source_coverage"][papers["a"]]
    assert row["chunks_inspected"] == 2 and row["chunks_supplied"] == 1
    assert row["excluded_chunks_total"] == 1
    assert row["excluded_chunk_reasons"] == {"source_locator_invalid": 1}
    assert row["reason_codes"] == ["source_locator_invalid"]
    assert row["scope"] == "bounded_current_chunks_not_complete_source"
    assert row["fulltext_checked"] is False and row["supplement_checked"] is False
    assert report["inspection_scope"]["characters_inspected"] == len(invalid_text) + len(valid_text)
    assert report["counts"]["source_captures"] == 1
    assert any(c["field"] == "tc_kelvin" and c["value"] == 17.5 for c in report["candidates"])
    for candidate in report["candidates"]:
        assert candidate["source"]["capture_id"] == valid_id
        assert candidate["source"]["locator"] == {"chunk_id": valid_id, "section": "Results"}
        assert candidate["source"]["content_sha256"] == hashlib.sha256(valid_text.encode()).hexdigest()
        assert candidate["source_content_checked"] is False and "evidence_text" not in candidate
        validate_candidate_identity(candidate)
    assert report["classification_candidates"] == []
    assert report["counts"]["promoted_facts"] == 0 and report["database_changed"] is False
    async with get_session_factory()() as session:
        chunk = await session.get(Chunk, invalid_id)
        assert chunk.text == invalid_text and chunk.section == bad_section
        assert (await session.get(Material, identifier)).records == original_records


@pytest.mark.asyncio
async def test_recovery_all_invalid_locators_preserve_unresolved_source_scope(client):
    identifier, papers = await seed_source_inventory({
        "a": [("NbN has Tc=999 K.", " Results", False),
              ("NbN has Tc=998 K.", "Results\nSynthetic label", False)],
    })
    response = await client.get(f"/v1/materials/{identifier}/enrichment")
    assert response.status_code == 200, response.text
    report = response.json()
    row = report["coverage"][0]["source_coverage"][papers["a"]]
    assert row["indexed_chunks_total"] == row["chunks_inspected"] == row["excluded_chunks_total"] == 2
    assert row["chunks_supplied"] == row["omitted_chunks_total"] == 0
    assert row["excluded_chunk_reasons"] == {"source_locator_invalid": 2}
    assert row["reason_codes"] == ["source_locator_invalid"]
    assert row["fulltext_checked"] is False and row["supplement_checked"] is False
    assert report["counts"]["source_captures"] == 0
    assert report["candidates"] == report["classification_candidates"] == []
    assert all(field["status"] != "not_found_in_checked_sources"
               for field in report["coverage"][0]["fields"])
    lattice = next(field for field in report["coverage"][0]["fields"] if field["field"] == "lattice_a")
    assert lattice["status"] == "not_extracted"
    assert lattice["reason_codes"] == ["original_source_capture_not_supplied"]
    assert report["scientific_acceptance"] is False and report["database_changed"] is False


@pytest.mark.asyncio
async def test_recovery_invalid_locators_spend_shared_read_budget_and_keep_other_paper(client):
    invalid_text, valid_text = "NbN has Tc=999 K.", "NbN has Tc=17.5 K."
    identifier, papers = await seed_source_inventory({
        "a": [(invalid_text, " Results", True)] * 45,
        "b": [(valid_text, "Results", False)],
    })
    response = await client.get(f"/v1/materials/{identifier}/enrichment")
    assert response.status_code == 200, response.text
    report = response.json()
    scope = report["inspection_scope"]
    assert scope["chunks_considered"] == scope["chunks_inspected"] == 40
    assert scope["characters_inspected"] == 39 * len(invalid_text) + len(valid_text)
    coverage = report["coverage"][0]["source_coverage"]
    first, second = coverage[papers["a"]], coverage[papers["b"]]
    assert first["chunks_supplied"] == 0 and first["excluded_chunks_total"] == 39
    assert first["excluded_chunk_reasons"] == {"source_locator_invalid": 39}
    assert first["omitted_chunk_reasons"] == {"chunk_inspection_limit": 6}
    assert first["truncated"] is True
    assert second["chunks_supplied"] == 1 and second["excluded_chunks_total"] == 0
    assert report["counts"]["source_captures"] == 1
    assert any(c["field"] == "tc_kelvin" and c["value"] == 17.5 for c in report["candidates"])
    assert all(c["source"]["paper_id"] == papers["b"] for c in report["candidates"])
    for row in coverage.values():
        assert row["chunks_supplied"] + row["excluded_chunks_total"] + row["omitted_chunks_total"] == row["indexed_chunks_total"]
        assert row["fulltext_checked"] is False and row["supplement_checked"] is False


@pytest.mark.asyncio
async def test_recovery_held_paper_is_excluded_before_invalid_locator_inspection(client):
    identifier, papers = await seed_source_inventory({
        "a": [("NbN has Tc=999 K.", " Results", True)],
        "b": [("NbN has Tc=17.5 K.", "Results", False)],
    })
    async with get_session_factory()() as session:
        paper = await session.get(Paper, papers["a"])
        paper.status = "withdrawn"
        await session.commit()
    response = await client.get(f"/v1/materials/{identifier}/enrichment")
    assert response.status_code == 200, response.text
    report = response.json()
    assert set(report["coverage"][0]["source_coverage"]) == {papers["b"]}
    assert report["inspection_scope"]["raw_retained_records_total"] == 2
    assert report["inspection_scope"]["current_eligible_records_total"] == 1
    assert report["inspection_scope"]["chunks_inspected"] == 1
    assert report["counts"]["source_captures"] == 1
    assert all(c["source"]["paper_id"] == papers["b"] for c in report["candidates"])
    assert report["scientific_acceptance"] is False and report["database_changed"] is False


def test_recovery_locator_preflight_does_not_swallow_source_integrity_failure():
    from services.material_enrichment import EnrichmentError
    from services.material_enrichment_read import _compile_recovery_report

    source = {"id": "synthetic:chunk", "paper_id": "synthetic:paper", "text": "NbN has Tc=999 K.",
              "content_sha256": "0" * 64, "source_revision": "synthetic-retained-revision",
              "kind": "legacy_unknown", "locator": {"section": " Results"}}
    # A malformed locator cannot turn an independent content-integrity error
    # into an apparently successful empty report.
    with pytest.raises(EnrichmentError, match="^source_content_changed$"):
        _compile_recovery_report({"id": "synthetic:material", "formula": "NbN", "records": []},
                                 [source], {}, {})


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
    ("NbN thin-film in this study is compared with the NbTiN film from a different study.", {"thin_film"}),
    ("NbN thin film contains a surface defect layer labelled SI.", {"thin_film"}),
    ("NbN and NbTiN films were compared; the thin-film specimen belongs to NbTiN.", set()),
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
        assert candidate["extractor_version"] == "materials-literal-extractor/1.1.1"
        assert candidate["source"]["paper_id"] == papers["a"]
        assert candidate["source"]["content_sha256"] == hashlib.sha256(passage.encode()).hexdigest()
        assert candidate["source_content_checked"] is False and candidate["disposition"] == "pending"
    assert report["counts"]["promoted_facts"] == 0 and report["database_changed"] is False
    async with get_session_factory()() as session:
        assert (await session.get(Material, identifier)).records == original_records


@pytest.mark.asyncio
async def test_recovery_reads_all_fourteen_literal_source_fields_without_promotion_or_unit_loss(client):
    # Synthetic native integration fixtures, not reported scientific values.
    from services.material_enrichment import (
        AUTHORITY,
        LITERAL_SOURCE_FIELDS,
        validate_candidate_identity,
    )

    printed = {
        "hc1_source_value": ("NbN has lower critical field above 200(5) mT.", "above 200(5) mT", "reported_property"),
        "gap_energy_source_value": (r"NbN has superconducting gap \Delta(0) = 0.590(5)~\mathrm{meV}.", r"0.590(5)~\mathrm{meV}", "reported_property"),
        "gap_ratio_source_value": ("NbN has superconducting gap ratio = 3.53 ± 0.04.", "3.53 ± 0.04", "reported_property"),
        "electronic_specific_heat_coefficient_source_value": (r"NbN has electronic specific-heat coefficient \gamma = 3.16 \mathrm{mJ mol^{-1} K^{-2}}.", r"3.16 \mathrm{mJ mol^{-1} K^{-2}}", "reported_property"),
        "debye_temperature_source_value": ("NbN has Debye temperature approximately 492(2) K.", "approximately 492(2) K", "reported_property"),
        "isotope_effect_exponent": ("NbN has isotope-effect exponent α = 0.42 ± 0.03.", "0.42 ± 0.03", "reported_property"),
        "dtc_dp_source_value": ("NbN has dTc/dP = −0.8 ± 0.1 K/GPa.", "−0.8 ± 0.1 K/GPa", "reported_property"),
        "maximum_applied_pressure_source_value": ("NbN has Tc=23 K and maximum applied pressure = 50.8 GPa.", "50.8 GPa", "study_extent"),
        "meissner_fraction_percent": ("NbN has field-cooled Meissner fraction = 12 ± 2 %.", "12 ± 2 %", "reported_property"),
        "transition_width_source_value": ("NbN has superconducting transition width below 1.5 K.", "below 1.5 K", "reported_property"),
        "minimum_temperature_k": ("NbN resistivity down to 0.3 K was measured.", "0.3 K", "measurement_limit"),
        "t_cdw_k": ("NbN has CDW transition temperature = 94 ± 1 K.", "94 ± 1 K", "reported_order_transition"),
        "t_afm_k": ("NbN has Néel temperature = 24(2) K.", "24(2) K", "reported_order_transition"),
        "t_sdw_k": ("NbN has SDW transition at 135 K.", "135 K", "reported_order_transition"),
    }
    assert set(printed) == LITERAL_SOURCE_FIELDS
    invalid_units = ["NbN has superconducting gap ratio = 3.5 Hz.",
                     "NbN has superconducting gap ratio = 3.5 N.",
                     "NbN has isotope exponent = 0.5 Oe.",
                     "NbN has isotope exponent = 0.5 G.",
                     "NbN has isotope exponent = 0.5 fictionalunit.",
                     r"NbN has superconducting gap ratio = 3.5 \times 10^{-3}."]
    inventory = [(text, "Synthetic bounded grammar fixture", False) for text, _, _ in printed.values()]
    inventory.extend((text, "Synthetic invalid dimensionless unit fixture", False) for text in invalid_units)
    identifier, papers = await seed_source_inventory({"a": inventory})
    async with get_session_factory()() as session:
        original_records = (await session.get(Material, identifier)).records
    response = await client.get(f"/v1/materials/{identifier}/enrichment")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    report = response.json()
    literal_rows = [row for row in report["candidates"] if row["field"] in printed]
    assert len(literal_rows) == 14
    rows = {row["field"]: row for row in literal_rows}
    assert set(rows) == set(printed)
    for field, (text, raw, role) in printed.items():
        candidate = rows[field]
        assert candidate["value"] == candidate["raw_value"] == raw
        assert candidate["quantity"] is None and candidate["source_value"]["normalization"] == "none"
        assert candidate["source_value"]["role"] == candidate["subject"]["field_role"] == role
        assert candidate["source"]["paper_id"] == papers["a"]
        assert candidate["source"]["content_sha256"] == hashlib.sha256(text.encode()).hexdigest()
        assert candidate["source"]["kind"] == "legacy_unknown"
        assert candidate["source_content_checked"] is False and candidate["disposition"] == "pending"
        assert "evidence_text" not in candidate
        assert all(candidate[key] is False for key in AUTHORITY)
        for name in ("value_span", "unit_span", "cue_span"):
            span = candidate["source_value"][name]
            if span is not None:
                exact = text[span["char_start"]:span["char_end"]]
                assert hashlib.sha256(exact.encode()).hexdigest() == span["text_sha256"]
        validate_candidate_identity(candidate)
    assert report["inspection_scope"]["chunks_inspected"] == 20
    assert report["counts"]["promoted_facts"] == 0 and report["database_changed"] is False
    fields = {row["field"]: row for row in report["coverage"][0]["fields"]}
    assert all(fields[field]["status"] == "pending_review" for field in printed)
    tc = next(row for row in report["candidates"] if row["field"] == "tc_kelvin")
    assert tc["subject"]["pressure_quantity"] is None
    assert not any(row["field"] == "pressure_gpa" for row in report["candidates"])
    repeated = await client.get(f"/v1/materials/{identifier}/enrichment")
    assert repeated.status_code == 200 and repeated.json() == report
    async with get_session_factory()() as session:
        assert (await session.get(Material, identifier)).records == original_records
        for index, (text, _, _) in enumerate(inventory):
            assert (await session.get(Chunk, f"{papers['a']}:{index}")).text == text
