"""Offline full-request provider-count boundary and actual SDK wire parity."""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from threading import Event
from types import SimpleNamespace

import pytest
from google import genai
from google.auth.credentials import AnonymousCredentials

from models.rag_input_budget import (
    DEFAULT_BYTE_LIMIT,
    HARD_BYTE_LIMIT,
    HARD_INPUT_TOKEN_LIMIT,
    RagInputBudgetReport,
)
from services import rag_input_budget as budget


def request(**changes):
    return budget.build_request(model="gemini-3.5-flash", contents='Question? Sources: [{"text":"超导 Ω <39 K"}]',
                                system_instruction="System instructions; language=en", **changes)


class FakeModels:
    def __init__(self, count=100, count_action=None, generation_action=None):
        self.count = count
        self.count_action = count_action
        self.generation_action = generation_action
        self.calls = []

    def count_tokens(self, **kwargs):
        self.calls.append(("count", copy.deepcopy(kwargs)))
        if self.count_action:
            self.count_action(kwargs)
        return SimpleNamespace(total_tokens=self.count)

    def generate_content(self, **kwargs):
        self.calls.append(("generate", copy.deepcopy(kwargs)))
        if self.generation_action:
            self.generation_action(kwargs)
        return SimpleNamespace(text="Synthetic response", usage_metadata=SimpleNamespace(prompt_token_count=101))


def run(models, prepared=None, **kwargs):
    return budget.generate_with_budget(SimpleNamespace(models=models), prepared or request(), **kwargs)


def test_full_input_system_and_generation_configuration_are_identical_for_count_and_generate():
    models = FakeModels()
    prepared = request()
    response, report = run(models, prepared)
    assert response.text == "Synthetic response"
    counted, generated = [item[1] for item in models.calls]
    assert counted["model"] == generated["model"] == prepared.model
    assert counted["contents"] == generated["contents"]
    assert counted["config"].system_instruction == generated["config"].system_instruction
    assert counted["config"].generation_config.model_dump(exclude_none=True) == {
        key: value for key, value in generated["config"].model_dump(exclude_none=True).items()
        if key not in {"system_instruction", "http_options"}}
    assert report.status == "counted" and report.input_tokens == 100 and report.generation_started
    assert report.input_tokens != response.usage_metadata.prompt_token_count  # preflight != billed/final usage
    assert report.count_method == "provider_count_tokens" and not report.scientific_acceptance
    assert report.request_sha256 == hashlib.sha256(prepared._payload_json.encode()).hexdigest()
    assert report.payload_bytes == len(prepared._payload_json.encode())
    assert "Sources" not in report.model_dump_json() and "System instructions" not in repr(prepared)


@pytest.mark.parametrize("change", ["model", "question", "metadata", "system", "language", "output"])
def test_digest_binds_every_input_and_profile_component(change):
    values = dict(model="gemini-3.5-flash", contents="Question? SourceJSON: []", system_instruction="System language=en")
    before = budget.build_request(**values)
    if change == "model":
        values["model"] = "gemini-2.5-flash"
    elif change in {"question", "metadata"}:
        values["contents"] += change
    elif change in {"system", "language"}:
        values["system_instruction"] += change
    else:
        values["max_output_tokens"] = 512
    assert budget.build_request(**values).request_sha256 != before.request_sha256
    assert budget.build_request(**dict(model="gemini-3.5-flash", contents="Question? SourceJSON: []",
        system_instruction="System language=en")).request_sha256 == before.request_sha256


def test_byte_limit_is_separate_from_provider_tokens_and_never_truncates_unicode():
    prepared = budget.build_request(model="gemini-3.5-flash", contents="超导" * 200,
        system_instruction="Language 中文; preserve every source condition")
    models = FakeModels(count=1)
    _, report = run(models, prepared, max_input_tokens=1)
    assert report.input_tokens == 1 and report.payload_bytes > 1000
    assert models.calls[1][1]["contents"][0]["parts"][0]["text"] == "超导" * 200
    with pytest.raises(budget.RagInputBudgetError) as caught:
        budget.build_request(model="gemini-3.5-flash", contents="超导" * 200,
            system_instruction="Language 中文; preserve every source condition", byte_limit=1000)
    assert caught.value.reason_code == "rag_input_byte_limit_exceeded"
    assert caught.value.report.input_tokens is None
    assert budget.measure_request(model="gemini-3.5-flash", contents="超导" * 200,
        system_instruction="Language 中文; preserve every source condition") > 1000


