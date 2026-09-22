"""Stream exact ML08 originals/context through an owned, bounded, read-only child.

The parent never buffers the complete upload. Context is hashed incrementally;
neither parent nor child writes source files, follows references or opens archives.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import subprocess
import sys
from pathlib import Path

from services import ml_pilot_canary as canary
from services import ml_pilot_documents as documents
from services import ml_pilot_review_documents as review
from services.ml_pilot_registration_documents import identifier
from services.ml_use_reconstruction_worker import _io_guard, _stop

VERSION = "ml08-evidence-upload/1.0.0"
PROOF_VERSION = "ml08-evidence-integrity/1.0.0"
MEDIA_TYPE = "application/vnd.sclib.ml08-evidence-v1"
MAGIC = b"SCLIB-ML08-EVIDENCE-1\n"
MAX_METADATA_BYTES = 1024 * 1024
MAX_ENVELOPE_BYTES = (
    len(MAGIC)
    + 9
    + MAX_METADATA_BYTES
    + 4 * documents.MAX_BYTES
    + canary.MAX_BYTES
    + canary.MAX_EVIDENCE_BYTES
)
MAX_OUTPUT_BYTES = review.MAX_PROJECTION_BYTES + 32768
MAX_CHUNKS = 65536
WALL_SECONDS = 45
CPU_SECONDS = 30
BLOCK = 65536
ORIGINALS = ("selection", "protocol", "reviews", "conclusion", "canary")
require = canary.require


class EvidenceLimitError(ValueError):
    """Transport budget exhausted; no original bytes are included in errors."""


def reference(params):
    require(
        type(params) is dict
        and set(params) == {"participant_id", "participant_sha256", "registration_sha256"}
    )
    identifier(params["participant_id"])
    require(
        all(
            type(params[key]) is str and canary.HASH.fullmatch(params[key])
            for key in ("participant_sha256", "registration_sha256")
        )
    )
    return params


def implementation():
    return {
        "version": PROOF_VERSION,
        "scope": "selected_installed_sources_not_runtime_attestation",
        "canary": canary.implementation(),
        "review": review.implementation(),
        "worker_sha256": canary.sha(Path(__file__).read_bytes()),
    }


def metadata(raw):
    require(type(raw) is bytes and 0 < len(raw) <= MAX_METADATA_BYTES)
    value = documents.json_value(raw)
    require(documents.canonical(value) == raw)
    require(
        type(value) is dict
        and set(value)
        == {"version", "parameters", "selection_sha256", "review_log_sha256", "files"}
        and value["version"] == VERSION
    )
    params = reference(value["parameters"])
    require(
        all(
            type(pin) is str and canary.HASH.fullmatch(pin)
            for pin in [
                params["participant_sha256"],
                params["registration_sha256"],
                value["selection_sha256"],
                value["review_log_sha256"],
            ]
        )
    )
    entries = value["files"]
    require(type(entries) is list and 5 <= len(entries) <= 5 + canary.MAX_CONTEXTS)
    for index, entry in enumerate(entries):
        require(type(entry) is dict and set(entry) == {"key", "sha256", "size_bytes"})
        require(type(entry["sha256"]) is str and canary.HASH.fullmatch(entry["sha256"]))
        require(
            type(entry["size_bytes"]) is int
            and 0 < entry["size_bytes"] <= (canary.MAX_BYTES if index == 4 else documents.MAX_BYTES)
        )
        require(entry["key"] == (ORIGINALS[index] if index < 5 else entry["sha256"] + ".bin"))
    contexts = entries[5:]
    require([row["sha256"] for row in contexts] == sorted({row["sha256"] for row in contexts}))
    require(sum(row["size_bytes"] for row in contexts) <= canary.MAX_EVIDENCE_BYTES)
    return value


class Reader:
    def __init__(self, stream):
        self.stream = stream
        self.hash = hashlib.sha256()
        self.size = 0

    def read(self, count):
        require(type(count) is int and 0 < count <= BLOCK)
        raw = self.stream.read(count)
        require(type(raw) is bytes and len(raw) <= count)
        self.size += len(raw)
        require(self.size <= MAX_ENVELOPE_BYTES)
        self.hash.update(raw)
        return raw

    def exact(self, count, *, capture=True):
        require(type(count) is int and 0 < count <= canary.MAX_BYTES)
        remaining, digest = count, hashlib.sha256()
        result = bytearray() if capture else None
        while remaining:
            raw = self.read(min(BLOCK, remaining))
            require(bool(raw), "pilot_evidence_truncated")
            digest.update(raw)
            if capture:
                result.extend(raw)
            remaining -= len(raw)
        return (bytes(result) if capture else None), digest.hexdigest()


def prepare(stream):
    before = implementation()
    reader = Reader(stream)
    magic, _ = reader.exact(len(MAGIC))
    require(magic == MAGIC)
    length, _ = reader.exact(9)
    require(re.fullmatch(rb"[0-9a-f]{8}\n", length))
    size = int(length[:8], 16)
    require(0 < size <= MAX_METADATA_BYTES)
    raw_meta, _ = reader.exact(size)
    value = metadata(raw_meta)
    originals = {}
    for entry in value["files"][:5]:
        raw, pin = reader.exact(entry["size_bytes"])
        require(pin == entry["sha256"], "pilot_evidence_file_hash_mismatch")
        originals[entry["key"]] = raw
    pins = {entry["key"] + "_file_sha256": entry["sha256"] for entry in value["files"][:4]}
    projection = review.checked(
        review.project(
            **{key + "_raw": originals[key] for key in ORIGINALS[:4]},
            **pins,
            selection_sha256=value["selection_sha256"],
            review_log_sha256=value["review_log_sha256"],
        )
    )
    require(
        projection["declared_canary_sha256"] == value["files"][4]["sha256"],
        "pilot_conclusion_canary_mismatch",
    )
    # Reject invalid/cross-version bundles before receiving any context leaves.
    supplied = canary.loads(originals["canary"])
    require(
        type(supplied) is dict
        and supplied.get("version") == canary.VERSION
        and supplied.get("implementation") == before["canary"]
    )
    del supplied
    selection = documents.json_value(originals["selection"])
    reviews = documents.review_records(originals["reviews"])
    required = canary.evidence_hashes(reviews)
    entries = value["files"][5:]
    require([row["sha256"] for row in entries] == required, "pilot_context_inventory_mismatch")
    evidence = []
    for entry in entries:
        _, pin = reader.exact(entry["size_bytes"], capture=False)
        require(pin == entry["sha256"], "pilot_context_bytes_mismatch")
        evidence.append({"sha256": pin, "size_bytes": entry["size_bytes"]})
    require(reader.read(1) == b"", "pilot_evidence_trailing_bytes")
    bundle = canary.compile_canary(
        selection,
        reviews,
        selection_sha256=value["selection_sha256"],
        review_log_sha256=value["review_log_sha256"],
        input_pins={
            key: pins[key]
            for key in ("selection_file_sha256", "reviews_file_sha256", "protocol_file_sha256")
        },
        source=before["canary"],
        evidence=evidence,
    )
    require(canary.canonical(bundle) == originals["canary"], "pilot_canary_replay_mismatch")
    require(implementation() == before, "pilot_implementation_changed")
    proof = {
        "version": PROOF_VERSION,
        "canary_version": canary.VERSION,
        "canary_sha256": projection["declared_canary_sha256"],
        "context_inventory_sha256": canary.digest(evidence),
        "context_file_count": len(evidence),
        "context_bytes_hashed": sum(row["size_bytes"] for row in evidence),
        "context_bytes_embedded": False,
        "context_bytes_checked": True,
        "canary_replay_verified": True,
        "conclusion_documentary_gate_verified": True,
        "implementation_sha256": canary.digest(before),
    }
    return {
        "version": VERSION,
        "input_sha256": reader.hash.hexdigest(),
        "parameters": value["parameters"],
        "document_check": projection,
        "implementation": before["review"],
        "evidence_implementation": before,
        "canary_check": proof,
    }


def checked(result):
    require(
        type(result) is dict
        and set(result)
        == {
            "version",
            "input_sha256",
            "parameters",
            "document_check",
            "implementation",
            "evidence_implementation",
            "canary_check",
        }
    )
    require(result["version"] == VERSION and result["evidence_implementation"] == implementation())
    require(result["implementation"] == review.implementation())
    reference(result["parameters"])
    projection = review.checked(result["document_check"])
    proof = result["canary_check"]
    require(
        type(proof) is dict
        and set(proof)
        == {
            "version",
            "canary_version",
            "canary_sha256",
            "context_inventory_sha256",
            "context_file_count",
            "context_bytes_hashed",
            "context_bytes_embedded",
            "context_bytes_checked",
            "canary_replay_verified",
            "conclusion_documentary_gate_verified",
            "implementation_sha256",
        }
    )
    require(proof["version"] == PROOF_VERSION and proof["canary_version"] == canary.VERSION)
    require(
        proof["canary_sha256"] == projection["declared_canary_sha256"]
        and proof["implementation_sha256"] == canary.digest(result["evidence_implementation"])
    )
    require(
        all(
            type(pin) is str and canary.HASH.fullmatch(pin)
            for pin in (result["input_sha256"], proof["context_inventory_sha256"])
        )
    )
    count, size = proof["context_file_count"], proof["context_bytes_hashed"]
    require(
        type(count) is int
        and 0 <= count <= canary.MAX_CONTEXTS
        and type(size) is int
        and 0 <= size <= canary.MAX_EVIDENCE_BYTES
    )
    require(
        (count == 0 and size == 0 and proof["context_inventory_sha256"] == canary.digest([]))
        or (0 < count <= size <= count * canary.MAX_CONTEXT_BYTES)
    )
    require(
        proof["context_bytes_embedded"] is False
        and all(
            proof[key] is True
            for key in (
                "context_bytes_checked",
                "canary_replay_verified",
                "conclusion_documentary_gate_verified",
            )
        )
    )
    return result


async def check_in_worker(stream):
    root = str(Path(__file__).resolve().parents[1])
    bootstrap = (
        "import sys;sys.path.insert(0,"
        + repr(root)
        + ");from services.ml_pilot_evidence_worker import main;main()"
    )
    creation = asyncio.create_task(
        asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-B",
            "-c",
            bootstrap,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={"LANG": "C.UTF-8", "PYTHONHASHSEED": "0"},
            limit=MAX_OUTPUT_BYTES + 1,
        )
    )
    try:
        process = await asyncio.shield(creation)
    except BaseException:
        process = await creation
        await asyncio.shield(_stop(process))
        raise
    observed = hashlib.sha256()
    try:

        async def send():
            size = chunks = 0
            async for part in stream:
                require(type(part) is bytes)
                chunks += 1
                size += len(part)
                if chunks > MAX_CHUNKS or size > MAX_ENVELOPE_BYTES:
                    raise EvidenceLimitError("pilot_evidence_transport_limit")
                observed.update(part)
                view = memoryview(part)
                for offset in range(0, len(part), BLOCK):
                    process.stdin.write(view[offset : offset + BLOCK])
                    await process.stdin.drain()
            process.stdin.close()
            await process.stdin.wait_closed()

        async def receive():
            output = bytearray()
            while part := await process.stdout.read(min(BLOCK, MAX_OUTPUT_BYTES + 1 - len(output))):
                output.extend(part)
                require(len(output) <= MAX_OUTPUT_BYTES)
            return bytes(output)

        try:
            async with asyncio.timeout(WALL_SECONDS):
                async with asyncio.TaskGroup() as group:
                    group.create_task(send())
                    received = group.create_task(receive())
                    group.create_task(process.wait())
        except ExceptionGroup as exc:
            leaves = []
            pending = [exc]
            while pending:
                item = pending.pop()
                if isinstance(item, BaseExceptionGroup):
                    pending.extend(item.exceptions)
                else:
                    leaves.append(item)
            if any(isinstance(item, EvidenceLimitError) for item in leaves):
                raise EvidenceLimitError("pilot_evidence_transport_limit") from None
            if all(
                isinstance(item, (ValueError, BrokenPipeError, ConnectionResetError))
                for item in leaves
            ):
                raise ValueError("pilot_evidence_worker_rejected") from None
            raise
        require(process.returncode == 0, "pilot_evidence_worker_rejected")
        result = checked(documents.json_value(received.result()))
        require(result["input_sha256"] == observed.hexdigest())
        return result
    finally:
        await asyncio.shield(_stop(process))


def main():
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS + 1))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    if sys.platform.startswith("linux"):
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    sys.addaudithook(_io_guard)
    try:
        result = checked(prepare(sys.stdin.buffer))
        raw = documents.canonical(result)
        require(len(raw) <= MAX_OUTPUT_BYTES)
        sys.stdout.buffer.write(raw)
    except Exception:
        raise SystemExit(2) from None
