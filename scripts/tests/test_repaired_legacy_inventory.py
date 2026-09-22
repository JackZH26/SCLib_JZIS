"""No-network proof of full coverage with independently receipted replacements."""

import sqlite3
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "api"), str(ROOT / "ingestion")]
from legacy_index_pack import Pack, PackError, specification
from embed_legacy_index_pack import Ledger, file_sha
from repair_legacy_index_pack import Origin, repair, compose, conservative_windows
from test_legacy_embedding_ledger import completed


def parents(tmp_path):
    tmp_path.chmod(0o700)
    path = tmp_path / "original.sqlite"
    pack = Pack(path, specification({"synthetic": True}))
    paper = {"id": "p", "title": "Synthetic"}
    for n in range(100):
        pack.append(
            n + 1, {"id": f"c{n:03}", "paper_id": "p", "text": "test " * 1100}, paper
        )
    pack.seal(100)
    pack.close()
    pack = Pack(path, readonly=True)
    ledger = Ledger(
        tmp_path / "original-ledger.sqlite", pack, file_sha(path), create=True
    )
    first = next(ledger.pending(1))
    ledger.fail(ledger.reserve(first), "provider_input_limit")
    for batch in ledger.pending():
        attempt = ledger.reserve(batch)
        ledger.finish(attempt, batch, completed(batch))
    assert ledger.status()["completed_members"] == 99
    ledger.close()
    pack.close()
    return Origin(path, tmp_path / "original-ledger.sqlite")


def repaired(tmp_path, original):
    report = repair(original, tmp_path / "repair.sqlite")
    assert report["sources"] == 1 and report["members"] > 1
    pack = Pack(tmp_path / "repair.sqlite", readonly=True)
    ledger = Ledger(
        tmp_path / "repair-ledger.sqlite", pack, file_sha(pack.path), create=True
    )
    for batch in ledger.pending():
        a = ledger.reserve(batch)
        ledger.finish(a, batch, completed(batch))
    ledger.seal()
    ledger.close()
    pack.close()
    return Origin(tmp_path / "repair.sqlite", tmp_path / "repair-ledger.sqlite")


def test_full_repaired_inventory_preserves_sources_and_receipt_origins(tmp_path):
    original = parents(tmp_path)
    replacement = repaired(tmp_path, original)
    try:
        result = compose(
            original,
            replacement,
            tmp_path / "effective.sqlite",
            tmp_path / "complete.sqlite",
        )
        effective = Pack(tmp_path / "effective.sqlite", readonly=True)
        assert (
            effective.verify(100)["source_manifest_sha256"]
            == original.report["source_manifest_sha256"]
        )
        assert result["members"] == 99 + replacement.report["members"]
        assert (
            result["embedding_completion_verified"] is True
            and result["index_publication_verified"] is False
        )
        with sqlite3.connect(tmp_path / "complete.sqlite") as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM completions WHERE origin_ledger_sha256=?",
                    (original.digest,),
                ).fetchone()[0]
                == 99
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM completions WHERE origin_ledger_sha256=?",
                    (replacement.digest,),
                ).fetchone()[0]
                == replacement.report["members"]
            )
            with pytest.raises(sqlite3.IntegrityError):
                db.execute("DELETE FROM completions")
        effective.close()
    finally:
        original.close()
        replacement.close()


def test_changed_origin_cannot_be_composed(tmp_path):
    original = parents(tmp_path)
    replacement = repaired(tmp_path, original)
    try:
        with sqlite3.connect(original.path) as db:
            db.execute("CREATE TABLE injected(x)")
        with pytest.raises(PackError, match="changed_during"):
            compose(
                original,
                replacement,
                tmp_path / "bad.sqlite",
                tmp_path / "bad-complete.sqlite",
            )
        with sqlite3.connect(tmp_path / "bad-complete.sqlite") as db:
            assert (
                db.execute("SELECT body FROM metadata WHERE key='report'").fetchone()
                is None
            )
    finally:
        original.close()
        replacement.close()


def test_utf8_windows_preserve_unicode_and_whitespace():
    text = "超导材料🙂" * 800 + " " * 2000
    spans = list(conservative_windows({"text": text}))
    assert "".join(text[start:end] for start, end, prefix, count in spans) == text
    assert all(
        len((prefix + text[start:end]).encode()) <= 1295 and 1 <= count <= 1536
        for start, end, prefix, count in spans
    )
