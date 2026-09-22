#!/usr/bin/env python3
"""Validate a reviewed RPS release offline. Never publishes or changes a DB.

Usage: python scripts/validate_priority_release.py /path/release-id.json --sha256 <manifest>
       python scripts/validate_priority_release.py --schema release
Use api/.venv/bin/python; no database credentials are needed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from services.priority_releases import (  # noqa: E402
    ActionContent,
    EvidenceContent,
    PriorityRelease,
    RubricContent,
    StateContent,
    read_release,
)
from services.research_priority import Assessment, Campaign, canonical_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, nargs="?")
    parser.add_argument(
        "--sha256", help="Expected canonical manifest hash; does not grant publication"
    )
    contracts = {"assessment": Assessment, "campaign": Campaign, "release": PriorityRelease,
                 "state": StateContent, "action": ActionContent, "evidence": EvidenceContent,
                 "rubric": RubricContent}
    parser.add_argument("--schema", choices=list(contracts))
    args = parser.parse_args()
    if args.schema:
        model = contracts[args.schema]
        print(json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2))
        return 0
    if not args.path or not args.sha256:
        parser.error("path and --sha256 are required for verification")
    try:
        release = read_release(args.path.parent, args.path.stem, args.sha256)
    except (ValueError, OSError) as exc:
        print(f"INVALID RELEASE: {exc}", file=sys.stderr)
        return 1
    rows = release.rows()
    print(
        canonical_json(
            {
                "status": "integrity_and_contract_verified_not_published",
                "release_id": release.id,
                "manifest_sha256": release.manifest_sha256,
                "campaign_hash": release.campaign_hash,
                "policy_hash": release.policy_hash,
                "total": len(rows),
                "eligible_actions": sum(r["result"]["eligibility"] == "eligible" for r in rows),
                "warning": "Scientific validity and public licensing still require authorized curator review and separate server-side digest approval.",
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
