"""FastAPI application entry point.

Exposes everything under /v1 so the path matches the public route
`api.jzis.org/sclib/v1/*` once Nginx strips `/sclib/`. Phase 1 only
mounts the auth router; Phase 3 will add search/ask/materials/etc.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import delete
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from config import allowed_browser_origins, get_settings
from models import get_session_factory
from models.db import AskHistory, get_engine
from models.errors import ApiErrorResponse
from routers import (
    admin,
    ask,
    auth,
    bookmarks,
    discovery,
    feedback,
    health,
    history,
    materials,
    observability,
    papers,
    search,
    seo,
    similar,
    stats,
    timeline,
    version,
)
from services.metrics import HTTP_IN_PROGRESS, observe_http
from services.request_context import (
    bind_request_id,
    reset_request_id,
    resolve_request_id,
)
from services.session_config import build_oauth_session_config
from services.stats_refresh import refresh_dashboard_cache
from services.timeline_projection import refresh_timeline_projection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s  %(message)s",
)
log = logging.getLogger("sclib.api")


async def _periodic_stats_refresh(interval_sec: int) -> None:
    """Recompute ``stats_cache['dashboard']`` every ``interval_sec``.

    The ingest pipeline runs out-of-band (瓦力 cron) and does not refresh
    the cache itself, so without this task the homepage would forever
    show whatever counts existed at the last manual ``POST /stats/refresh``.
    Runs until the app shuts down. Exceptions are logged and swallowed
    so a transient DB blip never crashes the API process — the next tick
    retries.
    """
    factory = get_session_factory()
    # Small delay on startup so the first tick doesn't race with
    # alembic upgrade + initial request traffic.
    await asyncio.sleep(30)
    while True:
        try:
            async with factory() as session:
                payload = await refresh_dashboard_cache(session)
            log.info(
                "stats_cache refreshed: %d papers / %d materials / %d chunks",
                payload["total_papers"],
                payload["total_materials"],
                payload["total_chunks"],
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("stats_cache refresh failed; retrying on next tick")
        await asyncio.sleep(interval_sec)


async def _periodic_timeline_projection(interval_sec: int) -> None:
    """Refresh the Timeline projection away from request latency."""
    from services.rate_limit import get_redis

    factory = get_session_factory()
    # Alembic runs before Uvicorn in entrypoint.sh. The extra delay keeps the
    # first full projection build away from startup health probes.
    await asyncio.sleep(60)
    while True:
        try:
            async with factory() as session:
                async with session.begin():
                    result = await refresh_timeline_projection(session)
            log.info(
                "timeline projection refreshed: %d materials / %d active points%s",
                result.materials_processed,
                result.active_points,
                " (full rebuild)" if result.full_rebuild else "",
            )
            if result.full_rebuild or result.materials_processed:
                try:
                    redis = get_redis()
                    keys = [
                        key async for key in redis.scan_iter(
                            match="timeline:*", count=200,
                        )
                    ]
                    if keys:
                        await redis.delete(*keys)
                except Exception:  # noqa: BLE001 - TTL remains the safe fallback
                    log.warning(
                        "timeline cache invalidation failed after projection refresh",
                        exc_info=True,
                    )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("timeline projection refresh failed; retrying next tick")
        await asyncio.sleep(interval_sec)


# Mirrors ingestion/ingestion/extract/formula_validator.py::_BLACKLIST_PATTERN
# and the same regex used by alembic 0020. Keep all three in sync.
_FORMULA_BLACKLIST_REGEX = (
    r"\m("
    r"interface|bilayer|trilayer|multilayer|monolayer|superlattice|"
    r"superlattices|homobilayer|homobilayers|heterostructure|graphene|"
    r"diamond|molecule|molecules|organic|compound|compounds|system|"
    r"systems|doped|undoped|intercalated|hybrid|twisted|valley|bulk|"
    r"ladder|mirror|surface|surfaces|nanoparticle|nanoparticles|film|"
    r"films|wire|wires|polycrystal|polycrystals|tube|tubes|composition|"
    r"compositions|underdoped|overdoped|optimal|optimally|holes?|"
    r"electrons?|cells?|samples?|layers?|chiral|kagome|nanotube|"
    r"nanotubes|nanowire|nanowires"
    r")\M"
)
# LOCKSTEP: mirrors formula_validator._CONDITION_PATTERN +
# api/alembic 0036_inequality_condition. ≤ ≥ < > never occur in a
# real chemical formula — they signal a glued-on range condition.
_FORMULA_CONDITION_REGEX = r"\(?\s*[xyzn]\s*=\s*[0-9]|[≤≥]|<=|>="

# Concatenated structural descriptors the word-boundary blacklist
# misses (e.g. "TaNSmonolayer", "Y-dopedBi2Sr2CaCu2O8"). Substring
# match (no \m/\M). Mirrors verbatim
#   ingestion/ingestion/extract/formula_validator.py::_CONCAT_DESCRIPTOR
#   api/alembic/versions/0034_concat_descriptor_validation.py
# Keep all three identical when editing.
_FORMULA_CONCAT_DESCRIPTOR_REGEX = (
    r"(monolayer|bilayer|trilayer|tetralayer|fewlayer|multilayer"
    r"|heterostructure|heterostructures|superlattice|superlattices"
    r"|nanotube|nanotubes|nanowire|nanowires|nanoparticle|nanoparticles"
    r"|nanosheet|nanosheets|nanoribbon|nanoribbons|nanostructure"
    r"|nanostructures|graphene|graphite|fullerene|thinfilm|epitaxial"
    r"|amorphous|polycrystalline|substrate|doped|undoped|intercalated)"
)


async def _periodic_formula_audit(interval_sec: int) -> None:
    """Re-flag any materials whose formula slips past the NER +
    aggregator validators. Runs hourly. Idempotent — only flips
    ``needs_review`` on rows currently marked False that match one of
    the named rules; never un-flags. Migrations 0020 + 0021 are the
    initial backfills; this loop is the safety net for anything that
    lands between releases.

    Each rule writes a distinct ``review_reason`` so admins can
    audit / unflag per-category. The set of rules mirrors
    ``ingestion/.../formula_validator.py``.
    """
    from sqlalchemy import text

    factory = get_session_factory()
    # Stagger from stats_refresh (30s) and ask_history_prune (90s)
    # so three lifespan tasks don't all hit the DB at once.
    await asyncio.sleep(150)
    rules: list[tuple[str, str]] = [
        # (review_reason, predicate fragment). Each runs as its own
        # idempotent UPDATE so a regex error in one rule does not
        # block the others.
        (
            "ner_extracted_descriptive_text",
            f"formula ~* '{_FORMULA_BLACKLIST_REGEX}' "
            f"OR formula ~* '{_FORMULA_CONCAT_DESCRIPTOR_REGEX}' "
            f"OR formula ~  '{_FORMULA_CONDITION_REGEX}' "
            f"OR formula !~ '[A-Z]'",
        ),
        (
            "system_designator_not_compound",
            r"formula ~ '^([A-Z][a-z]?-){2,}[A-Z][a-z]?$'",
        ),
        (
            "phase_prefix_in_formula",
            r"formula ~ '^(Fd-?3m|Fm-?3m|Im-?3m|Pm-?3m|Pnma|"
            r"P6_?3?/?mmc?|P6/mmm|R-?3m|R-?3c|I4/mmm|I4/mcm|"
            r"Pn-?3m|P6_?3mc|C2/m|Cmcm|P-?1|P21/c|P-43m|"
            r"P4/nmm|Pm-3n)-'",
        ),
        (
            "incomplete_or_charged_formula",
            r"formula ~ '[A-Za-z0-9][+\-]$'",
        ),
    ]
    while True:
        try:
            total_flagged = 0
            async with factory() as session:
                for reason, predicate in rules:
                    result = await session.execute(text(f"""
                        UPDATE materials
                        SET needs_review = TRUE,
                            review_reason = '{reason}'
                        WHERE needs_review = FALSE
                          AND admin_decision IS NULL
                          AND ({predicate});
                    """))
                    total_flagged += result.rowcount or 0
                await session.commit()
            if total_flagged:
                log.warning(
                    "formula audit: flagged %d materials across "
                    "%d naming-rule categories",
                    total_flagged, len(rules),
                )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("formula audit failed; retrying on next tick")
        await asyncio.sleep(interval_sec)


async def _nightly_data_audit(target_hour_utc: int = 20) -> None:
    """Run every audit_rule once per day at the configured UTC hour.

    Default 20:00 UTC = 04:00 Beijing — runs after the 14:00 UTC
    arXiv cron has settled but well before the next morning's
    14:00. Per-day cadence is a deliberate trade-off: the rules
    run heavy JSONB scans and we'd rather a regression land 24h
    later than spend hourly DB time on a corpus that only
    changes after each ingest.

    The hourly ``_periodic_formula_audit`` already keeps the
    string-shape naming rules tight; this task adds the broader
    Tc / pressure / year / cross-field / retraction surface.
    """
    factory = get_session_factory()
    while True:
        now = datetime.now(UTC)
        target = now.replace(
            hour=target_hour_utc, minute=0, second=0, microsecond=0,
        )
        if target <= now:
            target += timedelta(days=1)
        sleep_sec = (target - now).total_seconds()
        log.info(
            "nightly audit: sleeping %.0fs until %s UTC",
            sleep_sec, target.isoformat(),
        )
        try:
            await asyncio.sleep(sleep_sec)
        except asyncio.CancelledError:
            raise

        try:
            from services.audit_runner import run_audit
            async with factory() as session:
                await run_audit(session)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("nightly audit run failed; retrying tomorrow")


async def _periodic_ask_history_prune(interval_sec: int, retention_days: int) -> None:
    """Delete Ask history rows older than ``retention_days``.

    Product decision: users keep a rolling 90-day window. We run this
    in-process (daily tick) rather than via cron so Phase B has no
    ops dependency — if the API is up, history stays bounded.
    A larger deployment would likely move this to a batch job.
    """
    factory = get_session_factory()
    # Offset from the stats refresh so we don't pile two heavy loops on
    # the same 30-second startup slot.
    await asyncio.sleep(90)
    while True:
        try:
            cutoff = datetime.now(UTC) - timedelta(days=retention_days)
            async with factory() as session:
                result = await session.execute(
                    delete(AskHistory).where(AskHistory.created_at < cutoff)
                )
                await session.commit()
            deleted = result.rowcount or 0
            if deleted:
                log.info("ask_history prune: removed %d rows older than %dd",
                         deleted, retention_days)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("ask_history prune failed; retrying on next tick")
        await asyncio.sleep(interval_sec)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    log.info("SCLib API starting (env=%s, backend=%s)",
             settings.environment, settings.email_backend)

    # Schedule the hourly dashboard refresh. The 瓦力 ingest adds
    # ~100 papers/hour; without this loop the landing page and /stats
    # endpoint would keep serving stale numbers from stats_cache.
    # Override the cadence with SCLIB_STATS_REFRESH_INTERVAL_SEC for
    # tests (e.g. set to 10 to verify the loop fires).
    import os
    interval = int(os.environ.get("SCLIB_STATS_REFRESH_INTERVAL_SEC", "3600"))
    if interval > 0:
        refresh_task = asyncio.create_task(
            _periodic_stats_refresh(interval),
            name="sclib-stats-refresh",
        )
        log.info("stats_cache auto-refresh scheduled every %ds", interval)
    else:
        refresh_task = None
        log.info("stats_cache auto-refresh disabled (interval=%d)", interval)

    projection_interval = int(
        os.environ.get("SCLIB_TIMELINE_PROJECTION_INTERVAL_SEC", "900")
    )
    if projection_interval > 0:
        projection_task = asyncio.create_task(
            _periodic_timeline_projection(projection_interval),
            name="sclib-timeline-projection",
        )
        log.info(
            "timeline projection refresh scheduled every %ds",
            projection_interval,
        )
    else:
        projection_task = None
        log.info("timeline projection refresh disabled")

    # Formula audit — hourly. Catches dirty / descriptive material
    # formulas that slip past the NER + aggregator validators (eg
    # when a new descriptor pattern emerges before the prompt is
    # updated). Idempotent SQL; flips needs_review and never unflags.
    audit_interval = int(os.environ.get("SCLIB_FORMULA_AUDIT_INTERVAL_SEC", "3600"))
    if audit_interval > 0:
        audit_task = asyncio.create_task(
            _periodic_formula_audit(audit_interval),
            name="sclib-formula-audit",
        )
        log.info("formula audit scheduled every %ds", audit_interval)
    else:
        audit_task = None
        log.info("formula audit disabled")

    # Nightly broad-rule audit — 04:00 Beijing (= 20:00 UTC). Override
    # via SCLIB_NIGHTLY_AUDIT_HOUR_UTC for tests.
    nightly_hour = int(os.environ.get("SCLIB_NIGHTLY_AUDIT_HOUR_UTC", "20"))
    if 0 <= nightly_hour <= 23:
        nightly_task = asyncio.create_task(
            _nightly_data_audit(nightly_hour),
            name="sclib-nightly-data-audit",
        )
        log.info("nightly data audit scheduled at %02d:00 UTC", nightly_hour)
    else:
        nightly_task = None
        log.info("nightly data audit disabled (hour=%d)", nightly_hour)

    # Ask-history pruning runs once a day (86400s) and deletes rows
    # older than 90 days — matches the locked product decision.
    prune_interval = int(os.environ.get("SCLIB_ASK_HISTORY_PRUNE_INTERVAL_SEC", "86400"))
    retention_days = int(os.environ.get("SCLIB_ASK_HISTORY_RETENTION_DAYS", "90"))
    if prune_interval > 0 and retention_days > 0:
        prune_task = asyncio.create_task(
            _periodic_ask_history_prune(prune_interval, retention_days),
            name="sclib-ask-history-prune",
        )
        log.info("ask_history prune scheduled every %ds (retain %dd)",
                 prune_interval, retention_days)
    else:
        prune_task = None
        log.info("ask_history prune disabled")

    try:
        yield
    finally:
        for t in (
            refresh_task,
            projection_task,
            prune_task,
            audit_task,
            nightly_task,
        ):
            if t is None:
                continue
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        engine = get_engine()
        await engine.dispose()
        log.info("SCLib API shutdown complete")


settings = get_settings()

app = FastAPI(
    title="SCLib_JZIS API",
    version="1.0.0",
    description="Superconductivity research library — semantic search, materials DB, RAG Q&A.",
    openapi_url="/v1/openapi.json",
    docs_url="/v1/docs",
    redoc_url="/v1/redoc",
    lifespan=lifespan,
    responses={
        400: {"model": ApiErrorResponse, "description": "Bad request"},
        401: {"model": ApiErrorResponse, "description": "Authentication required"},
        403: {"model": ApiErrorResponse, "description": "Access denied"},
        404: {"model": ApiErrorResponse, "description": "Resource not found"},
        409: {"model": ApiErrorResponse, "description": "Request conflict"},
        422: {"model": ApiErrorResponse, "description": "Validation failed"},
        429: {"model": ApiErrorResponse, "description": "Rate limit exceeded"},
        500: {"model": ApiErrorResponse, "description": "Internal server error"},
    },
)


_ERROR_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    502: "upstream_error",
    503: "service_unavailable",
    504: "upstream_timeout",
}


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or resolve_request_id(request)


def _error_code(status_code: int, detail: object) -> str:
    if isinstance(detail, dict):
        explicit = detail.get("error")
        if isinstance(explicit, str) and explicit:
            return explicit
    return _ERROR_CODES.get(status_code, "http_error")


def _error_response(
    request: Request,
    *,
    status_code: int,
    detail: object,
    error_code: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = _request_id(request)
    response_headers = dict(headers or {})
    response_headers["X-Request-ID"] = request_id
    response_headers["X-API-Version"] = version.API_VERSION
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(
            ApiErrorResponse(
                detail=detail,
                error_code=error_code or _error_code(status_code, detail),
                request_id=request_id,
            ).model_dump()
        ),
        headers=response_headers,
    )


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return _error_response(
        request,
        status_code=exc.status_code,
        detail=exc.detail,
        headers=dict(exc.headers or {}),
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    # FastAPI's default error objects echo the rejected input. Omitting input
    # and validator context keeps passwords and tokens out of responses/logs.
    details = [
        {key: value for key, value in item.items() if key not in {"input", "ctx"}}
        for item in exc.errors()
    ]
    return _error_response(
        request,
        status_code=422,
        detail=details,
        error_code="validation_error",
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = _request_id(request)
    log.error(
        "unhandled request error request_id=%s",
        request_id,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return _error_response(
        request,
        status_code=500,
        detail="Internal server error",
        error_code="internal_error",
    )

# CORS origins must be scheme+host only (no path). `frontend_url` is a
# full base URL used for building verification / docs links, so we strip
# it down to origin form here. Browsers send `Origin: https://jzis.org`
# for a page served at `https://jzis.org/sclib/search`, and Starlette's
# middleware does an exact string match — mismatching on the trailing
# `/sclib` silently fails every POST preflight.
_allowed_origins = allowed_browser_origins(settings)

# --- Middleware stack (order matters!) ---
# Starlette applies middleware in reverse registration order, so the
# LAST middleware added is the OUTERMOST (first to run on a request).
# We need: Request → CORS (handle preflight) → GZip → Session → App
# So register Session first (innermost), then compression, then CORS.

# SessionMiddleware: stores OAuth state in a signed cookie. Must be
# inside the CORS layer so preflight OPTIONS never hits session logic.
_oauth_session = build_oauth_session_config(settings.environment)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.jwt_secret,
    session_cookie=_oauth_session.session_cookie,
    max_age=_oauth_session.max_age,
    path=_oauth_session.path,
    https_only=_oauth_session.https_only,
    same_site=_oauth_session.same_site,
)

app.add_middleware(
    GZipMiddleware,
    minimum_size=1024,
    compresslevel=6,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "ETag",
        "Last-Modified",
        "Retry-After",
        "X-API-Version",
        "X-Data-Version",
        "X-Request-ID",
    ],
)


@app.middleware("http")
async def request_contract_middleware(request: Request, call_next):
    """Attach stable correlation and API-version headers to every response."""
    request_id = resolve_request_id(request)
    request.state.request_id = request_id
    token = bind_request_id(request_id)
    method = request.method
    HTTP_IN_PROGRESS.labels(method).inc()
    started = asyncio.get_running_loop().time()
    status_code = 500
    response_bytes = 0
    try:
        response = await call_next(request)
        status_code = response.status_code
        content_length = response.headers.get("content-length")
        if content_length and content_length.isdigit():
            response_bytes = int(content_length)
    finally:
        route = getattr(request.scope.get("route"), "path", "unmatched")
        observe_http(
            method,
            route,
            status_code,
            asyncio.get_running_loop().time() - started,
            response_bytes,
        )
        HTTP_IN_PROGRESS.labels(method).dec()
        reset_request_id(token)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-API-Version"] = version.API_VERSION
    return response

app.include_router(health.router)
app.include_router(observability.router)
app.include_router(auth.router, prefix="/v1")
app.include_router(search.router, prefix="/v1")
app.include_router(ask.router, prefix="/v1")
app.include_router(materials.router, prefix="/v1")
app.include_router(papers.router, prefix="/v1")
app.include_router(seo.router, prefix="/v1")
app.include_router(similar.router, prefix="/v1")
app.include_router(stats.router, prefix="/v1")
app.include_router(timeline.router, prefix="/v1")
app.include_router(history.router, prefix="/v1")
app.include_router(bookmarks.router, prefix="/v1")
app.include_router(feedback.router, prefix="/v1")
app.include_router(version.router, prefix="/v1")
app.include_router(admin.router, prefix="/v1")
app.include_router(discovery.router, prefix="/v1")
