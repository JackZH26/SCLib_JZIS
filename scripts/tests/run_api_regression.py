"""Execute every ordinary API test module in separate owned-service batches.

This test-only coordinator never creates a database client, supplies a DSN,
changes an assertion, or attaches to a service. Only run_disposable_tests.py
owns services. Capacity and migration runs remain separate invocations.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
import time
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

from scripts.schema_rehearsal_report import capture_provenance, source_unchanged

ROOT = Path(__file__).resolve().parents[2]
MAX_XML_BYTES = 32 * 1024 * 1024


def modules(root: Path) -> list[str]:
    """Support the actual flat API suite; refuse changed discovery conventions."""
    config = tomllib.loads((root / "api/pyproject.toml").read_text())["tool"]["pytest"][
        "ini_options"
    ]
    if config.get("testpaths") != ["tests"] or any(
        key in config
        for key in (
            "python_files",
            "python_classes",
            "python_functions",
            "addopts",
            "norecursedirs",
        )
    ):
        raise ValueError("api_discovery_configuration_changed")
    directory = root / "api/tests"
    if directory.is_symlink():
        raise ValueError("test_module_symlink")
    selected = []
    for path in sorted(directory.iterdir()):
        if path.name == "__pycache__" or path.name.startswith("."):
            continue
        if path.is_symlink():
            raise ValueError("test_module_symlink")
        if path.is_dir():
            # The existing fixtures directory contains data, not Python tests.
            if path.name == "fixtures" and not any(
                item.is_symlink() or item.suffix == ".py" for item in path.rglob("*")
            ):
                continue
            raise ValueError("nested_test_layout_requires_review")
        if any(
            fnmatch.fnmatchcase(path.name, pattern)
            for pattern in ("test_*.py", "*_test.py")
        ):
            if not path.is_file() or not path.stem.isidentifier():
                raise ValueError("invalid_test_module")
            selected.append("tests/" + path.name)
    if not selected:
        raise ValueError("ordinary_api_suite_is_empty")
    return selected


def partition(selected: list[str], batches: int) -> list[list[str]]:
    if type(batches) is not int or not 2 <= batches <= 16 or batches > len(selected):
        raise ValueError("invalid_batch_count")
    if selected != sorted(set(selected)):
        raise ValueError("test_modules_must_be_unique_and_sorted")
    groups = [selected[index::batches] for index in range(batches)]
    if sorted(module for group in groups for module in group) != selected:
        raise ValueError("incomplete_module_partition")
    return groups


def counts(path: Path, expected: list[str]) -> dict:
    """Read actual JUnit outcomes, not stdout dots or a cached collection list."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_XML_BYTES:
        raise ValueError("missing_or_oversized_batch_junit")
    raw = path.read_bytes()
    if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise ValueError("invalid_batch_junit")
    document = ET.fromstring(raw)
    if document.tag != "testsuites":
        raise ValueError("invalid_batch_junit")
    cases = document.findall("./testsuite/testcase")
    expected_names = {
        Path(module).with_suffix("").as_posix().replace("/", "."): module
        for module in expected
    }
    observed = {module: 0 for module in expected}
    total = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    seen = set()
    for case in cases:
        classname, name = case.get("classname", ""), case.get("name", "")
        matches = [
            module
            for prefix, module in expected_names.items()
            if classname == prefix or classname.startswith(prefix + ".")
        ]
        if len(matches) != 1 or not name or (classname, name) in seen:
            raise ValueError("unexpected_or_duplicate_test_case")
        seen.add((classname, name))
        observed[matches[0]] += 1
        status = (
            "errors"
            if case.find("error") is not None
            else "failed"
            if case.find("failure") is not None
            else "skipped"
            if case.find("skipped") is not None
            else "passed"
        )
        total[status] += 1
    # An empty/omitted module cannot silently disappear behind other passing cases.
    if not cases or any(count == 0 for count in observed.values()):
        raise ValueError("test_module_has_no_reported_cases")
    return {**total, "test_cases": len(cases), "module_cases": observed}


def write_new(path: Path, value: dict) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def child_environment() -> dict[str, str]:
    # The inner runner applies the same boundary again before starting tests.
    keep = {"PATH", "HOME", "LANG", "LC_ALL", "TZ", "TMPDIR", "SYSTEMROOT", "TERM"}
    return {key: value for key, value in os.environ.items() if key in keep}


