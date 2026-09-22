"""Read a synthetic frame on stdin; test a dependency-free installed wheel only."""

from __future__ import annotations

import asyncio
import importlib.abc
import io
import json
import sys
from pathlib import Path


def main():
    if not sys.flags.isolated:
        raise RuntimeError("evidence_probe_requires_isolated_python")

    class NoServerImports(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split(".")[0] in {
                "scripts",
                "main",
                "config",
                "models",
                "sqlalchemy",
                "redis",
                "httpx",
                "ingestion",
                "tiktoken",
            }:
                raise RuntimeError("evidence_probe_server_import_forbidden")

    sys.meta_path.insert(0, NoServerImports())
    from services import ml_pilot_canary as canary
    from services import ml_pilot_evidence_worker as worker
    from services import ml_pilot_review_documents as review

    installed = Path(sys.prefix).resolve()
    for module, names in [
        (canary, canary.SOURCE_FILES),
        (review, review.implementation()["files"]),
        (worker, ["ml_pilot_evidence_worker.py"]),
    ]:
        for name in names:
            if (
                not Path(module.__file__)
                .with_name(name)
                .resolve()
                .is_relative_to(installed)
            ):
                raise RuntimeError("evidence_probe_repository_fallback_forbidden")
    raw = sys.stdin.buffer.read(worker.MAX_ENVELOPE_BYTES + 1)
    if not 0 < len(raw) <= worker.MAX_ENVELOPE_BYTES:
        raise ValueError("evidence_probe_frame_limit")
    expected = worker.checked(worker.prepare(io.BytesIO(raw)))
    loop = asyncio.new_event_loop()  # Own asyncio wakeup pair, before socket guard.
    root = str(Path(worker.__file__).resolve().parents[1])
    bootstrap = (
        "import sys;sys.path.insert(0,"
        + repr(root)
        + ");from services.ml_pilot_evidence_worker import main;main()"
    )
    argv = [sys.executable, "-I", "-B", "-c", bootstrap]
    spawned = []

    def guard(event, args):
        if event == "subprocess.Popen":
            executable, actual, cwd, env = args
            if (
                executable != sys.executable
                or list(actual) != argv
                or cwd is not None
                or spawned
                or env != {"LANG": "C.UTF-8", "PYTHONHASHSEED": "0"}
            ):
                raise RuntimeError("evidence_probe_unowned_child_forbidden")
            spawned.append(True)
        elif event in {
            "socket.__new__",
            "socket.connect",
            "socket.getaddrinfo",
            "os.system",
            "os.fork",
            "os.posix_spawn",
            "os.exec",
        }:
            raise RuntimeError("evidence_probe_external_io_forbidden")

    sys.addaudithook(guard)

    async def stream():
        for offset in range(0, len(raw), 997):
            yield raw[offset : offset + 997]

    try:
        result = loop.run_until_complete(worker.check_in_worker(stream()))
    finally:
        loop.close()
    if result != expected or len(spawned) != 1:
        raise RuntimeError("evidence_probe_replay_mismatch")
    print(
        json.dumps(
            {
                "scope": "synthetic_installed_byte_replay_not_scientific_acceptance",
                "python": sys.version,
                "input_sha256": result["input_sha256"],
                "proof": result["canary_check"],
                "implementation": result["evidence_implementation"],
                "actual_owned_child_count": len(spawned),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
