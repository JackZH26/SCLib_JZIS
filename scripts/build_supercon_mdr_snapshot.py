"""Reproduce the immutable licensed MDR metadata resource from verified bytes."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from services.material_supercon_references import (  # noqa: E402
    MANIFEST_PATH,
    MAX_SOURCE_BYTES,
    RESOURCE_PATH,
    build_snapshot,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Exact public 20240322_MDR_OAndM.txt bytes")
    parser.add_argument("--resource", type=Path, default=RESOURCE_PATH)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    args = parser.parse_args()
    if args.source.stat().st_size > MAX_SOURCE_BYTES:
        parser.error("source exceeds the fixed byte bound")
    resource, manifest = build_snapshot(args.source.read_bytes())
    args.resource.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.resource.write_bytes(resource)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"resource_bytes": len(resource), "resource_sha256": manifest["resource_sha256"],
                      "source_rows": manifest["source_rows"], "canonical_writes": False}))


if __name__ == "__main__":
    main()
