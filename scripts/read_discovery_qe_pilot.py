"""Read a locally captured QE pilot through the application's original-file reader.

No solver, SSH or network is invoked. Inputs and coordinator receipts are immutable;
the private output must be a new directory. Ordinary CI skips the opt-in harness.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("bundle", "capture", "output"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    for key in ("started", "finished", "runner", "pw"):
        parser.add_argument(f"--{key}-sha256", required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output must be new; existing readings are retained unchanged.")
    if not args.bundle.is_dir() or not args.capture.is_dir():
        parser.error("Bundle and capture must already be local directories.")
    request = {key: str(getattr(args, key).resolve()) for key in ("bundle", "capture", "output")}
    for key in ("started", "finished", "runner", "pw"):
        value = getattr(args, key + "_sha256")
        if not re.fullmatch(r"[a-f0-9]{64}", value):
            parser.error(f"Invalid {key} SHA-256.")
        request[key + "_sha256"] = value
    with tempfile.NamedTemporaryFile(mode="w", prefix="sclib-qe-read-", suffix=".json") as handle:
        json.dump(request, handle)
        handle.flush()
        env = dict(os.environ, SCLIB_QE_PILOT_READ_INPUT=handle.name)
        completed = subprocess.run(["pnpm", "exec", "vitest", "run", "tests/component/discovery-qe-pilot.read.test.tsx"],
                                   cwd=ROOT / "frontend", env=env, check=False)
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
