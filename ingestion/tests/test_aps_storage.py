"""Unit tests for ingestion.aps_storage (transient extraction + deletion).

The compliance-critical paths: BagIt extraction with traversal/zip-bomb
guards, force-delete + verify-gone, the audit-row builder, and the
janitor sweep. No network/DB — write_audit_log (which needs the DB) is
intentionally not exercised here.
"""
from __future__ import annotations

import io
import os
import zipfile
from datetime import datetime, timezone

import pytest

from ingestion.aps_storage import (
    ApsStorageError,
    TdmAudit,
    TempBagit,
    sweep_stale_temp_dirs,
)


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_extract_and_records_files():
    z = _zip({
        "data/article.xml": b"<article/>",
        "data/article.pdf": b"%PDF-1.4",
        "data/ocr.txt": b"text",
        "manifest-sha256.txt": b"hash",
    })
    with TempBagit("10.1103_PhysRevB.104.014501") as work:
        root = work.extract(z)
        assert (root / "data" / "article.xml").exists()
        kinds = {f.name: f.kind for f in work.files}
        assert kinds["data/article.xml"] == "xml"
        assert kinds["data/article.pdf"] == "pdf"
        assert kinds["data/ocr.txt"] == "ocr"
        assert work.bagit_bytes == len(z)
        saved_root = root
    # After the context exits, everything is gone + verified.
    assert work.deleted is True
    assert not saved_root.exists()


def test_dir_permissions_0700():
    with TempBagit("x") as work:
        mode = os.stat(work.root).st_mode & 0o777
        assert mode == 0o700


def test_purge_is_verified_and_idempotent():
    work = TempBagit("y").__enter__()
    root = work.root
    assert root.exists()
    assert work.purge() is True
    assert not root.exists()
    assert work.deleted_at is not None
    # Second purge is a harmless no-op.
    assert work.purge() is True


def test_purge_runs_even_when_body_raises():
    captured = {}
    with pytest.raises(ValueError):
        with TempBagit("z") as work:
            captured["root"] = work.root
            assert work.root.exists()
            raise ValueError("boom during NER")
    # __exit__ still purged the temp dir.
    assert not captured["root"].exists()


def test_extract_rejects_path_traversal():
    z = _zip({"../escape.xml": b"x"})
    with TempBagit("t") as work:
        with pytest.raises(ApsStorageError):
            work.extract(z)


def test_extract_rejects_absolute_path():
    # zipfile normalises leading slashes oddly; craft via raw name.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zi = zipfile.ZipInfo("/etc/evil.xml")
        zf.writestr(zi, b"x")
    with TempBagit("t") as work:
        with pytest.raises(ApsStorageError):
            work.extract(buf.getvalue())


def test_tdmaudit_from_temp_and_values():
    with TempBagit("doi_slug") as work:
        work.extract(_zip({"data/a.xml": b"<article/>"}))
        root = work.root
    audit = TdmAudit(doi="10.1103/PhysRevB.104.014501", paper_id="aps:...")
    audit.processed_at = datetime.now(timezone.utc)
    audit.ner_record_count = 3
    audit.status = "deleted"
    audit.from_temp(work)
    vals = audit.to_values()
    assert vals["deletion_confirmed"] is True
    assert vals["bagit_bytes"] > 0
    assert vals["files_processed"][0]["name"] == "data/a.xml"
    assert vals["ner_record_count"] == 3
    assert vals["temp_path"] == str(root)


def test_janitor_sweeps_old_dirs(monkeypatch, tmp_path):
    import ingestion.aps_storage as S

    monkeypatch.setattr(S, "_temp_base", lambda: tmp_path)
    old = tmp_path / "aps-old-xyz"
    old.mkdir()
    # Backdate mtime well past the threshold.
    past = datetime.now(timezone.utc).timestamp() - 10_000
    os.utime(old, (past, past))
    fresh = tmp_path / "aps-fresh-abc"
    fresh.mkdir()

    removed = sweep_stale_temp_dirs(max_age_seconds=1800)
    assert str(old) in removed
    assert not old.exists()
    assert fresh.exists()  # too new to sweep
