"""Private node input must reproduce the prepared development capture exactly."""

from copy import deepcopy

import pytest

from ingestion.materials_v3.blocks import parse_source
from ingestion.materials_v3.contract import digest
from ingestion.materials_v3.corpus import stage_development


def prepared(tmp_path):
    path = tmp_path / "original.html"
    path.write_text("<p>Synthetic development input: LaH10 has Tc 240 K at 150 GPa.</p>")
    source_id = "arxiv:2502.02252:2502.02252v1"
    document = parse_source(path, source_id=source_id)
    paper = {
        "paper_id": "arxiv:2502.02252",
        "split": "development",
        "source_version": "2502.02252v1",
        "source_format": "html",
        "source_url": "https://arxiv.org/html/2502.02252v1",
        "source_bytes": path.stat().st_size,
        "main_text_sha256": document["source_sha256"],
        "content_manifest_sha256": document["manifest_sha256"],
        "transfer_allowed": False,
        "cloud_inference_allowed": False,
        "supplement_status": "pending_source_scope_review",
    }
    body = {"papers": [paper]}
    return {**body, "manifest_sha256": digest(body)}, path.read_bytes()


class SyntheticSources:
    def __init__(self, data):
        self.data, self.calls = data, 0

    def fetch(self, url, path):
        self.calls += 1
        path.write_bytes(self.data)
        return self.data


def test_staging_reproduces_capture_without_granting_cloud_or_freezing_scope(tmp_path):
    manifest, data = prepared(tmp_path)
    original = deepcopy(manifest)
    sources = SyntheticSources(data)
    result = stage_development(manifest, tmp_path / "node", sources=sources)
    assert manifest == original and sources.calls == 1 and result["source_failures"] == []
    assert result["staged_development_papers"] == ["arxiv:2502.02252"]
    assert result["source_scope_frozen"] is result["scientific_acceptance"] is False
    paper = result["papers"][0]
    assert paper["cloud_inference_allowed"] is paper["transfer_allowed"] is False
    assert paper["supplement_status"] == "pending_source_scope_review"


def test_documented_public_receipt_preserves_private_parent_and_public_input_hash(tmp_path):
    import json
    from pathlib import Path

    receipt_path = (
        Path(__file__).resolve().parents[2] / "docs/pilot/materials-ner-50.sources.prepared.v1.json"
    )
    public = json.loads(receipt_path.read_bytes())
    assert "manifest_sha256" not in public
    manifest, data = prepared(tmp_path)
    public["papers"] = manifest[
        "papers"
    ]  # Synthetic bytes; retain the actual published receipt shape.
    result = stage_development(public, tmp_path / "node", sources=SyntheticSources(data))
    assert result["source_failures"] == []
    assert result["prepared_input_manifest_sha256"] == public["private_prepared_manifest_sha256"]
    assert result["staging_input_sha256"] == digest(public)
    assert result["staging_input_sha256"] != result["prepared_input_manifest_sha256"]


@pytest.mark.parametrize("mode", ["missing", "conflicting"])
def test_invalid_parent_receipt_identity_is_rejected_before_source_download(tmp_path, mode):
    manifest, data = prepared(tmp_path)
    if mode == "missing":
        manifest.pop("manifest_sha256")
    else:
        manifest["private_prepared_manifest_sha256"] = "0" * 64
    sources = SyntheticSources(data)
    with pytest.raises(ValueError, match="development_prepared_manifest_identity"):
        stage_development(manifest, tmp_path / "node", sources=sources)
    assert sources.calls == 0


@pytest.mark.parametrize(
    "url",
    [
        "https://arxiv.org/html/2502.02252v2",
        "http://127.0.0.1/private",
    ],
)
def test_staging_rejects_version_change_and_other_hosts_before_fetch(tmp_path, url):
    manifest, data = prepared(tmp_path)
    manifest["papers"][0]["source_url"] = url
    sources = SyntheticSources(data)
    result = stage_development(manifest, tmp_path / "node", sources=sources)
    assert sources.calls == 0 and result["staged_development_papers"] == []
    assert (
        result["source_failures"][0]["error"]
        == "development_source_must_be_original_pinned_arxiv_url"
    )


@pytest.mark.parametrize(
    "field,error",
    [
        ("main_text_sha256", "development_original_source_hash_mismatch"),
        ("content_manifest_sha256", "development_parsed_capture_differs_from_prepared_input"),
    ],
)
def test_staging_rejects_original_or_parsed_hash_mismatch(tmp_path, field, error):
    manifest, data = prepared(tmp_path)
    manifest["papers"][0][field] = "0" * 64
    result = stage_development(manifest, tmp_path / "node", sources=SyntheticSources(data))
    assert result["staged_development_papers"] == []
    assert result["source_failures"][0]["error"] == error
