"""Offline mocked transport tests: synthetic script bytes are not QE executions."""
from __future__ import annotations

import hashlib
import http.client
import importlib
import io
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


@pytest.fixture
def cli(monkeypatch):
    module = importlib.import_module("scripts.fetch_qe_matdyn_canaries")

    def no_network(*args, **kwargs):
        raise AssertionError("Tests must not access the network")

    monkeypatch.setattr(socket, "create_connection", no_network)
    return module


def sha(value):
    return hashlib.sha256(value).hexdigest()


def input_bytes(frequency, *, prefix=False, bn=False):
    names = b"flfrc='$PREFIX.444.fc', flfrq='$PREFIX.freq'" if prefix else (
        b"flfrc='synthetic.fc', flfrq='" + frequency.encode() + b"'")
    return b" &input\n asr='simple', " + names + (b", loto_2d=.true." if bn else b"") + b"\n /\n 1\n 0 0 0\n"


def script_bytes(frequency, *, prefix=False):
    return (b"#!/bin/sh\n# SYNTHETIC offline test, never executed\n"
            + (b"PREFIX='alas'\n" if prefix else b"")
            + b"cat > matdyn.in <<EOF\n" + input_bytes(frequency, prefix=prefix)
            + b"EOF\n# poison shell command remains inert\nexit 77\n")


class Response(io.BytesIO):
    def __init__(self, payload, url, *, status=200, headers=None):
        super().__init__(payload)
        self.status, self.url = status, url
        self.headers = {"Content-Length": str(len(payload))} if headers is None else headers

    def geturl(self):
        return self.url


@pytest.fixture
def upstream(cli, monkeypatch):
    paths = [path for path, _ in cli.UPSTREAM_FILES]
    frequency = b" &plot nbnd=3, nks=1 /\n 0 0 0\n -1.0000 0.0000 2.0000\n"
    raw = dict(zip(paths, [b"SYNTHETIC license bytes: no rights inferred.\n",
        script_bytes("al.freq"), frequency, script_bytes("alas.freq", prefix=True),
        frequency + b"\n", input_bytes("bn.freq", bn=True), frequency + b"\n\n"], strict=True))
    monkeypatch.setattr(cli, "UPSTREAM_FILES", tuple((path, sha(payload)) for path, payload in raw.items()))
    calls, handlers = [], []

    def open_request(request, *, timeout):
        calls.append((request, timeout))
        assert request.full_url.startswith(cli.RAW_BASE)
        return Response(raw[request.full_url[len(cli.RAW_BASE):]], request.full_url)

    def build_opener(*values):
        handlers.extend(values)
        return SimpleNamespace(open=open_request)

    monkeypatch.setattr(cli.urllib.request, "build_opener", build_opener)
    return SimpleNamespace(raw=raw, calls=calls, handlers=handlers)


def document(directory):
    return json.loads((directory / "manifest.json").read_bytes())


def payload(directory, role):
    entry = next(item for item in document(directory)["files"] if item["role"] == role)
    return (directory / (entry["sha256"] + ".bin")).read_bytes()


def provenance(directory):
    entry = next(item for item in document(directory)["files"] if item["logical_name"] == "derivation.json")
    return json.loads((directory / (entry["sha256"] + ".bin")).read_bytes())


def test_fixed_allowlist_is_exactly_seven_official_commit_pins(cli):
    assert cli.COMMIT == "770a0b2d12928a67048e2f3da8d10d057e52179e"
    assert cli.UPSTREAM_FILES == (
        ("License", "204d8eff92f95aac4df6c8122bc1505f468f3a901e5a4cc08940e0ede1938994"),
        ("PHonon/examples/example14/run_example", "50adcdc624018a8cc892d15246fdcce3a860d1df1cb4cf4ae8680e593f62dd4e"),
        ("PHonon/examples/example14/reference/al.freq", "ea63aef65be50e4a69ec6e8418b0c9d02c550b80837097d52c9a58b80f60a284"),
        ("PHonon/examples/GRID_recover_example/run_example", "5af2c411fbe5e523fe3600d04ccbbbcdf4de279d19f9cc169d8194002b5f3f3f"),
        ("PHonon/examples/GRID_recover_example/reference/alas.freq", "942744cf2cb3f74e703f7a271576bec4c4f006dd101e15153b704276e97e24a2"),
        ("PHonon/examples/example17/reference/matdyn.in", "322c7d3977062ba549e18966ba0e7b554b3c354f07b12fbdc65e89d2a4875ecd"),
        ("PHonon/examples/example17/reference/bn.freq", "b9b6ee8dfa04fbeccde442a3c68b38fe598c92497921ae2e4aaa684269621ece"))


