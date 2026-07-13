"""Low-cardinality Prometheus instrumentation for SCLib services."""
from __future__ import annotations

import re
import weakref
from collections.abc import Awaitable
from datetime import UTC, datetime
from time import perf_counter
from typing import TypeVar

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

HTTP_REQUESTS = Counter(
    "sclib_http_requests_total",
    "HTTP requests by route and status.",
    ("method", "route", "status"),
)
HTTP_DURATION = Histogram(
    "sclib_http_request_duration_seconds",
    "HTTP request duration by route.",
    ("method", "route"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)
HTTP_RESPONSE_BYTES = Counter(
    "sclib_http_response_bytes_total",
    "HTTP response bytes from Content-Length.",
    ("method", "route", "status"),
)
HTTP_IN_PROGRESS = Gauge(
    "sclib_http_requests_in_progress",
    "Requests currently executing.",
    ("method",),
)
PROVIDER_CALLS = Counter(
    "sclib_provider_calls_total",
    "External provider calls by outcome.",
    ("provider", "outcome"),
)
PROVIDER_ATTEMPTS = Counter(
    "sclib_provider_attempts_total",
    "External provider attempts, including bounded retries.",
    ("provider",),
)
PROVIDER_DURATION = Histogram(
    "sclib_provider_call_duration_seconds",
    "External provider call duration.",
    ("provider", "outcome"),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)
DEPENDENCY_CALLS = Counter(
    "sclib_dependency_calls_total",
    "Database and Redis operations by outcome.",
    ("dependency", "operation", "outcome"),
)
DEPENDENCY_DURATION = Histogram(
    "sclib_dependency_call_duration_seconds",
    "Database and Redis operation duration.",
    ("dependency", "operation", "outcome"),
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)
DB_ROWS = Counter(
    "sclib_db_rows_total",
    "Rows reported by the database driver for completed operations.",
    ("operation",),
)
DB_CONNECTIONS_IN_USE = Gauge(
    "sclib_db_connections_in_use",
    "Checked-out SQLAlchemy connections.",
)
RAG_ANSWERS = Counter(
    "sclib_rag_answers_total",
    "RAG answers by citation and fallback outcome.",
    ("citation_valid", "fallback"),
)
RAG_SOURCES = Histogram(
    "sclib_rag_sources",
    "Distinct papers supplied to an answer.",
    buckets=(0, 1, 2, 3, 5, 8, 10, 15, 20),
)
RAG_TOKENS = Histogram(
    "sclib_rag_tokens",
    "Generation tokens reported by the provider.",
    buckets=(0, 64, 128, 256, 512, 1024, 2048, 4096),
)
CLIENT_EVENTS = Counter(
    "sclib_client_events_total",
    "Privacy-minimized browser telemetry events.",
    ("event_type", "name", "rating"),
)
WEB_VITAL_VALUE = Histogram(
    "sclib_web_vital_value",
    "Browser Web Vital values (native metric units).",
    ("name",),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 4, 10, 100, 500, 1000, 2500, 4000, 10000),
)
DATASET_ROWS = Gauge(
    "sclib_dataset_rows",
    "Published dataset row counts.",
    ("entity",),
)
DATASET_AGE_SECONDS = Gauge(
    "sclib_dataset_age_seconds",
    "Seconds since the latest indexed paper.",
)
PIPELINE_STAGE_STATUS = Gauge(
    "sclib_pipeline_stage_status",
    "Pipeline stage status: complete=1, unknown=0, failed=-1.",
    ("stage",),
)

_T = TypeVar("_T")
_instrumented_engines: weakref.WeakSet[object] = weakref.WeakSet()
_DB_OPERATION = re.compile(r"^\s*([A-Za-z]+)")


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST


def observe_http(
    method: str,
    route: str,
    status: int,
    duration_seconds: float,
    response_bytes: int,
) -> None:
    labels = (method, route, str(status))
    HTTP_REQUESTS.labels(*labels).inc()
    HTTP_DURATION.labels(method, route).observe(max(0.0, duration_seconds))
    if response_bytes >= 0:
        HTTP_RESPONSE_BYTES.labels(*labels).inc(response_bytes)


def observe_provider(
    provider: str,
    outcome: str,
    duration_seconds: float,
    attempts: int,
) -> None:
    PROVIDER_CALLS.labels(provider, outcome).inc()
    PROVIDER_ATTEMPTS.labels(provider).inc(max(0, attempts))
    PROVIDER_DURATION.labels(provider, outcome).observe(max(0.0, duration_seconds))


