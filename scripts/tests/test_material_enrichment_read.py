"""Read adapter limits, source partition and public egress; zero DB/client I/O."""
from __future__ import annotations

import asyncio
import hashlib
import sys
import threading
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))

from services import material_enrichment_read as reader  # noqa: E402
from services.material_enrichment import digest, validate_candidate_identity  # noqa: E402


class FakeReadSession:
    def __init__(self, chunks, *, papers=()):
        self.chunks, self.papers, self.statements = chunks, papers, []
        self.measured_lengths = {}

    async def execute(self, statement):
        self.statements.append(statement)
        assert statement.is_select
        parameters = statement.compile().params
        paper_ids = next(value for value in parameters.values() if type(value) is list)
        columns = statement.column_descriptions
        names = {column["name"] for column in columns}
        if len(columns) == 3 and columns[0]["entity"] is reader.Paper:
            return SimpleNamespace(all=lambda: [paper for paper in self.papers if paper[0] in paper_ids])
        selected = [c for c in self.chunks if c.paper_id in paper_ids and 0 < len(c.text) <= 20000]
        if names == {"paper_id", "indexed_chunks_total", "bounded_indexed_chunks_total"}:
            rows = [(paper, sum(c.paper_id == paper for c in self.chunks),
                     sum(c.paper_id == paper for c in selected)) for paper in paper_ids]
            return SimpleNamespace(all=lambda: rows)
        if names == {"id", "paper_id", "characters"}:
            formula = next(value for value in parameters.values() if type(value) is str)
            selected.sort(key=lambda c: (formula not in c.text, not c.has_table, c.chunk_index, c.id))
            selected = selected[:statement._limit_clause.value]
            self.measured_lengths.update({c.id: len(c.text) for c in selected})
            rows = [(c.id, c.paper_id, len(c.text)) for c in selected]
            return SimpleNamespace(all=lambda: rows)
        if len(columns) == 1 and columns[0]["entity"] is reader.Paper:
            values = sorted({c.paper_id for c in selected})
        else:
            identifiers = parameters["id_1"]
            values = [c for c in selected if c.id in identifiers and len(c.text) == self.measured_lengths[c.id]]
            values = values[:statement._limit_clause.value]
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: values))


def material(records=None):
    current = records or [{"paper_id": "paper:1", "tc_kelvin": 116, "formula": "YScH10"}]
    return SimpleNamespace(id="mat:ysch10", formula="YScH10", records=[*current, {"paper_id": "paper:excluded"}],
                           current_records=lambda: current)


def chunk(index, *, paper_id="paper:1", section="Results", text=None):
    return SimpleNamespace(id=f"chunk:{index}", paper_id=paper_id, section=section, chunk_index=index,
                           text=text or "Computed YScH10 has Tc=116 K at 140 GPa.", has_table=False)


def test_public_classification_windows_and_hash_are_independent(monkeypatch):
    body = {"version": "materials-enrichment/1.0.0", "coverage": [], "counts": {"candidate_facts": 0},
            "candidates": [], "classification_candidates": [
                {"candidate_id": str(i), "field": "reported_order", "source": {"paper_id": "paper:a", "capture_id": "capture:a"}}
                for i in range(150)],
            "classification_review_findings": [
                {"fields": ["reported_order"], "reason_codes": [str(i)], "source": {"paper_id": "paper:a", "capture_id": "capture:a"}}
                for i in range(130)],
            "classification_counts": {"candidate_facts": 150, "review_findings": 130, "promoted_facts": 0}}
    monkeypatch.setattr(reader, "build_enrichment_report", lambda *_args, **_kwargs: body)
    result = reader._compile_recovery_report({}, [], {}, {
        "records_total": 0, "records_inspected": 0, "records_truncated": False, "raw_retained_records_total": 0})
    assert result["candidates"] == []
    assert len(result["classification_candidates"]) == len(result["classification_review_findings"]) == 100
    assert result["classification_candidates_truncated"] is True
    assert result["classification_review_findings_truncated"] is True
    assert result["classification_counts"] == {"candidate_facts": 150, "review_findings": 130,
        "promoted_facts": 0, "candidate_facts_returned": 100, "candidate_facts_omitted": 50,
        "review_findings_returned": 100, "review_findings_omitted": 30}
    assert result["report_sha256"] == digest({key: value for key, value in result.items() if key != "report_sha256"})