def test_byte_limit_includes_system_and_json_envelope_even_when_excerpt_fits():
    prepared = budget.build_request(model="gemini-3.5-flash", contents="x" * 300, system_instruction="y" * 300)
    with pytest.raises(budget.RagInputBudgetError) as caught:
        budget.build_request(model="gemini-3.5-flash", contents="x" * 300, system_instruction="y" * 300,
                             byte_limit=prepared.payload_bytes - 1)
    assert caught.value.report.payload_bytes == prepared.payload_bytes
    with pytest.raises(budget.RagInputBudgetError) as early:
        budget.build_request(model="gemini-3.5-flash", contents="x" * (HARD_BYTE_LIMIT + 1), system_instruction="y")
    assert early.value.report.payload_bytes is None  # not falsely reported as a complete serialized count


def test_packing_can_measure_complete_trial_larger_than_generation_hard_byte_limit():
    values = dict(model="gemini-3.5-flash", contents="literal\n\\\"超导" * 150000, system_instruction="System")
    measured = budget.measure_request(**values)
    assert measured > HARD_BYTE_LIMIT
    with pytest.raises(budget.RagInputBudgetError):
        budget.build_request(**values, byte_limit=HARD_BYTE_LIMIT)
    small = {**values, "contents": values["contents"][:1000]}
    assert budget.measure_request(**small) == budget.build_request(**small).payload_bytes


def test_measurement_resource_cap_fails_closed_without_truncation(monkeypatch):
    monkeypatch.setattr(budget, "MAX_MEASURED_BYTES", 1000)
    for contents in ("x" * 1001, "\x01" * 200):
        with pytest.raises(budget.RagInputBudgetError):
            budget.measure_request(model="gemini-3.5-flash", contents=contents, system_instruction="System")


@pytest.mark.parametrize("changes", [
    {"byte_limit": True}, {"byte_limit": HARD_BYTE_LIMIT + 1}, {"byte_limit": 0},
    {"model": "https://private-provider.invalid/model"}, {"model": ["gemini-3.5-flash"]},
    {"contents": None}, {"contents": " "}, {"contents": "\ud800"},
    {"system_instruction": []}, {"system_instruction": ""},
    {"max_output_tokens": True}, {"max_output_tokens": 8193},
])
def test_build_rejects_unbounded_nontext_and_unsupported_profile_inputs(changes):
    values = {"model": "gemini-3.5-flash", "contents": "Source and question", "system_instruction": "System"}
    with pytest.raises(budget.RagInputBudgetError) as caught:
        budget.build_request(**{**values, **changes})
    assert caught.value.report.generation_started is False and caught.value.report.input_tokens is None
    assert "private-provider" not in str(caught.value) + caught.value.report.model_dump_json()


@pytest.mark.parametrize("value", [None, True, False, 0, -1, 100.0, "100", 2147483648, {}, float("nan")])
def test_invalid_provider_count_never_starts_generation(value):
    models = FakeModels(count=value)
    with pytest.raises(budget.RagInputBudgetError) as caught:
        run(models)
    assert caught.value.reason_code == "rag_input_count_invalid"
    assert caught.value.report.status == "unavailable" and caught.value.report.input_tokens is None
    assert [item[0] for item in models.calls] == ["count"]


@pytest.mark.parametrize("limit,count,allowed", [(100, 100, True), (100, 101, False)])
def test_actual_provider_count_controls_inclusive_budget_admission(limit, count, allowed):
    models = FakeModels(count=count)
    if allowed:
        assert run(models, max_input_tokens=limit)[1].input_tokens == count
    else:
        with pytest.raises(budget.RagInputBudgetError) as caught:
            run(models, max_input_tokens=limit)
        assert caught.value.reason_code == "rag_input_token_limit_exceeded"
        assert caught.value.report.status == "rejected" and caught.value.report.input_tokens == count
        assert not caught.value.report.generation_started
        assert len(models.calls) == 1


