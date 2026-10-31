"""Bounded provider adapters. No provider writes the queue or canonical database."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

import httpx

from .contract import canonical
from .sources import private_write
from . import page_images


class ProviderFailure(RuntimeError):
    def __init__(self, code: str, retryable=False, usage=None):
        super().__init__(code)
        self.code, self.retryable, self.usage = code, retryable, usage or {}


@dataclass
class ProviderResult:
    text: str
    usage: dict
    provider: str
    model: str
    response_id: str | None
    elapsed_seconds: float


class CodexProvider:
    name = "codex"

    def __init__(self, executable=None):
        self.executable = executable or shutil.which("codex")
        if not self.executable:
            raise ProviderFailure("codex_executable_unavailable")

    def extract(self, prompt: str, schema: dict, config: dict, directory: Path) -> ProviderResult:
        try:images=page_images.validate_inputs(config.get('image_inputs',[]))
        except ValueError as exc:raise ProviderFailure(str(exc)) from None
        schema_path, output = directory / "schema.json", directory / "response.json"
        private_write(schema_path, canonical(schema).encode())
        command = [self.executable, "exec", "--ignore-user-config", "--ephemeral",
                   "--skip-git-repo-check", "--sandbox", "read-only", "--color", "never",
                   "--json", "--model", config["model"],
                   "-c", f'model_reasoning_effort="{config["reasoning"]}"',
                   "-c", 'approval_policy="never"', "-c", 'web_search="disabled"',
                   "--output-schema", str(schema_path), "--output-last-message", str(output),
                   "--cd", str(directory)]
        # These switches are verified against the installed CLI feature catalogue.
        for feature in ("shell_tool", "apps", "plugins", "multi_agent", "memories",
                        "hooks", "computer_use", "browser_use", "image_generation",
                        "skill_search"):
            command.extend(["--disable", feature])
        for item in images:command.extend(['--image',item['path']])
        command.append("-")
        version = subprocess.run([self.executable, "--version"], capture_output=True, text=True, timeout=15)
        private_write(directory / "provider-version.json", canonical({
            "executable": self.executable, "version": version.stdout.strip() if version.returncode == 0 else None,
        }).encode())
        private_write(directory / "command.json", canonical(command).encode())
        started = time.monotonic()
        # Exact prompt is retained privately and hashed by the worker.
        with (directory / "events.jsonl").open("wb") as events, (directory / "stderr.log").open("wb") as errors:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=events, stderr=errors,
                                       start_new_session=True)
            try:
                process.communicate(input=prompt.encode(), timeout=config["timeout_seconds"])
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
                raise ProviderFailure("codex_timeout_or_interruption", retryable=True) from None
        elapsed = time.monotonic() - started
        try:after_images=page_images.validate_inputs(images)
        except ValueError as exc:raise ProviderFailure(str(exc)) from None
        if after_images!=images:raise ProviderFailure('provider_image_input_changed')
        if 'image_inputs' in config:
            private_write(directory/'image-inputs.json',canonical(page_images.receipt(images)).encode())
        usage, completed, failed, tool_used, thread_id = {}, False, False, False, None
        for line in (directory / "events.jsonl").read_text().splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "turn.completed":
                completed = True
                usage = event.get("usage", {})
            elif event.get("type") == "thread.started":
                thread_id = event.get("thread_id")
            elif event.get("type") in {"turn.failed", "error"}:
                failed = True
            item = event.get("item", {})
            if item.get("type") in {"command_execution", "mcp_tool_call", "web_search", "file_change"}:
                tool_used = True
        if tool_used:
            raise ProviderFailure("unexpected_worker_tool_use", usage=usage)
        if process.returncode or failed or not completed:
            raise ProviderFailure("codex_turn_failed", usage=usage)
        if not output.is_file() or not output.stat().st_size:
            raise ProviderFailure("codex_missing_output", usage=usage)
        return ProviderResult(output.read_text(), usage, self.name, config["model"], thread_id, elapsed)


class ResponsesProvider:
    name = "responses"

    def extract(self, prompt: str, schema: dict, config: dict, directory: Path) -> ProviderResult:
        if config.get('image_inputs'):raise ProviderFailure('responses_image_inputs_unsupported')
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ProviderFailure("openai_api_key_unavailable")
        body = {"model": config["model"], "input": prompt, "store": False,
                "reasoning": {"effort": config["reasoning"]},
                "max_output_tokens": config["max_output_tokens"],
                "text": {"format": {"type": "json_schema", "name": "materials_ner",
                                    "strict": True, "schema": schema}}}
        started = time.monotonic()
        try:
            response = httpx.post("https://api.openai.com/v1/responses", json=body,
                                  headers={"Authorization": f"Bearer {key}"},
                                  timeout=config["timeout_seconds"])
        except httpx.TimeoutException:
            raise ProviderFailure("responses_timeout", retryable=True) from None
        except httpx.TransportError:
            raise ProviderFailure("responses_transport_error", retryable=True) from None
        private_write(directory / "provider-response.json", response.content)
        if response.status_code != 200:
            raise ProviderFailure(f"responses_http_{response.status_code}",
                                  retryable=response.status_code in {408, 429, 500, 502, 503, 504})
        try:
            data = response.json()
        except ValueError:
            raise ProviderFailure("responses_non_json") from None
        usage = data.get("usage") or {}
        if data.get("status") != "completed":
            raise ProviderFailure("responses_incomplete", usage=usage)
        parts = [content for item in data.get("output", []) if item.get("type") == "message"
                 for content in item.get("content", [])]
        if any(part.get("type") == "refusal" for part in parts):
            raise ProviderFailure("responses_refusal", usage=usage)
        text = "".join(part["text"] for part in parts if part.get("type") == "output_text")
        if not text:
            raise ProviderFailure("responses_missing_output", usage=usage)
        return ProviderResult(text, usage, self.name, data.get("model", config["model"]),
                              data.get("id"), time.monotonic() - started)