def observe_dependency(
    dependency: str,
    operation: str,
    outcome: str,
    duration_seconds: float,
) -> None:
    DEPENDENCY_CALLS.labels(dependency, operation, outcome).inc()
    DEPENDENCY_DURATION.labels(dependency, operation, outcome).observe(
        max(0.0, duration_seconds)
    )


async def instrument_dependency_call(
    dependency: str,
    operation: str,
    call: Awaitable[_T],
) -> _T:
    """Time an awaited dependency call without changing its failure behavior."""
    started = perf_counter()
    try:
        result = await call
    except Exception:
        observe_dependency(
            dependency,
            operation,
            "failure",
            perf_counter() - started,
        )
        raise
    observe_dependency(
        dependency,
        operation,
        "success",
        perf_counter() - started,
    )
    return result


def observe_rag(*, sources: int, tokens: int | None, citation_valid: bool, fallback: bool) -> None:
    RAG_ANSWERS.labels(str(citation_valid).lower(), str(fallback).lower()).inc()
    RAG_SOURCES.observe(max(0, sources))
    if tokens is not None:
        RAG_TOKENS.observe(max(0, tokens))


def observe_client_event(
    *,
    event_type: str,
    name: str,
    rating: str,
    value: float | None,
) -> None:
    CLIENT_EVENTS.labels(event_type, name, rating).inc()
    if event_type == "web_vital" and value is not None:
        WEB_VITAL_VALUE.labels(name).observe(max(0.0, value))


def update_dataset_metrics(payload: dict, stages: dict) -> None:
    for entity, key in (
        ("papers", "total_papers"),
        ("materials", "total_materials"),
        ("chunks", "total_chunks"),
    ):
        value = payload.get(key)
        if isinstance(value, int):
            DATASET_ROWS.labels(entity).set(value)

    last_ingest_at = payload.get("last_ingest_at")
    if isinstance(last_ingest_at, str):
        try:
            parsed = datetime.fromisoformat(last_ingest_at.replace("Z", "+00:00"))
        except ValueError:
            pass
        else:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            DATASET_AGE_SECONDS.set(max(0.0, (datetime.now(UTC) - parsed).total_seconds()))

    status_values = {"complete": 1, "unknown": 0, "failed": -1}
    for stage, state in stages.items():
        status = getattr(state, "status", "unknown")
        PIPELINE_STAGE_STATUS.labels(stage).set(status_values.get(status, 0))


def instrument_sqlalchemy(engine: AsyncEngine) -> None:
    """Attach per-engine SQL timing and pool usage hooks once."""
    sync_engine = engine.sync_engine
    if sync_engine in _instrumented_engines:
        return
    _instrumented_engines.add(sync_engine)

    @event.listens_for(sync_engine, "before_cursor_execute")
    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        context._sclib_metric_started = perf_counter()
        match = _DB_OPERATION.match(statement or "")
        context._sclib_metric_operation = (
            match.group(1).upper() if match else "OTHER"
        )

    @event.listens_for(sync_engine, "after_cursor_execute")
    def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        started = getattr(context, "_sclib_metric_started", perf_counter())
        operation = getattr(context, "_sclib_metric_operation", "OTHER")
        observe_dependency("postgres", operation, "success", perf_counter() - started)
        rowcount = getattr(cursor, "rowcount", -1)
        if isinstance(rowcount, int) and rowcount >= 0:
            DB_ROWS.labels(operation).inc(rowcount)

    @event.listens_for(sync_engine, "handle_error")
    def handle_error(exception_context) -> None:
        context = exception_context.execution_context
        started = getattr(context, "_sclib_metric_started", perf_counter())
        operation = getattr(context, "_sclib_metric_operation", "OTHER")
        observe_dependency(
            "postgres",
            operation,
            "failure",
            perf_counter() - started,
        )

    @event.listens_for(sync_engine.pool, "checkout")
    def pool_checkout(dbapi_connection, connection_record, connection_proxy):  # noqa: ARG001
        DB_CONNECTIONS_IN_USE.inc()

    @event.listens_for(sync_engine.pool, "checkin")
    def pool_checkin(dbapi_connection, connection_record):  # noqa: ARG001
        DB_CONNECTIONS_IN_USE.dec()
