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
    def __init__(self, chunks):
        self.chunks, self.statements = chunks, []

    async def execute(self, statement):
        self.statements.append(statement)
        assert statement.is_select
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: self.chunks))


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
async def test_paper_and_chunk_caps_use_only_current_eligible_source_partition(monkeypatch):
    records = [{"paper_id": f"paper:{i:02}", "formula": "YScH10", "tc_kelvin": 116} for i in range(10)]
    selected_ids = []
    async def descriptors(_db, selected):
        selected_ids.extend(c.id for c in selected)
        return {}
    monkeypatch.setattr(reader, "resolve_chunk_evidence", descriptors)
    db = FakeReadSession([chunk(i, paper_id="paper:00") for i in range(reader.MAX_CHUNKS + 1)])
    report = await reader.read_material_enrichment(db, material(records))
    parameters = db.statements[0].compile().params
    queried_papers = next(value for value in parameters.values() if type(value) is list)
    assert len(queried_papers) == reader.MAX_PAPERS
    assert "paper:excluded" not in queried_papers
    assert set(queried_papers) == {f"paper:{i:02}" for i in range(8)}
    assert len(selected_ids) == reader.MAX_CHUNKS
    assert report["coverage"][0]["source_coverage"]["paper:00"]["truncated"] is True
    assert report["counts"]["source_captures"] == reader.MAX_CHUNKS


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
