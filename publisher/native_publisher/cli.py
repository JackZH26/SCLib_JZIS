"""Bounded operator-owned completed-input manifest; preview is the default."""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import fields
import hashlib
import json
import os
from pathlib import Path
import stat

from ingestion.index import indexer
from ingestion.models import ApsArticleMeta, Chunk, PaperMetadata, ParsedPaper
from native_publisher.producer import NativePublisherError, RetainedInput, publish_prepared

MAX_PREPARED_BYTES = 64 * 1024**2


def load_prepared(path):
    """Read one stable bounded regular file; it is never removed or rewritten."""
    path = Path(path)
    if not path.is_absolute():
        raise NativePublisherError("An absolute operator-owned prepared file is required")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 1 <= before.st_size <= MAX_PREPARED_BYTES:
            raise NativePublisherError("A bounded regular prepared file is required")
        payload = bytearray()
        while block := os.read(descriptor, 1024**2):
            payload.extend(block)
            if len(payload) > MAX_PREPARED_BYTES:
                raise NativePublisherError("Prepared file exceeds its limit")
        after, named = os.fstat(descriptor), path.stat(follow_symlinks=False)
        keys = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if len(payload) != before.st_size or any(getattr(before, k) != getattr(item, k)
                for item in (after, named) for k in keys):
            raise NativePublisherError("Prepared file changed while reading")
    finally:
        os.close(descriptor)
    data = json.loads(payload)
    required = {"version", "source", "metadata", "chunks", "materials", "inputs"}
    if (type(data) is not dict or not required <= data.keys()
            or data.keys() - required - {"ingestion_capture", "related_paper_id"}
            or data["version"] != "native-prepared-paper/1.0.0"
            or type(data["metadata"]) is not dict
            or type(data["chunks"]) is not list or not 1 <= len(data["chunks"]) <= 1000
            or type(data["inputs"]) is not dict):
        raise NativePublisherError("Closed complete prepared-paper fields are required")
    if data["source"] == "arxiv":
        if data["metadata"].keys() - {f.name for f in fields(PaperMetadata)}:
            raise NativePublisherError("Unknown arXiv metadata fields")
        metadata = PaperMetadata.from_dict(data["metadata"])
        paper = ParsedPaper(metadata, sections=[], ingestion_capture=data.get("ingestion_capture", {}))
    elif data["source"] == "aps":
        if data["metadata"].keys() - {f.name for f in fields(ApsArticleMeta)} or "ingestion_capture" in data:
            raise NativePublisherError("Unknown APS metadata fields")
        paper = ApsArticleMeta.from_dict(data["metadata"])
    else:
        raise NativePublisherError("Explicit arXiv or APS source required")
    chunks = [Chunk(**row) for row in data["chunks"]]
    inputs = {kind: RetainedInput(**row) for kind, row in data["inputs"].items()}
    return paper, chunks, data["materials"], inputs, data.get("related_paper_id"), hashlib.sha256(payload).hexdigest()


async def execute(args):
    paper, chunks, materials, inputs, related, digest = load_prepared(args.prepared)
    root = Path(args.archive_root)
    if not root.is_absolute():
        raise NativePublisherError("An absolute operator-owned archive root is required")
    try:
        result = await publish_prepared(paper, chunks, materials, archive_root=root, inputs=inputs,
            related_paper_id=related, logical_index=args.logical_index, dry_run=not args.apply)
        result["prepared_sha256"] = digest
        print(json.dumps(result), flush=True)
    finally:
        await indexer.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", required=True)
    parser.add_argument("--archive-root", required=True)
    parser.add_argument("--logical-index", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(execute(args))
    except Exception as error:
        # Database/provider exceptions can include credentials or full input.
        print(json.dumps({"status": "failed", "error_class": type(error).__name__,
            "message": "Native publication failed; no completed commit receipt was produced"}), flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
