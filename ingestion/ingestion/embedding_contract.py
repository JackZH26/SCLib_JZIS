"""Strict text-embedding completeness policy; mirrored in API and ingestion.

This is SCLib's deliberately narrow allowlist, not Google's full model list.
Local cl100k counts / UTF-8 byte counts are admission estimates, never the
provider tokenizer. Completion requires an explicit untruncated provider
report for every input. Metadata records that report, not independent proof.

Google primary references (checked 2026-09-08):
https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/embeddings/get-text-embeddings
https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/models/text-embeddings-api
"""
from __future__ import annotations

import hashlib
import math
import re
import struct

VERSION = "sclib-embedding-completeness/1.0.0"
PROVIDER = "google-vertex-ai"
MODEL = "text-embedding-005"
DIMENSION = 768
PROVIDER_INPUT_TOKEN_LIMIT = 2048
PROVIDER_REQUEST_TOKEN_LIMIT = 20000
PROVIDER_INPUT_COUNT_LIMIT = 250
LOCAL_DOCUMENT_COUNT_METHOD = "tiktoken-cl100k_base/1"
LOCAL_DOCUMENT_INPUT_LIMIT = 1536
LOCAL_DOCUMENT_REQUEST_LIMIT = 14000
LOCAL_QUERY_COUNT_METHOD = "utf8-bytes/1"
LOCAL_QUERY_INPUT_LIMIT = 8192
LOCAL_QUERY_REQUEST_LIMIT = 8192
_TASKS = {"RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"}
_LOCAL_LIMITS = {
    LOCAL_DOCUMENT_COUNT_METHOD: (LOCAL_DOCUMENT_INPUT_LIMIT, LOCAL_DOCUMENT_REQUEST_LIMIT),
    LOCAL_QUERY_COUNT_METHOD: (LOCAL_QUERY_INPUT_LIMIT, LOCAL_QUERY_REQUEST_LIMIT),
}
_KEYS = {
    "version", "provider", "model", "task_type", "output_dimensionality",
    "content_sha256", "vector_sha256", "local_count_method", "local_count",
    "local_input_limit", "local_request_limit", "provider_token_count",
    "provider_input_token_limit", "provider_request_token_limit",
    "provider_truncated", "auto_truncate", "completeness_status",
}
_HASH = re.compile(r"[a-f0-9]{64}\Z")


class EmbeddingCompletenessError(ValueError):
    """A response cannot establish the required bounded completion report."""


