"""Synthetic recovery, record isolation and relational import acceptance checks."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3

import httpx
import jsonschema
import pytest

from ingestion.materials_ner.contract import Extraction, canonical, digest, output_schema
from ingestion.materials_ner.proposals import ProposalDatabase, import_packet, review_rows
from ingestion.materials_ner.recovery import RecoveryFailure, fetch_original, validate_url
from ingestion.materials_ner.sources import save_bundle
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.validation import validate_extraction
from ingestion.materials_ner.worker import configuration, run_one
from test_materials_ner_pipeline import FakeProvider, example


def make_packet(tmp_path, invalid=False):
    bundle, raw = example()
    bundle.work_id = raw["work_id"] = "arxiv:0001.00001"
    store = Store(tmp_path)
    identifier, _ = save_bundle(tmp_path, bundle)
    job = store.enqueue(work_id=bundle.work_id, bundle_hash=identifier, config=configuration())
    run_one(store, job_id=job, provider_override=FakeProvider({"wrong": 1} if invalid else raw))
    return store, import_packet(store, job)


def test_provider_schema_enforces_numeric_shape_before_generation():
    _, raw = example()
    schema = output_schema()
    jsonschema.validate(raw, schema)
    raw["results"][0]["quantity"]["upper"] = 99.0
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(raw, schema)


def test_luna_is_default_and_retains_pending_not_approved(tmp_path):
    _, packet = make_packet(tmp_path)
    assert packet["receipt"]["config"]["model"] == "gpt-6-luna"
    database = ProposalDatabase(tmp_path)
    assert database.ingest(packet)["inserted"]
    assert not database.ingest(packet)["inserted"]
    summary = database.summary()
    assert summary["tables"]["results"] == 1
    assert summary["result_review_states"] == {"pending_review": 1}
    with database.connect() as db:
        assert db.execute("SELECT scientific_acceptance,ml_training_eligible FROM runs").fetchone()[:] == (0, 0)
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE runs SET ml_training_eligible=1")


def test_broken_output_is_retained_without_fabricated_material_rows(tmp_path):
    _, packet = make_packet(tmp_path, invalid=True)
    ProposalDatabase(tmp_path).ingest(packet)
    assert packet["raw_output"] and packet["receipt"]["state"] == "quarantined"
    assert ProposalDatabase(tmp_path).summary()["tables"]["results"] == 0


def test_missing_citation_isolated_without_rejecting_independent_observations():
    bundle, raw = example()
    cited = deepcopy(raw["results"][0])
    cited.update(id="cited-unresolved", source_role="cited", cited_source_raw=None)
    raw["results"].append(cited)
    extraction = Extraction.model_validate(raw)
    report = validate_extraction(extraction, bundle)
    rows = review_rows(extraction, report)["results"]
    assert rows[0]["review_status"] == "pending_review"
    assert rows[1]["review_status"] == "quarantined"
    assert "cited_source_unresolved" in rows[1]["issues"]
    assert extraction.results[1].source_role == "cited"
    assert extraction.results[1].cited_source_raw is None


def test_citation_marker_requires_its_own_bound_source_evidence():
    bundle, raw = example()
    raw["results"][0].update(source_role="cited", cited_source_raw="[999]")
    report = validate_extraction(Extraction.model_validate(raw), bundle)
    assert {"code": "field_evidence_missing", "path": "/results/0/cited_source_raw"} in report["issues"]
    assert review_rows(Extraction.model_validate(raw), report)["results"][0]["review_status"] == "quarantined"
    unrelated = deepcopy(raw["results"][0]["evidence"][0])
    unrelated["field"] = "/cited_source_raw"
    raw["results"][0]["evidence"].append(unrelated)
    report = validate_extraction(Extraction.model_validate(raw), bundle)
    assert {"code": "citation_marker_not_in_field_evidence",
            "path": "/results/0/cited_source_raw"} in report["issues"]


def test_modified_receipt_or_row_does_not_import(tmp_path):
    _, packet = make_packet(tmp_path)
    database = ProposalDatabase(tmp_path)
    bad = deepcopy(packet)
    bad["rows"]["results"][0]["review_status"] = "quarantined"
    bad["packet_hash"] = digest({k: v for k, v in bad.items() if k != "packet_hash"})
    with pytest.raises(ValueError, match="derivation"):
        database.ingest(bad)
    assert database.summary()["tables"]["runs"] == 0


def test_row_isolation_propagates_dependencies_without_losing_valid_records():
    bundle, raw = example()
    other = deepcopy(raw["results"][0])
    other["id"] = "r2"
    other["quantity"]["value"] = 400.0
    derived = deepcopy(raw["results"][0])
    derived["id"] = "r3"
    derived["dependencies"] = [{"result_id": "r2", "relation": "derived_from"}]
    raw["results"].extend([other, derived])
    extraction = Extraction.model_validate(raw)
    rows = review_rows(extraction, validate_extraction(extraction, bundle))
    assert [r["review_status"] for r in rows["results"]] == [
        "pending_review", "quarantined", "quarantined"]
    assert "derived_input_has_validation_issues" in rows["results"][2]["issues"]


def test_cross_sample_foreign_key_rolls_back(tmp_path):
    _, packet = make_packet(tmp_path)
    database = ProposalDatabase(tmp_path)
    database.ingest(packet)
    with pytest.raises(sqlite3.IntegrityError), database.connect() as db:
        db.execute("UPDATE results SET sample_id='other'")
    assert database.summary()["tables"]["results"] == 1


@pytest.mark.parametrize("url", ["https://evil.test/src/1912.03080",
                               "https://arxiv.org/src/1912.03081",
                               "https://arxiv.org/src/1912.03080?token=secret"])
def test_recovery_rejects_unbound_redirects(url):
    with pytest.raises(RecoveryFailure):
        validate_url(url, "1912.03080")


def test_recovery_html_and_rate_limit_remain_explicit(tmp_path):
    for status, headers, code in [
        (200, {"content-type": "text/html"}, "arxiv_html"),
        (429, {"Retry-After": "900"}, "arxiv_http_429"),
    ]:
        throttle = tmp_path / "arxiv-throttle.json"
        throttle.unlink(missing_ok=True)
        with httpx.Client(transport=httpx.MockTransport(
                lambda request: httpx.Response(status, content=b"not original", headers=headers))) as client:
            with pytest.raises(RecoveryFailure, match=code):
                fetch_original(client, tmp_path, "1912.03080", "src")
        if status == 429:
            assert json.loads(throttle.read_text())["backoff_until"] > 0


def test_recovery_preserves_exact_bytes_with_hard_size_limit(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"%PDF-1.7 SYNTHETIC"))) as client:
        raw, receipt = fetch_original(client, tmp_path, "1912.03080", "pdf")
        assert raw == b"%PDF-1.7 SYNTHETIC" and receipt["kind"] == "pdf"
        (tmp_path / "arxiv-throttle.json").unlink()
        with pytest.raises(RecoveryFailure, match="byte_limit"):
            fetch_original(client, tmp_path, "1912.03080", "pdf", max_bytes=3)


def test_pdf_parser_limit_is_per_source_failure_and_batch_continues(tmp_path, monkeypatch):
    from pypdf.errors import LimitReachedError
    from ingestion.materials_ner import recovery
    from ingestion.materials_ner.sources import sha
    papers = [{"id": f"arxiv:0001.0000{i}", "arxiv_id": f"0001.0000{i}",
               "source": "arxiv", "title": "SYNTHETIC", "old_ner_records": 2 - i,
               "acquisition_status": "missing_archive"} for i in range(2)]
    plan = tmp_path / "plan.json"
    plan.write_text(canonical({"schema": "materials-ner-source-plan/1", "papers": papers}))
    blob = b"%PDF SYNTHETIC PARSER FAILURE FIXTURE"
    def fake_fetch(client, root, arxiv_id, kind, remaining):
        return blob, {"resolved_url": f"https://export.arxiv.org/{kind}/{arxiv_id}",
                      "source_version": None, "kind": "pdf", "sha256": sha(blob)}
    def fake_parse(path, **kwargs):
        if kwargs["work_id"] == papers[0]["id"]:
            raise LimitReachedError("SYNTHETIC configured decompression limit")
        bundle, _ = example()
        bundle.work_id = kwargs["work_id"]
        return bundle
    monkeypatch.setattr(recovery, "parse_local", fake_parse)
    result = recovery.recover_batch(tmp_path, plan, limit=2, fetch_fn=fake_fetch)
    assert [r["state"] for r in result["outcomes"]] == ["failed", "bundled"]
    assert (tmp_path / "sources" / sha(blob)).read_bytes() == blob
    assert any(e.get("code") == "LimitReachedError" for e in result["outcomes"][0]["attempts"])
    assert len(list((tmp_path / "recovery" / result["plan_sha256"]).glob("*.json"))) == 2


def test_postgres_contract_and_migration_importable():
    import runpy
    repo = Path(__file__).resolve().parents[2]
    schema = runpy.run_path(str(repo / "api/models/materials_ner_proposals_v1.py"))
    assert len(schema["TABLES"]) == 8
    assert all("public.material" not in sql for sql in schema["DDL"])
    assert "CHECK(NOT ml_training_eligible)" in canonical(schema["DDL"])


def test_campaign_resumes_without_duplicate_work_and_excludes_aps(tmp_path, monkeypatch):
    from ingestion.materials_ner import campaign
    papers = []
    extracts = {}
    for index in range(3):
        bundle, raw = example()
        work = f"arxiv:0001.0000{index}"
        bundle.work_id = raw["work_id"] = work
        save_bundle(tmp_path, bundle)
        extracts[work] = raw
        papers.append({"id": work, "source": "arxiv", "old_ner_records": index})
    papers.append({"id": "aps:synthetic", "source": "aps", "old_ner_records": 100})
    plan = tmp_path / "plan.json"
    plan.write_text(canonical({"schema": "materials-ner-source-plan/1", "papers": papers}))
    calls = []
    def fake_run(store, job_id, max_seconds):
        job = next(j for j in store.results() if j["id"] == job_id)
        calls.append(job["work_id"])
        return run_one(store, job_id=job_id, provider_override=FakeProvider(extracts[job["work_id"]]))
    monkeypatch.setattr(campaign, "run_one", fake_run)
    first = campaign.run_campaign(tmp_path, plan, batch_size=2, max_batches=1, progress=lambda _: None)
    assert first["selected_works"] == 2 and first["planned_works"] == 3
    second = campaign.run_campaign(tmp_path, plan, batch_size=1, max_batches=1, progress=lambda _: None)
    assert len(calls) == len(set(calls)) == 3 and "aps:synthetic" not in calls
    assert second["proposal_database"]["tables"]["results"] == 3
    assert second["stop_reason"] == "bounded_run_complete"


def test_celsius_offset_does_not_apply_to_uncertainty_and_mbar_is_pressure():
    from ingestion.materials_ner.contract import Evidence, Quantity
    from ingestion.materials_ner.validation import normalize, quantity_source_issues
    from test_materials_ner_pipeline import quantity
    q = Quantity.model_validate(quantity(750.0, "°C", "750 °C"))
    normalized = normalize("temperature", q)["normalized"]
    assert normalized["value"] == 1023.15 and normalized["conversion"]["offset"] == 273.15
    assert not quantity_source_issues("temperature", q, [
        Evidence(block_id="synthetic", quote="heated at 750 °C", field="/q")], "/q")
    vacuum = Quantity.model_validate(quantity(2.0, "mbar", "2 mbar"))
    assert normalize("pressure", vacuum)["normalized"]["value"] == 2e-7
    assert not quantity_source_issues("pressure", vacuum, [
        Evidence(block_id="synthetic", quote="pressure of 2 mbar", field="/q")], "/q")


def test_zero_tc_requires_review_even_if_it_occurs_in_a_table():
    bundle, raw = example()
    raw["results"][0]["quantity"]["value"] = 0.0
    report = validate_extraction(Extraction.model_validate(raw), bundle)
    assert any(i["code"] == "zero_tc_requires_non_detection_review" for i in report["issues"])


def test_compact_transport_preserves_values_quotes_and_builds_closed_graph():
    from ingestion.materials_ner.wire import CompactExtraction, output_schema
    from test_materials_ner_pipeline import compact_fixture
    bundle, raw = example()
    compact = compact_fixture(raw)
    jsonschema.validate(compact, output_schema(bundle))
    expanded = CompactExtraction.model_validate(compact).expand(bundle)
    assert expanded.results[0].quantity.model_dump() == raw["results"][0]["quantity"]
    assert raw["results"][0]["evidence"][0]["quote"] in expanded.results[0].evidence[0].quote
    assert expanded.results[0].sample_id == expanded.states[0].sample_id == expanded.samples[0].id
    assert validate_extraction(expanded, bundle)["valid"]
    assert "evidence_pool" not in compact


def test_compact_transport_refuses_missing_quote_and_does_not_merge_samples():
    from ingestion.materials_ner.wire import CompactExtraction
    from test_materials_ner_pipeline import compact_fixture
    bundle, raw = example()
    compact = compact_fixture(raw)
    copied = deepcopy(compact["observations"][0])
    copied["id"] = "r2"
    compact["observations"].append(copied)
    expanded = CompactExtraction.model_validate(compact).expand(bundle)
    assert len(expanded.samples) == 2
    assert expanded.samples[0].id != expanded.samples[1].id
    compact["observations"][0]["result"]["evidence"][0]["span_ids"] = ["S999"]
    with pytest.raises(ValueError, match="unknown_source_span"):
        CompactExtraction.model_validate(compact).expand(bundle)


@pytest.mark.parametrize("reason", [None, ""])
def test_provider_schema_cannot_emit_empty_without_a_reason(reason):
    from ingestion.materials_ner.wire import output_schema
    from test_materials_ner_pipeline import compact_fixture
    _, raw = example()
    compact = compact_fixture(raw)
    compact.update(completion={"outcome": "empty", "empty_reason": reason},
                   observations=[])
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(compact, output_schema())


def test_literal_prompt_preserves_tex_without_a_second_json_escape_layer():
    from ingestion.materials_ner.prompt import render
    from ingestion.materials_ner.sources import make_blocks
    bundle, _ = example()
    literal = "SYNTHETIC " + r"\lambda = 1.2; \begin{tabular} A & 39 \\ " + "\n"
    bundle.blocks = make_blocks(bundle.documents[0].id, [("synthetic:tex", literal)])
    text = render(bundle)
    assert "\n" + literal + "\nEND_TARGET_SPAN" in text
    assert canonical(literal) not in text


def test_original_windows_cover_every_character_without_recycling_legacy_chunks(tmp_path):
    from ingestion.materials_ner.windows import make_windows, spans
    from ingestion.materials_ner.sources import load_bundle
    from ingestion.materials_ner.campaign import available_bundles
    bundle, _ = example()
    bundle.work_id = "arxiv:0001.00001"
    parent_hash, _ = save_bundle(tmp_path, bundle)
    manifest = make_windows(tmp_path, bundle, max_chars=1000)
    assert manifest["parent_bundle_sha256"] == parent_hash
    text = bundle.blocks[0].text
    assert "".join(text[a:b] for a, b in spans(text, 1000)) == text
    assert manifest["target_characters"] == len(text)
    window = load_bundle(tmp_path / "bundles" / (manifest["windows"][0]["bundle_sha256"] + ".json"))
    assert window.documents[0].source_sha256 == bundle.documents[0].source_sha256
    assert window.documents[0].coverage == "partial"
    assert any(block.locator.startswith("target:") for block in window.blocks)
    assert available_bundles(tmp_path, {bundle.work_id})[bundle.work_id] == parent_hash


def test_dense_table_windows_have_at_most_three_numeric_rows():
    from ingestion.materials_ner.windows import spans
    text = "\\begin{tabular}{cc}\n" + "".join(f"A{i} & {i} \\\\\n" for i in range(20)) + "\\end{tabular}\n"
    offsets = list(spans(text, 4000))
    assert len(offsets) >= 7
    assert "".join(text[a:b] for a, b in offsets) == text
    assert all(text[a:b].count(" & ") <= 3 for a, b in offsets)


def test_new_windows_do_not_repeat_target_bytes_as_context(tmp_path):
    import re
    from ingestion.materials_ner.windows import make_windows
    from ingestion.materials_ner.sources import load_bundle,make_blocks
    bundle,_=example()
    bundle.blocks=make_blocks(bundle.documents[0].id,[("synthetic:page",bundle.blocks[0].text*12)])
    manifest=make_windows(tmp_path,bundle,max_chars=1000)
    for record in manifest["windows"]:
        window=load_bundle(tmp_path/"bundles"/(record["bundle_sha256"]+".json"))
        intervals=[]
        for block in window.blocks:
            match=re.search(r"chars\[(\d+):(\d+)\]$",block.locator)
            a,b=map(int,match.groups());intervals.append((a,b))
            assert block.text==bundle.blocks[0].text[a:b]
        for i,(a,b) in enumerate(intervals):
            assert all(b<=c or a>=d for c,d in intervals[i+1:])
