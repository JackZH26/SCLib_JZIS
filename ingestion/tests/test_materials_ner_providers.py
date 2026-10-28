"""Provider failure modes; mocked transport is explicitly not a live API test."""
import json

import httpx
import pytest

from ingestion.materials_ner.providers import ProviderFailure, ResponsesProvider


def config():
    return {"model": "gpt-6.1-sol", "reasoning": "medium",
            "max_output_tokens": 1000, "timeout_seconds": 10}


def test_api_credential_missing_fails_before_network(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    def forbidden(*args, **kwargs):
        raise AssertionError("must not call network")
    monkeypatch.setattr(httpx, "post", forbidden)
    with pytest.raises(ProviderFailure, match="openai_api_key_unavailable"):
        ResponsesProvider().extract("synthetic", {}, config(), tmp_path)


@pytest.mark.parametrize("status,retryable", [(401, False), (429, True), (503, True)])
def test_http_failures_remain_explicit_and_keep_receipts(monkeypatch, tmp_path, status, retryable):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-not-a-key")
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: httpx.Response(
        status, json={"error": {"message": "synthetic failure"}}))
    with pytest.raises(ProviderFailure) as failure:
        ResponsesProvider().extract("synthetic", {}, config(), tmp_path)
    assert failure.value.code == f"responses_http_{status}"
    assert failure.value.retryable == retryable
    assert json.loads((tmp_path / "provider-response.json").read_bytes())["error"]


def test_api_timeout_is_retryable_not_an_empty_result(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-not-a-key")
    def timeout(*args, **kwargs):
        raise httpx.ReadTimeout("synthetic")
    monkeypatch.setattr(httpx, "post", timeout)
    with pytest.raises(ProviderFailure) as failure:
        ResponsesProvider().extract("synthetic", {}, config(), tmp_path)
    assert failure.value.code == "responses_timeout" and failure.value.retryable


@pytest.mark.parametrize("body,code", [
    ({"status": "incomplete", "usage": {"output_tokens": 1000}}, "responses_incomplete"),
    ({"status": "completed", "output": [{"type": "message", "content": [
        {"type": "refusal", "refusal": "synthetic"}]}]}, "responses_refusal"),
])
def test_refusal_and_output_limit_preserve_failure(monkeypatch, tmp_path, body, code):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-not-a-key")
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: httpx.Response(200, json=body))
    with pytest.raises(ProviderFailure, match=code):
        ResponsesProvider().extract("synthetic", {}, config(), tmp_path)


def test_api_request_uses_strict_schema_no_store_and_explicit_model(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-not-a-key")
    def post(url, **kwargs):
        body = kwargs["json"]
        assert body["model"] == "gpt-6.1-sol" and body["store"] is False
        assert body["text"]["format"]["strict"] is True
        assert body["max_output_tokens"] == 1000
        return httpx.Response(200, json={"id": "synthetic:response", "model": "gpt-6.1-sol",
            "status": "completed", "usage": {"input_tokens": 1, "output_tokens": 2},
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "{}"}]}]})
    monkeypatch.setattr(httpx, "post", post)
    result = ResponsesProvider().extract("synthetic", {}, config(), tmp_path)
    assert result.text == "{}" and result.response_id == "synthetic:response"
