from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date

import pytest

from ingestion import pipeline
from ingestion.collect.arxiv_oai import ArxivClient, ArxivError
from ingestion.models import PaperMetadata


def _record_xml(*, deleted: bool = False) -> ET.Element:
    status = ' status="deleted"' if deleted else ""
    metadata = "" if deleted else """
      <metadata>
        <arXiv xmlns="http://arxiv.org/OAI/arXiv/">
          <id>2602.22793</id>
          <created>2026-02-26</created>
          <authors>
            <author><keyname>Zhou</keyname><forenames>Jian</forenames></author>
          </authors>
          <title> Hourglass Dirac chains enable superconductivity </title>
          <categories>cond-mat.supr-con cond-mat.mtrl-sci</categories>
          <abstract> A targeted backfill test. </abstract>
        </arXiv>
      </metadata>
    """
    return ET.fromstring(
        f"""
        <OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
          <GetRecord>
            <record>
              <header{status}>
                <identifier>oai:arXiv.org:2602.22793</identifier>
              </header>
              {metadata}
            </record>
          </GetRecord>
        </OAI-PMH>
        """
    )


@pytest.mark.asyncio
async def test_get_record_builds_oai_identifier_and_parses_metadata() -> None:
    client = object.__new__(ArxivClient)
    seen: dict[str, str] = {}

    async def fake_oai_get(params: dict[str, str]) -> ET.Element:
        seen.update(params)
        return _record_xml()

    client._oai_get = fake_oai_get  # type: ignore[method-assign]
    meta = await client.get_record(" 2602.22793 ")

    assert seen == {
        "verb": "GetRecord",
        "metadataPrefix": "arXiv",
        "identifier": "oai:arXiv.org:2602.22793",
    }
    assert meta.arxiv_id == "2602.22793"
    assert meta.primary_category == "cond-mat.supr-con"
    assert meta.authors == ["Jian Zhou"]


@pytest.mark.asyncio
async def test_get_record_rejects_deleted_record() -> None:
    client = object.__new__(ArxivClient)

    async def fake_oai_get(_params: dict[str, str]) -> ET.Element:
        return _record_xml(deleted=True)

    client._oai_get = fake_oai_get  # type: ignore[method-assign]
    with pytest.raises(ArxivError, match="deleted or empty"):
        await client.get_record("2602.22793")


@pytest.mark.asyncio
async def test_get_record_rejects_empty_id() -> None:
    client = object.__new__(ArxivClient)
    with pytest.raises(ValueError, match="must not be empty"):
        await client.get_record(" ")


@pytest.mark.asyncio
async def test_ids_mode_deduplicates_and_processes_only_requested_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    looked_up: list[str] = []
    processed: list[str] = []

    class FakeClient:
        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def get_record(self, arxiv_id: str) -> PaperMetadata:
            looked_up.append(arxiv_id)
            return PaperMetadata(
                arxiv_id=arxiv_id,
                title=f"Paper {arxiv_id}",
                authors=["Jian Zhou"],
                abstract="Superconductivity.",
                date_submitted=date(2026, 1, 1),
                categories=["cond-mat.supr-con"],
                primary_category="cond-mat.supr-con",
            )

    async def fake_process_paper(
        _client: FakeClient,
        meta: PaperMetadata,
        **_kwargs: object,
    ) -> dict[str, object]:
        processed.append(meta.arxiv_id)
        return {
            "arxiv_id": meta.arxiv_id,
            "title": meta.title,
            "ok": True,
            "n_chunks": 1,
            "n_materials": 0,
        }

    monkeypatch.setattr(pipeline, "ArxivClient", FakeClient)
    monkeypatch.setattr(pipeline, "process_paper", fake_process_paper)
    monkeypatch.setattr(pipeline.storage, "load_failed_papers", lambda: {})
    monkeypatch.setattr(pipeline.storage, "clear_failure", lambda *_args: False)

    results = await pipeline.run(
        mode="ids",
        from_date=None,
        until_date=None,
        limit=None,
        skip_vector_search=False,
        skip_ner=False,
        skip_geo=False,
        arxiv_ids=["2602.22793", "2602.22793", "2505.00514"],
    )

    assert looked_up == ["2602.22793", "2505.00514"]
    assert processed == looked_up
    assert [row["arxiv_id"] for row in results] == looked_up
