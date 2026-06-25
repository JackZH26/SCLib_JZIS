"""Tests for hydride parameter runner helpers."""
from __future__ import annotations

from ingestion.hydride_parameters import _read_manifest


def test_read_manifest_keeps_explicit_aps_id_separate_from_doi(tmp_path) -> None:
    manifest = tmp_path / "manifest.txt"
    manifest.write_text(
        "\n".join([
            "aps:10.1103/PhysRevB.111.184512",
            "10.1103/PhysRevB.111.134516",
            "arxiv:2505.05176",
        ]),
        encoding="utf-8",
    )

    ids, dois = _read_manifest(manifest)

    assert "aps:10.1103/PhysRevB.111.184512" in ids
    assert "arxiv:2505.05176" in ids
    assert "10.1103/PhysRevB.111.184512" not in dois
    assert "10.1103/PhysRevB.111.134516" in dois
