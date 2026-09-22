"""Bounded private CLI captures; real SQL build/rebuild lives in API tests."""
from __future__ import annotations

import hashlib
import os

import pytest
from services.research_release_manifest import canonical

from scripts import ml_scientific_dataset as cli


def write(path, value):
    payload = canonical(value)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def test_companion_full_file_capture(tmp_path):
    path = tmp_path / "companion.json"
    expected = write(path, {"synthetic": True, "companion_sha256": "f" * 64})
    assert cli.read_companion(path, expected)[0] == {"synthetic": True, "companion_sha256": "f" * 64}
    with pytest.raises(ValueError):
        cli.read_companion(path, "f" * 64)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "directory"])
def test_companion_alias_and_nonregular_inputs_rejected(tmp_path, kind):
    original, path = tmp_path / "original.json", tmp_path / "companion.json"
    expected = write(original, {"synthetic": True})
    if kind == "symlink": path.symlink_to(original)
    elif kind == "hardlink": os.link(original, path)
    elif kind == "fifo": os.mkfifo(path)
    else: path.mkdir()
    with pytest.raises((ValueError, OSError)):
        cli.read_companion(path, expected)


@pytest.mark.parametrize("payload", [b'{"a":1,"a":2}', b'{"a":NaN}', b'{ "a":1}', b'["bad"]\n'])
def test_noncanonical_or_ambiguous_companion_rejected(tmp_path, payload):
    path = tmp_path / "companion.json"
    path.write_bytes(payload)
    with pytest.raises(ValueError):
        cli.read_companion(path, hashlib.sha256(payload).hexdigest())


def test_companion_wire_limit(tmp_path, monkeypatch):
    path = tmp_path / "companion.json"
    expected = write(path, {"synthetic": "a" * 100})
    monkeypatch.setattr(cli, "MAX_DOCUMENT_BYTES", 10)
    with pytest.raises(ValueError):
        cli.read_companion(path, expected)


def test_cli_errors_do_not_echo_source_or_paths(capsys):
    assert cli.main(["build", "--manifest", "PRIVATE-SOURCE-TOKEN"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == '{"status":"invalid","output_written":false}\n'
