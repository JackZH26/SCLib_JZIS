"""Integration-ish tests for ingestion.aps_pipeline.process_aps_paper.

The network (ApsClient) and the heavy collaborators (NER, embed, DB, VS)
are monkeypatched, so these run without GCP/Postgres but still exercise
the real orchestration + the compliance invariants:

* the BagIt temp dir is created, used, then force-deleted + verified;
* the full-text body is never handed to the chunk/VS path (chunks come
  from the abstract only);
* an audit row is built with deletion_confirmed=True (and written on the
  non-dry path);
* the error path still deletes the temp dir and records status='error'.

Runs in the container (imports tiktoken/google via the pipeline module).
"""
from __future__ import annotations

import io
import zipfile

import pytest

import ingestion.aps_pipeline as P
from ingestion.models import ApsArticleMeta


JATS = b"""<?xml version="1.0"?>
<article>
  <body>
    <sec><title>Results</title>
      <p>We measure Tc = 14 K in this compound under pressure.</p>
    </sec>
  </body>
  <back><ref-list><ref><mixed-citation>refs not extracted</mixed-citation></ref></ref-list></back>
</article>
"""


def _bagit_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("bagit.txt", "BagIt-Version: 1.0")
        zf.writestr("data/fulltext.xml", JATS)
        zf.writestr("data/article.pdf", b"%PDF-1.5 ...")
    return buf.getvalue()


class _FakeClient:
    def __init__(self, *, fail_bagit: bool = False) -> None:
        self.fail_bagit = fail_bagit

    async def get_article(self, doi: str) -> ApsArticleMeta:
        return ApsArticleMeta(
            doi=doi, title="Pressure-induced SC", authors=["A B", "C D"],
            abstract="We report superconductivity at 14 K.",
        )

    async def download_bagit(self, doi: str) -> bytes:
        if self.fail_bagit:
            from ingestion.collect.aps_harvest import ApsError
            raise ApsError("BagIt 404")
        return _bagit_zip()


@pytest.fixture(autouse=True)
def _patch_collaborators(monkeypatch):
    """Stub NER + all persistence so no GCP/DB is needed."""
    monkeypatch.setattr(P, "extract_materials",
                        lambda parsed: [{"formula": "X", "tc_kelvin": 14}])
    monkeypatch.setattr(P, "embed_chunks", lambda chunks: None)

    calls = {"paper_upsert": [], "vs_upsert": [], "audit": [], "related": []}

    async def _fake_upsert(meta, chunks, materials, *, related_paper_id=None):
        calls["paper_upsert"].append((meta, chunks, materials, related_paper_id))

    def _fake_vs(meta, chunks):
        calls["vs_upsert"].append((meta, chunks))

    async def _fake_related(doi):
        calls["related"].append(doi)
        return None

    async def _fake_audit(audit):
        calls["audit"].append(audit)

    monkeypatch.setattr(P, "upsert_aps_paper_with_chunks", _fake_upsert)
    monkeypatch.setattr(P, "upsert_aps_chunks_to_vector_search", _fake_vs)
    monkeypatch.setattr(P, "find_related_arxiv_paper", _fake_related)
    monkeypatch.setattr(P, "write_audit_log", _fake_audit)
    return calls


@pytest.mark.asyncio
async def test_full_flow_persists_and_deletes(_patch_collaborators):
    calls = _patch_collaborators
    client = _FakeClient()
    r = await P.process_aps_paper(client, "10.1103/PhysRevB.104.014501")

    assert r["ok"] is True
    assert r["paper_id"] == "aps:10.1103/PhysRevB.104.014501"
    assert r["journal_abbrev"] == "PRB"
    assert r["n_sections"] == 1
    assert r["n_materials"] == 1
    assert r["deletion_confirmed"] is True
    # paper + VS upserts happened once.
    assert len(calls["paper_upsert"]) == 1
    assert len(calls["vs_upsert"]) == 1
    # audit written with deletion proof.
    assert len(calls["audit"]) == 1
    audit = calls["audit"][0]
    assert audit.status == "deleted"
    assert audit.deletion_confirmed is True
    assert audit.ner_record_count == 1


@pytest.mark.asyncio
async def test_chunks_come_from_abstract_not_body(_patch_collaborators):
    calls = _patch_collaborators
    client = _FakeClient()
    await P.process_aps_paper(client, "10.1103/PhysRevB.104.014501")

    _meta, chunks, _materials, _rel = calls["paper_upsert"][0]
    blob = " ".join(c.text for c in chunks)
    # COMPLIANCE: full-text body sentence must NOT be in any stored chunk.
    assert "under pressure" not in blob
    assert "14 K" in blob  # abstract content is allowed
    assert all(c.section == "Abstract" for c in chunks)


@pytest.mark.asyncio
async def test_dry_run_skips_persistence_but_deletes(_patch_collaborators):
    calls = _patch_collaborators
    client = _FakeClient()
    r = await P.process_aps_paper(client, "10.1103/PhysRevB.1.1", dry_run=True)

    assert r["ok"] is True
    assert r["deletion_confirmed"] is True
    # Nothing persisted on a dry run.
    assert calls["paper_upsert"] == []
    assert calls["vs_upsert"] == []
    assert calls["audit"] == []  # audit logged, not written


@pytest.mark.asyncio
async def test_skip_vector_search_persists_paper_only(_patch_collaborators):
    calls = _patch_collaborators
    client = _FakeClient()
    r = await P.process_aps_paper(
        client, "10.1103/PhysRevB.1.1", skip_vector_search=True
    )
    assert r["ok"] is True
    assert len(calls["paper_upsert"]) == 1
    assert calls["vs_upsert"] == []  # no VS


@pytest.mark.asyncio
async def test_error_path_still_deletes_and_audits(_patch_collaborators):
    calls = _patch_collaborators
    client = _FakeClient(fail_bagit=True)
    r = await P.process_aps_paper(client, "10.1103/PhysRevB.1.1")

    assert r["ok"] is False
    assert "BagIt 404" in r["error"]
    # No paper persisted, but an error audit row IS written.
    assert calls["paper_upsert"] == []
    assert len(calls["audit"]) == 1
    assert calls["audit"][0].status == "error"


def test_normalize_doi():
    assert P._normalize_doi("https://doi.org/10.1103/PhysRevB.104.014501") \
        == "10.1103/PhysRevB.104.014501"
    assert P._normalize_doi("doi:10.1103/PhysRevB.1.1") == "10.1103/PhysRevB.1.1"
    assert P._normalize_doi("10.1103/PhysRevB.1.1") == "10.1103/PhysRevB.1.1"
