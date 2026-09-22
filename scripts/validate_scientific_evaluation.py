"""Read-only, offline verification of one independently hash-pinned evaluation.

Usage with the API runtime:
  api/.venv/bin/python scripts/validate_scientific_evaluation.py validate /absolute/package.json --sha256 HASH
  api/.venv/bin/python scripts/validate_scientific_evaluation.py compare /absolute/package.json --sha256 HASH

The supplied digest must be obtained independently, not trusted because it is
inside the package. Two complete local captures check the bytes and observed
path/inode identity; they are not source authentication or future immutability.
This command never opens package URIs, connects to services, or writes files.
"""
from __future__ import annotations

import sys

# Importing the offline evaluator must not create repository bytecode files.
sys.dont_write_bytecode = True

import argparse
import hashlib
import json
import math
import os
import re
import stat
from pathlib import Path

MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 500_000
_HASH = re.compile(r"^[0-9a-f]{64}$")
_REJECTION_CODES = frozenset({
    "invalid_arguments", "invalid_expected_sha256", "invalid_artifact_path", "artifact_not_regular",
    "artifact_size_limit", "artifact_changed", "artifact_sha256_mismatch", "invalid_json",
    "duplicate_json_keys", "nonfinite_json", "json_resource_limit", "evaluation_rejected",
    "report_invalid", "artifact_unavailable", "evaluation_unavailable",
})


class EvaluationCLIRejection(ValueError):
    """The reason is a fixed code, never an input path, payload, or exception."""


def _require(condition, code):
    if not condition:
        raise EvaluationCLIRejection(code)


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise EvaluationCLIRejection("invalid_arguments")


def parser():
    # argparse's usual error/usage includes raw arguments. Invalid invocations
    # have the same JSON-only sanitized boundary as rejected artifact bytes.
    result = _Parser(add_help=False, allow_abbrev=False)
    result.add_argument("command", choices=("validate", "compare"))
    result.add_argument("path")
    result.add_argument("--sha256", required=True)
    return result


def _path(value):
    _require(type(value) in (str, Path) or isinstance(value, Path), "invalid_artifact_path")
    raw = os.fspath(value)
    _require(type(raw) is str and 0 < len(raw) <= 4096
             and not any(ord(char) < 32 or ord(char) == 127 for char in raw), "invalid_artifact_path")
    path = Path(raw)  # Never resolve(): symlink ancestors must be refused.
    _require(path.is_absolute() and path.anchor == "/" and path.name
             and ".." not in path.parts, "invalid_artifact_path")
    return path


def _signature(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _directory_fd(path):
    """Walk every ancestor without following a symlink, retaining identities."""
    descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    observed = []
    try:
        info = os.fstat(descriptor)
        observed.append((info.st_dev, info.st_ino, info.st_mode))
        for part in path.parts[1:]:
            following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
            info = os.fstat(descriptor)
            observed.append((info.st_dev, info.st_ino, info.st_mode))
        return descriptor, tuple(observed)
    except BaseException:
        os.close(descriptor)
        raise


def _capture(path):
    directory, ancestors = _directory_fd(path.parent)
    try:
        initial = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
        _require(stat.S_ISREG(initial.st_mode) and initial.st_nlink == 1, "artifact_not_regular")
        _require(0 < initial.st_size <= MAX_INPUT_BYTES, "artifact_size_limit")
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            before = os.fstat(descriptor)
            _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, "artifact_not_regular")
            _require(0 < before.st_size <= MAX_INPUT_BYTES, "artifact_size_limit")
            _require(_signature(initial) == _signature(before), "artifact_changed")
            size, pieces = 0, []
            while True:
                piece = os.read(descriptor, min(1024 * 1024, MAX_INPUT_BYTES - size + 1))
                if not piece:
                    break
                size += len(piece)
                _require(size <= MAX_INPUT_BYTES, "artifact_size_limit")
                pieces.append(piece)
            after = os.fstat(descriptor)
            pointed = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
            _require(_signature(before) == _signature(after) == _signature(pointed)
                     and size == before.st_size, "artifact_changed")
            return b"".join(pieces), (ancestors, _signature(after))
        finally:
            os.close(descriptor)
    finally:
        os.close(directory)


