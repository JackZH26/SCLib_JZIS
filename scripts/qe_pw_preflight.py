#!/usr/bin/env python3
"""Read original QE files into a new private report; never run or upload files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from services.qe_pw_import import MAX_OUTPUT_BYTES, MAX_UPF_BYTES, preflight_pw  # noqa: E402
from services.qe_pw_input import MAX_INPUT_BYTES, QePwImportError, require  # noqa: E402


def capture(path, limit):
    """One explicit local regular file, with no symlink or changing-file fallback."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= limit, "qe_local_file_bound")
        chunks, size = [], 0
        while True:
            chunk = os.read(fd, min(65536, limit - size + 1))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            require(size <= limit, "qe_local_file_bound")
        after = os.fstat(fd)

        def signature(s):
            return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns

        require(
            signature(before) == signature(after) and size == before.st_size,
            "qe_local_file_changed",
        )
        return b"".join(chunks)
    finally:
        os.close(fd)


def write_report(path, report):
    """Atomically create owner-only bytes; never replace an existing path."""
    output = Path(path)
    payload = (
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()
    fd, temporary = tempfile.mkstemp(prefix=".qe-preflight-", dir=output.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, output, follow_symlinks=False)
    finally:
        os.unlink(temporary)
    return hashlib.sha256(payload).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--xml", type=Path, required=True)
    parser.add_argument("--stdout", type=Path, required=True)
    parser.add_argument("--upf", type=Path, required=True, action="append")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        require(
            1 <= len(args.upf) <= 8 and len({path.name for path in args.upf}) == len(args.upf),
            "qe_upf_inventory_bound",
        )
        report = preflight_pw(
            input_bytes=capture(args.input, MAX_INPUT_BYTES),
            xml_bytes=capture(args.xml, MAX_OUTPUT_BYTES),
            stdout_bytes=capture(args.stdout, MAX_OUTPUT_BYTES),
            pseudopotentials={path.name: capture(path, MAX_UPF_BYTES) for path in args.upf},
        )
        digest = write_report(args.output, report)
    except (QePwImportError, OSError) as error:
        print(
            str(error)
            if isinstance(error, QePwImportError)
            else "qe_local_capture_or_report_write_failed",
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps({"status": report["status"], "report_sha256": digest, "database_write": False})
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
