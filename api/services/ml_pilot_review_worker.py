"""Owned child for the four-file pre-signoff check; no source access or writes."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

from services import ml_pilot_review_documents as documents
from services.ml_pilot_documents import canonical, json_value
from services.ml_pilot_registration_documents import decode, identifier
from services.ml_use_reconstruction_worker import _io_guard, _stop

VERSION = "ml08-review-upload/1.0.0"
WALL_SECONDS = 35
CPU_SECONDS = 25
MAX_OUTPUT_BYTES = documents.MAX_PROJECTION_BYTES + 16384
require = documents.require


def prepare(raw):
    require(type(raw) is bytes and 0 < len(raw) <= documents.MAX_ENVELOPE_BYTES)
    from services import ml_pilot_accounting as accounting
    from services import ml_pilot_documents as codec

    codec._preparse(raw)
    value = accounting._loads(raw.decode("utf-8"))
    names = ("selection", "reviews", "protocol", "conclusion")
    require(
        type(value) is dict
        and set(value)
        == {
            "version",
            "parameters",
            "selection_sha256",
            "review_log_sha256",
            *(name + "_base64" for name in names),
            *(name + "_file_sha256" for name in names),
        }
        and value["version"] == VERSION
    )
    params = value["parameters"]
    require(
        type(params) is dict
        and set(params) == {"participant_id", "participant_sha256", "registration_sha256"}
    )
    identifier(params["participant_id"])
    require(
        all(
            type(params[key]) is str and codec.HASH.fullmatch(params[key])
            for key in ("participant_sha256", "registration_sha256")
        )
    )
    before = documents.implementation()
    args = {
        **{name + "_raw": decode(value[name + "_base64"]) for name in names},
        **{name + "_file_sha256": value[name + "_file_sha256"] for name in names},
        "selection_sha256": value["selection_sha256"],
        "review_log_sha256": value["review_log_sha256"],
    }
    result = documents.checked(documents.project(**args))
    require(documents.implementation() == before)
    return {
        "version": VERSION,
        "input_sha256": documents.sha(raw),
        "parameters": params,
        "document_check": result,
        "implementation": before,
    }


async def check_in_worker(raw):
    require(type(raw) is bytes and 0 < len(raw) <= documents.MAX_ENVELOPE_BYTES)
    root = str(Path(__file__).resolve().parents[1])
    bootstrap = (
        "import sys;sys.path.insert(0,"
        + repr(root)
        + ");from services.ml_pilot_review_worker import main;main()"
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
        result = json_value(received.result())
        require(
            type(result) is dict
            and set(result)
            == {"version", "input_sha256", "parameters", "document_check", "implementation"}
            and result["version"] == VERSION
            and result["input_sha256"] == documents.sha(raw)
            and result["implementation"] == documents.implementation()
        )
        documents.checked(result["document_check"])
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
        raw = canonical(prepare(sys.stdin.buffer.read(documents.MAX_ENVELOPE_BYTES + 1)))
        require(len(raw) <= MAX_OUTPUT_BYTES)
        sys.stdout.buffer.write(raw)
    except Exception:
        raise SystemExit(2) from None