def _preflight_json(text):
    """Bound container depth and value/key nodes before JSON allocates a tree.

    This is a resource lexer, not an alternative JSON parser. json.loads still
    checks every grammar rule. A string key and each value/container count as
    separate nodes; punctuation and string contents do not add nodes.
    """
    depth = nodes = 0
    quoted = escaped = primitive = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char.isspace() or char in ",:":
            primitive = False
            continue
        if char in "}]":
            depth -= 1
            primitive = False
            _require(depth >= 0, "invalid_json")
            continue
        if char == '"':
            nodes += 1
            quoted, primitive = True, False
        elif char in "{[":
            depth += 1
            nodes += 1
            primitive = False
            _require(depth <= MAX_JSON_DEPTH, "json_resource_limit")
        elif not primitive:
            nodes += 1
            primitive = True
        _require(nodes <= MAX_JSON_NODES, "json_resource_limit")
    _require(not quoted and depth == 0, "invalid_json")


def _strict_json(payload):
    try:
        text = payload.decode("utf-8", errors="strict")
        _preflight_json(text)

        def unique_pairs(items):
            result = {}
            for key, value in items:
                _require(key not in result, "duplicate_json_keys")
                result[key] = value
            return result

        def reject_constant(_value):
            raise EvaluationCLIRejection("nonfinite_json")

        def finite_float(value):
            result = float(value)
            _require(math.isfinite(result), "nonfinite_json")
            return result

        document = json.loads(text, object_pairs_hook=unique_pairs,
                              parse_constant=reject_constant, parse_float=finite_float)
        _require(type(document) is dict, "invalid_json")
        # JSON escape sequences can introduce an unpaired surrogate even
        # when the original file was valid UTF-8. Reject before the DTO.
        pending = [document]
        while pending:
            value = pending.pop()
            if type(value) is dict:
                pending.extend(value.keys())
                pending.extend(value.values())
            elif type(value) is list:
                pending.extend(value)
            elif type(value) is str:
                value.encode("utf-8", errors="strict")
        return document
    except EvaluationCLIRejection:
        raise
    except (ValueError, UnicodeError, TypeError, RecursionError, OverflowError):
        raise EvaluationCLIRejection("invalid_json") from None


def _evaluate(command, document):
    # No old report aggregator, dataset stratifier, settings resolution, or
    # external-service setup belongs in this offline command.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
    from services.scientific_evaluation import compare_package, validate_package

    try:
        return (validate_package if command == "validate" else compare_package)(document)
    except Exception:  # noqa: BLE001 - raw evaluator errors may contain private input.
        raise EvaluationCLIRejection("evaluation_rejected") from None


def validate_artifact(*, command, path, expected_sha256):
    """Return sanitized evaluator JSON only after two identical full captures."""
    _require(command in ("validate", "compare"), "invalid_arguments")
    _require(type(expected_sha256) is str and _HASH.fullmatch(expected_sha256), "invalid_expected_sha256")
    selected = _path(path)
    try:
        payload, identity = _capture(selected)
        _require(hashlib.sha256(payload).hexdigest() == expected_sha256, "artifact_sha256_mismatch")
        document = _strict_json(payload)
        report = _evaluate(command, document)
        _require(type(report) is dict, "report_invalid")
        try:
            serialized = json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
            _require(len(serialized.encode("utf-8")) <= MAX_INPUT_BYTES, "report_invalid")
        except (TypeError, ValueError, RecursionError, OverflowError):
            raise EvaluationCLIRejection("report_invalid") from None
        repeated, repeated_identity = _capture(selected)
        _require(repeated == payload and repeated_identity == identity
                 and hashlib.sha256(repeated).hexdigest() == expected_sha256, "artifact_changed")
        return serialized
    except EvaluationCLIRejection:
        raise
    except OSError:
        raise EvaluationCLIRejection("artifact_unavailable") from None


def main(argv=None):
    try:
        requested = list(sys.argv[1:] if argv is None else argv)
        if requested in (["--help"], ["-h"]):
            print(json.dumps({
                "status": "usage", "commands": ["validate", "compare"],
                "usage": "validate_scientific_evaluation.py {validate|compare} /absolute/package.json --sha256 HASH",
                "sha256_requirement": "Independently supplied lowercase SHA-256 of the complete raw file bytes.",
                "read_only": True, "offline": True,
                "exit_codes": {"0": "Well-formed diagnostic; not release approval.", "2": "Input or evaluation rejected."},
            }, sort_keys=True))
            return 0
        args = parser().parse_args(requested)
        output = validate_artifact(command=args.command, path=args.path, expected_sha256=args.sha256)
    except EvaluationCLIRejection as exc:
        code = str(exc) if str(exc) in _REJECTION_CODES else "evaluation_unavailable"
        print(json.dumps({"status": "rejected", "reason_code": code}, sort_keys=True))
        return 2
    except (Exception, KeyboardInterrupt):  # noqa: BLE001 - fixed JSON-only outer boundary.
        print(json.dumps({"status": "rejected", "reason_code": "evaluation_unavailable"}, sort_keys=True))
        return 2
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