def execute(
    *,
    output: Path,
    backend: str,
    postgres_bin: Path | None,
    redis_bin: Path | None,
    batches: int = 8,
    root: Path = ROOT,
) -> int:
    if backend not in {"native", "docker"} or (
        backend == "native" and (postgres_bin is None or redis_bin is None)
    ):
        raise ValueError("explicit_backend_binaries_required")
    if backend == "docker" and (postgres_bin is not None or redis_bin is not None):
        raise ValueError("native_paths_require_native_backend")
    if not output.is_absolute() or output.parent.resolve() != output.parent:
        raise ValueError("absolute_new_output_required")
    selected = modules(root)
    groups = partition(selected, batches)
    provenance = capture_provenance(root)
    output.mkdir(mode=0o700)  # Exclusive: never replace earlier evidence.
    plan = {
        "version": "owned-api-module-batches/1.1.0",
        "backend": backend,
        "module_count": len(selected),
        "batches": groups,
        "provenance": provenance,
        "scope": "ordinary_api_tests_only",
        "capacity_included": False,
        "production_or_scientific_acceptance": False,
    }
    write_new(output / "plan.json", plan)
    print(f"API batch artifacts: {output}", flush=True)
    completed = []
    started = time.monotonic()
    status, reason, exit_code = "incomplete", None, 1
    try:
        for index, group in enumerate(groups, 1):
            source_unchanged(provenance, capture_provenance(root))
            report = output / f"batch-{index:02d}.xml"
            command = [
                sys.executable,
                str(root / "scripts/run_disposable_tests.py"),
                "--backend",
                backend,
                "--suite",
                "api",
            ]
            if backend == "native":
                command += [
                    "--postgres-bin",
                    str(postgres_bin),
                    "--redis-bin",
                    str(redis_bin),
                ]
            command += [
                "--",
                "-q",
                "--tb=short",
                "--durations=10",
                f"--junitxml={report}",
                *group,
            ]
            print(
                f"API batch {index}/{len(groups)}: {len(group)} whole modules; new owned services.",
                flush=True,
            )
            # Sequential, no shell, no shared service and no test-selection flags.
            result = subprocess.run(
                command, cwd=root, env=child_environment(), check=False
            )
            entry = {
                "batch": index,
                "runner_exit_code": result.returncode,
                "junit": report.name,
            }
            completed.append(entry)
            if result.returncode != 0:
                reason = "owned_batch_failed_or_interrupted"
                # A failed test batch may still have a complete, valid JUnit.
                # Retain those actual failures; a nonzero cleanup/interruption
                # exit remains a failure even when the XML reports only passes.
                try:
                    entry["counts"] = counts(report, group)
                except (ValueError, OSError, ET.ParseError):
                    entry["junit_status"] = "unavailable_or_incomplete"
                else:
                    entry["junit_status"] = "complete_junit_verified"
                break  # Never start another service lifetime after failed cleanup/tests.
            entry["counts"] = counts(report, group)
            entry["junit_status"] = "complete_junit_verified"
            if entry["counts"]["failed"] or entry["counts"]["errors"]:
                raise ValueError("junit_disagrees_with_success_exit")
        else:
            source_unchanged(provenance, capture_provenance(root))
            if modules(root) != selected:
                raise ValueError("ordinary_api_module_inventory_changed")
            status, exit_code = "completed", 0
    except (ValueError, OSError, ET.ParseError):
        reason = "batch_evidence_or_source_check_failed"
    finally:
        totals = {
            key: sum(entry.get("counts", {}).get(key, 0) for entry in completed)
            for key in ("passed", "failed", "errors", "skipped", "test_cases")
        }
        write_new(
            output / "result.json",
            {
                "version": plan["version"],
                "status": status,
                "reason": reason,
                "duration_seconds": round(time.monotonic() - started, 3),
                "module_count": len(selected),
                "batches": completed,
                "counts": totals,
                "counts_scope": "complete_verified_junit_batches_only",
                "counted_batches": [
                    entry["batch"] for entry in completed if "counts" in entry
                ],
                "unreported_batches": [
                    index
                    for index in range(1, len(groups) + 1)
                    if not any(
                        entry["batch"] == index and "counts" in entry
                        for entry in completed
                    )
                ],
                "full_module_coverage": status == "completed",
                "production_or_scientific_acceptance": False,
            },
        )
    return exit_code


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("invalid_api_regression_arguments")


def main(argv=None) -> int:
    parser = Parser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--backend", choices=("docker", "native"), required=True)
    parser.add_argument("--postgres-bin", type=Path)
    parser.add_argument("--redis-bin", type=Path)
    parser.add_argument("--batches", type=int, default=8)
    parser.add_argument("--output", type=Path, required=True)
    try:
        return execute(**vars(parser.parse_args(argv)))
    except (ValueError, OSError):
        print("API regression refused; no passing completion report.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
