"""Synthetic arXiv capture regressions; no provider/DB/GCS/model operations.

Fixtures are invented plumbing cases, not adjudicated scientific examples.
"""
from __future__ import annotations

import copy
import hashlib
import xml.etree.ElementTree as ET
from datetime import date
from unittest.mock import AsyncMock

import httpx
import pytest
from google.api_core.exceptions import PreconditionFailed
from sqlalchemy.dialects import postgresql

from ingestion import pipeline, storage
from ingestion.collect.arxiv_oai import (
    ArxivCaptureError,
    ArxivClient,
    ArxivDownload,
    ArxivError,
    _parse_record,
    _Throttle,
)
from ingestion.extract.material_ner import _MAX_CHARS, _assemble_text, _build_prompt
from ingestion.index import indexer
from ingestion.models import Chunk, PaperMetadata, ParsedPaper, Section, split_arxiv_id
from ingestion.source_capture import build_ingestion_capture


def metadata(identifier="2602.00001", **kwargs):
    return PaperMetadata(
        arxiv_id=identifier, title="Synthetic v2 metadata", authors=["Synthetic author"],
        abstract="A v2-only reported transition at 300 K.",
        date_submitted=date(2020, 1, 1), categories=["cond-mat.supr-con"],
        primary_category="cond-mat.supr-con", **kwargs,
    )


def download(identifier="2602.00001v1", *, data=b"synthetic-source-v1", kind="source"):
    endpoint = "src" if kind == "source" else "pdf"
    url = f"https://export.arxiv.org/{endpoint}/{identifier}"
    return ArxivDownload(data=data, kind=kind, requested_id=identifier,
                         requested_url=url, resolved_url=url,
                         captured_at="2026-09-07T01:00:00+00:00")


@pytest.mark.parametrize("identifier,work,version", [
    ("2602.00001v1", "2602.00001", "v1"),
    (" 0706.0001v20 ", "0706.0001", "v20"),
    ("cond-mat/0607123v2", "cond-mat/0607123", "v2"),
    ("math.GT/0309136", "math.GT/0309136", None),
])
def test_canonical_identity_and_version_roundtrip(identifier, work, version):
    meta = metadata(identifier, metadata_modified_date=date(2026, 8, 20),
                    metadata_datestamp="2026-09-01T00:00:00Z",
                    metadata_sha256="a" * 64, metadata_captured_at="2026-09-07T01:00:00Z")
    assert meta.arxiv_id == work
    assert meta.paper_id == f"arxiv:{work}"
    assert meta.download_id == work + (version or "")
    assert meta.requested_version == version
    assert meta.yymm == work.rsplit("/", 1)[-1][:4]
    assert PaperMetadata.from_dict(meta.to_dict()) == meta


@pytest.mark.parametrize("identifier", [
    "", "2602.00001v0", "2602.00001v01", "2602.00001v-1", "2602.00001v1?key=secret",
    "https://arxiv.org/abs/2602.00001v1", "../2602.00001", "2613.00001", "2602.00001v9999999",
])
def test_identifier_rejects_ambiguous_or_unsafe_input(identifier):
    with pytest.raises(ValueError):
        split_arxiv_id(identifier)


def test_conflicting_embedded_version_refused():
    with pytest.raises(ValueError, match="conflicting"):
        metadata("2602.00001v1", requested_version="v2")


def record_xml(identifier="2602.00001"):
    return ET.fromstring(f'''<record xmlns="http://www.openarchives.org/OAI/2.0/">
      <header><datestamp>2026-09-01T00:00:00Z</datestamp></header>
      <metadata><arXiv xmlns="http://arxiv.org/OAI/arXiv/">
      <id>{identifier}</id><created>2020-01-01</created><updated>2026-08-20</updated>
      <title>Synthetic latest metadata</title><abstract>300 K in v2 only</abstract>
      </arXiv></metadata></record>''')


def test_oai_metadata_dates_and_hash_are_observations_not_revision_dates():
    record = record_xml("cond-mat/0607123")
    meta = _parse_record(record)
    assert meta.arxiv_id == "cond-mat/0607123"
    assert meta.date_submitted == date(2020, 1, 1)
    assert meta.metadata_modified_date == date(2026, 8, 20)
    assert meta.metadata_datestamp == "2026-09-01T00:00:00Z"
    assert meta.metadata_captured_at
    assert meta.metadata_sha256 == hashlib.sha256(ET.tostring(record, encoding="utf-8")).hexdigest()
    assert meta.requested_version is None
    assert "available_at" not in meta.to_dict()