def test_public_window_keeps_sparse_second_source_and_honest_omitted_counts(monkeypatch):
    dense = [{"candidate_id": f"a:{i:03}", "field": "tc_kelvin", "value": 23,
              "source": {"paper_id": "paper:a", "capture_id": f"capture:a:{i}"}} for i in range(120)]
    sparse = {"candidate_id": "z:distinct-tc", "field": "tc_kelvin", "value": 17.5,
              "source": {"paper_id": "paper:b", "capture_id": "capture:b"}}
    body = {"version": "materials-enrichment/1.0.0", "coverage": [], "counts": {"candidate_facts": 121},
            "candidates": [*dense, sparse], "classification_candidates": [],
            "classification_review_findings": [], "classification_counts": {}}
    monkeypatch.setattr(reader, "build_enrichment_report", lambda *_args, **_kwargs: body)
    result = reader._compile_recovery_report({}, [], {}, {
        "records_total": 0, "records_inspected": 0, "records_truncated": False, "raw_retained_records_total": 0})
    assert len(result["candidates"]) == 100 and result["candidates_truncated"] is True
    assert sparse in result["candidates"][:40]
    assert result["counts"]["candidate_facts"] == 121
    assert result["counts"]["candidate_facts_returned"] == 100
    assert result["counts"]["candidate_facts_omitted"] == 21
    assert result["report_sha256"] == digest({key: value for key, value in result.items() if key != "report_sha256"})


@pytest.mark.asyncio
async def test_descriptor_holds_generated_facts_and_public_egress(monkeypatch):
    chunks = [chunk(i) for i in range(5)]
    chunks[1].section = "Facts"
    chunks[2].section = "Synthetic Facts"
    async def descriptors(_db, selected):
        return {
            chunks[0].id: {"chunk_kind": "original_passage", "currentness": "current",
                           "permission_status": "unresolved", "source_locator": {"table": "2", "page": 5}},
            chunks[3].id: {"chunk_kind": "original_passage", "currentness": "current", "permission_status": "restricted"},
            chunks[4].id: {"chunk_kind": "original_passage", "currentness": "stale", "permission_status": "unresolved"},
        }
    monkeypatch.setattr(reader, "resolve_chunk_evidence", descriptors)
    db = FakeReadSession(chunks)
    report = await reader.read_material_enrichment(db, material())
    assert report["counts"]["source_captures"] == 1
    assert report["coverage"][0]["source_coverage"]["paper:1"]["excluded_chunks_total"] == 4
    assert report["candidates"]
    for candidate in report["candidates"]:
        assert "evidence_text" not in candidate
        assert candidate["source"]["capture_id"] == "chunk:0"
        assert candidate["source"]["locator"]["page"] == 5
        assert candidate["source"]["locator"]["table"] == "2"
        assert candidate["source"]["publication_revision_verified"] is False
        validate_candidate_identity(candidate)
    assert report["report_sha256"] == digest({key: value for key, value in report.items() if key != "report_sha256"})


@pytest.mark.asyncio
async def test_bounded_primary_links_use_selected_publication_metadata_without_releasing_held_evidence(monkeypatch):
    records = [{"paper_id": f"paper:{i}", "formula": "YScH10", "tc_kelvin": 116} for i in range(4)]
    chunks = [chunk(i, paper_id=record["paper_id"]) for i, record in enumerate(records)]
    publications = [("paper:0", "10.1234/value(1)?x#part", "2401.01234v2"),
                    ("paper:1", "javascript:alert(1)", "2401.01234v2"),
                    ("paper:2", "10.1234/stale", None), ("paper:3", "10.1234/restricted", None),
                    ("paper:excluded", "10.1234/excluded", None)]
    async def descriptors(_db, selected):
        return {c.id: {"currentness": "stale" if c.paper_id == "paper:2" else "current",
                       "permission_status": "restricted" if c.paper_id == "paper:3" else "unresolved"}
                for c in selected}
    monkeypatch.setattr(reader, "resolve_chunk_evidence", descriptors)
    db = FakeReadSession(chunks, papers=publications)
    report = await reader.read_material_enrichment(db, material(records))
    urls = {c["source"]["paper_id"]: c["source"].get("source_url") for c in report["candidates"]}
    assert urls == {"paper:0": "https://doi.org/10.1234/value%281%29%3Fx%23part",
                    "paper:1": "https://arxiv.org/abs/2401.01234v2"}
    assert all(c["source"]["publication_revision_verified"] is False for c in report["candidates"])
    assert all(c["source"]["source_revision_basis"] == "retained_chunk_capture_not_publication_version" for c in report["candidates"])
    assert len(db.statements[0].column_descriptions) == 3
    assert {c["name"] for c in db.statements[0].column_descriptions} == {"id", "doi", "arxiv_id"}
    assert "stale" not in str(report) and "https://doi.org/10.1234/restricted" not in str(report)


