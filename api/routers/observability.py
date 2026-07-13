"""Internal metrics and aggregate, consent-gated browser telemetry."""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response

from config import get_settings
from models.telemetry import ClientTelemetryEvent
from services.auth_security import privacy_hash
from services.metrics import (
    instrument_dependency_call,
    observe_client_event,
    render_metrics,
)
from services.rate_limit import get_redis
from services.request_context import client_ip

router = APIRouter(tags=["observability"])
log = logging.getLogger(__name__)


@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics() -> Response:
    """Prometheus scrape target; Nginx denies this path publicly."""
    payload, content_type = render_metrics()
    return Response(
        content=payload,
        headers={"Content-Type": content_type, "Cache-Control": "no-store"},
    )


@router.post("/v1/telemetry/client", status_code=202)
async def client_telemetry(body: ClientTelemetryEvent, request: Request) -> Response:
    """Aggregate bounded browser health signals without identifiers or messages."""
    if not await _within_budget(request):
        return Response(status_code=202)
    observe_client_event(
        event_type=body.event_type,
        name=body.name,
        rating=body.rating,
        value=body.value,
    )
    return Response(status_code=202)


async def _within_budget(request: Request) -> bool:
    now = datetime.now(UTC)
    minute = now.strftime("%Y%m%d%H%M")
    subject = privacy_hash("client-telemetry", client_ip(request))
    key = f"telemetry:minute:{minute}:{subject}"
    redis = get_redis()
    try:
        pipe = redis.pipeline(transaction=True)
        pipe.incr(key)
        pipe.expire(key, 120, nx=True)
        count, _ = await instrument_dependency_call(
            "redis", "telemetry_limit", pipe.execute()
        )
    except Exception:  # noqa: BLE001 - telemetry must never affect the product path
        log.warning("dropping client telemetry because Redis is unavailable")
        return False
    return int(count) <= get_settings().client_telemetry_per_minute
