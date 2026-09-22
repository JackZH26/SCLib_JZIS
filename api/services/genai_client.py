"""Shared Google Gen AI client construction for the API process."""
from __future__ import annotations

from functools import lru_cache

from google import genai
from google.genai import types as genai_types

from config import get_settings


@lru_cache(maxsize=1)
def public_credentials():
    """Share refreshable ADC across embedding, vector and answer transports."""
    import google.auth

    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    return credentials


@lru_cache(maxsize=1)
def embedding_client() -> genai.Client:
    """Use the document embedding region, independently of Gemini routing."""
    settings = get_settings()
    return genai.Client(
        vertexai=True,
        project=settings.gcp_project,
        location=settings.gcp_region,
        credentials=public_credentials(),
        http_options=genai_types.HttpOptions(api_version="v1", timeout=120_000),
    )


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
            credentials=public_credentials(),
            http_options=http_options,
        )
    return genai.Client(
        vertexai=True,
        project=settings.gcp_project,
        location=settings.gcp_region,
        credentials=public_credentials(),
        http_options=http_options,
    )


def dispose() -> None:
    client.cache_clear()
    embedding_client.cache_clear()
    public_credentials.cache_clear()