@pytest.mark.parametrize("doi,arxiv_id,expected", [
    (None, "hep-th/9901001v3", "https://arxiv.org/abs/hep-th/9901001v3"),
    ("10.1234/value\n", "javascript:alert(1)", None),
    ("https://evil.invalid/10.1234/value", "2401.01234?private=1", None),
    ("10.1234/", "2401.01234#fragment", None),
    (None, None, None),
])
def test_primary_link_identifier_validation_never_guesses_opaque_ids(doi, arxiv_id, expected):
    assert reader._primary_source_url(doi, arxiv_id) == expected


@pytest.mark.asyncio
async def test_paper_and_chunk_caps_use_only_current_eligible_source_partition(monkeypatch):
    records = [{"paper_id": f"paper:{i:02}", "formula": "YScH10", "tc_kelvin": 116} for i in range(10)]
    selected_ids = []
    async def descriptors(_db, selected):
        selected_ids.extend(c.id for c in selected)
        return {}
    monkeypatch.setattr(reader, "resolve_chunk_evidence", descriptors)
    db = FakeReadSession([chunk(i, paper_id="paper:00") for i in range(reader.MAX_CHUNKS + 1)])
    report = await reader.read_material_enrichment(db, material(records))
    probe_parameters = db.statements[0].compile().params
    probe_papers = next(value for value in probe_parameters.values() if type(value) is list)
    assert set(probe_papers) == {f"paper:{i:02}" for i in range(10)}
    assert "paper:excluded" not in probe_papers
    parameters = db.statements[1].compile().params
    queried_papers = next(value for value in parameters.values() if type(value) is list)
    assert len(queried_papers) == reader.MAX_PAPERS
    assert "paper:excluded" not in queried_papers
    assert "paper:00" in queried_papers
    assert "paper:09" in queried_papers
    assert set(queried_papers) != {f"paper:{i:02}" for i in range(8)}
    assert len(selected_ids) == reader.MAX_CHUNKS
    assert report["coverage"][0]["source_coverage"]["paper:00"]["truncated"] is True
    assert report["counts"]["source_captures"] == reader.MAX_CHUNKS


@pytest.mark.asyncio
async def test_ninth_paper_only_indexed_source_is_reachable_and_unlinked_source_cannot_prioritize(monkeypatch):
    records = [{"paper_id": f"paper:{i:02}", "formula": "YScH10", "tc_kelvin": 116} for i in range(9)]
    db = FakeReadSession([chunk(8, paper_id="paper:08"), chunk(99, paper_id="paper:excluded")])
    async def descriptors(_db, selected):
        return {}
    monkeypatch.setattr(reader, "resolve_chunk_evidence", descriptors)
    report = await reader.read_material_enrichment(db, material(records))
    tc = next(c for c in report["candidates"] if c["field"] == "tc_kelvin")
    assert tc["source"]["paper_id"] == "paper:08"
    assert report["counts"]["source_captures"] == 1
    assert report["inspection_scope"]["papers_with_bounded_indexed_chunks"] == 1
    assert report["inspection_scope"]["papers_inspected"] == reader.MAX_PAPERS
    assert report["inspection_scope"]["papers_total"] == 9
    assert report["inspection_scope"]["papers_truncated"] is True
    assert report["counts"]["retained_records_inspected"] == reader.MAX_PAPERS
    for statement in db.statements:
        queried = next(value for value in statement.compile().params.values() if type(value) is list)
        assert "paper:excluded" not in queried