@pytest.mark.asyncio
async def test_get_versioned_id_uses_canonical_oai_item_without_pinning_metadata():
    client = object.__new__(ArxivClient)
    root = ET.Element("{http://www.openarchives.org/OAI/2.0/}OAI-PMH")
    child = ET.SubElement(root, "{http://www.openarchives.org/OAI/2.0/}GetRecord")
    child.append(record_xml())
    client._oai_get = AsyncMock(return_value=root)
    meta = await client.get_record("2602.00001v1")
    assert client._oai_get.call_args.args[0]["identifier"] == "oai:arXiv.org:2602.00001"
    assert meta.requested_version == "v1"
    assert meta.abstract == "300 K in v2 only"


@pytest.mark.asyncio
async def test_get_record_identity_mismatch_refused():
    client = object.__new__(ArxivClient)
    root = ET.Element("{http://www.openarchives.org/OAI/2.0/}OAI-PMH")
    child = ET.SubElement(root, "{http://www.openarchives.org/OAI/2.0/}GetRecord")
    child.append(record_xml("2602.00002"))
    client._oai_get = AsyncMock(return_value=root)
    with pytest.raises(ArxivCaptureError, match="identity mismatch"):
        await client.get_record("2602.00001v1")


def mock_client(handler):
    client = object.__new__(ArxivClient)
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client._file_throttle = _Throttle(0)
    return client


@pytest.mark.asyncio
async def test_capture_pins_request_and_retains_bytes_digest_not_latest_label():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.host == "export.arxiv.org":
            return httpx.Response(302, headers={"Location": "https://arxiv.org/src/2602.00001v2"})
        return httpx.Response(200, content=b"synthetic-v2")

    async with mock_client(handler) as client:
        artifact = await client.download_source_capture("2602.00001v2")
    provenance = artifact.provenance()
    assert seen == ["https://export.arxiv.org/src/2602.00001v2",
                    "https://arxiv.org/src/2602.00001v2"]
    assert provenance["source_version"] == "v2"
    assert provenance["version_status"] == "explicit_version_url"
    assert provenance["sha256"] == hashlib.sha256(b"synthetic-v2").hexdigest()
    assert provenance["version_available_at"] is None


@pytest.mark.parametrize("location", [
    "https://arxiv.org/src/2602.00001", "https://arxiv.org/src/2602.00001v2",
    "https://arxiv.org/src/2602.00002v1", "https://private.example/2602.00001v1",
    "https://arxiv.org/src/2602.00001v1?token=secret", "https://user:secret@arxiv.org/src/2602.00001v1",
    "http://arxiv.org/src/2602.00001v1", "https://arxiv.org/abs/2602.00001v1",
])
@pytest.mark.asyncio
async def test_unsafe_or_version_losing_redirect_is_never_requested(location):
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"Location": location})

    async with mock_client(handler) as client:
        with pytest.raises(ArxivCaptureError) as exc:
            await client.download_source_capture("2602.00001v1")
    assert len(seen) == 1
    assert "secret" not in str(exc.value)


@pytest.mark.asyncio
async def test_unversioned_download_never_claims_version_or_latest():
    async with mock_client(lambda _: httpx.Response(200, content=b"unknown revision")) as client:
        artifact = await client.download_source_capture("2602.00001")
    assert artifact.provenance()["version_status"] == "unversioned_unknown"
    assert artifact.provenance()["source_version"] is None


@pytest.mark.asyncio
async def test_source_pdf_magic_and_pdf_nonmagic_refused():
    async with mock_client(lambda _: httpx.Response(200, content=b"%PDF-1.5")) as client:
        with pytest.raises(ArxivError, match="no LaTeX"):
            await client.download_source_capture("2602.00001v1")
    async with mock_client(lambda _: httpx.Response(200, content=b"not pdf")) as client:
        with pytest.raises(ArxivError, match="non-PDF"):
            await client.download_pdf_capture("2602.00001v1")


class MemoryBlob:
    def __init__(self, bucket, name):
        self.bucket = bucket
        self.name = name
        self.generation = 1

    def upload_from_string(self, data, *, content_type, if_generation_match):
        assert if_generation_match == 0
        if self.name in self.bucket.objects:
            raise PreconditionFailed("already exists")
        self.bucket.objects[self.name] = bytes(data)

    def reload(self):
        assert self.name in self.bucket.objects

    def download_as_bytes(self, *, if_generation_match):
        assert if_generation_match == self.generation
        return self.bucket.objects[self.name]


class MemoryBucket:
    def __init__(self):
        self.objects = {}

    def blob(self, name):
        return MemoryBlob(self, name)


@pytest.fixture
def bucket(monkeypatch):
    value = MemoryBucket()
    monkeypatch.setattr(storage, "_bucket", lambda: value)
    return value


def test_immutable_objects_and_version_anchor_create_or_verify(bucket):
    first = storage.archive_arxiv_capture(download())
    snapshot = copy.deepcopy(bucket.objects)
    assert storage.archive_arxiv_capture(download()) == first
    assert bucket.objects == snapshot
    assert all(name.startswith("captures/arxiv/") for name in bucket.objects)
    with pytest.raises(ArxivCaptureError, match="content mismatch"):
        storage.archive_arxiv_capture(download(data=b"different bytes for same v1"))
    for name, data in snapshot.items():
        assert bucket.objects[name] == data


