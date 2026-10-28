"""No network or database: prevent known legacy re-NER data loss."""
import asyncio

from ingestion import rener


class NoWrites:
    async def execute(self, *args, **kwargs):
        raise AssertionError("existing records must be preserved")

    async def commit(self):
        raise AssertionError("must not commit")


def test_aps_abstract_and_facts_are_rejected_before_extraction(monkeypatch):
    def forbidden(*args):
        raise AssertionError("must not call Gemini or rebuild APS Facts")
    monkeypatch.setattr(rener, "_rebuild_parsed", forbidden)
    monkeypatch.setattr(rener, "extract_materials", forbidden)
    assert asyncio.run(rener.rener_one(NoWrites(), "aps:10.synthetic/one"))["reason"] == "aps_original_source_required"


def test_empty_or_provider_failed_result_never_overwrites_previous(monkeypatch):
    async def parsed(*args):
        return object()
    monkeypatch.setattr(rener, "_rebuild_parsed", parsed)
    monkeypatch.setattr(rener, "extract_materials", lambda _: [])
    result = asyncio.run(rener.rener_one(NoWrites(), "arxiv:synthetic"))
    assert result["ok"] is False
    assert result["reason"] == "empty_or_failed_extraction_preserved_previous"