def test_count_failure_is_sanitized_without_generation_or_retry():
    def broken(kwargs):
        raise RuntimeError("PRIVATE_PROVIDER_CREDENTIAL_AND_SOURCE")
    models = FakeModels(count_action=broken)
    with pytest.raises(budget.RagInputBudgetError) as caught:
        run(models)
    assert caught.value.reason_code == "rag_input_count_unavailable"
    assert "PRIVATE" not in str(caught.value) + caught.value.report.model_dump_json()
    assert len(models.calls) == 1 and caught.value.__suppress_context__


def test_generation_failure_is_sanitized_and_not_retried():
    def broken(kwargs):
        raise RuntimeError("PRIVATE_GENERATION_ERROR")
    models = FakeModels(generation_action=broken)
    with pytest.raises(budget.RagInputBudgetError) as caught:
        run(models)
    assert caught.value.reason_code == "rag_input_generation_unavailable"
    assert caught.value.report.generation_started and caught.value.report.input_tokens == 100
    assert caught.value.report.status == "unavailable" and len(models.calls) == 2


@pytest.mark.parametrize("phase", ["before_count", "after_count", "after_generation"])
def test_cancellation_never_launches_late_followup_or_returns_late_generated_text(phase):
    stop = Event()
    if phase == "before_count":
        stop.set()
    models = FakeModels(count_action=(lambda _: stop.set()) if phase == "after_count" else None,
        generation_action=(lambda _: stop.set()) if phase == "after_generation" else None)
    with pytest.raises(budget.RagInputBudgetError) as caught:
        run(models, stop_event=stop)
    assert caught.value.reason_code == "rag_input_cancelled"
    assert caught.value.provider_attempted is (phase != "before_count")
    assert len(models.calls) == {"before_count": 0, "after_count": 1, "after_generation": 2}[phase]