def test_fetches_exact_seven_and_creates_owner_only_complete_capsules(cli, upstream, tmp_path):
    parent = tmp_path.resolve()
    result = cli.run(output_parent=parent)
    root = Path(result["directory"])
    assert root.parent == parent and root.stat().st_mode & 0o777 == 0o700
    assert result["status"] == "fetched" and result["commit"] == cli.COMMIT
    assert all(value is False for value in result["authority"].values())
    assert len(result["packages"]) == 3
    assert [request.full_url for request, _ in upstream.calls] == [cli.RAW_BASE + path for path, _ in cli.UPSTREAM_FILES]
    assert all(timeout == 15 and request.get_method() == "GET" for request, timeout in upstream.calls)
    assert all(request.get_header("Accept-encoding") == "identity" for request, _ in upstream.calls)
    assert all(handler.proxies == {} for handler in upstream.handlers if isinstance(handler, cli.urllib.request.ProxyHandler))
    for package in result["packages"]:
        directory = Path(package["manifest_path"]).parent
        assert directory.stat().st_mode & 0o777 == 0o700
        manifest_bytes = (directory / "manifest.json").read_bytes()
        assert sha(manifest_bytes) == package["manifest_sha256"]
        manifest = document(directory)
        assert cli.canonical(manifest) == manifest_bytes
        assert set(file.name for file in directory.iterdir()) == {"manifest.json"} | {
            entry["sha256"] + ".bin" for entry in manifest["files"]}
        for file in directory.iterdir():
            assert file.stat().st_mode & 0o777 == 0o600 and file.stat().st_nlink == 1
        assert payload(directory, "license") == upstream.raw["License"]
        assert manifest["context"]["license_spdx"] is None
        assert manifest["declarations"] == {"review_status": "unreviewed", "execution_attested": False,
                                            "ml_training_approved": False}
        details = provenance(directory)
        assert details["license_declaration"]["rights_reviewed"] is False
        assert all(value is False for value in details["authority"].values())
        assert details["input_derivation"]["input_derived"] is package["input_derived"]


def test_literal_and_prefix_derivations_preserve_exact_original_spans(cli, upstream, tmp_path):
    result = cli.run(output_parent=tmp_path.resolve())
    for package in result["packages"]:
        directory = Path(package["manifest_path"]).parent
        derivation = provenance(directory)["input_derivation"]
        original = upstream.raw[derivation["source_path"]]
        span = original[derivation["source_byte_start"]:derivation["source_byte_end"]]
        assert sha(span) == derivation["source_span_sha256"]
        assert sha(original) == derivation["source_sha256"]
        actual = payload(directory, "input")
        assert sha(actual) == derivation["input_sha256"]
        if package["id"] == "alas-grid-recover":
            assert actual == span.replace(b"$PREFIX", b"alas") and b"$" not in actual
            assert len(derivation["replacements"]) == 2
            for replacement in derivation["replacements"]:
                assert original[replacement["source_byte_start"]:replacement["source_byte_end"]] == b"$PREFIX"
                assert replacement["from"] == "$PREFIX" and replacement["to"] == "alas"
            assignment = derivation["prefix_assignment"]
            assert original[assignment["source_byte_start"]:assignment["source_byte_end"]] == b"PREFIX='alas'"
        else:
            assert span == actual and derivation["replacements"] == []
        if package["input_derived"]:
            script = next(item for item in document(directory)["files"] if item["logical_name"] == "upstream-run_example.txt")
            assert (directory / (script["sha256"] + ".bin")).read_bytes() == original
        else:
            assert document(directory)["context"]["geometry_scope"] == "other"


