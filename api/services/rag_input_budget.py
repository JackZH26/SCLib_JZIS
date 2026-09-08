"""Count the exact frozen Gemini text request before any generation.

Provider CountTokens is a preflight observation, not an immutable model-version
attestation or final billed usage. Bytes only bound local/request memory. Neither
UTF-8 bytes, characters nor a foreign tokenizer are called Gemini tokens here.
No source is truncated, dropped or summarized by this boundary.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass, field

from google.genai import types

from models.rag_input_budget import (
    DEFAULT_BYTE_LIMIT,
    DEFAULT_INPUT_TOKEN_LIMIT,
    HARD_BYTE_LIMIT,
    HARD_INPUT_TOKEN_LIMIT,
    INPUT_PROFILE,
    RagInputBudgetReport,
)

_MODEL = re.compile(r"gemini-[A-Za-z0-9][A-Za-z0-9._-]{0,119}\Z")
MAX_MEASURED_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class FrozenRagRequest:
    model: str
    profile: str
    request_sha256: str
    payload_bytes: int
    byte_limit: int
    _payload_json: str = field(repr=False)


class RagInputBudgetError(RuntimeError):
    """Sanitized operational failure; no provider errors or source text."""

    def __init__(self, reason_code: str, report: RagInputBudgetReport, *, provider_attempted: bool = False):
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.report = report
        self.provider_attempted = provider_attempted


def _reject(reason, *, model=None, byte_limit=DEFAULT_BYTE_LIMIT, payload_bytes=None):
    raise RagInputBudgetError(reason, RagInputBudgetReport(status="rejected", model=model,
        byte_limit=byte_limit, payload_bytes=payload_bytes, generation_started=False)) from None


def _serialize_request(*, model, contents, system_instruction, max_output_tokens, resource_limit, byte_limit):
    if type(model) is not str or not _MODEL.fullmatch(model):
        _reject("rag_input_profile_unsupported", byte_limit=byte_limit)
    if (type(contents) is not str or type(system_instruction) is not str
            or not contents.strip() or not system_instruction.strip()
            or type(max_output_tokens) is not int or not 1 <= max_output_tokens <= 8192):
        _reject("rag_input_payload_invalid", model=model, byte_limit=byte_limit)
    # A cheap lower-bound rejection prevents giant serialization allocations.
    # No actual byte count is reported until the complete JSON is serialized.
    if len(contents) + len(system_instruction) > resource_limit:
        _reject("rag_input_byte_limit_exceeded", model=model, byte_limit=byte_limit)
    escaped_lower_bound = 0
    try:
        for text in (contents, system_instruction):
            for start in range(0, len(text), 65536):
                # JSON string quoting is additive per Unicode code point.
                # Bound expansion before allocating a whole large JSON string.
                fragment = text[start:start + 65536]
                escaped_lower_bound += len(json.dumps(fragment, ensure_ascii=False).encode("utf-8")) - 2
                if escaped_lower_bound > resource_limit:
                    _reject("rag_input_byte_limit_exceeded", model=model, byte_limit=byte_limit)
    except UnicodeError:
        _reject("rag_input_payload_invalid", model=model, byte_limit=byte_limit)
    payload = {"profile": INPUT_PROFILE, "model": model,
        "contents": [{"role": "user", "parts": [{"text": contents}]}],
        "system_instruction": {"parts": [{"text": system_instruction}]},
        "generation_config": {"temperature": 0.2, "max_output_tokens": max_output_tokens,
                              "thinking_config": {"thinking_budget": 0}}}
    try:
        serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        encoded = serialized.encode("utf-8")
    except (ValueError, UnicodeError):
        _reject("rag_input_payload_invalid", model=model, byte_limit=byte_limit)
    size = len(encoded)
    if size > resource_limit:
        _reject("rag_input_byte_limit_exceeded", model=model, byte_limit=byte_limit, payload_bytes=size)
    return serialized, encoded


def measure_request(*, model: str, contents: str, system_instruction: str, max_output_tokens: int = 1024) -> int:
    """Exact canonical complete-payload bytes for bounded packing trials.

    Trials may exceed the generation byte limit and then be excluded intact.
    The 64MiB measurement resource cap is not a model token count or transport
    wire-size claim; serialization includes the model/profile envelope too.
    """
    _, encoded = _serialize_request(model=model, contents=contents, system_instruction=system_instruction,
        max_output_tokens=max_output_tokens, resource_limit=MAX_MEASURED_BYTES, byte_limit=DEFAULT_BYTE_LIMIT)
    return len(encoded)


def build_request(*, model: str, contents: str, system_instruction: str,
                  max_output_tokens: int = 1024, byte_limit: int = DEFAULT_BYTE_LIMIT) -> FrozenRagRequest:
    """Freeze full input under the stricter generation byte limit.

    Only the current text-only configuration is supported; tools, cache IDs,
    media, automatic routing and external URIs cannot enter this profile.
    """
    if type(byte_limit) is not int or not 1 <= byte_limit <= HARD_BYTE_LIMIT:
        _reject("rag_input_budget_invalid")
    serialized, encoded = _serialize_request(model=model, contents=contents, system_instruction=system_instruction,
        max_output_tokens=max_output_tokens, resource_limit=byte_limit, byte_limit=byte_limit)
    size = len(encoded)
    return FrozenRagRequest(model, INPUT_PROFILE, hashlib.sha256(encoded).hexdigest(), size, byte_limit, serialized)


def _checked_payload(request):
    try:
        if type(request) is not FrozenRagRequest or type(request._payload_json) is not str or len(request._payload_json) > HARD_BYTE_LIMIT:
            raise ValueError
        value = json.loads(request._payload_json)
        checked = build_request(model=value["model"], contents=value["contents"][0]["parts"][0]["text"],
            system_instruction=value["system_instruction"]["parts"][0]["text"],
            max_output_tokens=value["generation_config"]["max_output_tokens"], byte_limit=request.byte_limit)
        if checked != request:
            raise ValueError
        return value
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, RecursionError, RagInputBudgetError):
        _reject("rag_input_payload_invalid")


def _duration(value):
    return type(value) in (int, float) and 0 < value <= 120 and math.isfinite(value)


def generate_with_budget(client, request: FrozenRagRequest, *, max_input_tokens: int = DEFAULT_INPUT_TOKEN_LIMIT,
                         timeout_seconds: float = 30, count_timeout_seconds: float = 5,
                         stop_event=None):
    """Blocking count+generation, one deadline and one attempt per RPC.

    Caller must signal stop_event when its worker await times out/cancels. An
    in-flight synchronous SDK call cannot be forcibly cancelled, but a late
    count never starts generation after the event/deadline. All actual remote
    calls must be mocked in tests; this module itself performs no test calls.
    """
    payload = _checked_payload(request)
    if (type(max_input_tokens) is not int or not 1 <= max_input_tokens <= HARD_INPUT_TOKEN_LIMIT
            or not _duration(timeout_seconds) or not _duration(count_timeout_seconds)):
        _reject("rag_input_budget_invalid", model=request.model, byte_limit=request.byte_limit)
    started = time.monotonic()
    deadline = started + timeout_seconds
    base = dict(model=request.model, profile=request.profile, request_sha256=request.request_sha256,
        payload_bytes=request.payload_bytes, byte_limit=request.byte_limit, max_input_tokens=max_input_tokens)
    input_tokens, generation_started, provider_attempted = None, False, False

    def fail(reason, status="unavailable"):
        raise RagInputBudgetError(reason, RagInputBudgetReport(status=status, input_tokens=input_tokens,
            generation_started=generation_started, **base), provider_attempted=provider_attempted) from None

    def remaining():
        try:
            stopped = stop_event.is_set() if stop_event is not None else False
            if type(stopped) is not bool:
                raise ValueError
        except Exception:
            fail("rag_input_cancellation_unavailable")
        if stopped:
            fail("rag_input_cancelled")
        value = deadline - time.monotonic()
        if value < 0.001:
            fail("rag_input_deadline_exceeded")
        return value

    def options(seconds):
        return types.HttpOptions(timeout=max(1, int(seconds * 1000)), retry_options=types.HttpRetryOptions(attempts=1))

    remaining()
    try:
        models = client.models
        count_config = types.CountTokensConfig(
            system_instruction=payload["system_instruction"],
            generation_config=types.GenerationConfig(**payload["generation_config"]),
            http_options=options(min(count_timeout_seconds, remaining())))
        provider_attempted = True
        count = models.count_tokens(model=request.model, contents=payload["contents"], config=count_config)
    except RagInputBudgetError:
        raise
    except Exception:
        fail("rag_input_count_unavailable")
    remaining()
    try:
        observed = getattr(count, "total_tokens", None)
    except Exception:
        fail("rag_input_count_invalid")
    if type(observed) is not int or not 1 <= observed <= 2147483647:
        fail("rag_input_count_invalid")
    input_tokens = observed
    if observed > max_input_tokens:
        fail("rag_input_token_limit_exceeded", status="rejected")
    # Reconstruct from frozen bytes: even a mutating test/client count method
    # cannot alter the question, system instructions or source JSON to generate.
    payload = _checked_payload(request)
    config = types.GenerateContentConfig(system_instruction=payload["system_instruction"],
        **payload["generation_config"], http_options=options(remaining()))
    remaining()
    generation_started = True
    try:
        response = models.generate_content(model=request.model, contents=payload["contents"], config=config)
    except Exception:
        fail("rag_input_generation_unavailable")
    remaining()
    return response, RagInputBudgetReport(status="counted", input_tokens=input_tokens,
        generation_started=True, **base)