@pytest.mark.asyncio
async def test_indexed_paper_priority_spans_large_inventory_and_preserves_evidence_gates(monkeypatch):
    records = [{"paper_id": f"paper:{i:03}", "formula": "YScH10", "tc_kelvin": 116} for i in range(100)]
    chunks = [chunk(i, paper_id=record["paper_id"]) for i, record in enumerate(records)]
    chunks[99].section = "Generated Facts"
    queried = []
    async def descriptors(_db, selected):
        queried.extend(c.paper_id for c in selected)
        return {c.id: {"currentness": "stale" if c.paper_id == "paper:000" else "current",
                       "permission_status": "restricted" if c.paper_id == "paper:084" else "unresolved"}
                for c in selected}
    monkeypatch.setattr(reader, "resolve_chunk_evidence", descriptors)
    report = await reader.read_material_enrichment(FakeReadSession(chunks), material(records))
    assert set(queried) == {f"paper:{i:03}" for i in (0, 14, 28, 42, 56, 70, 84, 99)}
    assert report["inspection_scope"]["papers_with_bounded_indexed_chunks"] == 100
    assert report["inspection_scope"]["records_inspected"] == reader.MAX_PAPERS
    assert report["counts"]["source_captures"] == 5
    assert not {"paper:000", "paper:084", "paper:099"} & {c["source"]["paper_id"] for c in report["candidates"]}
    assert report["inspection_scope"]["paper_sampling"] == "indexed_chunk_priority_evenly_spaced_eligible_inventory"


def test_no_indexed_priority_still_spans_whole_eligible_paper_inventory():
    records = [{"paper_id": f"paper:{i:03}", "formula": "YScH10", "tc_kelvin": 116} for i in range(100)]
    selected, _, paper_ids, scope = reader._sample_records(records, indexed_paper_ids=[])
    assert paper_ids == [f"paper:{i:03}" for i in (0, 14, 28, 42, 56, 70, 84, 99)]
    assert len(selected) == reader.MAX_PAPERS
    assert scope["papers_with_bounded_indexed_chunks"] == 0
    assert scope["records_truncated"] is True


@pytest.mark.asyncio
async def test_combined_source_character_cap_is_checked_before_descriptor_resolution(monkeypatch):
    selected_lengths = []
    text = "Computed YScH10 has Tc=116 K. " + "x" * 19960
    async def descriptors(_db, selected):
        selected_lengths.extend(len(c.text) for c in selected)
        return {}
    monkeypatch.setattr(reader, "resolve_chunk_evidence", descriptors)
    report = await reader.read_material_enrichment(FakeReadSession([chunk(i, text=text) for i in range(10)]), material())
    assert sum(selected_lengths) <= reader.MAX_CHARS
    assert sum(selected_lengths) + len(text) > reader.MAX_CHARS
    assert report["coverage"][0]["source_coverage"]["paper:1"]["truncated"] is True


@pytest.mark.asyncio
async def test_first_paper_cannot_consume_second_papers_unique_fact(monkeypatch):
    records = [{"paper_id": paper, "formula": "YScH10", "tc_kelvin": 116}
               for paper in ("paper:a", "paper:b")]
    chunks = [chunk(i, paper_id="paper:a") for i in range(45)]
    for c in chunks:
        c.has_table = True
    chunks.append(chunk(100, paper_id="paper:b", text="YScH10 has Tc=17.5 K, measured by resistivity."))
    observed = []
    async def descriptors(_db, selected):
        observed.extend(selected)
        return {}
    monkeypatch.setattr(reader, "resolve_chunk_evidence", descriptors)
    report = await reader.read_material_enrichment(FakeReadSession(chunks), material(records))
    assert len(observed) == reader.MAX_CHUNKS
    assert observed[1].paper_id == "paper:b"
    assert any(c["field"] == "tc_kelvin" and c["value"] == 17.5
               and c["source"]["paper_id"] == "paper:b" for c in report["candidates"])
    coverage = report["coverage"][0]["source_coverage"]
    assert coverage["paper:a"]["chunks_supplied"] == 39
    assert coverage["paper:a"]["omitted_chunk_reasons"] == {"chunk_inspection_limit": 6}
    assert coverage["paper:b"]["chunks_supplied"] == 1
    assert coverage["paper:b"]["truncated"] is False


