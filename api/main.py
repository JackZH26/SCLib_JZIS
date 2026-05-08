"""FastAPI application entry point.

Exposes everything under /v1 so the path matches the public route
`api.jzis.org/sclib/v1/*` once Nginx strips `/sclib/`. Phase 1 only
mounts the auth router; Phase 3 will add search/ask/materials/etc.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import delete
from starlette.middleware.sessions import SessionMiddleware

from config import get_settings
from models import get_session_factory
from models.db import AskHistory, get_engine
from routers import (
    ask,
    auth,
    bookmarks,
    feedback,
    history,
    materials,
    papers,
    search,
    similar,
    stats,
    timeline,
    version,
)
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
_FORMULA_CONDITION_REGEX = r"\(?\s*[xyzn]\s*=\s*[0-9]"


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
                        WHERE needs_review = FALSE AND ({predicate});
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
            cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
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
        for t in (refresh_task, prune_task, audit_task):
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
app.include_router(history.router, prefix="/v1")
app.include_router(bookmarks.router, prefix="/v1")
app.include_router(feedback.router, prefix="/v1")
app.include_router(version.router, prefix="/v1")


@app.get("/v1/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "sclib-api", "version": "0.1.0"}
