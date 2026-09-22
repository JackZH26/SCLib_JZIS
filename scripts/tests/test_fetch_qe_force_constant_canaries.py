"""No-network transfer and new-private-output tests for the fixed FC downloader."""
from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
fetcher = importlib.import_module("scripts.fetch_qe_force_constant_canaries")


def response(monkeypatch, *, data=b"synthetic FC bytes", status=200, redirect=False, encoding="identity"):
    pin = ("PHonon/synthetic.fc", len(data), hashlib.sha256(data).hexdigest())
    monkeypatch.setattr(fetcher, "REFERENCES", (pin,))
    requested = []

    class Response:
        headers = {"Content-Encoding": encoding}

        def __enter__(self):
            self.status = status
            return self

        def __exit__(self, *_args):
            pass

        def geturl(self):
            return requested[0].full_url + ("?redirected" if redirect else "")

        def read(self, size):
            assert size == len(data) + 1
            return data

    def open_request(request, timeout):
        assert timeout == 15
        requested.append(request)
        return Response()

    monkeypatch.setattr(fetcher.urllib.request, "build_opener", lambda *args: SimpleNamespace(open=open_request))
    return pin, requested


def test_exact_fixed_source_bytes(monkeypatch):
    pin, requests = response(monkeypatch)
    assert fetcher.fetch(pin) == b"synthetic FC bytes"
    assert requests[0].full_url == f"https://raw.githubusercontent.com/QEF/q-e/{fetcher.COMMIT}/PHonon/synthetic.fc"


@pytest.mark.parametrize("changes", [{"status": 206}, {"redirect": True}, {"encoding": "gzip"}])
def test_nonidentity_or_wrong_response_fails_closed(monkeypatch, changes):
    pin, _ = response(monkeypatch, **changes)
    with pytest.raises(ValueError, match="reference_response_rejected"):
        fetcher.fetch(pin)


def test_content_pin_is_independent_of_response(monkeypatch):
    pin, _ = response(monkeypatch)
    bad = (*pin[:2], "0" * 64)
    monkeypatch.setattr(fetcher, "REFERENCES", (bad,))
    with pytest.raises(ValueError, match="reference_bytes_mismatch"):
        fetcher.fetch(bad)


def test_arbitrary_network_target_never_opens(monkeypatch):
    _, requests = response(monkeypatch)
    with pytest.raises(ValueError, match="reference_not_allowlisted"):
        fetcher.fetch(("https://localhost/private", 1, "0" * 64))
    assert requests == []


def test_redirect_handler_never_follows():
    with pytest.raises(ValueError, match="reference_redirect_rejected"):
        fetcher.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "http://localhost")


def test_new_owner_only_capture_retains_whole_bytes_and_false_authority(tmp_path, monkeypatch):
    pin, _ = response(monkeypatch)
    directory = fetcher.run(tmp_path)
    assert directory.parent == tmp_path
    assert directory.stat().st_mode & 0o777 == 0o700
    assert {path.name for path in directory.iterdir()} == {pin[2] + ".bin", "capture.json"}
    assert (directory / (pin[2] + ".bin")).read_bytes() == b"synthetic FC bytes"
    for file in directory.iterdir():
        assert file.stat().st_mode & 0o777 == 0o600
    receipt = json.loads((directory / "capture.json").read_bytes())
    assert receipt["execution_attested"] is receipt["scientific_accepted"] is receipt["redistribution_authorized"] is False
    second = fetcher.run(tmp_path)
    assert second != directory
    assert (second / "capture.json").read_bytes() == (directory / "capture.json").read_bytes()


def test_network_failure_creates_no_partial_capture(tmp_path, monkeypatch):
    def fail(_):
        raise OSError("synthetic network failure")
    monkeypatch.setattr(fetcher, "fetch", fail)
    with pytest.raises(OSError):
        fetcher.run(tmp_path)
    assert not list(tmp_path.iterdir())