def _integer(value, *, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise EmbeddingCompletenessError("A positive bounded integer is required")
    return value


def validate_profile(*, model, dimension, task_type):
    """Refuse unreviewed model/space/task combinations before provider calls."""
    if (type(model) is not str or model != MODEL or type(dimension) is not int
            or dimension != DIMENSION or type(task_type) is not str or task_type not in _TASKS):
        raise EmbeddingCompletenessError("Unsupported SCLib embedding model, dimension or task")


def _text_bytes(text):
    if type(text) is not str or not text.strip():
        raise EmbeddingCompletenessError("A nonempty embedding input is required")
    try:
        value = text.encode("utf-8")
    except UnicodeError as exc:
        raise EmbeddingCompletenessError("Embedding input is not valid UTF-8") from exc
    if len(value) > 1024 * 1024:
        raise EmbeddingCompletenessError("Embedding input exceeds the byte safety limit")
    return value


def content_sha256(text):
    return hashlib.sha256(_text_bytes(text)).hexdigest()


def validate_vector(vector, *, dimension=DIMENSION):
    """Return canonical finite values; an all-zero cosine vector is unusable."""
    if type(dimension) is not int or dimension != DIMENSION:
        raise EmbeddingCompletenessError("Unsupported SCLib embedding dimension")
    if type(vector) not in {list, tuple} or len(vector) != dimension:
        raise EmbeddingCompletenessError("Embedding response dimension mismatch")
    result = []
    for value in vector:
        if type(value) not in {int, float}:
            raise EmbeddingCompletenessError("Embedding values must be finite numbers")
        try:
            number = float(value)
        except (OverflowError, ValueError) as exc:
            raise EmbeddingCompletenessError("Embedding values must be finite numbers") from exc
        if not math.isfinite(number):
            raise EmbeddingCompletenessError("Embedding values must be finite numbers")
        try:
            # IndexDatapoint.feature_vector is protobuf float (binary32).
            # Bind the actual transport representation, not unattainable f64.
            number = struct.unpack("!f", struct.pack("!f", number))[0]
        except (OverflowError, struct.error) as exc:
            raise EmbeddingCompletenessError("Embedding value exceeds float32 transport range") from exc
        if not math.isfinite(number):
            raise EmbeddingCompletenessError("Embedding value exceeds float32 transport range")
        result.append(0.0 if number == 0 else number)
    if not any(result):
        raise EmbeddingCompletenessError("A zero embedding is not usable for retrieval")
    return result


def vector_sha256(vector):
    """Hash canonical big-endian IEEE754 binary32 values, -0 normalized to +0."""
    values = validate_vector(vector)
    return hashlib.sha256(struct.pack(">" + "f" * len(values), *values)).hexdigest()


def _local_policy(method, input_limit, request_limit):
    if type(method) is not str or method not in _LOCAL_LIMITS:
        raise EmbeddingCompletenessError("Unsupported local embedding count method")
    maximum_input, maximum_request = _LOCAL_LIMITS[method]
    _integer(input_limit, maximum=maximum_input)
    _integer(request_limit, maximum=maximum_request)
    if input_limit > request_limit:
        raise EmbeddingCompletenessError("Local input limit exceeds request limit")


def validate_embedding_inputs(texts, *, model, dimension, task_type, local_counts,
                              local_count_method, local_input_limit, local_request_limit):
    """Validate exact full input strings; local sizing is not provider tokenization."""
    validate_profile(model=model, dimension=dimension, task_type=task_type)
    _local_policy(local_count_method, local_input_limit, local_request_limit)
    if type(texts) not in {list, tuple} or not 1 <= len(texts) <= PROVIDER_INPUT_COUNT_LIMIT:
        raise EmbeddingCompletenessError("Embedding input count is outside the supported limit")
    if type(local_counts) not in {list, tuple} or len(local_counts) != len(texts):
        raise EmbeddingCompletenessError("Embedding local count inventory mismatch")
    for text, count in zip(texts, local_counts, strict=True):
        encoded = _text_bytes(text)
        _integer(count, maximum=local_input_limit)
        if local_count_method == LOCAL_QUERY_COUNT_METHOD and count != len(encoded):
            raise EmbeddingCompletenessError("Local UTF-8 byte count mismatch")
    if sum(local_counts) > local_request_limit:
        raise EmbeddingCompletenessError("Embedding local request budget exceeded")


def validate_embedding_provenance(value, *, text=None, vector=None, expected_task=None):
    """Validate a closed report; optional actual text/vector bind its hashes.

    A well-formed report alone does not authenticate a provider or prove an
    upload/current index binding. The writer must also supply actual inputs.
    """
    if type(value) is not dict or set(value) != _KEYS:
        raise EmbeddingCompletenessError("Malformed embedding completeness metadata")
    validate_profile(model=value["model"], dimension=value["output_dimensionality"], task_type=value["task_type"])
    if expected_task is not None and (type(expected_task) is not str or expected_task not in _TASKS
                                      or value["task_type"] != expected_task):
        raise EmbeddingCompletenessError("Embedding task does not match its consumer")
    if (value["version"] != VERSION or value["provider"] != PROVIDER
            or value["completeness_status"] != "provider_reported_complete"
            or value["provider_truncated"] is not False or value["auto_truncate"] is not False
            or type(value["provider_input_token_limit"]) is not int
            or value["provider_input_token_limit"] != PROVIDER_INPUT_TOKEN_LIMIT
            or type(value["provider_request_token_limit"]) is not int
            or value["provider_request_token_limit"] != PROVIDER_REQUEST_TOKEN_LIMIT):
        raise EmbeddingCompletenessError("Embedding completeness report is not admissible")
    _local_policy(value["local_count_method"], value["local_input_limit"], value["local_request_limit"])
    _integer(value["local_count"], maximum=value["local_input_limit"])
    _integer(value["provider_token_count"], maximum=PROVIDER_INPUT_TOKEN_LIMIT)
    for name in ("content_sha256", "vector_sha256"):
        if type(value[name]) is not str or not _HASH.fullmatch(value[name]):
            raise EmbeddingCompletenessError("Invalid embedding content or vector hash")
    if text is not None:
        if content_sha256(text) != value["content_sha256"]:
            raise EmbeddingCompletenessError("Embedding input text hash mismatch")
        if value["local_count_method"] == LOCAL_QUERY_COUNT_METHOD and len(_text_bytes(text)) != value["local_count"]:
            raise EmbeddingCompletenessError("Local UTF-8 byte count mismatch")
    if vector is not None and vector_sha256(vector) != value["vector_sha256"]:
        raise EmbeddingCompletenessError("Embedding vector hash mismatch")
    return dict(value)


def _field(value, key):
    return value.get(key) if type(value) is dict else getattr(value, key, None)


def _provider_count(value):
    # google-genai ContentEmbeddingStatistics.token_count is Optional[float].
    if type(value) not in {int, float}:
        raise EmbeddingCompletenessError("Provider embedding token statistics are unavailable")
    try:
        finite = math.isfinite(value)
    except OverflowError as exc:
        raise EmbeddingCompletenessError("Provider embedding token statistics are invalid") from exc
    if not finite or not 1 <= value <= PROVIDER_INPUT_TOKEN_LIMIT or int(value) != value:
        raise EmbeddingCompletenessError("Provider embedding token statistics are invalid")
    return int(value)


def validate_embedding_response(texts, response, *, model, dimension, task_type, local_counts,
                                local_count_method, local_input_limit, local_request_limit):
    """Validate every response before returning any publishable vector/report."""
    validate_embedding_inputs(texts, model=model, dimension=dimension, task_type=task_type,
        local_counts=local_counts, local_count_method=local_count_method,
        local_input_limit=local_input_limit, local_request_limit=local_request_limit)
    embeddings = _field(response, "embeddings")
    if type(embeddings) not in {list, tuple} or len(embeddings) != len(texts):
        raise EmbeddingCompletenessError("Embedding response count mismatch")
    completed = []
    for text, count, embedding in zip(texts, local_counts, embeddings, strict=True):
        statistics = _field(embedding, "statistics")
        if statistics is None or _field(statistics, "truncated") is not False:
            raise EmbeddingCompletenessError("Explicit untruncated provider statistics are required")
        provider_count = _provider_count(_field(statistics, "token_count"))
        vector = validate_vector(_field(embedding, "values"), dimension=dimension)
        metadata = {
            "version": VERSION, "provider": PROVIDER, "model": model, "task_type": task_type,
            "output_dimensionality": dimension, "content_sha256": content_sha256(text),
            "vector_sha256": vector_sha256(vector), "local_count_method": local_count_method,
            "local_count": count, "local_input_limit": local_input_limit,
            "local_request_limit": local_request_limit, "provider_token_count": provider_count,
            "provider_input_token_limit": PROVIDER_INPUT_TOKEN_LIMIT,
            "provider_request_token_limit": PROVIDER_REQUEST_TOKEN_LIMIT,
            "provider_truncated": False, "auto_truncate": False,
            "completeness_status": "provider_reported_complete",
        }
        completed.append((vector, validate_embedding_provenance(metadata, text=text, vector=vector,
                                                               expected_task=task_type)))
    if sum(metadata["provider_token_count"] for _, metadata in completed) > PROVIDER_REQUEST_TOKEN_LIMIT:
        raise EmbeddingCompletenessError("Provider embedding request token budget exceeded")
    return completed
