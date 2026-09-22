"""Owned, bounded child process for private, CPU-heavy input reconstruction.

Python audit hooks reduce accidental I/O; they are not an OS security sandbox.
Only installed server code executes. Submitted bytes are strict JSON, not code.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

MAX_OUTPUT_BYTES = 128 * 1024
WALL_SECONDS = 45
CPU_SECONDS = 30


async def _stop(process):
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    await process.wait()


async def reconstruct_in_worker(raw):
    from services.ml_audited_dataset import loads
    from services.ml_use_reconstruction import MAX_ENVELOPE_BYTES
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_ENVELOPE_BYTES:
        raise ValueError("ml_use_reconstruction_invalid")
    # The path is implementation-owned, never a supplied file/URL/command.
    root = str(Path(__file__).resolve().parents[1])
    bootstrap = "import sys;sys.path.insert(0," + repr(root) + ");from services.ml_use_reconstruction_worker import main;main()"
    creation = asyncio.create_task(asyncio.create_subprocess_exec(
        sys.executable, "-I", "-B", "-c", bootstrap, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=subprocess.DEVNULL,
        env={"LANG": "C.UTF-8", "PYTHONHASHSEED": "0"}, limit=MAX_OUTPUT_BYTES + 1))
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
                if len(output) > MAX_OUTPUT_BYTES:
                    raise ValueError("ml_use_reconstruction_output_limit")
            return bytes(output)

        async with asyncio.timeout(WALL_SECONDS):
            async with asyncio.TaskGroup() as group:
                group.create_task(send())
                received = group.create_task(receive())
                group.create_task(process.wait())
        if process.returncode != 0:
            raise ValueError("ml_use_reconstruction_failed")
        return loads(received.result())
    finally:
        await asyncio.shield(_stop(process))


def _io_guard(event, args):
    if event in {"socket.__new__", "socket.connect", "socket.getaddrinfo", "subprocess.Popen", "os.system",
                 "os.fork", "os.forkpty", "os.exec", "os.posix_spawn", "sqlite3.connect",
                 "os.remove", "os.rename", "os.mkdir", "os.rmdir", "os.chmod", "os.link", "os.symlink", "os.truncate"}:
        raise RuntimeError("reconstruction_io_forbidden")
    if event == "open":
        mode, flags = args[1:3]
        if (isinstance(mode, str) and any(char in mode for char in "wax+")) or (
            isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
            raise RuntimeError("reconstruction_write_forbidden")


def main():
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS + 1))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    if sys.platform.startswith("linux"):
        resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024 * 1024, 1536 * 1024 * 1024))
    sys.addaudithook(_io_guard)
    from services import ml_baseline_numerics as numerics
    from services import ml_baseline_rehearsal as baseline
    from services.ml_audited_dataset import canonical
    from services.ml_use_reconstruction import MAX_ENVELOPE_BYTES, reconstruct

    def denied(*_args, **_kwargs):
        raise RuntimeError("model_fitting_forbidden")

    numerics.fit_select = numerics.predict = denied
    baseline._evaluate_prepared = baseline.run_synthetic_rehearsal = denied
    try:
        report = reconstruct(sys.stdin.buffer.read(MAX_ENVELOPE_BYTES + 1))
        raw = canonical(report)
        if len(raw) > MAX_OUTPUT_BYTES:
            raise ValueError("reconstruction_output_limit")
        sys.stdout.buffer.write(raw)
    except Exception:
        raise SystemExit(2) from None
