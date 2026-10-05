"""Prepare private table intake from pinned local source bytes; no network or DB."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
from services.material_table_field_prepare import prepare_table_package  # noqa: E402
from services.source_expression_contract_v2_2 import compile_package  # noqa: E402


def checked_package(capture, metadata, formulas, original_text, text_sha256, original_parent):
    if hashlib.sha256(original_text).hexdigest() != text_sha256:
        raise ValueError("Original extracted text SHA256 mismatch")
    if hashlib.sha256(original_parent).hexdigest() != capture["capture_sha256"]:
        raise ValueError("Original parent SHA256 mismatch")
    loc = capture["locator"]
    start, end = loc.get("char_start"), loc.get("char_end")
    if type(start) is not int or type(end) is not int or not 0 <= start < end:
        raise ValueError("Original extracted-text window required")
    if original_text.decode("utf-8")[start:end] != capture["text"]:
        raise ValueError("Table differs from its original extracted-text window")
    return prepare_table_package(capture, formulas=formulas, source_metadata=metadata)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("capture", "metadata", "source-text", "source-parent", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--source-text-sha256", required=True)
    parser.add_argument("--formula", action="append", required=True)
    args = parser.parse_args()
    package = checked_package(json.loads(args.capture.read_text()), json.loads(args.metadata.read_text()),
        args.formula, args.source_text.read_bytes(), args.source_text_sha256, args.source_parent.read_bytes())
    prepared = compile_package(package)
    content = (json.dumps(package, ensure_ascii=False, indent=2) + "\n").encode()
    # Exact exclusive file creation: no user file is overwritten or made public.
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(content)
    print(json.dumps({"package_sha256": prepared.package_sha256,
                      "file_sha256": hashlib.sha256(content).hexdigest(),
                      "expressions": len(prepared.projections), "database_changed": False,
                      "scientific_acceptance": False, "layout_reviewed": False}))


if __name__ == "__main__":
    main()
