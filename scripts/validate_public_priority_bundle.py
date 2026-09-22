#!/usr/bin/env python3
"""Thin launcher; use the matching API locked environment and verifier sources."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

if __name__ == "__main__":
    from services.priority_public_bundle_cli import main
    raise SystemExit(main())