def test_existing_corrupt_digest_object_is_not_a_cache_hit(bucket):
    artifact = download()
    name = f"captures/arxiv/2602.00001/source/sha256/{artifact.provenance()['sha256']}"
    bucket.objects[name] = b"corrupt"
    with pytest.raises(ArxivCaptureError):
        storage.archive_arxiv_capture(artifact)
    assert bucket.objects[name] == b"corrupt"


def test_v1_v2_and_unversioned_captures_do_not_overwrite_each_other(bucket):
    for identifier in ("2602.00001", "2602.00001v1", "2602.00001v2"):
        storage.archive_arxiv_capture(download(identifier, data=identifier.encode()))
    assert len(bucket.objects) == 5
    assert not any("versions/None" in name for name in bucket.objects)


def test_manifest_is_immutable_bounded_and_has_no_source_excerpt(bucket):
    parsed = ParsedPaper(meta=metadata("2602.00001v1"), sections=[])
    capture = build_ingestion_capture(parsed, ner_input=_assemble_text(parsed))
    name = storage.archive_arxiv_capture_manifest(capture)
    assert storage.archive_arxiv_capture_manifest(capture) == name
    assert b"300 K" not in bucket.objects[name]
    with pytest.raises(ArxivCaptureError, match="bounded"):
        storage.archive_arxiv_capture_manifest({"text": "x" * 17000})


def test_mixed_metadata_and_v1_body_remain_temporally_unknown():
    parsed = ParsedPaper(meta=metadata("2602.00001v1"),
                         sections=[Section(name="Results", text="v1: no transition reported.")],
                         ingestion_capture={"artifact": download().provenance()})
    body = _assemble_text(parsed)
    capture = build_ingestion_capture(parsed, ner_input=body)
    assert "300 K" in body
    assert capture["ner_input"]["sha256"] == hashlib.sha256(body.encode()).hexdigest()
    assert capture["ner_input"]["sha256"] != capture["artifact"]["sha256"]
    assert capture["ner_input"]["input_binding"] == "mixed_unverified"
    assert capture["metadata"]["version_status"] == "unversioned_metadata"
    assert capture["scientific_available_at"] is None
    assert capture["temporal_status"] == "unknown"


def test_ner_document_digest_excludes_unseen_text_after_actual_prompt_truncation():
    meta = metadata("2602.00001v1")
    meta.abstract = "x" * 17000
    parsed = ParsedPaper(meta=meta, sections=[Section("Results", "UNSEEN_V2_RESULT")],
                         ingestion_capture={"artifact": download().provenance()})
    assembled = _assemble_text(parsed)
    capture = build_ingestion_capture(parsed, ner_input=assembled, document_char_limit=_MAX_CHARS)
    exact_document = assembled[:_MAX_CHARS]
    assert exact_document in _build_prompt(assembled, "experimental")
    assert "UNSEEN_V2_RESULT" not in _build_prompt(assembled, "experimental")
    assert capture["ner_input"]["sha256"] == hashlib.sha256(exact_document.encode()).hexdigest()
    assert capture["ner_input"]["assembled_sha256"] == hashlib.sha256(assembled.encode()).hexdigest()
    assert capture["ner_input"]["truncated"] is True
    assert capture["ner_input"]["artifact_used"] is False
    assert capture["ner_input"]["sections_used"] == 0


def test_versioned_failure_pool_retains_independent_requests():
    pool = {}
    for identifier in ("2602.00001", "2602.00001v1", "2602.00001v2"):
        storage.record_failure(pool, metadata(identifier), stage="download", error="synthetic")
    assert set(pool) == {"2602.00001", "2602.00001v1", "2602.00001v2"}
    restored = PaperMetadata.from_dict(pool["2602.00001v1"].meta)
    assert restored.download_id == "2602.00001v1"
    storage.clear_failure(pool, restored.download_id)
    assert "2602.00001v2" in pool and "2602.00001" in pool


