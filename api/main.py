"""FastAPI application entry point.

Exposes everything under /v1 so the path matches the public route
`api.jzis.org/sclib/v1/*` once Nginx strips `/sclib/`. Phase 1 only
mounts the auth router; Phase 3 will add search/ask/materials/etc.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from models.db import get_engine
from routers import ask, auth, materials, papers, search, similar, stats, timeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s  %(message)s",
)
log = logging.getLogger("sclib.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    log.info("SCLib API starting (env=%s, backend=%s)",
             settings.environment, settings.email_backend)
    yield
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
_allowed_origins = [_frontend_origin, "http://localhost:3000"]
if _fe.netloc and not _fe.netloc.startswith("www."):
    _allowed_origins.append(f"{_fe.scheme}://www.{_fe.netloc}")

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
