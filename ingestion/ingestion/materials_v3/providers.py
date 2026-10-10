"""Provider-specific transport, common input semantics and bounded output."""

from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass, field
from urllib.parse import urlsplit

import httpx

from .contract import digest, provider_schema
from .runtime import model_pin

_MODEL_PIN = model_pin()
MODEL = _MODEL_PIN["model_id"]
REVISION = _MODEL_PIN["revision"]


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    model: str
    revision: str | None = None
    context_tokens: int = 16384
    max_output_tokens: int = 4096
    timeout_seconds: int = 240
    reasoning_effort: str = "low"
    endpoint: str | None = None

    def __post_init__(self):
        if self.provider not in {"local_mlx", "gemini", "openai"}:
            raise ValueError("unknown_provider")
        if self.provider == "openai" and self.model != "gpt-6.1-sol":
            raise ValueError("pilot_openai_model_must_be_gpt_6_1_sol")
        if self.provider != "local_mlx" and self.endpoint is not None:
            raise ValueError("cloud_endpoint_override_not_supported")
        if any(
            type(v) is not int
            for v in (self.context_tokens, self.max_output_tokens, self.timeout_seconds)
        ):
            raise ValueError("provider_budget_requires_integer_values")
        if self.provider == "local_mlx" and (self.model != MODEL or self.revision != REVISION):
            raise ValueError("local_model_revision_not_frozen")
        if (
            self.max_output_tokens <= 0
            or self.timeout_seconds <= 0
            or self.context_tokens <= self.max_output_tokens
        ):
            raise ValueError("invalid_provider_budget")
        if self.provider == "openai" and self.reasoning_effort not in {
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        }:
            raise ValueError("unsupported_openai_reasoning_effort")
        if (
            self.provider == "gemini"
            and self.model.startswith("gemini-3")
            and self.reasoning_effort not in {"minimal", "low", "medium", "high"}
        ):
            raise ValueError("unsupported_gemini_thinking_level")

    @property
    def sha256(self):
        return digest(asdict(self))


def common_configuration_hash(config):
    provider = ProviderConfig(**config["provider"])
    return digest(
        {
            "semantics": {k: v for k, v in config.items() if k != "provider"},
            "generation_limits": {
                k: getattr(provider, k)
                for k in ("context_tokens", "max_output_tokens", "timeout_seconds")
            },
        }
    )


@dataclass
class Response:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    cached_tokens: int | None = None
    finish_reason: str = "stop"
    seconds: float = 0
    metadata: dict = field(default_factory=dict)


class ProviderError(RuntimeError):
    """Static error code; credentials and provider response bodies are not logged."""

    def __init__(self, code, *, receipt=None):
        super().__init__(code)
        self.receipt = receipt


class OutputLimit(ProviderError):
    pass


class ResourceLimit(ProviderError):
    pass


