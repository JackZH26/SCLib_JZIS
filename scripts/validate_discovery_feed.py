#!/usr/bin/env python3
"""Validate and optionally publish a downloaded Discovery feed locally.

Use the API Python environment (Pydantic v2 required). This CLI imports neither
the API app nor settings/ORM, and never reads .env or contacts a service.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from services.discovery_feed import (  # noqa: E402
    producer_digest,
    publish_feed,
    read_json_file,
    record_update_failure,
    validate_feed,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed", type=Path)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--publish", type=Path, help="Local destination; omitted means validation only")
    parser.add_argument("--mark-failed", type=Path, help="Record a failed pull attempt without touching the feed")
    args = parser.parse_args()
    try:
        if args.mark_failed is not None:
            record_update_failure(args.mark_failed)
            return 0
        if args.feed is None or args.metadata is None:
            parser.error("--feed and --metadata are required unless --mark-failed is supplied")
        if args.publish is not None:
            document = publish_feed(args.feed, args.metadata, args.publish)
            feed, raw = document.feed, document.raw_feed
        else:
            raw = read_json_file(args.feed)
            feed = validate_feed(raw, read_json_file(args.metadata))
    except (OSError, ValueError, TypeError, KeyError):
        if args.publish is not None:
            try:
                record_update_failure(args.publish)
            except OSError:
                print("Could not persist the Discovery pull-failure status.", file=sys.stderr)
        # Avoid dumping candidate payloads or local paths into scheduled logs.
        print("Discovery validation/publication failed; last-good cache retained.", file=sys.stderr)
        return 1
    print(f"validated Discovery feed: status={feed.status} candidates={len(feed.candidates)} sha256={producer_digest(raw)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