@pytest.fixture
def pipeline_mocks(monkeypatch, bucket):
    seen = {}

    def stale_cache_forbidden(*args):
        pytest.fail("legacy work-level cache used by new capture path")

    for name in ("source_exists", "download_source", "upload_source", "upload_pdf"):
        monkeypatch.setattr(storage, name, stale_cache_forbidden)
    monkeypatch.setattr(pipeline, "embed_chunks", lambda _: None)
    monkeypatch.setattr(pipeline, "chunk_paper", lambda parsed: [
        Chunk(id=f"{parsed.meta.paper_id}_chunk_000", paper_id=parsed.meta.paper_id,
              chunk_index=0, section="Abstract", text=parsed.meta.abstract, token_count=9),
    ])
    monkeypatch.setattr(pipeline, "parse_source_tarball", lambda data, meta: ParsedPaper(
        meta=meta, sections=[Section("Results", data.decode())],
    ))

    def extract(parsed):
        seen["ner_input"] = _assemble_text(parsed)
        return [{"formula": "H3S", "tc_kelvin": 300}]

    monkeypatch.setattr(pipeline, "extract_materials", extract)

    async def upsert(parsed, chunks, materials):
        seen.update(parsed=parsed, chunks=chunks, materials=materials)

    monkeypatch.setattr(pipeline, "upsert_paper_with_chunks", upsert)
    return seen


@pytest.mark.asyncio
async def test_real_pipeline_binds_exact_input_and_persists_only_unknown_capture(pipeline_mocks):
    client = type("Client", (), {"download_source_capture": AsyncMock(return_value=download())})()
    result = await pipeline.process_paper(client, metadata("2602.00001v1"),
                                          skip_vector_search=True, skip_geo=True)
    assert result["ok"]
    client.download_source_capture.assert_awaited_once_with("2602.00001v1")
    seen = pipeline_mocks
    capture = seen["materials"][0]["ingestion_capture"]
    assert capture == result["ingestion_capture"] == seen["parsed"].ingestion_capture
    assert capture["ner_input"]["sha256"] == hashlib.sha256(seen["ner_input"].encode()).hexdigest()
    assert capture["scientific_available_at"] is None
    assert "available_at" not in seen["materials"][0]
    assert "source_version" not in seen["materials"][0]
    assert seen["chunks"][0].materials_mentioned == seen["materials"]


@pytest.mark.asyncio
@pytest.mark.parametrize("strategy", ["default", "force_pdf"])
async def test_pdf_fallback_capture_is_not_the_extraction_input(strategy, pipeline_mocks):
    client = type("Client", (), {
        "download_source_capture": AsyncMock(side_effect=ArxivError("no source")),
        "download_pdf_capture": AsyncMock(return_value=download(data=b"%PDF-1.5", kind="pdf")),
    })()
    result = await pipeline.process_paper(client, metadata("2602.00001v1"), strategy=strategy,
                                          skip_vector_search=True, skip_geo=True)
    assert result["ok"]
    capture = result["ingestion_capture"]
    assert capture["artifact"]["kind"] == "pdf"
    assert capture["ner_input"]["input_binding"] == "metadata_only"
    assert capture["ner_input"]["artifact_used"] is False
    assert "%PDF" not in pipeline_mocks["ner_input"]


@pytest.mark.asyncio
async def test_no_ner_has_no_invented_input_hash(pipeline_mocks):
    result = await pipeline.process_paper(object(), metadata(), strategy="abstract_only",
                                          skip_ner=True, skip_vector_search=True, skip_geo=True)
    assert result["ok"]
    assert result["ingestion_capture"]["artifact"] is None
    assert result["ingestion_capture"]["ner_input"]["status"] == "not_run"
    assert result["ingestion_capture"]["ner_input"]["sha256"] is None
    assert "ner_input" not in pipeline_mocks


@pytest.mark.asyncio
async def test_archive_integrity_failure_does_not_fall_back_to_pdf(pipeline_mocks):
    client = type("Client", (), {
        "download_source_capture": AsyncMock(side_effect=ArxivCaptureError("wrong version")),
        "download_pdf_capture": AsyncMock(),
    })()
    with pytest.raises(ArxivCaptureError):
        await pipeline.process_paper(client, metadata("2602.00001v1"),
                                     skip_vector_search=True, skip_geo=True)
    client.download_pdf_capture.assert_not_awaited()
    assert "materials" not in pipeline_mocks


@pytest.mark.asyncio
async def test_arxiv_upsert_merges_diagnostics_without_replacing_unrelated_metadata(monkeypatch):
    statements = []

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        def begin(self):
            return self

        async def execute(self, statement, *args):
            statements.append(statement)

    monkeypatch.setattr(indexer, "_session_factory", lambda: Session)
    parsed = ParsedPaper(meta=metadata("2602.00001v1"), sections=[])
    parsed.ingestion_capture = build_ingestion_capture(parsed, ner_input=None)
    await indexer.upsert_paper_with_chunks(parsed, [], [])
    compiled = statements[0].compile(dialect=postgresql.dialect())
    assert compiled.params["publication_ref"] == {"ingestion_capture": parsed.ingestion_capture}
    sql = str(compiled)
    assert "jsonb_typeof(papers.publication_ref)" in sql
    assert "jsonb_build_object" in sql
    assert "legacy_publication_ref" in compiled.params.values()
    assert "|| excluded.publication_ref" in sql
    assert "source_versions" not in sql and "result_occurrences" not in sql
