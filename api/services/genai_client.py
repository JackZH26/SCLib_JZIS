"""Shared Google Gen AI client construction for the API process."""
from __future__ import annotations

from functools import lru_cache

from google import genai
from google.genai import types as genai_types

from config import get_settings


@lru_cache(maxsize=1)
def client() -> genai.Client:
    """Create a Gen AI client using the configured runtime surface."""
    settings = get_settings()
    http_options = genai_types.HttpOptions(
        api_version=settings.gemini_api_version,
        timeout=120_000,
    )
    if settings.gemini_use_enterprise:
        return genai.Client(
            enterprise=True,
            project=settings.gcp_project,
            location=settings.gemini_location,
            http_options=http_options,
        )
    return genai.Client(
        vertexai=True,
        project=settings.gcp_project,
        location=settings.gcp_region,
        http_options=http_options,
    )


def dispose() -> None:
    client.cache_clear()
