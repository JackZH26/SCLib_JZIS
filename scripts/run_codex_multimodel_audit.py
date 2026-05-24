"""Run the OpenAI/Codex side of the Phase 2a multimodel audit.

This orchestration script deliberately keeps the actual extraction outside
Python: each pending (paper, prompt) is handed to `codex exec` in a fresh
ephemeral session, then the JSON-only final message is persisted with
`scripts/multimodel_audit.py save`.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone


REPO = pathlib.Path(__file__).resolve().parents[1]
AUDIT_DIR = REPO / "audit"
RUNS_DIR = AUDIT_DIR / "runs"
RESULTS_DIR = RUNS_DIR / "extraction_results"
EXEC_LOG_DIR = RUNS_DIR / "codex_exec_logs"
SCHEMA_DIR = RUNS_DIR / "schemas"
DB_PATH = AUDIT_DIR / "audit_review.db"

AUDIT_ENV = {
    "AUDIT_VENDOR": "openai",
    "AUDIT_MODEL_NAME": "gpt-5.5",
    "AUDIT_THINKING_MODE": "high",
    "AUDIT_AGENT_CLI": "codex",
}


@dataclass(frozen=True)
class Pending:
    paper_id: str
    arxiv_id: str
    prompt_version: str
    prompt_type: str

    @property
    def safe_arxiv_id(self) -> str:
        return self.arxiv_id.replace("/", "_")


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(AUDIT_ENV)
    return env


def _run_setup() -> None:
    subprocess.run(
        [sys.executable, "scripts/multimodel_audit.py", "setup"],
        cwd=REPO,
        env=_env(),
        check=True,
    )


def _pending() -> list[Pending]:
    proc = subprocess.run(
        [sys.executable, "scripts/multimodel_audit.py", "pending"],
        cwd=REPO,
        env=_env(),
        check=True,
        text=True,
        capture_output=True,
    )
    out: list[Pending] = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        paper_id, arxiv_id, prompt_version, prompt_type = line.split("\t")
        out.append(Pending(paper_id, arxiv_id, prompt_version, prompt_type))
    return out


def _prompt(item: Pending) -> str:
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/multimodel_audit.py",
            "prompt",
            "--arxiv-id",
            item.arxiv_id,
            "--prompt-type",
            item.prompt_type,
        ],
        cwd=REPO,
        env=_env(),
        check=True,
        text=True,
        capture_output=True,
    )
    return proc.stdout


def _schema_path(prompt_type: str) -> pathlib.Path:
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    path = SCHEMA_DIR / f"{prompt_type}_final_response.schema.json"
    if path.exists():
        return path
    if prompt_type == "material":
        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": True,
            },
        }
    elif prompt_type == "geo":
        schema = {
            "type": "object",
            "required": ["affiliations"],
            "additionalProperties": True,
            "properties": {
                "affiliations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": True,
                    },
                }
            },
        }
    else:
        raise ValueError(prompt_type)
    path.write_text(json.dumps(schema, indent=2))
    return path


def _result_path(item: Pending, attempt: int) -> pathlib.Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "" if attempt == 1 else f".attempt{attempt}"
    return RESULTS_DIR / f"{item.safe_arxiv_id}__{item.prompt_type}{suffix}.json"


def _base_result_path(item: Pending) -> pathlib.Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    return RESULTS_DIR / f"{item.safe_arxiv_id}__{item.prompt_type}.json"


def _exec_log_path(item: Pending, attempt: int) -> pathlib.Path:
    EXEC_LOG_DIR.mkdir(parents=True, exist_ok=True)
    return EXEC_LOG_DIR / f"{item.safe_arxiv_id}__{item.prompt_type}.attempt{attempt}.log"


async def _run_codex(item: Pending, attempt: int) -> tuple[int, float, pathlib.Path]:
    prompt = _prompt(item)
    out_path = _result_path(item, attempt)
    log_path = _exec_log_path(item, attempt)
    cmd = [
        "codex",
        "exec",
        "--ephemeral",
        "--ignore-rules",
        "-C",
        str(REPO),
        "-s",
        "read-only",
        "-m",
        "gpt-5.5",
        "-c",
        'model_reasoning_effort="high"',
        "--color",
        "never",
        "-o",
        str(out_path),
        "-",
    ]
    started = time.time()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=REPO,
        env=_env(),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate(prompt.encode())
    elapsed = time.time() - started
    log_path.write_bytes(stdout)
    return proc.returncode or 0, elapsed, out_path


def _save(item: Pending, out_path: pathlib.Path, error: str | None = None) -> str:
    cmd = [
        sys.executable,
        "scripts/multimodel_audit.py",
        "save",
        "--arxiv-id",
        item.arxiv_id,
        "--prompt-type",
        item.prompt_type,
    ]
    if error:
        cmd += ["--error", error]
    else:
        cmd += ["--result-file", str(out_path)]
    proc = subprocess.run(
        cmd,
        cwd=REPO,
        env=_env(),
        check=True,
        text=True,
        capture_output=True,
    )
    return proc.stdout.strip()


def _row_error(item: Pending) -> str | None:
    con = sqlite3.connect(DB_PATH)
    try:
        row = con.execute(
            """SELECT materials_error, affiliations_error
               FROM audit_extraction_model
               WHERE vendor='openai' AND model_name='gpt-5.5'
                 AND run_idx=0 AND paper_id=? AND prompt_version=?""",
            (item.paper_id, item.prompt_version),
        ).fetchone()
    finally:
        con.close()
    if not row:
        return "missing_after_save"
    return row[0] or row[1]


async def _worker(
    name: int,
    queue: asyncio.Queue[Pending],
    run_log: pathlib.Path,
    retries: int,
) -> None:
    while True:
        try:
            item = queue.get_nowait()
        except asyncio.QueueEmpty:
            return
        total_elapsed = 0.0
        final_error: str | None = None
        attempts_done = 0
        try:
            for attempt in range(1, retries + 2):
                attempts_done = attempt
                rc, elapsed, out_path = await _run_codex(item, attempt)
                total_elapsed += elapsed
                if rc != 0:
                    final_error = f"codex_exec_rc_{rc}"
                    continue
                save_msg = _save(item, out_path)
                final_error = _row_error(item)
                if final_error is None:
                    if attempt > 1:
                        _base_result_path(item).write_text(out_path.read_text())
                    break
                # Preserve failed attempt output, then retry once with fresh context.
                final_error = final_error[:200]
            if final_error is not None:
                _save(item, _result_path(item, attempts_done), error=final_error)
            status = "OK" if final_error is None else f"ERR:{final_error}"
        except Exception as exc:  # Keep the batch moving.
            final_error = type(exc).__name__ + ": " + str(exc)[:180]
            _save(item, _base_result_path(item), error=final_error)
            status = f"ERR:{final_error}"
        line = (
            f"{datetime.now(timezone.utc).isoformat()}\tworker={name}\t"
            f"{item.paper_id}\t{item.prompt_version}\t"
            f"runs_completed={attempts_done}\terrors={'' if final_error is None else final_error}\t"
            f"total_seconds={total_elapsed:.2f}\t{status}\n"
        )
        with run_log.open("a") as fh:
            fh.write(line)
        print(line, end="", flush=True)
        queue.task_done()


async def _main_async(args: argparse.Namespace) -> None:
    _run_setup()
    items = _pending()
    if args.limit:
        items = items[: args.limit]
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_log = RUNS_DIR / f"openai_{stamp}.log"
    run_log.write_text(
        "vendor=openai model=gpt-5.5 thinking=high mechanism=codex_exec_per_prompt\n"
    )
    print(f"pending={len(items)} concurrency={args.concurrency} log={run_log}")
    queue: asyncio.Queue[Pending] = asyncio.Queue()
    for item in items:
        queue.put_nowait(item)
    workers = [
        asyncio.create_task(_worker(i + 1, queue, run_log, args.retries))
        for i in range(args.concurrency)
    ]
    await asyncio.gather(*workers)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--retries", type=int, default=1)
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