class HTTPProvider:
    def __init__(self, config: ProviderConfig, *, client=None):
        self.config = config
        self.client = client or httpx.Client(timeout=config.timeout_seconds, follow_redirects=False)
        if config.provider == "local_mlx":
            parsed = urlsplit(config.endpoint or "http://127.0.0.1:8096/v1/chat/completions")
            if (
                parsed.scheme != "http"
                or parsed.hostname != "127.0.0.1"
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("local_endpoint_must_be_literal_loopback_http")

    def _check_context_budget(self, result):
        count = result.input_tokens
        verified = type(count) is int and count >= 0
        result.metadata["input_context_budget_verified"] = verified
        if verified and count + self.config.max_output_tokens > self.config.context_tokens:
            result.metadata.update(
                generation_attempted=True,
                provider_finish_reason=result.finish_reason,
                input_context_budget_verified=False,
                reserved_output_tokens=self.config.max_output_tokens,
                context_tokens=self.config.context_tokens,
            )
            result.finish_reason = "input_limit"
            raise OutputLimit("observed_input_context_budget_exceeded", receipt=result)
        return result

    def generate(self, messages) -> Response:
        config, started = self.config, time.monotonic()
        if config.provider == "openai":
            key = os.environ.get("OPENAI_API_KEY")
            if not key:
                raise ProviderError("openai_credentials_unavailable")
            url = "https://api.openai.com/v1/responses"
            body = {
                "model": config.model,
                "input": messages,
                "max_output_tokens": config.max_output_tokens,
                "reasoning": {"effort": config.reasoning_effort},
                "store": False,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "materials_ner_v3",
                        "strict": True,
                        "schema": provider_schema(),
                    }
                },
            }
            headers = {"Authorization": "Bearer " + key}
        elif config.provider == "local_mlx":
            url = config.endpoint or "http://127.0.0.1:8096/v1/chat/completions"
            body = {
                "model": config.model,
                "messages": messages,
                "max_tokens": config.max_output_tokens,
                "temperature": 0,
                "chat_template_kwargs": {"enable_thinking": False},
            }
            headers = {}
        else:
            return self._gemini(messages, started)
        try:
            response = self.client.post(url, json=body, headers=headers)
        except httpx.HTTPError:
            raise ProviderError("provider_transport_failure") from None
        if response.status_code != 200:
            raise ProviderError("provider_http_" + str(response.status_code))
        try:
            raw = response.json()
            usage = raw.get("usage", {})
            if config.provider == "openai":
                text = "".join(
                    c.get("text", "")
                    for item in raw.get("output", [])
                    if item.get("type") == "message"
                    for c in item.get("content", [])
                    if c.get("type") == "output_text"
                )
                result = Response(
                    text,
                    usage.get("input_tokens"),
                    usage.get("output_tokens"),
                    usage.get("output_tokens_details", {}).get("reasoning_tokens"),
                    usage.get("input_tokens_details", {}).get("cached_tokens"),
                    seconds=time.monotonic() - started,
                    metadata={"response_id": raw.get("id"), "actual_model": raw.get("model")},
                )
                if raw.get("status") == "incomplete":
                    if raw.get("incomplete_details", {}).get("reason") == "max_output_tokens":
                        result.finish_reason = "length"
                        raise OutputLimit("output_limit", receipt=result)
                    raise ProviderError("provider_incomplete", receipt=result)
                return self._check_context_budget(result)
            choice = raw["choices"][0]
            result = Response(
                choice["message"]["content"],
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
                finish_reason=choice.get("finish_reason", "stop"),
                seconds=time.monotonic() - started,
            )
            if result.finish_reason == "length":
                raise OutputLimit("output_limit", receipt=result)
            return self._check_context_budget(result)
        except (KeyError, TypeError, ValueError):
            raise ProviderError("provider_response_invalid") from None

    def _gemini(self, messages, started):
        from google import genai
        from google.genai import types

        project = (
            os.environ.get("GCP_PROJECT_ID")
            or os.environ.get("GOOGLE_CLOUD_PROJECT")
            or os.environ.get("GCP_PROJECT")
        )
        if not project:
            raise ProviderError("gemini_project_unavailable")
        generation_options = (
            {
                "thinking_config": types.ThinkingConfig(
                    thinking_level=self.config.reasoning_effort.upper()
                )
            }
            if self.config.model.startswith("gemini-3")
            else {"temperature": 0, "thinking_config": types.ThinkingConfig(thinking_budget=0)}
        )
        try:
            with genai.Client(
                vertexai=True,
                project=project,
                location=os.environ.get("GCP_LOCATION", "global"),
                http_options=types.HttpOptions(timeout=self.config.timeout_seconds * 1000),
            ) as client:
                raw = client.models.generate_content(
                    model=self.config.model,
                    contents=messages[-1]["content"],
                    config=types.GenerateContentConfig(
                        system_instruction=messages[0]["content"],
                        max_output_tokens=self.config.max_output_tokens,
                        response_mime_type="application/json",
                        response_json_schema=provider_schema(),
                        **generation_options,
                    ),
                )
        except Exception:
            raise ProviderError("gemini_request_failure") from None
        usage = raw.usage_metadata
        result = Response(
            raw.text or "",
            getattr(usage, "prompt_token_count", None),
            getattr(usage, "candidates_token_count", None),
            getattr(usage, "thoughts_token_count", None),
            getattr(usage, "cached_content_token_count", None),
            seconds=time.monotonic() - started,
            metadata={"actual_model": getattr(raw, "model_version", None)},
        )
        if raw.candidates and str(raw.candidates[0].finish_reason).endswith("MAX_TOKENS"):
            result.finish_reason = "length"
            raise OutputLimit("output_limit", receipt=result)
        return self._check_context_budget(result)


class MLXProvider:
    """In-process single-model runtime; loaded once for an entire local batch."""

    def __init__(self, config: ProviderConfig, model_path: str, *, guard=None):
        if config.provider != "local_mlx":
            raise ValueError("mlx_requires_local_configuration")
        self.config, self.guard = config, guard
        from mlx_lm import load

        self.model, self.tokenizer = load(model_path)
        self.closed = False

    def close(self):
        import gc
        import mlx.core as mx

        self.closed = True
        self.model, self.tokenizer = None, None
        gc.collect()
        mx.clear_cache()

    def generate(self, messages):
        if getattr(self, "closed", False):
            raise ProviderError("local_provider_closed")
        import mlx.core as mx
        from mlx_lm import stream_generate
        from mlx_lm.sample_utils import make_sampler

        config = self.config
        prompt = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
        )
        tokens = self.tokenizer.encode(prompt)
        if len(tokens) + config.max_output_tokens > config.context_tokens:
            raise OutputLimit(
                "input_context_budget_requires_split",
                receipt=Response(
                    "",
                    len(tokens),
                    0,
                    finish_reason="input_limit",
                    metadata={"generation_attempted": False},
                ),
            )
        started, pieces, count, finish = time.monotonic(), [], 0, None

        def partial(reason):
            return Response(
                "".join(pieces),
                len(tokens),
                count,
                finish_reason=reason,
                seconds=time.monotonic() - started,
                metadata={
                    "metal_peak_bytes": mx.get_peak_memory(),
                    "enable_thinking": False,
                    "prefill_step_size": 512,
                },
            )

        def check(*_):
            if time.monotonic() - started > config.timeout_seconds:
                raise ProviderError("local_generation_timeout", receipt=partial("timeout"))
            if self.guard:
                try:
                    self.guard()
                except ResourceLimit as exc:
                    raise ResourceLimit(str(exc), receipt=partial("resource_exhausted")) from None

        check()
        for item in stream_generate(
            self.model,
            self.tokenizer,
            tokens,
            max_tokens=config.max_output_tokens,
            sampler=make_sampler(temp=0),
            prefill_step_size=512,
            prompt_progress_callback=check,
        ):
            if count % 32 == 0:
                check()
            pieces.append(item.text)
            count, finish = item.generation_tokens, item.finish_reason
        check()
        result = partial(finish or "unknown")
        if finish == "length":
            raise OutputLimit("output_limit", receipt=result)
        if finish != "stop":
            raise ProviderError("local_generation_missing_terminal", receipt=result)
        return result