def test_capsules_are_accepted_by_real_offline_preflight_not_attested_execution(cli, upstream, tmp_path):
    preflight = importlib.import_module("scripts.scientific_program_preflight")
    result = cli.run(output_parent=tmp_path.resolve())
    for package in result["packages"]:
        report = preflight.run(manifest_path=package["manifest_path"], expected_manifest_sha256=package["manifest_sha256"])
        assert report["status"] == ("quarantined" if package["id"] == "bn-example17-2d" else "parsed")
        assert report["authority"]["execution_attested"] is False
        assert report["authority"]["ml_training_approved"] is False


def test_repeat_fetch_has_fresh_paths_but_identical_capsule_bytes(cli, upstream, tmp_path):
    first = cli.run(output_parent=tmp_path.resolve())
    before = {str(path.relative_to(first["directory"])): path.read_bytes()
              for path in Path(first["directory"]).rglob("*") if path.is_file()}
    second = cli.run(output_parent=tmp_path.resolve())
    assert first["directory"] != second["directory"]
    assert [item["manifest_sha256"] for item in first["packages"]] == [item["manifest_sha256"] for item in second["packages"]]
    assert before == {str(path.relative_to(first["directory"])): path.read_bytes()
                      for path in Path(first["directory"]).rglob("*") if path.is_file()}


@pytest.mark.parametrize("change", [
    lambda data: data.replace(b"cat > matdyn.in <<EOF", b"cat > matdyn.in <<'EOF'"),
    lambda data: data + b"cat > matdyn.in <<EOF\n&input /\nEOF\n",
    lambda data: data.replace(b"\nEOF\n", b"\nNOT_EOF\n"),
    lambda data: data.replace(b"synthetic.fc", b"${SECRET}"),
    lambda data: data.replace(b"synthetic.fc", b"$(touch bad)"),
    lambda data: data.replace(b"synthetic.fc", b"`touch bad`"),
    lambda data: data.replace(b"synthetic.fc", b"synthetic\\\n.fc"),
])
def test_rejects_unreviewed_shell_processing_or_ambiguous_heredocs(cli, change):
    with pytest.raises(ValueError):
        cli.derive_matdyn_input(change(script_bytes("al.freq")))


@pytest.mark.parametrize("change", [
    lambda data: data.replace(b"PREFIX='alas'", b"PREFIX='other'"),
    lambda data: data.replace(b"PREFIX='alas'", b"PREFIX=$(cat private)"),
    lambda data: data.replace(b"PREFIX='alas'", b"export PREFIX='alas'"),
    lambda data: data.replace(b"PREFIX='alas'", b"PREFIX='alas'\nPREFIX='alas'"),
    lambda data: data.replace(b"PREFIX='alas'\n", b"") + b"PREFIX='alas'\n",
    lambda data: data.replace(b"$PREFIX.freq", b"${PREFIX}.freq"),
    lambda data: data.replace(b"$PREFIX.freq", b"$PREFIX_EXTRA.freq"),
    lambda data: data.replace(b"$PREFIX.freq", b"$OTHER.freq"),
    lambda data: data.replace(b"$PREFIX.freq", b"$PREFIX.$OTHER"),
    lambda data: data.replace(b"\n /\n", b", extra='$PREFIX_SUFFIX'\n /\n"),
])
def test_only_reviewed_alas_prefix_assignment_and_two_literal_uses_allowed(cli, change):
    with pytest.raises(ValueError):
        cli.derive_matdyn_input(change(script_bytes("alas.freq", prefix=True)), substitute_alas_prefix=True)


@pytest.mark.parametrize("path", ["License?token=secret", "../License", "https://example.org/License", "License/", "README.md", None])
def test_unknown_paths_never_reach_transport(cli, upstream, path):
    with pytest.raises(ValueError, match="upstream_path_not_allowed"):
        cli.download_reference(path)
    assert not upstream.calls


@pytest.mark.parametrize("status,url_suffix,headers,payload", [
    (302, "", {}, b""), (404, "", {}, b"private server failure"),
    (200, "/redirected", {}, b"ok"), (200, "", {"Content-Encoding": "gzip"}, b"ok"),
    (200, "", {"Content-Length": "9999999"}, b"ok"),
    (200, "", {"Content-Length": "-1"}, b"ok"),
    (200, "", {"Content-Length": "false"}, b"ok"),
    (200, "", {"Content-Length": "0"}, b""),
    (200, "", {"Content-Length": "1"}, b"ok"),
    (200, "", {}, b"wrong pinned bytes"),
])
def test_bad_http_metadata_or_bytes_fail_closed(cli, upstream, monkeypatch, status, url_suffix, headers, payload):
    monkeypatch.setattr(cli.urllib.request, "build_opener", lambda *args: SimpleNamespace(open=lambda req, **kwargs:
        Response(payload, req.full_url + url_suffix, status=status, headers=headers)))
    with pytest.raises(ValueError):
        cli.download_reference("License")