@pytest.mark.asyncio
async def test_nonfitting_chunk_does_not_hide_later_whole_chunk_or_forge_hash(monkeypatch):
    first = "YScH10 has Tc=116 K. " + "x" * 50
    nonfitting = "YScH10 has Tc=999 K. " + "y" * 80
    later = "YScH10 has Tc=17.5 K."
    monkeypatch.setattr(reader, "MAX_CHARS", len(first) + len(later))
    supplied = []
    async def descriptors(_db, selected):
        supplied.extend(selected)
        return {c.id: {"source_locator": {"page": 8, "char_start": 125, "char_end": 145}} for c in selected}
    monkeypatch.setattr(reader, "resolve_chunk_evidence", descriptors)
    report = await reader.read_material_enrichment(FakeReadSession([
        chunk(0, text=first), chunk(1, text=nonfitting), chunk(2, text=later),
    ]), material())
    assert [c.id for c in supplied] == ["chunk:0", "chunk:2"]
    assert [c.text for c in supplied] == [first, later]
    assert report["inspection_scope"]["characters_inspected"] == len(first) + len(later)
    coverage = report["coverage"][0]["source_coverage"]["paper:1"]
    assert coverage["chunks_considered"] == 3 and coverage["chunks_inspected"] == 2
    assert coverage["omitted_chunk_reasons"] == {"character_inspection_limit": 1}
    assert coverage["omitted_chunks_total"] == 1 and coverage["excluded_chunks_total"] == 0
    candidate = next(c for c in report["candidates"] if c["value"] == 17.5)
    assert candidate["source"]["content_sha256"] == hashlib.sha256(later.encode()).hexdigest()
    assert candidate["source"]["locator"] == {"page": 8, "char_start": 125, "char_end": 145,
                                              "chunk_id": "chunk:2", "section": "Results"}
    assert all(c["value"] != 999 for c in report["candidates"])


@pytest.mark.asyncio
async def test_per_paper_exclusions_length_omissions_and_unsampled_sources_are_honest(monkeypatch):
    records = [{"paper_id": f"paper:{i:02}", "formula": "YScH10"} for i in range(9)]
    chunks = [chunk(0, paper_id="paper:00", section="Facts"),
              chunk(1, paper_id="paper:00"), chunk(2, paper_id="paper:08"),
              chunk(3, paper_id="paper:08", text="x" * 20001)]
    async def descriptors(_db, selected):
        return {"chunk:1": {"permission_status": "restricted"}}
    monkeypatch.setattr(reader, "resolve_chunk_evidence", descriptors)
    report = await reader.read_material_enrichment(FakeReadSession(chunks), material(records))
    coverage = report["coverage"][0]["source_coverage"]
    first, last = coverage["paper:00"], coverage["paper:08"]
    assert first["excluded_chunks_total"] == 2
    assert first["excluded_chunk_reasons"] == {"derived_source": 1, "source_permission_restricted": 1}
    assert last["excluded_chunks_total"] == 0 and last["chunks_supplied"] == 1
    assert last["omitted_chunk_reasons"] == {"indexed_chunk_length_outside_bounds": 1}
    assert last["indexed_chunks_total"] == 2 and last["bounded_indexed_chunks_total"] == 1
    for row in (first, last):
        assert row["chunks_supplied"] + row["excluded_chunks_total"] + row["omitted_chunks_total"] == row["indexed_chunks_total"]
    omitted = next(row for row in coverage.values() if "paper_sampling_limit" in row["reason_codes"])
    assert omitted["chunks_inspected"] == 0 and omitted["indexed_chunks_total"] is None
    assert omitted["omitted_chunks_total"] is None and omitted["truncated"] is True


