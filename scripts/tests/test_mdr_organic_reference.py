"""Verify the full licensed source table and its browser projection independently."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from build_mdr_organic_reference import FILENAME, SOURCE_SHA256, build  # noqa: E402


def test_every_original_cell_and_physical_line_survives():
    folder = ROOT / "frontend/public/research-pilots"
    raw = (folder / "240322_MDR_Organic.txt").read_bytes()
    resource = (folder / FILENAME).read_bytes()
    data = json.loads(resource)
    assert hashlib.sha256(raw).hexdigest() == SOURCE_SHA256
    assert data == build(raw)
    assert resource == (json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    assert (folder / (FILENAME + ".sha256")).read_text() == hashlib.sha256(resource).hexdigest() + "  " + FILENAME + "\n"
    reader = csv.reader(io.StringIO(raw.decode(), newline=""), delimiter="\t")
    assert next(reader) == data["source_labels"]
    assert next(reader) == data["columns"]
    actual = list(reader)
    nonempty = [row for row in actual if any(row)]
    assert len(nonempty) == 568 and len(actual) == 569
    assert [row["values"] for row in data["rows"]] == nonempty
    lines = raw.splitlines(keepends=True)
    for row in data["rows"] + data["excluded_rows"]:
        assert hashlib.sha256(b"".join(lines[row["line_start"] - 1:row["line_end"]])).hexdigest() == row["sha256"]
    assert data["coverage"]["tc"] == 517
    assert data["coverage"]["tcmax"] == 83
    assert data["coverage"]["pcrit"] == 484
    assert data["coverage"]["hc2zero"] == 70
    assert data["coverage"]["cohere"] == 73
    assert data["source_labels"][data["columns"].index("tc")] == "Tc at pcrit or Tc at atmospheric pressure"


def test_another_version_cannot_silently_replace_the_source():
    raw = (ROOT / "frontend/public/research-pilots/240322_MDR_Organic.txt").read_bytes()
    with pytest.raises(ValueError, match="source bytes"):
        build(raw.replace(b"9.5", b"9.6", 1))
