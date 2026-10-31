"""Mac-side immutable GCS capture using ADC or the existing read-only SSH bridge."""
from __future__ import annotations

import json
from pathlib import Path
import shlex
import subprocess

from .contract import canonical, digest
from .sources import private_write, sha


def capture(root: Path, object_name: str, *, bucket="sclib-jzis", project="jzis-sclib",
            ssh_host: str | None = None, generation: str | None = None) -> dict:
    if not object_name.startswith(("src/", "pdf/", "captures/arxiv/")):
        raise ValueError("only original arXiv archive prefixes are supported")
    if "\x00" in object_name or ".." in object_name.split("/"):
        raise ValueError("invalid object path")
    cache = root / "capture-index" / f'{digest([bucket, object_name, str(generation)])}.json'
    if generation is not None and cache.exists():
        receipt = json.loads(cache.read_bytes())
        raw = (root / "sources" / receipt["sha256"]).read_bytes()
        if (sha(raw) != receipt["sha256"] or len(raw) != receipt["size"]
                or receipt["name"] != object_name or receipt["bucket"] != bucket
                or str(receipt["generation"]) != str(generation)):
            raise ValueError("cached capture integrity failure")
        return {**receipt, "local_path": str((root / "sources" / receipt["sha256"]).resolve())}
    request = {"action": "download", "object": object_name, "bucket": bucket,
               "project": project, "generation": generation}
    if ssh_host:
        script = Path(__file__).resolve().parents[3] / "scripts" / "materials_ner_gcs_read.py"
        remote = shlex.join(["docker", "exec", "-i", "sclib-api", "python", "-", canonical(request)])
        response = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                                   ssh_host, remote], input=script.read_bytes(),
                                  capture_output=True, timeout=180)
        if response.returncode:
            # Never echo SSH/container authentication or secret-bearing errors.
            raise ValueError("GCS bridge failed; no archive accepted")
        header, raw = response.stdout.split(b"\n", 1)
        envelope = json.loads(header)
        if envelope.get("ok") is not True:
            raise ValueError("GCS object not available")
        metadata = envelope["metadata"]
    else:
        from google.cloud import storage
        blob = storage.Client(project=project).bucket(bucket).blob(object_name)
        blob.reload(timeout=30)
        if generation is not None and str(blob.generation) != str(generation):
            raise ValueError("GCS generation changed")
        if blob.size > 64 * 1024 * 1024:
            raise ValueError("GCS object byte limit exceeded")
        raw = blob.download_as_bytes(if_generation_match=blob.generation, checksum="crc32c", timeout=120)
        metadata = {"name": object_name, "bucket": bucket, "generation": str(blob.generation),
                    "size": blob.size, "sha256": sha(raw), "crc32c": blob.crc32c}
    if (len(raw) != metadata["size"] or sha(raw) != metadata["sha256"]
            or metadata["name"] != object_name or metadata["bucket"] != bucket
            or generation is not None and str(metadata["generation"]) != str(generation)):
        raise ValueError("GCS capture byte verification failed")
    target = root / "sources" / metadata["sha256"]
    if target.exists() and target.read_bytes() != raw:
        raise ValueError("immutable capture collision")
    if not target.exists():
        private_write(target, raw)
    receipt = {**metadata, "source_uri": f"gs://{bucket}/{object_name}#{metadata['generation']}",
               "local_path": str(target.resolve()), "publication_version_verified": False,
               "transport": "ssh_existing_credentials" if ssh_host else "application_default_credentials"}
    receipt_path = root / "captures" / f'{metadata["sha256"]}-{metadata["generation"]}.json'
    private_write(receipt_path, canonical(receipt).encode())
    if generation is not None:
        private_write(cache, canonical(receipt).encode())
    return receipt
