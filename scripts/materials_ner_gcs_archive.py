"""Create-only original arXiv archive bridge; credentials remain in the API container."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys


def main():
    from google.cloud import storage
    from google.api_core.exceptions import PreconditionFailed

    header = sys.stdin.buffer.readline(4096)
    request = json.loads(header)
    raw = sys.stdin.buffer.read(64 * 1024**2 + 1)
    digest = hashlib.sha256(raw).hexdigest()
    if (not 0 < len(raw) <= 64 * 1024**2 or len(raw) != request["size"]
            or digest != request["sha256"]
            or not re.fullmatch(
                r"captures/arxiv/(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?_\d{7})(?:v[1-9]\d*)?/"
                r"(?:source|pdf)/sha256/" + digest, request["object"])):
        raise ValueError("invalid bounded arXiv capture")
    bucket_name = os.getenv("GCS_BUCKET", "sclib-jzis")
    blob = storage.Client(project=os.getenv("GCP_PROJECT", "jzis-sclib")).bucket(bucket_name).blob(request["object"])
    try:
        blob.upload_from_string(raw, if_generation_match=0, checksum="crc32c", timeout=90,
                                content_type="application/pdf" if raw.startswith(b"%PDF-") else "application/octet-stream")
    except PreconditionFailed:
        pass
    blob.reload(timeout=30)
    observed = blob.download_as_bytes(if_generation_match=blob.generation, checksum="crc32c", timeout=90)
    if observed != raw:
        raise ValueError("immutable GCS archive mismatch")
    return {"ok": True, "bucket": bucket_name, "name": blob.name, "generation": str(blob.generation),
            "size": blob.size, "sha256": digest, "readback_verified": True}


if __name__ == "__main__":
    try:
        print(json.dumps(main()))
    except Exception as error:
        print(json.dumps({"ok": False, "error_class": type(error).__name__}))
        sys.exit(1)
