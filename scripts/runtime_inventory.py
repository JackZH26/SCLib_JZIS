"""Emit a credential-free package/lock inventory or compare runtime vs test.

Capture in each actual environment. A lock hash is provenance, not by itself
proof that two environments installed the same platform-dependent graph.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
from pathlib import Path

DEV_ONLY = {"pytest", "pytest-asyncio", "ruff", "iniconfig", "pluggy", "pygments"}


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def compare(runtime: dict, tests: dict) -> list[str]:
    failures = []
    if runtime["lock_sha256"] != tests["lock_sha256"]:
        failures.append("lock mismatch")
    if runtime["python_minor"] != tests["python_minor"]:
        failures.append("Python minor mismatch")
    for name, version in runtime["packages"].items():
        if tests["packages"].get(name) != version:
            failures.append(f"runtime package mismatch: {name}")
    extras = set(tests["packages"]) - set(runtime["packages"])
    if extras - DEV_ONLY:
        failures.append("undocumented test-only packages: " + ", ".join(sorted(extras - DEV_ONLY)))
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--tests", type=Path)
    args = parser.parse_args()
    if args.runtime and args.tests and not args.lock:
        failures = compare(json.loads(args.runtime.read_text()), json.loads(args.tests.read_text()))
        print(json.dumps({"matches": not failures, "failures": failures}, sort_keys=True))
        return int(bool(failures))
    if not args.lock or args.runtime or args.tests:
        parser.error("Specify --lock for capture, or --runtime and --tests for comparison.")
    result = {
        "schema": "sclib-runtime-inventory/v1", "python_minor": ".".join(platform.python_version_tuple()[:2]),
        "python_version": platform.python_version(), "system": platform.system(),
        "machine": platform.machine(), "lock_sha256": hashlib.sha256(args.lock.read_bytes()).hexdigest(),
        "packages": dict(sorted((normalize(d.metadata["Name"]), d.version)
                                for d in importlib.metadata.distributions())),
    }
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
