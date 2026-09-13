"""Owned, bounded ML08 upload checker; submitted content is never code.

Audit hooks are accident guards, not an OS sandbox. The child has no service
credentials, source URL access, write authority, ORM import or training path.
"""

from __future__ import annotations

import asyncio
import re
import subprocess
import sys
from pathlib import Path

from services import ml_pilot_registration_documents as documents
from services.ml_use_reconstruction_worker import _io_guard, _stop

VERSION = "ml08-registration-upload/1.0.0"
MAX_OUTPUT_BYTES = 128 * 1024
WALL_SECONDS = 20
CPU_SECONDS = 15
require = documents.require


def parameters(value, operation):
    require(type(value) is dict)
    value = dict(value)
    value.setdefault("dry_run", True)
    value.setdefault("expected_intent_sha256", None)
    common = {"request_key", "expected_intent_sha256", "dry_run"}
    required = common | (
        {"curator_grant_id"}
        if operation == "register"
        else {
            "participant_id",
            "participant_sha256",
            "registration_sha256",
            "reason_code",
            "supersedes_id",
            "supersedes_sha256",
        }
    )
    require(set(value) == required and type(value["dry_run"]) is bool)
    require(
        type(value["request_key"]) is str
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}", value["request_key"])
    )
    require(value["dry_run"] or value["expected_intent_sha256"] is not None)
    for key, item in value.items():
        if key.endswith("sha256") and item is not None:
            require(type(item) is str and re.fullmatch(r"[a-f0-9]{64}", item))
    if operation == "register":
        documents.identifier(value["curator_grant_id"])
    else:
        documents.identifier(value["participant_id"])
        require(
            type(value["participant_sha256"]) is str and type(value["registration_sha256"]) is str
        )
        require((value["supersedes_id"] is None) == (value["supersedes_sha256"] is None))
        if value["supersedes_id"] is not None:
            documents.identifier(value["supersedes_id"])
        require(
            type(value["reason_code"]) is str
            and re.fullmatch(r"[a-z][a-z0-9_]{0,159}", value["reason_code"])
        )
    return value


def prepare(raw):
    require(type(raw) is bytes and 0 < len(raw) <= documents.MAX_ENVELOPE_BYTES)
    from services import ml_pilot_accounting as accounting
    from services import ml_pilot_documents as codec

    codec._preparse(raw)
    value = accounting._loads(raw.decode("utf-8"))
    require(
        type(value) is dict
        and value.get("version") == VERSION
        and value.get("operation") in {"register", "accept"}
    )
    operation = value["operation"]
    fields = {
        "version",
        "operation",
        "parameters",
        "selection_base64",
        "protocol_base64",
        "selection_file_sha256",
        "protocol_file_sha256",
        "selection_sha256",
    }
    require(set(value) == fields | ({"bindings"} if operation == "register" else set()))
    args = parameters(value["parameters"], operation)
    inputs = {
        name: value[name]
        for name in ("selection_file_sha256", "protocol_file_sha256", "selection_sha256")
    }
    inputs.update(
        selection_raw=documents.decode(value["selection_base64"]),
        protocol_raw=documents.decode(value["protocol_base64"]),
    )
    before = documents.implementation()
    checked = (
        documents.check(**inputs, bindings=value["bindings"])
        if operation == "register"
        else documents.verify_files(**inputs)
    )
    require(documents.implementation() == before)
    return {
        "version": VERSION,
        "operation": operation,
        "parameters": args,
        "input_sha256": documents.sha(raw),
        "document_check": checked,
        "implementation": before,
    }


async def check_in_worker(raw):
    require(type(raw) is bytes and 0 < len(raw) <= documents.MAX_ENVELOPE_BYTES)
    root = str(Path(__file__).resolve().parents[1])
    bootstrap = (
        "import sys;sys.path.insert(0,"
        + repr(root)
        + ");from services.ml_pilot_registration_worker import main;main()"
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
    try:

        async def send():
            process.stdin.write(raw)
            await process.stdin.drain()
            process.stdin.close()
            await process.stdin.wait_closed()

        async def receive():
            output = bytearray()
            while part := await process.stdout.read(min(65536, MAX_OUTPUT_BYTES + 1 - len(output))):
                output.extend(part)
                require(len(output) <= MAX_OUTPUT_BYTES)
            return bytes(output)

        async with asyncio.timeout(WALL_SECONDS):
            async with asyncio.TaskGroup() as group:
                group.create_task(send())
                received = group.create_task(receive())
                group.create_task(process.wait())
        require(process.returncode == 0)
        from services.ml_pilot_documents import json_value

        result = json_value(received.result())
        require(
            type(result) is dict
            and set(result)
            == {
                "version",
                "operation",
                "parameters",
                "input_sha256",
                "document_check",
                "implementation",
            }
            and result["version"] == VERSION
            and result["input_sha256"] == documents.sha(raw)
            and result["implementation"] == documents.implementation()
        )
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
    from services.ml_pilot_documents import canonical

    try:
        result = prepare(sys.stdin.buffer.read(documents.MAX_ENVELOPE_BYTES + 1))
        raw = canonical(result)
        require(len(raw) <= MAX_OUTPUT_BYTES)
        sys.stdout.buffer.write(raw)
    except Exception:
        raise SystemExit(2) from None
