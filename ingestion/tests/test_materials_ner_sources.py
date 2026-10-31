"""Source-denominator and acquisition controls; fixtures contain no scientific gold."""
import gzip
import json
from pathlib import Path

import pytest

from ingestion.materials_ner.contract import canonical, digest
from ingestion.materials_ner.planning import acquire_batch, compile_plan, save_plan
from ingestion.materials_ner.sources import parse_local, sha


def inventory():
    return {
        "schema": "materials-ner-source-inventory/1", "captured_at": "synthetic", "errors": [],
        "paper_plan": [
            {"id": "arxiv:0101.0001", "source": "arxiv", "title": "Synthetic A",
             "doi": "10.synthetic/one", "arxiv_id": "0101.0001", "material_family": "test"},
            {"id": "arxiv:0101.0002", "source": "arxiv", "title": "Synthetic B"},
            {"id": "aps:one", "source": "aps", "title": "Synthetic APS", "doi": "10.SYNTHETIC/one"},
            {"id": "aps:two", "source": "aps", "title": "Synthetic APS missing"},
        ],
        "gcs": {"listing_complete": True, "bucket": "synthetic-bucket",
                "objects": [
                    {"name": "src/0101/0101.0001.tar.gz", "size": 100, "generation": 1},
                    {"name": "pdf/0101/0101.0001.pdf", "size": 200, "generation": 2},
                    {"name": "src/0101/0101.0009.tar.gz", "size": 100, "generation": 3},
                ]},
    }


def test_plan_keeps_missing_denominator_and_does_not_substitute_aps():
    plan = compile_plan(inventory())
    assert plan["summary"]["papers"] == 4
    assert plan["summary"]["acquisition_states"] == {
        "aps_authorization_pending": 2, "available_in_gcs": 1, "missing_archive": 1}
    assert plan["summary"]["arxiv_with_both"] == 1
    assert plan["summary"]["aps_with_gcs_arxiv_candidate"] == 1
    assert plan["summary"]["unmatched_objects"] == 1
    aps = plan["papers"][2]
    assert aps["alternate_work_ids"] == ["arxiv:0101.0001"] and not aps["candidates"]
    assert plan["harvest_allowed"] is False


def test_partial_or_failed_inventory_is_not_a_corpus_plan():
    data = inventory()
    data["gcs"]["listing_complete"] = False
    with pytest.raises(ValueError, match="complete"):
        compile_plan(data)
    data["gcs"]["listing_complete"] = True
    data["errors"].append({"stage": "gcs"})
    with pytest.raises(ValueError, match="complete"):
        compile_plan(data)


def test_gzip_tex_keeps_exact_original_text_and_compressed_hash(tmp_path):
    original = b"SYNTHETIC: $T_c = 39$~K.\n"
    compressed = gzip.compress(original)
    path = tmp_path / "input.tar.gz"
    path.write_bytes(compressed)
    bundle = parse_local(path, work_id="synthetic:gzip", title="Synthetic",
                         source_uri="synthetic:local", processing_permission="allowed")
    assert bundle.blocks[0].text == original.decode()
    assert bundle.documents[0].source_sha256 == sha(compressed)
    assert "raw-gzip-tex:utf-8" in bundle.documents[0].parser
    assert bundle.documents[0].coverage == "partial"


def test_legacy_encoding_is_never_silently_guessed(tmp_path):
    raw = b"SYNTHETIC: Pis\x92ma"
    path = tmp_path / "legacy.tex"
    path.write_bytes(raw)
    with pytest.raises(UnicodeDecodeError):
        parse_local(path, work_id="synthetic:old", title="Synthetic", source_uri="synthetic:local")
    bundle = parse_local(path, work_id="synthetic:old", title="Synthetic",
                         source_uri="synthetic:local", text_encoding="cp1252")
    assert bundle.blocks[0].text == "SYNTHETIC: Pis’ma"
    assert bundle.documents[0].source_sha256 == sha(raw)
    assert any("cp1252" in note for note in bundle.acquisition_notes)


def test_batch_generation_pin_fallback_and_resume_keep_failures(tmp_path):
    source = tmp_path / "inventory.json"
    source.write_text(canonical(inventory()))
    _, path = save_plan(tmp_path, source)
    calls = []

    def capture(root, name, **kwargs):
        calls.append((name, kwargs["generation"]))
        if name.startswith("src/"):
            raise ValueError("simulated source failure")
        raw = b"SYNTHETIC ORIGINAL TEXT"
        artifact = root / "source"
        artifact.write_bytes(raw)
        return {"local_path": str(artifact), "source_uri": "synthetic:source#2", "sha256": sha(raw)}

    result = acquire_batch(tmp_path, path, processing_allowed=True, capture_fn=capture)
    assert calls == [("src/0101/0101.0001.tar.gz", "1"), ("pdf/0101/0101.0001.pdf", "2")]
    assert result["source_plan_denominator"] == 4
    assert result["outcomes"][0]["state"] == "bundled"
    assert result["outcomes"][0]["candidate_attempts"][0]["state"] == "failed"
    assert acquire_batch(tmp_path, path, processing_allowed=True, capture_fn=capture)["attempted_papers"] == 0
    assert len(calls) == 2


def test_batch_budget_and_aps_selection_do_not_download(tmp_path):
    source = tmp_path / "inventory.json"
    source.write_text(canonical(inventory()))
    _, path = save_plan(tmp_path, source)

    def forbidden(*args, **kwargs):
        raise AssertionError("must not download")

    assert acquire_batch(tmp_path, path, processing_allowed=True, max_bytes=50,
                         capture_fn=forbidden)["attempted_papers"] == 0
    with pytest.raises(ValueError, match="APS cannot silently"):
        acquire_batch(tmp_path, path, processing_allowed=True, work_ids=["aps:one"], capture_fn=forbidden)
    with pytest.raises(ValueError, match="authorization"):
        acquire_batch(tmp_path, path, processing_allowed=False, capture_fn=forbidden)


def test_cached_capture_is_byte_verified(tmp_path):
    from ingestion.materials_ner.gcs import capture
    name, bucket, generation = "src/0101/0101.0001.tar.gz", "test", "5"
    raw = b"SYNTHETIC cache"
    hashed = sha(raw)
    (tmp_path / "sources").mkdir()
    (tmp_path / "sources" / hashed).write_bytes(raw)
    (tmp_path / "capture-index").mkdir()
    index = tmp_path / "capture-index" / f'{digest([bucket, name, generation])}.json'
    index.write_text(json.dumps({"name": name, "bucket": bucket, "generation": generation,
                                "sha256": hashed, "size": len(raw)}))
    assert Path(capture(tmp_path, name, bucket=bucket, generation=generation)["local_path"]).read_bytes() == raw
    (tmp_path / "sources" / hashed).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="integrity"):
        capture(tmp_path, name, bucket=bucket, generation=generation)
