"""Thin async client for the Materials Project REST API.

We deliberately do *not* depend on the official ``mp-api`` package
(it pulls in pymatgen, mongomock, and a long tail of scientific
deps that we do not need here — we just want a few fields per
formula). This wrapper covers exactly the calls SCLib makes:

- ``search_by_formula``: formula → list of MP summaries (used by the
  Phase B sync script and the Phase C RAG augmentation).

Conventions:

- Calls are async (httpx.AsyncClient) so the FastAPI request loop
  is never blocked. The Phase B sync script runs the same client
  via ``asyncio.run`` so a one-shot batch job and live-traffic
  paths share exactly the same code.
- The MP API is rate-limited; we do not implement client-side
  throttling here — callers (sync script, RAG path) are responsible
  for spacing their requests. Keeping the throttle out of the client
  means a request inside a FastAPI handler stays a single round-trip
  and doesn't accidentally sleep on the event loop.
- Failures raise ``httpx.HTTPStatusError`` for non-2xx responses or
  ``httpx.RequestError`` for transport-level problems. Callers
  decide whether to swallow these (RAG augmentation: yes, fail open)
  or surface them (sync script: log and continue with the next
  material).
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx

log = logging.getLogger(__name__)

MP_API_BASE = "https://api.materialsproject.org"
DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=30.0)


class MaterialsProjectClient:
    """Async wrapper around a small slice of the MP REST API.

    Use as an async context manager so the underlying connection pool
    closes deterministically::

        async with MaterialsProjectClient(api_key) as mp:
            hits = await mp.search_by_formula("La3Ni2O7")
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = MP_API_BASE,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    ) -> None:
        if not api_key:
            raise ValueError(
                "MaterialsProjectClient requires a non-empty api_key — set "
                "MP_API_KEY in the environment, or get a free one at "
                "https://next-gen.materialsproject.org/api"
            )
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-API-KEY": api_key, "Accept": "application/json"},
            timeout=timeout,
        )

    async def __aenter__(self) -> "MaterialsProjectClient":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search_by_formula(
        self,
        formula: str,
        *,
        fields: tuple[str, ...] = (
            "material_id",
            "formula_pretty",
            "energy_above_hull",
            "band_gap",
            "is_metal",
            "symmetry",
        ),
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return MP summary docs whose ``formula_pretty`` matches.

        Sorted by the caller (we don't add ``_sort`` server-side since
        ``energy_above_hull`` may be NULL for some entries and the API
        treats NULL as "smallest"). The caller does the ``min(eah)``
        pick after the fetch.

        Empty list when no match — the partial-index assumption in
        the materials table holds (most rows will have no MP id).
        """
        params = {
            "formula": formula,
            "_fields": ",".join(fields),
            "_limit": limit,
        }
        resp = await self._client.get("/materials/summary/", params=params)
        resp.raise_for_status()
        body = resp.json()
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list):
            log.warning(
                "MP /materials/summary returned unexpected shape for %s: %r",
                formula,
                type(body).__name__,
            )
            return []
        return data


@asynccontextmanager
async def open_client(api_key: str) -> AsyncIterator[MaterialsProjectClient]:
    """Convenience helper so callers can ``async with open_client(key) as mp``
    without importing the class directly. Mirrors the openai / google.genai
    factory pattern.
    """
    client = MaterialsProjectClient(api_key)
    try:
        yield client
    finally:
        await client.aclose()


def best_match(
    rows: list[dict[str, Any]],
) -> tuple[str | None, list[str]]:
    """Pick the primary mp_id and full alternates list from search hits.

    The primary is the row with the smallest ``energy_above_hull``;
    rows missing that field are sorted last (None → +inf). The
    alternates list is the full set of mp ids in the same order, so
    ``alternates[0] == primary`` whenever there's at least one match.
    Two-return convention keeps the call site at the sync script
    short:

        primary, alternates = best_match(rows)
        material.mp_id = primary
        material.mp_alternate_ids = alternates
    """
    if not rows:
        return None, []

    def _key(r: dict[str, Any]) -> float:
        v = r.get("energy_above_hull")
        return float(v) if isinstance(v, (int, float)) else float("inf")

    ordered = sorted(rows, key=_key)
    ids = [r["material_id"] for r in ordered if r.get("material_id")]
    return (ids[0] if ids else None), ids
