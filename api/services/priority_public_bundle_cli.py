"""Offline, read-only public RPS verification; never authorizes publication.

Run using the exact API lock and matching five-file verifier source bundle.
This packaged entry point is also available via ``python -m``; the repository
script only launches this implementation and contains no verification logic.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


class _ArgumentsError(ValueError):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, _message):
        # argparse's default output can echo private paths or arbitrary inputs.
        raise _ArgumentsError()


def main(argv=None):
    parser = _Parser(add_help=False, allow_abbrev=False)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--release-sha256")
    if argv is None:
        import sys
        argv = sys.argv[1:]
    if argv in (["--help"], ["-h"]):
        print(json.dumps({"status": "usage", "offline": True, "read_only": True,
            "required": ["--bundle ABSOLUTE_RELEASE_ID.public.json", "--sha256 INDEPENDENT_BUNDLE_SHA256"],
            "optional": ["--release-sha256 INDEPENDENT_RELEASE_SHA256"]}, sort_keys=True))
        return 0
    try:
        args = parser.parse_args(argv)
    except _ArgumentsError:
        print(json.dumps({"integrity_verified": False, "error": "invalid_arguments"}))
        return 2
    # No application configuration, database or provider modules are imported.
    from services.priority_public_bundle import (
        PublicPriorityBundleError,
        read_public_bundle,
    )
    try:
        path = Path(args.bundle)
        if (not path.is_absolute() or ".." in path.parts or "\x00" in args.bundle
                or args.bundle.startswith("//") or not path.name.endswith(".public.json")):
            raise PublicPriorityBundleError("invalid public bundle path")
        identifier = path.name[:-len(".public.json")]
        result = read_public_bundle(path.parent, identifier, args.sha256,
            expected_release_sha256=args.release_sha256)
    except (OSError, ValueError, TypeError):
        print(json.dumps({"integrity_verified": False, "error": "public_bundle_verification_failed"}))
        return 1
    print(json.dumps(result.metadata, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
