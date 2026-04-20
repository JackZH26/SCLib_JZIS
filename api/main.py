"""FastAPI application entry point.

Exposes everything under /v1 so the path matches the public route
`api.jzis.org/sclib/v1/*` once Nginx strips `/sclib/`. Phase 1 only
mounts the auth router; Phase 3 will add search/ask/materials/etc.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from config import get_settings
from models import get_session_factory
from models.db import get_engine
from routers import ask, auth, materials, papers, search, similar, stats, timeline
from services.stats_refresh import refresh_dashboard_cache

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

    try:
        yield
    finally:
        if refresh_task is not None:
            refresh_task.cancel()
            try:
                await refresh_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        engine = get_engine()
        await engine.dispose()
        log.info("SCLib API shutdown complete")


settings = get_settings()

app = FastAPI(
    title="SCLib_JZIS API",
    version="0.1.0",
    description="Superconductivity research library — semantic search, materials DB, RAG Q&A.",
    openapi_url="/v1/openapi.json",
    docs_url="/v1/docs",
    redoc_url="/v1/redoc",
    lifespan=lifespan,
)

# CORS origins must be scheme+host only (no path). `frontend_url` is a
# full base URL used for building verification / docs links, so we strip
# it down to origin form here. Browsers send `Origin: https://jzis.org`
# for a page served at `https://jzis.org/sclib/search`, and Starlette's
# middleware does an exact string match — mismatching on the trailing
# `/sclib` silently fails every POST preflight.
_fe = urlsplit(str(settings.frontend_url))
_frontend_origin = f"{_fe.scheme}://{_fe.netloc}" if _fe.scheme and _fe.netloc else str(settings.frontend_url)

# Include the `www.` sibling of the frontend origin. Users may hit the
# site via either `jzis.org` or `www.jzis.org` (both resolve in DNS),
# and the browser sends whichever host is in the address bar as the
# Origin header. Starlette does exact-match so we need both.
_allowed_origins = [_frontend_origin, "http://localhost:3000", "https://asrp.jzis.org"]
if _fe.netloc and not _fe.netloc.startswith("www."):
    _allowed_origins.append(f"{_fe.scheme}://www.{_fe.netloc}")

# --- Middleware stack (order matters!) ---
# Starlette applies middleware in reverse registration order, so the
# LAST middleware added is the OUTERMOST (first to run on a request).
# We need: Request → CORS (handle preflight) → Session → App
# So register Session first (innermost), then CORS (outermost).

# SessionMiddleware: stores OAuth state in a signed cookie. Must be
# inside the CORS layer so preflight OPTIONS never hits session logic.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.jwt_secret,
    max_age=300,        # OAuth state lives 5 minutes
    https_only=settings.environment == "production",
    same_site="lax",    # safe for OAuth redirect (top-level GET)
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/v1")
app.include_router(search.router, prefix="/v1")
app.include_router(ask.router, prefix="/v1")
app.include_router(materials.router, prefix="/v1")
app.include_router(papers.router, prefix="/v1")
app.include_router(similar.router, prefix="/v1")
app.include_router(stats.router, prefix="/v1")
app.include_router(timeline.router, prefix="/v1")


@app.get("/v1/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "sclib-api", "version": "0.1.0"}
