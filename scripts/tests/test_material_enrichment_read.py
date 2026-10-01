"""Read adapter limits, source partition and public egress; zero DB/client I/O."""
from __future__ import annotations

import asyncio
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

    async def execute(self, statement):
        self.statements.append(statement)
        assert statement.is_select
        parameters = statement.compile().params
        paper_ids = next(value for value in parameters.values() if type(value) is list)
        if len(statement.column_descriptions) == 3 and statement.column_descriptions[0]["entity"] is reader.Paper:
            return SimpleNamespace(all=lambda: [paper for paper in self.papers if paper[0] in paper_ids])
        selected = [c for c in self.chunks if c.paper_id in paper_ids and 0 < len(c.text) <= 20000]
        if len(statement.column_descriptions) == 1 and statement.column_descriptions[0]["entity"] is reader.Paper:
            values = sorted({c.paper_id for c in selected})
        else:
            values = selected[:reader.MAX_CHUNKS + 1]
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: values))


def material(records=None):
    current = records or [{"paper_id": "paper:1", "tc_kelvin": 116, "formula": "YScH10"}]
    return SimpleNamespace(id="mat:ysch10", formula="YScH10", records=[*current, {"paper_id": "paper:excluded"}],
                           current_records=lambda: current)


def chunk(index, *, paper_id="paper:1", section="Results", text=None):
    return SimpleNamespace(id=f"chunk:{index}", paper_id=paper_id, section=section, chunk_index=index,
                           text=text or "Computed YScH10 has Tc=116 K at 140 GPa.", has_table=False)


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
