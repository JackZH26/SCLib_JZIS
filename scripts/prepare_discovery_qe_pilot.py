"""Prepare nine real-file QE decks locally. Never runs QE, SSH, or a job scheduler."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for element in ("mg", "al", "b"):
        parser.add_argument(f"--{element}-upf", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-receipt", type=Path, action="append", default=[])
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output must be a new directory; existing preparations are immutable.")
    request = {"output": str(args.output.resolve()), "upfs": {element: str(getattr(args, element.lower() + "_upf").resolve()) for element in ("Mg", "Al", "B")},
               "source_receipts": [str(p.resolve()) for p in args.source_receipt]}
    for path in [*request["upfs"].values(), *request["source_receipts"]]:
        if not Path(path).is_file():
            parser.error("Every UPF and source receipt must already exist locally.")
    with tempfile.NamedTemporaryFile(mode="w", prefix="sclib-qe-pilot-request-", suffix=".json") as handle:
        json.dump(request, handle)
        handle.flush()
        env = dict(os.environ, SCLIB_QE_PILOT_PREPARE_INPUT=handle.name)
        completed = subprocess.run(["pnpm", "exec", "vitest", "run", "tests/component/discovery-qe-pilot.prepare.test.tsx"], cwd=ROOT / "frontend", env=env, check=False)
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
