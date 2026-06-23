from __future__ import annotations

import json

import pytest

import ingestion.aps_batch as B


def test_load_manifest_text_dedupes_and_normalizes(tmp_path):
    manifest = tmp_path / "aps.txt"
    manifest.write_text(
        "\n".join([
            "# comment",
            "https://doi.org/10.1103/PhysRevB.1.1",
            "doi:10.1103/PhysRevLett.2.2",
            "10.1103/PhysRevB.1.1",
            "not a doi",
        ])
    )
    assert B.load_manifest(manifest) == [
        "10.1103/PhysRevB.1.1",
        "10.1103/PhysRevLett.2.2",
    ]


def test_load_manifest_csv_uses_doi_column(tmp_path):
    manifest = tmp_path / "aps.csv"
    manifest.write_text(
        "title,doi\n"
        "a,10.1103/PhysRevB.1.1\n"
        "b,https://doi.org/10.1103/PhysRevX.3.3\n"
    )
    assert B.load_manifest(manifest) == [
        "10.1103/PhysRevB.1.1",
        "10.1103/PhysRevX.3.3",
    ]


def test_select_pending_skips_ok_and_failed_unless_retry_requested():
    dois = [
        "10.1103/PhysRevB.1.1",
        "10.1103/PhysRevB.2.2",
        "10.1103/PhysRevB.3.3",
    ]
    checkpoint = {
        dois[0].lower(): {"doi": dois[0], "status": "ok"},
        dois[1].lower(): {"doi": dois[1], "status": "error"},
    }
    assert B.select_pending(dois, checkpoint) == ([dois[2]], 2)
    assert B.select_pending(dois, checkpoint, retry_failed=True) == (
        [dois[1], dois[2]], 1,
    )


def test_select_pending_never_retries_terminal_statuses():
    dois = [
        "10.1103/PhysRevB.1.1",
        "10.1103/PhysRevB.2.2",
        "10.1103/PhysRevB.3.3",
    ]
    checkpoint = {
        dois[0].lower(): {"doi": dois[0], "status": "unsupported_no_jats"},
        dois[1].lower(): {"doi": dois[1], "status": "unsupported_no_text"},
    }
    assert B.select_pending(dois, checkpoint, retry_failed=True) == ([dois[2]], 2)


@pytest.mark.asyncio
async def test_run_batch_checkpoint_resume_and_dry_run(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql://sclib:test@postgres:5432/sclib")
    B.get_settings.cache_clear()

    manifest = tmp_path / "aps.txt"
    manifest.write_text("10.1103/PhysRevB.1.1\n10.1103/PhysRevB.2.2\n")
    checkpoint = tmp_path / "aps.checkpoint.jsonl"
    calls: list[tuple[str, bool]] = []

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

    async def fake_process(client, doi, *, dry_run=False, **kwargs):
        calls.append((doi, dry_run))
        return {"doi": doi, "ok": True, "deletion_confirmed": True}

    async def fake_dispose():
        return None

    monkeypatch.setattr(B, "ApsClient", FakeClient)
    monkeypatch.setattr(B, "process_aps_paper", fake_process)
    monkeypatch.setattr(B, "dispose", fake_dispose)

    dry = await B.run_batch(manifest, checkpoint, limit=1, dry_run=True)
    assert dry.ok == 1
    records = [json.loads(line) for line in checkpoint.read_text().splitlines()]
    assert records[-1]["status"] == "dry_run_ok"

    full = await B.run_batch(manifest, checkpoint, limit=1)
    assert full.ok == 1
    records = [json.loads(line) for line in checkpoint.read_text().splitlines()]
    assert records[-1]["status"] == "ok"
    assert calls == [
        ("10.1103/PhysRevB.1.1", True),
        ("10.1103/PhysRevB.1.1", False),
    ]

    resume = await B.run_batch(manifest, checkpoint)
    assert resume.ok == 1
    records = [json.loads(line) for line in checkpoint.read_text().splitlines()]
    assert records[-1]["doi"] == "10.1103/PhysRevB.2.2"
    assert records[-1]["status"] == "ok"


@pytest.mark.asyncio
async def test_run_batch_terminal_status_is_not_error(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql://sclib:test@postgres:5432/sclib")
    B.get_settings.cache_clear()

    manifest = tmp_path / "aps.txt"
    manifest.write_text("10.1103/PhysRevB.1.1\n")
    checkpoint = tmp_path / "aps.checkpoint.jsonl"

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

    async def fake_process(client, doi, **kwargs):
        return {
            "doi": doi,
            "ok": False,
            "terminal": True,
            "status": "unsupported_no_jats",
            "error": "no JATS <article> XML or fulltext OCR",
        }

    async def fake_dispose():
        return None

    monkeypatch.setattr(B, "ApsClient", FakeClient)
    monkeypatch.setattr(B, "process_aps_paper", fake_process)
    monkeypatch.setattr(B, "dispose", fake_dispose)

    summary = await B.run_batch(manifest, checkpoint)
    assert summary.ok == 0
    assert summary.terminal == 1
    assert summary.error == 0
    records = [json.loads(line) for line in checkpoint.read_text().splitlines()]
    assert records[-1]["status"] == "unsupported_no_jats"
