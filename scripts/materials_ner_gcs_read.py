"""GCS read bridge: metadata or one generation-pinned object, never credentials.

Protocol: a JSON header line, followed by exact raw object bytes for downloads.
Run in the existing authenticated container; no remote file is created.
"""
import hashlib
import json
import sys


def execute(request):
    from google.cloud import storage
    name = request["object"]
    if (not name.startswith(("src/", "pdf/", "captures/arxiv/"))
            or ".." in name.split("/") or "\x00" in name):
        raise ValueError("source prefix refused")
    client = storage.Client(project=request.get("project", "jzis-sclib"))
    blob = client.bucket(request.get("bucket", "sclib-jzis")).blob(name)
    blob.reload(timeout=30)
    if request.get("generation") is not None and str(blob.generation) != str(request["generation"]):
        raise ValueError("object generation changed")
    metadata = {"name": blob.name, "size": blob.size, "generation": str(blob.generation),
                "crc32c": blob.crc32c, "updated": blob.updated.isoformat(),
                "bucket": blob.bucket.name}
    raw = b""
    if request["action"] == "download":
        if blob.size > 64 * 1024 * 1024:
            raise ValueError("object byte limit exceeded")
        raw = blob.download_as_bytes(if_generation_match=blob.generation, checksum="crc32c", timeout=120)
        if len(raw) != blob.size:
            raise ValueError("object size mismatch")
        metadata["sha256"] = hashlib.sha256(raw).hexdigest()
    elif request["action"] != "stat":
        raise ValueError("unknown action")
    sys.stdout.buffer.write(json.dumps({"ok": True, "metadata": metadata}).encode() + b"\n" + raw)


if __name__ == "__main__":
    try:
        execute(json.loads(sys.argv[1]))
    except Exception as error:
        print(json.dumps({"ok": False, "error": type(error).__name__}))
        sys.exit(1)
