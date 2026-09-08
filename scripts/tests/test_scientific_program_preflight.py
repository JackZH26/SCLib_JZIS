"""Actual offline file/CLI boundaries using explicitly synthetic QE output.

No quantum calculation, source authentication, database access or ML approval
is implied by parsing these small hand-written program-format fixtures.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

SYNTHETIC_INPUT = (
    b" &input\n asr='simple', flfrc='synthetic.fc', flfrq='synthetic.freq'\n /\n 1\n 0 0 0\n"
)
SYNTHETIC_FREQUENCY = (
    b" &plot nbnd=3, nks=1 /\n 0.000000 0.000000 0.000000\n -1.0000 0.0000 2.0000\n"
)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


@pytest.fixture
def cli():
    # Late import avoids collection races while the independently owned CLI is
    # being implemented; the tests still exercise the real module and adapter.
    return importlib.import_module("scripts.scientific_program_preflight")


def package(tmp_path, *, frequency=SYNTHETIC_FREQUENCY, extra_files=()):
    directory = tmp_path.resolve() / "synthetic-package"
    directory.mkdir()
    files = [("input", "synthetic.in", SYNTHETIC_INPUT), ("frequency", "synthetic.freq", frequency), *extra_files]
    document = {
        "version": "scientific-program-package/1.0.0", "adapter_id": "qe-matdyn-flfrq",
        "files": [{"role": role, "logical_name": name, "sha256": sha(payload), "size_bytes": len(payload)}
                  for role, name, payload in files],
        "context": {"material_formula": None, "material_id": None, "geometry_scope": "unknown",
                    "source_url": None, "source_revision": None, "license_spdx": None},
        "declarations": {"review_status": "unreviewed", "execution_attested": False, "ml_training_approved": False},
    }
    for _, _, payload in files:
        (directory / (sha(payload) + ".bin")).write_bytes(payload)
    path = directory / "manifest.json"
    path.write_bytes(canonical(document))
    return {"path": path, "document": document, "sha": sha(path.read_bytes())}


def repin(fixture):
    fixture["path"].write_bytes(canonical(fixture["document"]))
    fixture["sha"] = sha(fixture["path"].read_bytes())


def run(cli, fixture, *, output_path=None):
    return cli.run(manifest_path=fixture["path"], expected_manifest_sha256=fixture["sha"], output_path=output_path)


def arguments(fixture):
    return ["--manifest", str(fixture["path"]), "--manifest-sha256", fixture["sha"]]


def inventory(directory):
    return {path.name: (path.read_bytes(), path.stat().st_mode & 0o777)
            for path in directory.iterdir() if path.is_file()}


def test_actual_bytes_parse_deterministically_with_default_read_only_and_no_authority(cli, tmp_path):
    fixture = package(tmp_path)
    before = inventory(fixture["path"].parent)
    report = run(cli, fixture)
    assert report == run(cli, fixture)
    assert report["status"] == report["parse_result"]["status"] == "parsed"
    assert report["parse_result"]["files"] == {
        "input_sha256": sha(SYNTHETIC_INPUT), "frequency_sha256": sha(SYNTHETIC_FREQUENCY)}
    assert report["parse_result"]["spectrum"]["mode_count"] == 3
    assert report["parse_result"]["spectrum"]["qpoint_count"] == 1
    assert report["package_sha256"] == fixture["sha"]
    assert report["source_code_sha256"] and all(
        value == sha((ROOT / name).read_bytes()) for name, value in report["source_code_sha256"].items())
    assert report["coverage"] == {"packages_seen": 1, "packages_parsed": 1, "packages_quarantined": 0,
        "property_candidates": len(report["parse_result"]["property_candidates"]),
        "scientifically_accepted_properties": 0, "ml_admitted_properties": 0}
    for field in ("calculation_cpu_seconds", "calculation_wall_seconds", "calculation_monetary_cost", "import_elapsed_seconds"):
        assert report["costs"][field] is None
    assert report["authority"] and all(value is False for value in report["authority"].values())
    assert report["authority"]["ml_training_approved"] is False
    assert report["context_declarations"] == fixture["document"]["context"]
    assert inventory(fixture["path"].parent) == before
    assert {path.name for path in tmp_path.iterdir()} == {"synthetic-package"}


def test_output_is_exact_report_immutable_owner_only_and_does_not_rewrite_input(cli, tmp_path):
    fixture = package(tmp_path)
    before = inventory(fixture["path"].parent)
    expected = run(cli, fixture)
    output = tmp_path.resolve() / "report.json"
    assert run(cli, fixture, output_path=output) == expected
    assert output.read_bytes() == canonical(expected)
    assert output.stat().st_mode & 0o777 == 0o600
    assert inventory(fixture["path"].parent) == before
    with pytest.raises((ValueError, OSError)):
        run(cli, fixture, output_path=output)
    assert output.read_bytes() == canonical(expected)
    assert not any(path.name.startswith(".") for path in tmp_path.iterdir())


def test_quarantined_parse_can_write_a_report_but_never_claims_scientific_admission(cli, tmp_path, capsys):
    fixture = package(tmp_path, frequency=b"SYNTHETIC_PRIVATE_UNPARSEABLE_OUTPUT\n")
    output = tmp_path.resolve() / "quarantined.json"
    code = cli.main([*arguments(fixture), "--output", str(output)])
    captured = capsys.readouterr()
    assert code == 3 and captured.err == ""
    summary, report = json.loads(captured.out), json.loads(output.read_bytes())
    assert summary["status"] == report["status"] == "quarantined"
    assert summary["report_sha256"] == sha(output.read_bytes())
    assert summary["output_written"] is True
    assert report["coverage"] == {"packages_seen": 1, "packages_parsed": 0, "packages_quarantined": 1,
        "property_candidates": 0, "scientifically_accepted_properties": 0, "ml_admitted_properties": 0}
    assert "SYNTHETIC_PRIVATE" not in captured.out
    assert all(value is False for value in report["authority"].values())


def test_matdyn_output_logical_name_mismatch_is_quarantined_not_silently_associated(cli, tmp_path):
    fixture = package(tmp_path)
    fixture["document"]["files"][1]["logical_name"] = "another-output.freq"
    repin(fixture)
    report = run(cli, fixture)
    assert report["status"] == "quarantined"
    assert all(value is False for value in report["authority"].values())


def test_renamed_original_input_capsule_cannot_become_output_directory(cli, tmp_path, monkeypatch):
    fixture = package(tmp_path)
    source = fixture["path"].parent
    before = inventory(source)
    renamed = tmp_path.resolve() / "renamed-source"
    writer = cli.write_new_report

    def rename_before_write(*args, **kwargs):
        source.rename(renamed)
        source.mkdir()
        return writer(*args, **kwargs)

    monkeypatch.setattr(cli, "write_new_report", rename_before_write)
    with pytest.raises(ValueError, match="report_cannot_modify_input_capsule"):
        run(cli, fixture, output_path=renamed / "report.json")
    assert inventory(renamed) == before
    assert list(source.iterdir()) == []


def test_nonbulk_declaration_does_not_gain_bulk_scientific_meaning_from_a_parse(cli, tmp_path):
    fixture = package(tmp_path)
    fixture["document"]["context"]["geometry_scope"] = "other"
    repin(fixture)
    report = run(cli, fixture)
    assert report["parse_result"]["status"] == "parsed"
    assert report["status"] == "quarantined"
    assert "nonbulk_context_declared" in report["reason_codes"]
    assert report["coverage"]["packages_seen"] == report["coverage"]["packages_quarantined"] == 1
    assert report["coverage"]["scientifically_accepted_properties"] == report["coverage"]["ml_admitted_properties"] == 0


@pytest.mark.parametrize("pin", [None, "", "0" * 64, "A" * 64, True, 123])
def test_independent_complete_manifest_pin_required(cli, tmp_path, pin):
    fixture = package(tmp_path)
    before = inventory(fixture["path"].parent)
    with pytest.raises((ValueError, TypeError)):
        cli.run(manifest_path=fixture["path"], expected_manifest_sha256=pin)
    assert inventory(fixture["path"].parent) == before


@pytest.mark.parametrize("payload", [
    b'{"version":"x","version":"y"}', b'{"bad":NaN}', b'{"bad":Infinity}',
    b'{"bad":1e999}', b'{"bad":"\\ud800"}', b'{"bad":"\xff"}', b'[]', b'{',
])
def test_ambiguous_nonfinite_or_nonobject_json_rejected_even_with_fresh_pin(cli, tmp_path, payload):
    fixture = package(tmp_path)
    fixture["path"].write_bytes(payload)
    fixture["sha"] = sha(payload)
    with pytest.raises((ValueError, TypeError)):
        run(cli, fixture)


@pytest.mark.parametrize("style", ["newline", "pretty"])
def test_manifest_must_be_exact_canonical_bytes(cli, tmp_path, style):
    fixture = package(tmp_path)
    raw = canonical(fixture["document"]) + b"\n" if style == "newline" else json.dumps(fixture["document"], indent=2).encode()
    fixture["path"].write_bytes(raw)
    fixture["sha"] = sha(raw)
    with pytest.raises(ValueError):
        run(cli, fixture)


@pytest.mark.parametrize("change", ["extra_top", "extra_context", "missing_context", "extra_file", "size_bool",
    "size_float", "wrong_size", "missing_frequency_role", "unsupported_adapter", "approved", "attested_zero", "training_true"])
def test_manifest_is_closed_typed_and_never_confers_review_execution_or_training(cli, tmp_path, change):
    fixture = package(tmp_path)
    document = fixture["document"]
    if change == "extra_top": document["scientific_acceptance"] = True
    elif change == "extra_context": document["context"]["inferred_structure_id"] = "FAKE"
    elif change == "missing_context": document["context"].pop("material_formula")
    elif change == "extra_file": document["files"][0]["path"] = "PRIVATE_SOURCE_PATH"
    elif change == "size_bool": document["files"][0]["size_bytes"] = True
    elif change == "size_float": document["files"][0]["size_bytes"] = float(len(SYNTHETIC_INPUT))
    elif change == "wrong_size": document["files"][0]["size_bytes"] += 1
    elif change == "missing_frequency_role": document["files"][1]["role"] = "license"
    elif change == "unsupported_adapter": document["adapter_id"] = "guess-any-science"
    elif change == "approved": document["declarations"]["review_status"] = "approved"
    elif change == "attested_zero": document["declarations"]["execution_attested"] = 0
    else: document["declarations"]["ml_training_approved"] = True
    repin(fixture)
    with pytest.raises((ValueError, TypeError)):
        run(cli, fixture)


@pytest.mark.parametrize("change", ["missing", "changed", "undeclared_hash_leaf", "unexpected_name"])
def test_exact_complete_declared_file_inventory_and_payload_hashes(cli, tmp_path, change):
    fixture = package(tmp_path)
    leaf = fixture["path"].parent / (sha(SYNTHETIC_FREQUENCY) + ".bin")
    if change == "missing": leaf.unlink()
    elif change == "changed": leaf.write_bytes(b"PRIVATE_CHANGED_BYTES")
    else:
        extra = b"UNDECLARED_PRIVATE_BYTES"
        name = sha(extra) + ".bin" if change == "undeclared_hash_leaf" else "private-source.txt"
        (fixture["path"].parent / name).write_bytes(extra)
    with pytest.raises((ValueError, OSError)):
        run(cli, fixture)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "directory"])
def test_hash_named_leaves_cannot_be_aliases_or_nonregular_files(cli, tmp_path, kind):
    fixture = package(tmp_path)
    leaf = fixture["path"].parent / (sha(SYNTHETIC_FREQUENCY) + ".bin")
    original = tmp_path.resolve() / "private-real-source"
    original.write_bytes(leaf.read_bytes())
    leaf.unlink()
    if kind == "symlink": leaf.symlink_to(original)
    elif kind == "hardlink": os.link(original, leaf)
    elif kind == "fifo": os.mkfifo(leaf)
    else: leaf.mkdir()
    with pytest.raises((ValueError, OSError)):
        run(cli, fixture)


@pytest.mark.parametrize("kind", ["symlink_parent", "traversal", "relative"])
def test_input_path_has_nonalias_absolute_ancestors(cli, tmp_path, kind):
    fixture = package(tmp_path)
    if kind == "symlink_parent":
        alias = tmp_path.resolve() / "alias"
        alias.symlink_to(fixture["path"].parent, target_is_directory=True)
        fixture["path"] = alias / "manifest.json"
    elif kind == "traversal":
        fixture["path"] = fixture["path"].parent / ".." / "synthetic-package" / "manifest.json"
    else:
        fixture["path"] = Path(os.path.relpath(fixture["path"]))
    with pytest.raises((ValueError, OSError)):
        run(cli, fixture)


@pytest.mark.parametrize("limit", ["MAX_MANIFEST_BYTES", "MAX_FILE_BYTES", "MAX_PACKAGE_BYTES", "MAX_FILES"])
def test_limits_reject_without_publishing_partial_report(cli, tmp_path, monkeypatch, limit):
    fixture = package(tmp_path)
    output = tmp_path.resolve() / "must-not-exist.json"
    monkeypatch.setattr(cli, limit, 1)
    with pytest.raises((ValueError, OSError)):
        run(cli, fixture, output_path=output)
    assert not output.exists()


def test_seventeen_entries_are_not_silently_sampled(cli, tmp_path):
    extras = [("provenance", f"synthetic-{number}.txt", f"Synthetic provenance {number}".encode()) for number in range(15)]
    fixture = package(tmp_path, extra_files=extras)
    with pytest.raises(ValueError):
        run(cli, fixture)


def test_full_sixteen_file_package_retains_unreviewed_optional_documents(cli, tmp_path):
    extras = [("license" if number == 0 else "provenance", f"synthetic-{number}.txt",
               f"Synthetic unreviewed auxiliary bytes {number}".encode()) for number in range(14)]
    fixture = package(tmp_path, extra_files=extras)
    before = inventory(fixture["path"].parent)
    report = run(cli, fixture)
    assert report["status"] == "parsed" and len(report["inventory"]) == 16
    assert report["context_declarations"]["license_spdx"] is None
    assert report["authority"]["redistribution_authorized"] is False
    assert inventory(fixture["path"].parent) == before


@pytest.mark.parametrize("url", ["file:///PRIVATE_PATH", "http://example.invalid/PRIVATE", "https://user:PRIVATE@example.invalid/"])
def test_untrusted_source_uri_cannot_request_local_files_or_include_credentials(cli, tmp_path, capsys, url):
    fixture = package(tmp_path)
    fixture["document"]["context"]["source_url"] = url
    repin(fixture)
    assert cli.main(arguments(fixture)) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["status"] == "invalid"
    assert "PRIVATE" not in output.err and str(fixture["path"]) not in output.err


def test_second_read_detects_real_file_drift_before_output(cli, tmp_path, monkeypatch):
    fixture = package(tmp_path)
    original, calls = cli.capture_package, []
    def changed(path):
        value = original(path)
        calls.append(True)
        if len(calls) == 1:
            leaf = fixture["path"].parent / (sha(SYNTHETIC_FREQUENCY) + ".bin")
            leaf.write_bytes(SYNTHETIC_FREQUENCY.replace(b"2.0000", b"3.0000"))
        return value
    monkeypatch.setattr(cli, "capture_package", changed)
    output = tmp_path.resolve() / "must-not-exist.json"
    with pytest.raises(ValueError):
        run(cli, fixture, output_path=output)
    assert len(calls) == 2
    assert not output.exists()


@pytest.mark.parametrize("changed_part", ["bytes", "signature"])
def test_second_capture_comparison_checks_both_bytes_and_file_identity(cli, tmp_path, monkeypatch, changed_part):
    fixture = package(tmp_path)
    original, calls = cli.capture_package, []
    def changed(path):
        values, signatures = original(path)
        calls.append(True)
        if len(calls) == 2:
            if changed_part == "bytes": values = {**values, "manifest.json": values["manifest.json"] + b" "}
            else: signatures = {**signatures, "manifest.json": ("changed-inode",)}
        return values, signatures
    monkeypatch.setattr(cli, "capture_package", changed)
    with pytest.raises(ValueError):
        run(cli, fixture)
    assert len(calls) == 2


@pytest.mark.parametrize("name", ["report.json", "manifest.json"])
def test_output_cannot_modify_closed_input_package(cli, tmp_path, name):
    fixture = package(tmp_path)
    before = inventory(fixture["path"].parent)
    with pytest.raises((ValueError, OSError)):
        run(cli, fixture, output_path=fixture["path"].parent / name)
    assert inventory(fixture["path"].parent) == before


def test_output_alias_does_not_overwrite_private_file(cli, tmp_path):
    fixture = package(tmp_path)
    original, output = tmp_path.resolve() / "private.json", tmp_path.resolve() / "report.json"
    original.write_bytes(b"PRIVATE_EXISTING_CONTENT")
    output.symlink_to(original)
    with pytest.raises((ValueError, OSError)):
        run(cli, fixture, output_path=output)
    assert original.read_bytes() == b"PRIVATE_EXISTING_CONTENT"


def test_output_parent_alias_is_rejected_without_writing(cli, tmp_path):
    fixture = package(tmp_path)
    actual = tmp_path.resolve() / "actual-output-directory"
    actual.mkdir()
    alias = tmp_path.resolve() / "alias-output-directory"
    alias.symlink_to(actual, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        run(cli, fixture, output_path=alias / "report.json")
    assert list(actual.iterdir()) == []


def test_cli_summary_is_metadata_only_and_invalid_error_is_sanitized(cli, tmp_path, capsys):
    fixture = package(tmp_path)
    assert cli.main(arguments(fixture)) == 0
    result = capsys.readouterr()
    summary = json.loads(result.out)
    assert set(summary) == {"status", "report_sha256", "output_written", "authority"}
    assert summary["status"] == "parsed" and summary["output_written"] is False
    assert summary["report_sha256"] == sha(canonical(run(cli, fixture)))
    assert result.err == ""
    assert cli.main(["--manifest", "PRIVATE_SOURCE_PATH"]) == 2
    result = capsys.readouterr()
    assert result.out == "" and json.loads(result.err)["status"] == "invalid"
    assert "PRIVATE_SOURCE_PATH" not in result.err


@pytest.mark.parametrize("case", ["missing_file", "private_invalid_json"])
def test_complete_cli_requests_sanitize_file_and_raw_document_failures(cli, tmp_path, capsys, case):
    fixture = package(tmp_path)
    if case == "missing_file":
        fixture["path"] = tmp_path.resolve() / "PRIVATE_MISSING_PATH" / "manifest.json"
    else:
        payload = b'{"PRIVATE_RAW_SOURCE_TEXT":NaN}'
        fixture["path"].write_bytes(payload)
        fixture["sha"] = sha(payload)
    assert cli.main(arguments(fixture)) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err) == {"status": "invalid", "output_written": False}
    assert "PRIVATE" not in output.err and str(tmp_path.resolve()) not in output.err


def test_no_network_calls_and_declared_source_url_is_not_fetched(cli, tmp_path, monkeypatch):
    fixture = package(tmp_path)
    fixture["document"]["context"]["source_url"] = "https://example.invalid/PRIVATE_SOURCE_PATH"
    repin(fixture)
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Offline preflight attempted network I/O")
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    assert run(cli, fixture)["status"] == "parsed"


def test_actual_subprocess_is_offline_and_independent_of_database_environment(cli, tmp_path):
    fixture = package(tmp_path)
    code = """
import importlib.abc, json, socket, sys
class NoDatabase(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {'models.db', 'config', 'sqlalchemy', 'asyncpg', 'psycopg', 'psycopg2'}:
            raise AssertionError('Offline preflight imported database/config runtime')
def no_network(*args, **kwargs):
    raise AssertionError('Offline preflight attempted network')
sys.meta_path.insert(0, NoDatabase())
socket.socket = socket.create_connection = no_network
from scripts.scientific_program_preflight import main
raise SystemExit(main(sys.argv[1:]))
"""
    env = {**os.environ, "DATABASE_URL": "not-a-database-url:PRIVATE_ENV", "REDIS_URL": "not-a-redis-url:PRIVATE_ENV",
           "GOOGLE_APPLICATION_CREDENTIALS": "/PRIVATE_DO_NOT_READ/credentials.json"}
    result = subprocess.run([sys.executable, "-c", code, *arguments(fixture)], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["status"] == "parsed" and summary["output_written"] is False
    assert result.stderr == "" and "PRIVATE_" not in result.stdout
