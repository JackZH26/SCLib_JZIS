"""Google Gen AI client helpers shared by ingestion NER modules."""
from __future__ import annotations

from google import genai
from google.genai import types as genai_types

from ingestion.config import IngestionSettings, get_settings


def make_genai_client(settings: IngestionSettings | None = None) -> genai.Client:
    """Create a Gemini client using the configured runtime surface.

    Gemini 3.5 Flash is served through Gemini Enterprise Agent Platform
    from the global endpoint. Older deployments can still set
    GEMINI_USE_ENTERPRISE=false to use the Vertex publisher endpoint.
    """
    s = settings or get_settings()
    http_options = genai_types.HttpOptions(
        api_version=s.gemini_api_version,
        timeout=120_000,
    )
    if s.gemini_use_enterprise:
        return genai.Client(
            enterprise=True,
            project=s.gcp_project,
            location=s.gemini_location,
            http_options=http_options,
        )
    return genai.Client(
        vertexai=True,
        project=s.gcp_project,
        location=s.gcp_region,
        http_options=http_options,
    )