def test_redirect_handler_never_constructs_followup_request(cli):
    with pytest.raises(ValueError, match="upstream_redirect_rejected"):
        cli._NoRedirects().redirect_request(None, None, 302, "redirect", {}, "https://offsite.invalid/private")


def test_stream_limit_without_content_length_is_bounded(cli, upstream, monkeypatch):
    monkeypatch.setattr(cli, "MAX_DOWNLOAD_BYTES", 8)
    reads = []

    class Stream(Response):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)

    monkeypatch.setattr(cli.urllib.request, "build_opener", lambda *args: SimpleNamespace(open=lambda req, **kwargs:
        Stream(b"x" * 1000, req.full_url, headers={})))
    with pytest.raises(ValueError, match="upstream_byte_limit"):
        cli.download_reference("License")
    assert reads == [9]


def test_slow_completed_response_never_becomes_success(cli, upstream, monkeypatch):
    ticks = iter([0, 0, 16])
    monkeypatch.setattr(cli.time, "monotonic", lambda: next(ticks))
    with pytest.raises(ValueError, match="upstream_deadline_exceeded"):
        cli.download_reference("License")


@pytest.mark.parametrize("mutation", ["missing", "extra", "changed", "wrong_type"])
def test_pure_builder_rechecks_exact_pinned_inventory(cli, upstream, mutation):
    copied = dict(upstream.raw)
    if mutation == "missing":
        copied.pop("License")
    elif mutation == "extra":
        copied["private"] = b"secret"
    elif mutation == "changed":
        copied["License"] += b"drift"
    else:
        copied["License"] = bytearray(copied["License"])
    with pytest.raises(ValueError):
        cli.build_packages(copied)


def test_download_failure_does_not_create_any_output(cli, upstream, tmp_path):
    upstream.raw["License"] += b"changed"
    with pytest.raises(ValueError, match="upstream_hash_mismatch"):
        cli.run(output_parent=tmp_path.resolve())
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("kind", ["missing", "relative", "traversal", "symlink", "file"])
def test_unsafe_parent_fails_before_network(cli, upstream, tmp_path, kind):
    root = tmp_path.resolve()
    if kind == "missing":
        path = root / "absent"
    elif kind == "relative":
        path = Path("relative-private")
    elif kind == "traversal":
        path = root / ".." / root.name
    elif kind == "symlink":
        path = root / "alias"
        path.symlink_to(root, target_is_directory=True)
    else:
        path = root / "file"
        path.write_bytes(b"private")
    with pytest.raises((ValueError, OSError)):
        cli.run(output_parent=path)
    assert not upstream.calls


def test_parent_replacement_during_download_fails_before_writes(cli, upstream, tmp_path, monkeypatch):
    parent = tmp_path.resolve() / "parent"
    parent.mkdir()
    original = cli.download_reference
    called = False

    def replace(path):
        nonlocal called
        result = original(path)
        if not called:
            called = True
            parent.rename(parent.with_name("original"))
            parent.mkdir()
        return result

    monkeypatch.setattr(cli, "download_reference", replace)
    with pytest.raises(ValueError, match="output_directory_changed"):
        cli.run(output_parent=parent)
    assert list(parent.iterdir()) == [] and list(parent.with_name("original").iterdir()) == []


def test_colliding_directory_is_never_reused_or_modified(cli, upstream, tmp_path, monkeypatch):
    parent = tmp_path.resolve()
    existing = parent / "qe-matdyn-canaries-fixed"
    existing.mkdir()
    (existing / "private").write_bytes(b"preserve")
    monkeypatch.setattr(cli, "uuid4", lambda: SimpleNamespace(hex="fixed"))
    with pytest.raises(ValueError, match="fresh_output_directory_unavailable"):
        cli.run(output_parent=parent)
    assert list(parent.iterdir()) == [existing]
    assert (existing / "private").read_bytes() == b"preserve"


