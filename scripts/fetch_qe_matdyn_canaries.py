#!/usr/bin/env python3
"""Explicitly fetch three pinned upstream QE reference-format canaries.

This command alone performs network I/O. It downloads seven allowlisted files,
never executes upstream scripts, never accesses a database, and writes new
owner-only capsules. These are upstream reference files, not attested new
calculations, independently reviewed science, or authorized public releases.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import stat
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

COMMIT = "770a0b2d12928a67048e2f3da8d10d057e52179e"
RAW_BASE = "https://raw.githubusercontent.com/QEF/q-e/" + COMMIT + "/"
MAX_DOWNLOAD_BYTES = 128 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 15
UPSTREAM_FILES = (
    ("License", "204d8eff92f95aac4df6c8122bc1505f468f3a901e5a4cc08940e0ede1938994"),
    ("PHonon/examples/example14/run_example", "50adcdc624018a8cc892d15246fdcce3a860d1df1cb4cf4ae8680e593f62dd4e"),
    ("PHonon/examples/example14/reference/al.freq", "ea63aef65be50e4a69ec6e8418b0c9d02c550b80837097d52c9a58b80f60a284"),
    ("PHonon/examples/GRID_recover_example/run_example", "5af2c411fbe5e523fe3600d04ccbbbcdf4de279d19f9cc169d8194002b5f3f3f"),
    ("PHonon/examples/GRID_recover_example/reference/alas.freq", "942744cf2cb3f74e703f7a271576bec4c4f006dd101e15153b704276e97e24a2"),
    ("PHonon/examples/example17/reference/matdyn.in", "322c7d3977062ba549e18966ba0e7b554b3c354f07b12fbdc65e89d2a4875ecd"),
    ("PHonon/examples/example17/reference/bn.freq", "b9b6ee8dfa04fbeccde442a3c68b38fe598c92497921ae2e4aaa684269621ece"),
)
_PACKAGES = (
    ("al-example14", "Al", "bulk_3d", "PHonon/examples/example14", "al.freq", True),
    ("alas-grid-recover", "AlAs", "bulk_3d", "PHonon/examples/GRID_recover_example", "alas.freq", True),
    ("bn-example17-2d", "BN", "other", "PHonon/examples/example17", "bn.freq", False),
)


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def _authority():
    return {key: False for key in ("execution_attested", "scientific_accepted", "ml_training_approved",
                                  "redistribution_authorized", "public_release", "database_changed")}


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("upstream_redirect_rejected")


def download_reference(path):
    """Fetch one exact allowlisted URL; fail closed before following redirects.

    The socket operation timeout is 15 seconds. An additional elapsed deadline
    rejects a slow completed response; this is not cancellation of an in-flight
    socket operation. No environment proxy or alternate URL is accepted.
    """
    pins = dict(UPSTREAM_FILES)
    _require(type(path) is str and path in pins, "upstream_path_not_allowed")
    url = RAW_BASE + path
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirects())
    request = urllib.request.Request(url, method="GET", headers={
        "Accept": "application/octet-stream", "Accept-Encoding": "identity",
        "User-Agent": "SCLib-pinned-reference-canary/1.0.0"})
    started = time.monotonic()
    with opener.open(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
        _require(response.status == 200 and response.geturl() == url, "upstream_response_rejected")
        _require(response.headers.get("Content-Encoding", "identity").lower() == "identity",
                 "upstream_encoding_rejected")
        length = response.headers.get("Content-Length")
        if length is not None:
            _require(type(length) is str and re.fullmatch(r"[0-9]{1,10}", length)
                     and 0 < int(length) <= MAX_DOWNLOAD_BYTES, "upstream_byte_limit")
        chunks, size = [], 0
        while True:
            _require(time.monotonic() - started <= DOWNLOAD_TIMEOUT_SECONDS, "upstream_deadline_exceeded")
            chunk = response.read(min(65536, MAX_DOWNLOAD_BYTES - size + 1))
            _require(type(chunk) is bytes, "upstream_response_rejected")
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            _require(size <= MAX_DOWNLOAD_BYTES, "upstream_byte_limit")
        _require(time.monotonic() - started <= DOWNLOAD_TIMEOUT_SECONDS, "upstream_deadline_exceeded")
        _require(size > 0 and (length is None or int(length) == size), "upstream_length_mismatch")
    payload = b"".join(chunks)
    _require(sha(payload) == pins[path], "upstream_hash_mismatch")
    return payload


def derive_matdyn_input(script, *, substitute_alas_prefix=False):
    """Extract a reviewed literal heredoc, not a shell interpreter.

    All offsets are zero-based byte offsets into the retained original script;
    end offsets are exclusive. No shell command or interpolation is evaluated.
    """
    _require(type(script) is bytes and 0 < len(script) <= MAX_DOWNLOAD_BYTES, "invalid_reference_script")
    command = list(re.finditer(rb"(?m)^[ \t]*cat[ \t]+>[ \t]*matdyn\.in[ \t]+<<EOF[ \t]*\r?\n", script))
    _require(len(command) == 1, "unique_reviewed_matdyn_heredoc_required")
    start = command[0].end()
    ending = re.search(rb"(?m)^EOF[ \t]*(?:\r?\n|$)", script[start:])
    _require(ending is not None, "matdyn_heredoc_terminator_missing")
    end = start + ending.start()
    original = script[start:end]
    _require(original and b"`" not in original and b"\\" not in original,
             "unreviewed_heredoc_interpolation")
    replacements, assignment = [], None
    derived = original
    if substitute_alas_prefix:
        assignments = list(re.finditer(rb"(?m)^[ \t]*(?:export[ \t]+)?PREFIX=[^\r\n]*", script))
        _require(len(assignments) == 1 and re.fullmatch(rb"[ \t]*PREFIX='alas'[ \t]*", assignments[0].group())
                 and assignments[0].end() < command[0].start(), "reviewed_alas_prefix_assignment_required")
        assignment = {"source_byte_start": assignments[0].start(), "source_byte_end": assignments[0].end(),
                      "raw_text": assignments[0].group().decode("ascii"), "value": "alas"}
        matches = list(re.finditer(rb"\$PREFIX(?![A-Za-z0-9_])", original))
        _require(len(matches) == 2, "reviewed_alas_prefix_uses_required")
        for match in matches:
            replacements.append({"source_byte_start": start + match.start(),
                                 "source_byte_end": start + match.end(), "from": "$PREFIX", "to": "alas"})
        # Replace only the exact tokens recorded above. A broader bytes.replace
        # would silently consume an unreviewed $PREFIX_SUFFIX alongside them.
        derived = re.sub(rb"\$PREFIX(?![A-Za-z0-9_])", b"alas", original)
    _require(b"$" not in derived, "unreviewed_heredoc_interpolation")
    return derived, {
        "kind": "heredoc_with_reviewed_prefix_substitution" if substitute_alas_prefix else "literal_heredoc",
        "input_derived": True, "source_byte_start": start, "source_byte_end": end,
        "source_span_sha256": sha(original), "input_sha256": sha(derived),
        "prefix_assignment": assignment, "replacements": replacements,
    }


def build_packages(downloaded):
    """Pure deterministic capsules from exactly the seven pinned byte objects."""
    _require(type(downloaded) is dict and set(downloaded) == {path for path, _ in UPSTREAM_FILES},
             "exact_upstream_inventory_required")
    for path, expected in UPSTREAM_FILES:
        value = downloaded[path]
        _require(type(value) is bytes and 0 < len(value) <= MAX_DOWNLOAD_BYTES and sha(value) == expected,
                 "upstream_hash_mismatch")
    result = []
    for name, formula, geometry, base, frequency_name, derived in _PACKAGES:
        input_path = base + ("/run_example" if derived else "/reference/matdyn.in")
        frequency_path = base + "/reference/" + frequency_name
        raw = downloaded[input_path]
        if derived:
            input_bytes, derivation = derive_matdyn_input(raw, substitute_alas_prefix=formula == "AlAs")
        else:
            input_bytes = raw
            derivation = {"kind": "upstream_file", "input_derived": False, "source_byte_start": 0,
                          "source_byte_end": len(raw), "source_span_sha256": sha(raw),
                          "input_sha256": sha(raw), "prefix_assignment": None, "replacements": []}
        derivation.update(source_path=input_path, source_sha256=sha(raw))
        provenance = {
            "version": "qe-reference-canary-provenance/1.0.0", "repository": "https://github.com/QEF/q-e",
            "commit": COMMIT, "classification": "real_upstream_reference_format_canary",
            "input_derivation": derivation,
            "sources": [{"path": path, "url": RAW_BASE + path, "sha256": sha(downloaded[path]),
                         "size_bytes": len(downloaded[path])} for path in (input_path, frequency_path, "License")],
            "license_declaration": {"license_spdx": None, "rights_reviewed": False,
                                    "note": "Original upstream License bytes retained; no SPDX or redistribution adjudication."},
            "authority": _authority(),
        }
        items = [("input", "matdyn.in", input_bytes),
                 ("frequency", frequency_name, downloaded[frequency_path]),
                 ("license", "License", downloaded["License"]),
                 ("provenance", "derivation.json", canonical(provenance))]
        if derived:
            items.append(("provenance", "upstream-run_example.txt", raw))
        manifest = {
            "version": "scientific-program-package/1.0.0", "adapter_id": "qe-matdyn-flfrq",
            "files": [{"role": role, "logical_name": logical, "sha256": sha(payload), "size_bytes": len(payload)}
                      for role, logical, payload in items],
            "context": {"material_formula": formula, "material_id": None, "geometry_scope": geometry,
                        "source_url": "https://github.com/QEF/q-e/tree/" + COMMIT + "/" + base,
                        "source_revision": COMMIT, "license_spdx": None},
            "declarations": {"review_status": "unreviewed", "execution_attested": False, "ml_training_approved": False},
        }
        files = {sha(payload) + ".bin": payload for _, _, payload in items}
        files["manifest.json"] = canonical(manifest)
        result.append({"id": name, "input_derived": derived, "files": files,
                       "manifest_sha256": sha(files["manifest.json"])})
    return result


def _directory_fd(path):
    _require(path.is_absolute() and ".." not in path.parts, "absolute_non_traversing_parent_required")
    descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _identity(info):
    return info.st_dev, info.st_ino


def _check_directory(path, descriptor):
    current = _directory_fd(path)
    try:
        _require(_identity(os.fstat(current)) == _identity(os.fstat(descriptor)), "output_directory_changed")
    finally:
        os.close(current)


def _write_new(directory, name, payload):
    descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
    try:
        os.fchmod(descriptor, 0o600)
        remaining = memoryview(payload)
        while remaining:
            count = os.write(descriptor, remaining)
            _require(count > 0, "output_write_failed")
            remaining = remaining[count:]
        os.fsync(descriptor)
        info = os.fstat(descriptor)
        _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size == len(payload)
                 and stat.S_IMODE(info.st_mode) == 0o600, "output_file_changed")
        return _identity(info)
    finally:
        os.close(descriptor)


def _check_files(directory, files, identities):
    _require(set(os.listdir(directory)) == set(files), "output_inventory_changed")
    for name, payload in files.items():
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            info = os.fstat(descriptor)
            _require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1
                     and _identity(info) == identities[name] and info.st_size == len(payload), "output_file_changed")
            chunks, size = [], 0
            while size <= len(payload):
                chunk = os.read(descriptor, min(65536, len(payload) - size + 1))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            _require(b"".join(chunks) == payload, "output_file_changed")
        finally:
            os.close(descriptor)


def _create_directory(parent, name):
    os.mkdir(name, 0o700, dir_fd=parent)
    before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    try:
        after = os.fstat(descriptor)
        _require(_identity(before) == _identity(after) and stat.S_IMODE(after.st_mode) == 0o700
                 and after.st_uid == os.geteuid(), "new_output_directory_changed")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _new_directory(parent):
    for _ in range(5):
        name = "qe-matdyn-canaries-" + uuid4().hex
        try:
            return name, _create_directory(parent, name)
        except FileExistsError:
            continue
    raise ValueError("fresh_output_directory_unavailable")


def run(*, output_parent):
    """Explicit network entry point; no writes occur before all downloads verify.

    On a failed write, a partial *new* private directory may remain for operator
    inspection. Never recursively delete or overwrite existing user data.
    """
    path = Path(output_parent)
    parent = _directory_fd(path)
    try:
        downloaded = {name: download_reference(name) for name, _ in UPSTREAM_FILES}
        packages = build_packages(downloaded)
        _check_directory(path, parent)
        name, root = _new_directory(parent)
        try:
            opened, summaries = [], []
            try:
                for package in packages:
                    directory = _create_directory(root, package["id"])
                    opened.append((package, directory))
                    identities = {leaf: _write_new(directory, leaf, data) for leaf, data in package["files"].items()}
                    package["identities"] = identities
                    summaries.append({"id": package["id"], "manifest_path": str(path / name / package["id"] / "manifest.json"),
                                      "manifest_sha256": package["manifest_sha256"], "input_derived": package["input_derived"],
                                      "file_count": len(package["files"]) - 1})
                _require(set(os.listdir(root)) == {package["id"] for package in packages}, "output_inventory_changed")
                for package, directory in opened:
                    _check_directory(path / name / package["id"], directory)
                    _check_files(directory, package["files"], package["identities"])
                    _require(stat.S_IMODE(os.fstat(directory).st_mode) == 0o700
                             and os.fstat(directory).st_uid == os.geteuid(), "output_directory_permissions_changed")
                _check_directory(path / name, root)
                _require(stat.S_IMODE(os.fstat(root).st_mode) == 0o700 and os.fstat(root).st_uid == os.geteuid(),
                         "output_directory_permissions_changed")
                _check_directory(path, parent)
            finally:
                for _, descriptor in opened:
                    os.close(descriptor)
        finally:
            os.close(root)
    finally:
        os.close(parent)
    return {"version": "qe-reference-canary-fetch/1.0.0", "status": "fetched",
            "classification": "real_upstream_reference_format_canaries_not_verified_new_executions",
            "commit": COMMIT, "directory": str(path / name), "packages": summaries, "authority": _authority()}


class _SafeParser(argparse.ArgumentParser):
    def error(self, _message):
        raise ValueError("invalid_arguments")


def main(argv=None):
    parser = _SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--output-parent", required=True)
    try:
        args = parser.parse_args(argv)
        result = run(output_parent=args.output_parent)
    except (ValueError, OSError, TypeError, OverflowError, urllib.error.URLError, http.client.HTTPException):
        print('{"status":"failed","complete_capsules_reported":false}', file=sys.stderr)
        return 2
    print(canonical(result).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
