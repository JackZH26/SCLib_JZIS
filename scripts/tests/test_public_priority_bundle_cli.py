"""Actual offline public recomputation, never scientific or disclosure approval."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "validate_public_priority_bundle.py"
CANARY = "PRIVATE-PUBLIC-BUNDLE-INPUT-PATH-DO-NOT-PRINT"


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "api"))
    from services import priority_public_bundle_cli
    from services.priority_release_cache import clear_release_cache
    clear_release_cache()
    return priority_public_bundle_cli


@pytest.fixture
def bundle(cli, tmp_path):
    from services.research_priority import canonical_json
    from tests.test_priority_public_bundle import public_bundle_payload
    value = public_bundle_payload()
    path = tmp_path / (value["release"]["id"] + ".public.json")
    path.write_bytes(canonical_json(value).encode("utf-8"))
    return value, path


def arguments(bundle):
    value, path = bundle
    return ["--bundle", str(path), "--sha256", value["bundle_sha256"],
            "--release-sha256", value["release"]["manifest_sha256"]]


def report(capsys):
    value = capsys.readouterr()
    assert value.err == "" and CANARY not in value.out and "Traceback" not in value.out
    return json.loads(value.out)


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_help_is_static_read_only_json(cli, flag, capsys):
    assert cli.main([flag]) == 0
    result = report(capsys)
    assert result["status"] == "usage" and result["offline"] and result["read_only"]


@pytest.mark.parametrize("args", [[], [CANARY], ["--bundle", CANARY],
    ["--bundle", CANARY, "--sha256"], ["--bun", CANARY, "--sha256", "a" * 64],
    ["--bundle", CANARY, "--sha256", "a" * 64, "--extra", CANARY]])
def test_invalid_arguments_never_echo_arbitrary_input(cli, args, capsys):
    assert cli.main(args) == 2
    assert report(capsys) == {"integrity_verified": False, "error": "invalid_arguments"}


@pytest.mark.parametrize("path", ["relative.public.json", "https://private.invalid/" + CANARY,
    "file:///tmp/" + CANARY, "/tmp/../" + CANARY + ".public.json", "//host/" + CANARY,
    "/tmp/\x00secret.public.json", "/tmp/secret.json"])
def test_unsafe_paths_fail_before_any_input_is_opened(cli, path, monkeypatch, capsys):
    from services import priority_release_cache
    monkeypatch.setattr(priority_release_cache, "read_verified_file", lambda *a, **k: pytest.fail("unsafe path opened"))
    assert cli.main(["--bundle", path, "--sha256", "a" * 64]) == 1
    assert report(capsys)["error"] == "public_bundle_verification_failed"


@pytest.mark.parametrize("sha", ["", "a" * 63, "a" * 65, "A" * 64, "g" * 64, CANARY])
def test_digest_format_is_checked_before_file_capture(cli, bundle, sha, monkeypatch, capsys):
    from services import priority_release_cache
    monkeypatch.setattr(priority_release_cache, "read_verified_file", lambda *a, **k: pytest.fail("bad digest opened file"))
    args = arguments(bundle)
    args[3] = sha
    assert cli.main(args) == 1
    assert report(capsys)["error"] == "public_bundle_verification_failed"


@pytest.mark.parametrize("raw", [b"[]", b"null", b"true", b"1", b'"private"', b'{"release":[]}',
    b'{"release":null}', b'{"a":1,"a":2}', b'{"a":{"b":1,"b":2}}', b'{"a":NaN}',
    b'{"a":Infinity}', b'{"a":-Infinity}', b'{"a":1e999}', b'\xff', b'{"a":"\\ud800"}',
    b'{} trailing', b'{"a":'])
def test_malformed_root_and_recursive_json_sanitize_actual_service_error(cli, bundle, raw, capsys):
    bundle[1].write_bytes(raw)
    assert cli.main(arguments(bundle)) == 1
    assert report(capsys) == {"integrity_verified": False, "error": "public_bundle_verification_failed"}


@pytest.mark.parametrize("mutation", ["source", "verifier", "rows", "policy", "release", "disclosure"])
def test_actual_cli_recomputes_self_resealed_document_not_only_envelope_hash(cli, bundle, mutation, capsys):
    from services.priority_public_bundle import bundle_sha256
    from services.research_priority import canonical_json
    value, path = bundle
    if mutation == "source": value["verifier"]["source_sha256"] = "0" * 64
    elif mutation == "verifier": value["verifier"]["version"] = "future"
    elif mutation == "rows": value["rows"][0]["result"]["score_display"] = 9999
    elif mutation == "policy": value["policy"]["offset"] += 1
    elif mutation == "release": value["release"]["artifacts"].clear()
    else: value["disclosure"]["review_attestations"].clear()
    value["bundle_sha256"] = bundle_sha256(value)
    path.write_text(canonical_json(value))
    assert cli.main(arguments(bundle)) == 1
    assert report(capsys)["error"] == "public_bundle_verification_failed"


@pytest.mark.parametrize("kind", ["symlink", "fifo", "directory", "missing"])
def test_only_bounded_regular_leaf_is_read(cli, bundle, kind, capsys):
    import os
    _, path = bundle
    raw = path.read_bytes()
    path.unlink()
    if kind == "symlink":
        target = path.parent / "private.json"
        target.write_bytes(raw)
        path.symlink_to(target)
    elif kind == "fifo": os.mkfifo(path)
    elif kind == "directory": path.mkdir()
    assert cli.main(arguments(bundle)) == 1
    assert report(capsys)["error"] == "public_bundle_verification_failed"


@pytest.mark.parametrize("entry", ["script", "module"])
def test_actual_subprocess_forbids_network_database_and_filesystem_writes(cli, bundle, entry):
    value, path = bundle
    before = path.read_bytes()
    inventory = set(path.parent.iterdir())
    bootstrap = """