def test_created_directory_swap_cannot_redirect_writes_to_replacement(cli, upstream, tmp_path, monkeypatch):
    parent = tmp_path.resolve()
    original = cli._new_directory
    replacement = None

    def replace(descriptor):
        nonlocal replacement
        name, held = original(descriptor)
        replacement = parent / name
        replacement.rename(parent / "owned-original")
        replacement.mkdir(mode=0o700)
        (replacement / "private").write_bytes(b"do not change")
        return name, held

    monkeypatch.setattr(cli, "_new_directory", replace)
    with pytest.raises((ValueError, OSError)):
        cli.run(output_parent=parent)
    assert [item.name for item in replacement.iterdir()] == ["private"]
    assert (replacement / "private").read_bytes() == b"do not change"


def test_exclusive_leaf_writer_never_overwrites_or_follows_symlink(cli, tmp_path):
    root = tmp_path.resolve()
    (root / "real").write_bytes(b"private")
    (root / "alias").symlink_to(root / "real")
    descriptor = cli._directory_fd(root)
    try:
        for name in ("real", "alias"):
            with pytest.raises(FileExistsError):
                cli._write_new(descriptor, name, b"replacement")
    finally:
        os.close(descriptor)
    assert (root / "real").read_bytes() == b"private"


@pytest.mark.parametrize("mutation", ["changed", "mode", "hardlink", "extra"])
def test_output_tamper_before_final_check_is_not_reported_complete(cli, upstream, tmp_path, monkeypatch, mutation):
    original = cli._check_files
    called = False

    def tamper(directory, files, identities):
        nonlocal called
        if not called:
            called = True
            leaf = next(iter(files))
            if mutation == "changed":
                fd = os.open(leaf, os.O_WRONLY, dir_fd=directory)
                try:
                    os.write(fd, b"X")
                finally:
                    os.close(fd)
            elif mutation == "mode":
                os.chmod(leaf, 0o644, dir_fd=directory)
            elif mutation == "hardlink":
                os.link(leaf, "extra", src_dir_fd=directory, dst_dir_fd=directory)
            else:
                cli._write_new(directory, "extra", b"extra")
        return original(directory, files, identities)

    monkeypatch.setattr(cli, "_check_files", tamper)
    with pytest.raises(ValueError, match="output_"):
        cli.run(output_parent=tmp_path.resolve())


def test_successful_main_emits_only_summary_not_source_prose(cli, upstream, tmp_path, capsys):
    assert cli.main(["--output-parent", str(tmp_path.resolve())]) == 0
    captured = capsys.readouterr()
    value = json.loads(captured.out)
    assert not captured.err and value["status"] == "fetched"
    assert set(value) == {"version", "status", "classification", "commit", "directory", "packages", "authority"}
    assert "SYNTHETIC license" not in captured.out and "poison shell" not in captured.out


@pytest.mark.parametrize("error", [ValueError("private path"), OSError("private credentials"),
    http.client.IncompleteRead(b"secret source"), TimeoutError("private remote")])
def test_errors_are_sanitized_and_never_claim_complete_output(cli, monkeypatch, capsys, error):
    def fail(**kwargs):
        raise error

    monkeypatch.setattr(cli, "run", fail)
    assert cli.main(["--output-parent", "/private/location"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == '{"status":"failed","complete_capsules_reported":false}\n'


def test_real_subprocess_import_and_help_need_no_network_database_or_environment(tmp_path):
    code = '''
import builtins, os, runpy, socket, sys
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in {'config', 'models', 'sqlalchemy', 'asyncpg', 'psycopg', 'psycopg2'}:
        raise AssertionError('database or app config imported')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
def deny(*args, **kwargs):
    raise AssertionError('network attempted')
socket.create_connection = deny
sys.argv = [sys.argv[1], '--help']
runpy.run_path(sys.argv[0], run_name='__main__')
'''
    result = subprocess.run([sys.executable, "-c", code, str(ROOT / "scripts/fetch_qe_matdyn_canaries.py")],
        cwd=tmp_path.resolve(), env={**os.environ, "DATABASE_URL": "not-a-real-database", "REDIS_URL": "invalid",
                                    "HTTPS_PROXY": "https://private.invalid"},
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert "--output-parent" in result.stdout and result.stderr == ""