@pytest.mark.asyncio
async def test_character_limit_explicit_when_every_paper_cannot_be_supplied(monkeypatch):
    records = [{"paper_id": paper, "formula": "YScH10"} for paper in ("paper:a", "paper:b")]
    text = "YScH10 has Tc=116 K."
    monkeypatch.setattr(reader, "MAX_CHARS", len(text))
    async def descriptors(_db, _selected):
        return {}
    monkeypatch.setattr(reader, "resolve_chunk_evidence", descriptors)
    report = await reader.read_material_enrichment(FakeReadSession([
        chunk(0, paper_id="paper:a", text=text), chunk(1, paper_id="paper:b", text=text),
    ]), material(records))
    coverage = report["coverage"][0]["source_coverage"]
    assert coverage["paper:a"]["chunks_supplied"] == 1
    assert coverage["paper:b"]["chunks_supplied"] == 0
    assert coverage["paper:b"]["omitted_chunk_reasons"] == {"character_inspection_limit": 1}
    assert coverage["paper:b"]["fulltext_checked"] is False


@pytest.mark.asyncio
async def test_chunk_length_change_after_metadata_cannot_exceed_text_budget(monkeypatch):
    original = chunk(0)
    monkeypatch.setattr(reader, "MAX_CHARS", len(original.text))
    class ChangingSession(FakeReadSession):
        async def execute(self, statement):
            result = await super().execute(statement)
            if "characters" in {column["name"] for column in statement.column_descriptions}:
                original.text += " Changed synthetic text exceeds the measured budget."
            return result
    resolved = []
    async def descriptors(_db, selected):
        resolved.extend(selected)
        return {}
    monkeypatch.setattr(reader, "resolve_chunk_evidence", descriptors)
    report = await reader.read_material_enrichment(ChangingSession([original]), material())
    assert resolved == [] and report["candidates"] == []
    assert report["inspection_scope"]["characters_inspected"] == 0
    row = report["coverage"][0]["source_coverage"]["paper:1"]
    assert row["chunks_considered"] == 1 and row["chunks_inspected"] == 0
    assert row["omitted_chunk_reasons"] == {"indexed_chunk_changed_or_unavailable": 1}
    assert row["omitted_chunks_total"] == 1 and row["truncated"] is True


@pytest.mark.asyncio
async def test_no_current_sources_has_zero_queries_and_explicit_missing_route(monkeypatch):
    db = FakeReadSession([])
    mat = SimpleNamespace(id="mat:none", formula="Nb", records=[{"paper_id": "paper:excluded"}], current_records=lambda: [])
    async def unexpected(*_args):
        raise AssertionError("No selected chunks should invoke evidence resolution")
    monkeypatch.setattr(reader, "resolve_chunk_evidence", unexpected)
    report = await reader.read_material_enrichment(db, mat)
    assert not db.statements
    assert report["counts"]["source_captures"] == 0
    assert all(field["status"] == "source_unavailable" for field in report["coverage"][0]["fields"])


@pytest.mark.parametrize("section,paper_id,text", [
    ("Facts", "paper:1", "YScH10 has Tc=116 K."),
    ("generated_facts", "paper:1", "YScH10 has Tc=116 K."),
    ("Derived-Results", "paper:1", "YScH10 has Tc=116 K."),
    ("Model Summary", "paper:1", "YScH10 has Tc=116 K."),
    ("Results", "facts:1", "YScH10 has Tc=116 K."),
    ("Results", "derived:1", "YScH10 has Tc=116 K."),
    ("Results", "generated:1", "YScH10 has Tc=116 K."),
    ("Results", "paper:1", "Section: Facts\nYScH10 has Tc=116 K."),
    ("Results", "paper:1", "Header\n  Section: Derived\nYScH10 has Tc=116 K."),
])
@pytest.mark.asyncio
async def test_every_legacy_generated_source_hint_is_excluded(monkeypatch, section, paper_id, text):
    async def descriptors(_db, selected):
        return {c.id: {"chunk_kind": "legacy_unknown"} for c in selected}
    monkeypatch.setattr(reader, "resolve_chunk_evidence", descriptors)
    mat = material([{"paper_id": paper_id, "tc_kelvin": 116, "formula": "YScH10"}])
    report = await reader.read_material_enrichment(FakeReadSession([chunk(0, paper_id=paper_id, section=section, text=text)]), mat)
    assert report["counts"]["source_captures"] == 0
    assert report["candidates"] == []
    assert report["coverage"][0]["source_coverage"][paper_id]["excluded_chunks_total"] == 1