import sys
sys.dont_write_bytecode = True
import os, runpy
def offline_readonly(event, args):
    if event.startswith('socket.') or event == 'sqlite3.connect':
        raise RuntimeError('Forbidden external service')
    if event == 'open':
        mode, flags = args[1], args[2]
        if (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
            raise RuntimeError('Forbidden file write')
sys.addaudithook(offline_readonly)
entry, api, launcher = sys.argv[1:4]
sys.path.insert(0, api)
sys.argv = [launcher, *sys.argv[4:]]
if entry == 'module':
    runpy.run_module('services.priority_public_bundle_cli', run_name='__main__')
else:
    runpy.run_path(launcher, run_name='__main__')
"""
    process = subprocess.run([sys.executable, "-I", "-B", "-c", bootstrap, entry,
        str(ROOT / "api"), str(SCRIPT), *arguments(bundle)], capture_output=True, text=True,
        timeout=20, check=False)
    assert process.returncode == 0, process.stdout + process.stderr
    assert process.stderr == ""
    result = json.loads(process.stdout)
    assert result["integrity_verified"] and result["scoring_recomputed"]
    for field in ("current_public_authorization_checked", "reviewer_identity_authenticated",
                  "source_rights_verified", "scientific_acceptance", "empirical_calibration_verified"):
        assert result[field] is False
    for item in value["release"]["artifacts"]:
        if item["kind"] in {"review", "template_review"}:
            assert item["content"]["reviewer_id"] not in process.stdout
    assert str(path) not in process.stdout and CANARY not in process.stdout
    assert path.read_bytes() == before and set(path.parent.iterdir()) == inventory


def test_actual_subprocess_malformed_arguments_and_list_root_never_emit_traceback(cli, bundle):
    for args in ([CANARY], arguments(bundle)):
        bundle[1].write_text("[]")
        process = subprocess.run([sys.executable, "-B", str(SCRIPT), *args],
            capture_output=True, text=True, timeout=20, check=False)
        assert process.returncode in {1, 2} and process.stderr == ""
        assert json.loads(process.stdout)["integrity_verified"] is False
        assert CANARY not in process.stdout and "Traceback" not in process.stdout


def test_public_json_size_limit_is_checked_before_json_parsing(cli, bundle, monkeypatch, capsys):
    from services import priority_public_bundle
    monkeypatch.setattr(priority_public_bundle, "MAX_BYTES", 10)
    assert cli.main(arguments(bundle)) == 1
    assert report(capsys)["error"] == "public_bundle_verification_failed"