def test_shared_deadline_sdk_timeout_and_retry_controls(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(budget.time, "monotonic", lambda: now[0])
    models = FakeModels(count_action=lambda _: now.__setitem__(0, 103.0))
    run(models, timeout_seconds=10, count_timeout_seconds=4)
    assert [call[1]["config"].http_options.timeout for call in models.calls] == [4000, 7000]
    assert all(call[1]["config"].http_options.retry_options.attempts == 1 for call in models.calls)


def test_count_returning_after_overall_deadline_does_not_generate(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(budget.time, "monotonic", lambda: now[0])
    models = FakeModels(count_action=lambda _: now.__setitem__(0, 11.0))
    with pytest.raises(budget.RagInputBudgetError) as caught:
        run(models, timeout_seconds=10)
    assert caught.value.reason_code == "rag_input_deadline_exceeded" and len(models.calls) == 1
    assert caught.value.provider_attempted is True


def test_count_side_mutation_cannot_change_frozen_generation_payload():
    def mutate(kwargs):
        kwargs["contents"][0]["parts"][0]["text"] = "MUTATED"
        kwargs["config"].system_instruction.parts[0].text = "MUTATED"
    prepared = request()
    models = FakeModels(count_action=mutate)
    run(models, prepared)
    assert models.calls[0][1]["contents"] == models.calls[1][1]["contents"]
    assert models.calls[0][1]["config"].system_instruction == models.calls[1][1]["config"].system_instruction
    with pytest.raises(FrozenInstanceError):
        prepared.model = "gemini-other"


@pytest.mark.parametrize("fault", ["digest", "model", "profile", "byte_count", "extra_field"])
def test_forged_frozen_envelopes_fail_before_count(fault):
    prepared = request()
    changes = {"digest": {"request_sha256": "0" * 64}, "model": {"model": "gemini-other"},
        "profile": {"profile": "unreviewed"}, "byte_count": {"payload_bytes": 1}}
    if fault == "extra_field":
        payload = json.loads(prepared._payload_json)
        payload["tools"] = [{"PRIVATE": "external tool"}]
        changes[fault] = {"_payload_json": json.dumps(payload)}
    models = FakeModels()
    with pytest.raises(budget.RagInputBudgetError):
        run(models, replace(prepared, **changes[fault]))
    assert not models.calls


@pytest.mark.parametrize("kwargs", [{"max_input_tokens": True}, {"max_input_tokens": "100"},
    {"max_input_tokens": HARD_INPUT_TOKEN_LIMIT + 1}, {"timeout_seconds": True},
    {"timeout_seconds": float("inf")}, {"count_timeout_seconds": 0}])
def test_invalid_limits_fail_before_count(kwargs):
    models = FakeModels()
    with pytest.raises(budget.RagInputBudgetError):
        run(models, **kwargs)
    assert not models.calls


@pytest.mark.parametrize("changes", [{"scientific_acceptance": 0}, {"scientific_acceptance": True},
    {"scientific_acceptance": "false"}, {"status": "counted"}, {"generation_started": True},
    {"input_tokens": True}, {"max_input_tokens": HARD_INPUT_TOKEN_LIMIT + 1},
    {"prompt": "PRIVATE"}, {"byte_limit": HARD_BYTE_LIMIT + 1}])
def test_report_is_closed_strict_and_cannot_imply_generation_without_count(changes):
    with pytest.raises(ValueError):
        RagInputBudgetReport.model_validate(changes)
    assert RagInputBudgetReport().byte_limit == DEFAULT_BYTE_LIMIT


def test_outer_timeout_can_truthfully_report_unknown_generation_start():
    report = RagInputBudgetReport(status="unavailable")
    assert report.generation_started is None and report.input_tokens is None
    assert RagInputBudgetReport().generation_started is None


@pytest.mark.parametrize("changes", [{"model": "gemini-3.5-flash"}, {"request_sha256": "1" * 64},
    {"payload_bytes": 10}, {"max_input_tokens": 10}, {"generation_started": False}])
def test_not_requested_cannot_describe_prepared_or_dispatched_work(changes):
    with pytest.raises(ValueError):
        RagInputBudgetReport(**changes)


@pytest.mark.parametrize("started", [None, False])
def test_counted_completed_pipeline_requires_generation_start(started):
    with pytest.raises(ValueError):
        RagInputBudgetReport(status="counted", model="gemini-3.5-flash", request_sha256="1" * 64,
            payload_bytes=10, input_tokens=10, max_input_tokens=20, generation_started=started)


def test_developer_api_cannot_count_only_contents_and_drop_system_instruction(monkeypatch):
    client = genai.Client(api_key="synthetic-offline-key")
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("Unsupported count profile must fail before transport")
    monkeypatch.setattr(client._api_client, "request", forbidden)
    try:
        with pytest.raises(budget.RagInputBudgetError) as caught:
            budget.generate_with_budget(client, request())
    finally:
        client.close()
    assert caught.value.reason_code == "rag_input_count_unavailable" and not calls


@pytest.mark.parametrize("enterprise", [True, False])
def test_installed_sdk_wire_payload_is_identical_and_never_accesses_network(monkeypatch, enterprise):
    # Exercise the actual installed SDK's conversion code, intercepting its
    # transport before authentication/request execution; no paid/cloud calls.
    client = genai.Client(**({"enterprise": True} if enterprise else {"vertexai": True}),
        project="synthetic-budget-project", location="global", credentials=AnonymousCredentials())
    calls = []
    def transport(method, path, body, options):
        calls.append((method, path, copy.deepcopy(body), options))
        response = ({"totalTokens": 77} if path.endswith(":countTokens") else
                    {"candidates": [{"content": {"role": "model", "parts": [{"text": "Synthetic only"}]}}]})
        return SimpleNamespace(body=json.dumps(response), headers={})
    monkeypatch.setattr(client._api_client, "request", transport)
    try:
        response, report = budget.generate_with_budget(client, request())
    finally:
        client.close()
    assert response.text == "Synthetic only" and report.input_tokens == 77
    assert len(calls) == 2 and calls[0][1].replace(":countTokens", ":generateContent") == calls[1][1]
    assert calls[0][2] == calls[1][2]
    body = calls[0][2]
    assert {"contents", "systemInstruction", "generationConfig"} <= set(body)
    assert "language=en" in body["systemInstruction"]["parts"][0]["text"]
    assert "超导 Ω <39 K" in body["contents"][0]["parts"][0]["text"]
    assert all(item[3].retry_options.attempts == 1 and 1 <= item[3].timeout <= 30000 for item in calls)
