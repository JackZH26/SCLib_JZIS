#!/usr/bin/env python3
"""Explicit download of two exact QE force-constant reference sidecars.

No upstream executable is run. A new private directory retains complete source
bytes and their retrieval inventory, not a per-file redistribution permission or
an attestation that they produced a frequency file. No Al example14 FC exists
in the reviewed reference inventory; no substitute is downloaded for that case.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import urllib.request
from pathlib import Path

COMMIT = "770a0b2d12928a67048e2f3da8d10d057e52179e"
REFERENCES = (
    ("PHonon/examples/GRID_recover_example/reference/alas.444.fc", 77388,
     "b683e6fa7b6182c25ed5a25ee61038f10841d5e4827b7c6396a33b6ca4cc2047"),
    ("PHonon/examples/example17/reference/bn881.fc", 77384,
     "34945d97a3458ea6833df66485feb4ab09e6c9b65f022e99ff7387dae87e3bde"),
)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise ValueError("reference_redirect_rejected")


def fetch(reference):
    if reference not in REFERENCES:
        raise ValueError("reference_not_allowlisted")
    path, size, checksum = reference
    url = f"https://raw.githubusercontent.com/QEF/q-e/{COMMIT}/{path}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(url, headers={"Accept-Encoding": "identity"})
    with opener.open(request, timeout=15) as response:
        if (response.status != 200 or response.geturl() != url
                or response.headers.get("Content-Encoding", "identity").lower() != "identity"):
            raise ValueError("reference_response_rejected")
        payload = response.read(size + 1)
    if len(payload) != size or hashlib.sha256(payload).hexdigest() != checksum:
        raise ValueError("reference_bytes_mismatch")
    return payload


def run(parent):
    # Fetch and verify before creating any files. Socket timeout is bounded per
    # operation, not a guarantee of total wall time for a slow remote sender.
    captured = [(reference, fetch(reference)) for reference in REFERENCES]
    directory = Path(tempfile.mkdtemp(prefix="qe-force-constants-", dir=Path(parent).resolve(strict=True)))
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        def write(name, payload):
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=descriptor)
            with os.fdopen(fd, "wb") as output:
                output.write(payload)
        for (_, _, checksum), payload in captured:
            write(checksum + ".bin", payload)
        receipt = {"version": "qe-fc-reference-capture/1.0.0", "commit": COMMIT,
            "files": [{"repository_path": path, "size_bytes": size, "sha256": checksum}
                      for path, size, checksum in REFERENCES],
            "execution_attested": False, "scientific_accepted": False, "redistribution_authorized": False}
        write("capture.json", json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode())
    finally:
        os.close(descriptor)
    return directory


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args.parent)
    except (OSError, ValueError):
        parser.exit(2, "Reference capture failed; no source path or response contents disclosed.\n")
    print(result)
