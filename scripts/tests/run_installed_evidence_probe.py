"""CI-only synthetic wheel check; never reads real scientific input or a service.

Run from the repository root with the locked test interpreter, after explicitly
building/installing a wheel into a new dependency-free environment. The installed
interpreter is isolated and runs from an owned empty directory. This driver uses
the existing synthetic fixtures; it is not an application or intake CLI.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import tempfile
from pathlib import Path

from services import ml_pilot_evidence_worker as worker

from scripts.tests.test_ml_pilot_evidence_worker import fixture, frame

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "scripts/probe_ml_pilot_evidence_install.py"
ENV = {"LANG": "C.UTF-8", "PYTHONHASHSEED": "0"}
NOTICE = "synthetic_installed_byte_replay_not_scientific_acceptance"
IDENTITY = """
import importlib.metadata as m, json, pathlib, sys
d = m.distribution('sclib-api')
print(json.dumps({'isolated': sys.flags.isolated,
 'prefix': str(pathlib.Path(sys.prefix).resolve()),
 'python': sys.version,
 'direct_url': json.loads(d.read_text('direct_url.json')),
 'distributions': sorted(x.metadata['Name'].lower() for x in m.distributions())}))
"""


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def invoke(python, args, cwd, raw=b""):
    return subprocess.run(
        [str(python), "-I", "-B", *args],
        input=raw,
        capture_output=True,
        cwd=cwd,
        env=ENV,
        timeout=70,
        check=False,
    )


def parsed(result):
    if result.returncode or result.stderr or not 0 < len(result.stdout) <= 2**20:
        raise ValueError("installed_evidence_probe_failed")
    return json.loads(result.stdout)


def check_identity(value, python, wheel, wheel_sha256):
    direct = value["direct_url"]
    if (
        value["isolated"] != 1
        or value["prefix"] != str(python.parent.parent.resolve())
        or direct.get("url") != wheel.as_uri()
        or direct.get("archive_info", {}).get("hashes", {}).get("sha256")
        != wheel_sha256
        or "sclib-api" not in value["distributions"]
        or set(value["distributions"]) - {"sclib-api", "pip", "setuptools"}
    ):
        raise ValueError("installed_evidence_wheel_identity_mismatch")


def check_success(value, expected):
    if (
        set(value)
        != {
            "scope",
            "python",
            "input_sha256",
            "proof",
            "implementation",
            "actual_owned_child_count",
        }
        or value["scope"] != NOTICE
        or value["input_sha256"] != expected["input_sha256"]
        or value["proof"] != expected["canary_check"]
        or value["implementation"] != expected["evidence_implementation"]
        or type(value["actual_owned_child_count"]) is not int
        or value["actual_owned_child_count"] != 1
    ):
        raise ValueError("installed_evidence_source_replay_mismatch")


def run(python, wheel, output):
    if (
        not all(p.is_absolute() for p in (python, wheel, output))
        or not python.is_file()
        or not os.access(python, os.X_OK)
        or not wheel.is_file()
        or wheel.is_symlink()
        or wheel.suffix != ".whl"
        or not 0 < wheel.stat().st_size <= 32 * 2**20
        or output.exists()
        or output.is_symlink()
        or not output.parent.is_dir()
    ):
        raise ValueError("installed_evidence_explicit_new_paths_required")
    wheel = wheel.resolve()
    wheel_pin = sha(wheel.read_bytes())
    source_before = worker.implementation()
    probe_pin = sha(PROBE.read_bytes())
    cases = []
    with tempfile.TemporaryDirectory(prefix="sclib-installed-evidence-") as directory:
        identity = parsed(invoke(python, ["-c", IDENTITY], directory))
        check_identity(identity, python, wheel, wheel_pin)
        for name, options in (
            ("zero_context", {"empty": True}),
            ("all_revisions", {"superseded": True}),
            ("full_eight_mib_context", {"size": 8 * 2**20}),
        ):
            raw = frame(*fixture(**options))
            expected = worker.checked(worker.prepare(io.BytesIO(raw)))
            actual = parsed(invoke(python, [str(PROBE)], directory, raw))
            check_success(actual, expected)
            cases.append({"case": name, "frame_bytes": len(raw), **actual})

        # Keep the old hashes while corrupting an actual context byte. A passing
        # unmodified replay does not demonstrate rejection of damaged evidence.
        rejected = invoke(python, [str(PROBE)], directory, raw[:-1] + b"!")
        if rejected.returncode == 0 or rejected.stdout:
            raise ValueError("installed_evidence_corrupt_input_not_rejected")
        if b"SYNTHETIC ONLY" in rejected.stderr:
            raise ValueError("installed_evidence_error_echoed_context")
        after = parsed(invoke(python, ["-c", IDENTITY], directory))
        check_identity(after, python, wheel, wheel_pin)
    if (
        sha(wheel.read_bytes()) != wheel_pin
        or worker.implementation() != source_before
        or sha(PROBE.read_bytes()) != probe_pin
    ):
        raise ValueError("installed_evidence_sources_changed")
    report = {
        "version": "sclib-installed-evidence-ci/1.0.0",
        "synthetic_only": True,
        "scientific_acceptance": False,
        "application_or_database_executed": False,
        "linux_image_parity_verified": False,
        "wheel_sha256": wheel_pin,
        "probe_sha256": probe_pin,
        "driver_sha256": sha(Path(__file__).read_bytes()),
        "installed_identity": identity,
        "cases": cases,
        "corrupt_context_rejected": True,
        "owned_working_directory_removed": not Path(directory).exists(),
    }
    with os.fdopen(
        os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
    ) as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.python, args.wheel, args.output)
    print(
        "Installed synthetic byte replay: 3 cases and corrupt-context rejection passed."
    )


if __name__ == "__main__":
    main()
