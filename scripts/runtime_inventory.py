"""Capture installed Python packages without importing application code.

Version 2 binds both project inputs, collector bytes and source revision.
Python package parity is not OS-library equivalence or scientific validation.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
from pathlib import Path

import tomllib

SCHEMA = "sclib-runtime-inventory/v2"
# Exclusive dev-extra tools/dependencies only. Runtime packages always match.
DEV_ONLY = {"pytest", "pytest-asyncio", "ruff", "iniconfig", "pluggy", "pygments"}
FIELDS = {"schema", "python_minor", "python_version", "implementation", "system", "machine",
          "lock_sha256", "pyproject_sha256", "collector_sha256", "source_revision",
          "project_name", "project_version", "packages"}


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate(value: object) -> None:
    """Fail closed on missing provenance and ambiguous package identities."""
    if not isinstance(value, dict) or set(value) != FIELDS or value.get("schema") != SCHEMA:
        raise ValueError("invalid inventory schema")
    for field in ("lock_sha256", "pyproject_sha256", "collector_sha256"):
        if not isinstance(value[field], str) or not re.fullmatch(r"[0-9a-f]{64}", value[field]):
            raise ValueError("invalid inventory digest")
    if not isinstance(value["source_revision"], str) or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value["source_revision"]):
        raise ValueError("invalid source revision")
    for field in ("python_minor", "python_version", "implementation", "system", "machine", "project_name", "project_version"):
        if not isinstance(value[field], str) or not re.fullmatch(r"[A-Za-z0-9_.+!-]{1,100}", value[field]):
            raise ValueError("invalid inventory identity")
    if not re.fullmatch(r"3\.\d+", value["python_minor"]) or not value["python_version"].startswith(value["python_minor"] + "."):
        raise ValueError("invalid Python identity")
    packages = value["packages"]
    if not isinstance(packages, dict) or not 1 <= len(packages) <= 5000:
        raise ValueError("invalid package inventory")
    for name, version in packages.items():
        if (not isinstance(name, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)
                or not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9_.+!-]{1,100}", version)):
            raise ValueError("invalid package identity")
    if packages.get(value["project_name"]) != value["project_version"]:
        raise ValueError("project is absent or has a different installed version")


def capture(lock: Path, pyproject: Path, revision: str, *, collector_sha256: str | None = None) -> dict:
    lock_bytes, project_bytes = lock.read_bytes(), pyproject.read_bytes()
    project = tomllib.loads(project_bytes.decode())["project"]
    locked = tomllib.loads(lock_bytes.decode())
    packages = {}
    for distribution in importlib.metadata.distributions():
        name = normalize(distribution.metadata["Name"])
        if name in packages:
            raise ValueError("duplicate installed package identity")
        packages[name] = distribution.version
    # uv --locked is the resolver consistency gate. Reject installed packages
    # that cannot be accounted for by this exact captured lock as well.
    permitted: dict[str, set[str]] = {}
    for package in locked["package"]:
        permitted.setdefault(normalize(package["name"]), set()).add(package["version"])
    if any(version not in permitted.get(name, set()) for name, version in packages.items()):
        raise ValueError("installed package is not represented by the captured lock")
    result = {
        "schema": SCHEMA, "python_minor": ".".join(platform.python_version_tuple()[:2]),
        "python_version": platform.python_version(), "implementation": platform.python_implementation(),
        "system": platform.system(), "machine": platform.machine().lower(),
        "lock_sha256": digest(lock_bytes), "pyproject_sha256": digest(project_bytes),
        "collector_sha256": collector_sha256 or digest(Path(__file__).read_bytes()),
        "source_revision": revision, "project_name": normalize(project["name"]),
        "project_version": project["version"], "packages": dict(sorted(packages.items())),
    }
    validate(result)
    return result


def compare(runtime: dict, tests: dict) -> list[str]:
    try:
        validate(runtime)
        validate(tests)
    except (ValueError, TypeError, KeyError):
        return ["invalid runtime or test inventory"]
    failures = []
    for field, label in (("lock_sha256", "lock"), ("pyproject_sha256", "pyproject"),
                         ("collector_sha256", "collector"), ("source_revision", "source revision"),
                         ("python_minor", "Python minor"), ("implementation", "Python implementation"),
                         ("system", "system"), ("machine", "architecture"),
                         ("project_name", "project name"), ("project_version", "project version")):
        if runtime[field] != tests[field]:
            failures.append(f"{label} mismatch")
    for name, version in runtime["packages"].items():
        if tests["packages"].get(name) != version:
            failures.append(f"runtime package mismatch: {name}")
    extras = set(tests["packages"]) - set(runtime["packages"])
    if extras - DEV_ONLY:
        failures.append("undocumented test-only packages: " + ", ".join(sorted(extras - DEV_ONLY)))
    return failures


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def loads(text: str) -> dict:
    result = json.loads(text, object_pairs_hook=_unique_object)
    validate(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--pyproject", type=Path)
    parser.add_argument("--revision")
    parser.add_argument("--collector-sha256", help="For identical collector supplied via isolated stdin only")
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--tests", type=Path)
    args = parser.parse_args()
    try:
        if args.runtime and args.tests and not any((args.lock, args.pyproject, args.revision, args.collector_sha256)):
            failures = compare(loads(args.runtime.read_text()), loads(args.tests.read_text()))
            print(json.dumps({"matches": not failures, "failures": failures}, sort_keys=True))
            return int(bool(failures))
        if not all((args.lock, args.pyproject, args.revision)) or args.runtime or args.tests:
            parser.error("Specify --lock, --pyproject and --revision for capture, or --runtime and --tests for comparison.")
        print(json.dumps(capture(args.lock, args.pyproject, args.revision,
                                 collector_sha256=args.collector_sha256), sort_keys=True, indent=2))
        return 0
    except (ValueError, TypeError, KeyError, OSError):
        # Do not reflect arbitrary metadata, local paths or parser input.
        print(json.dumps({"matches": False, "failures": ["inventory capture or validation failed"]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