@pytest.mark.asyncio
async def test_record_limit_samples_across_papers_and_deep_retained_positions(monkeypatch):
    records = [{"paper_id": f"paper:{paper}", "ordinal": index, "formula": "YScH10", "tc_kelvin": 116}
               for paper in reversed(range(reader.MAX_PAPERS)) for index in range(100)]
    parsed_payloads = []
    original = reader.build_enrichment_report
    def builder(payloads, *args, **kwargs):
        parsed_payloads.extend(payloads)
        return original(payloads, *args, **kwargs)
    async def descriptors(_db, _selected):
        return {}
    monkeypatch.setattr(reader, "build_enrichment_report", builder)
    monkeypatch.setattr(reader, "resolve_chunk_evidence", descriptors)
    report = await reader.read_material_enrichment(FakeReadSession([]), material(records))
    inspected = parsed_payloads[0]["records"]
    assert len(inspected) == reader.MAX_RECORDS
    assert Counter(record["paper_id"] for record in inspected) == {f"paper:{paper}": 4 for paper in range(reader.MAX_PAPERS)}
    assert {record["ordinal"] for record in inspected} == {0, 33, 66, 99}
    assert reader._sample_records(records)[0] == reader._sample_records(records)[0]
    scope = report["inspection_scope"]
    assert scope["records_total"] == 800
    assert scope["raw_retained_records_total"] == 801
    assert scope["records_inspected"] == reader.MAX_RECORDS
    assert scope["records_truncated"] is True
    assert report["counts"]["retained_records"] == 800
    assert report["counts"]["retained_records_inspected"] == reader.MAX_RECORDS
    assert report["coverage"][0]["record_scan_truncated"] is True
    assert all("retained_record_inventory_not_fully_inspected" in field["reason_codes"]
               for field in report["coverage"][0]["fields"])


@pytest.mark.asyncio
async def test_report_parsing_runs_outside_event_loop_thread(monkeypatch):
    main_thread, observed = threading.get_ident(), []
    original = reader.build_enrichment_report
    def builder(*args, **kwargs):
        observed.append(threading.get_ident())
        return original(*args, **kwargs)
    async def descriptors(_db, _selected):
        return {}
    monkeypatch.setattr(reader, "build_enrichment_report", builder)
    monkeypatch.setattr(reader, "resolve_chunk_evidence", descriptors)
    await reader.read_material_enrichment(FakeReadSession([]), material())
    assert observed and all(identifier != main_thread for identifier in observed)


@pytest.mark.asyncio
async def test_cancelled_request_holds_worker_slot_until_cpu_work_finishes(monkeypatch):
    loop = asyncio.get_running_loop()
    lock, gates = threading.Lock(), [threading.Event() for _ in range(3)]
    two_started, third_started = asyncio.Event(), asyncio.Event()
    state = {"active": 0, "peak": 0, "started": []}
    def worker(payload, _sources, _coverage, _scope):
        job = payload["job"]
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
            state["started"].append(job)
            if len(state["started"]) == 2:
                loop.call_soon_threadsafe(two_started.set)
            if job == 2:
                loop.call_soon_threadsafe(third_started.set)
        gates[job].wait(timeout=5)
        with lock:
            state["active"] -= 1
        return {"job": job}
    monkeypatch.setattr(reader, "_compile_recovery_report", worker)
    tasks = [asyncio.create_task(reader._bounded_compile({"job": i}, [], {}, {})) for i in range(3)]
    try:
        await asyncio.wait_for(two_started.wait(), timeout=2)
        tasks[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await tasks[0]
        assert not third_started.is_set()
        assert set(state["started"]) == {0, 1}
        gates[0].set()
        await asyncio.wait_for(third_started.wait(), timeout=2)
        assert state["peak"] == reader.MAX_CPU_WORKERS
    finally:
        for gate in gates:
            gate.set()
        await asyncio.gather(*tasks, return_exceptions=True)
