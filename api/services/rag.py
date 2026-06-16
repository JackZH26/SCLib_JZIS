"""RAG answer generation on top of Gemini.

We keep this thin: the router does all the retrieval work and hands
us a prepared list of sources. This module's job is prompt assembly,
the LLM call, and usage-count extraction.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

from google import genai
from google.genai import types as genai_types

from config import get_settings

log = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are SCLib, a superconductivity research assistant.

Answer the user's question using ONLY the provided source excerpts.
Each source has an index like [1], [2], etc. You MUST cite every
factual claim inline using bracket notation: "NbTi has a Tc of about
9 K [1]." Prefer shorter, precise answers over speculation.

If the sources do not contain enough information to answer, say so
explicitly. Do not invent citations, formulas, or numerical values.
The user language preference is: {language}.
"""


@dataclass(slots=True)
class RagSourceInput:
    index: int
    title: str
    authors_short: str
    year: int | None
    section: str | None
    text: str


@dataclass(slots=True)
class RagResult:
    answer: str
    tokens_used: int | None


@lru_cache(maxsize=1)
def _client() -> genai.Client:
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


def _format_sources(sources: list[RagSourceInput]) -> str:
    blocks: list[str] = []
    for s in sources:
        header = f"[{s.index}] {s.title} — {s.authors_short}"
        if s.year:
            header += f" ({s.year})"
        if s.section:
            header += f" · {s.section}"
        blocks.append(f"{header}\n{s.text.strip()}")
    return "\n\n".join(blocks)


def generate_answer(
    question: str,
    sources: list[RagSourceInput],
    *,
    language: str = "auto",
) -> RagResult:
    """Blocking Gemini call. Callers should push this to a worker thread."""
    if not sources:
        return RagResult(
            answer="I couldn't find any indexed sources that address this question.",
            tokens_used=0,
        )

    sys = SYSTEM_PROMPT.format(language=language)
    body = _format_sources(sources)
    prompt = (
        f"{sys}\n\n"
        f"## Sources\n\n{body}\n\n"
        f"## Question\n\n{question}\n\n"
        f"## Answer (markdown, with [n] citations)\n"
    )

    settings = get_settings()
    resp = _client().models.generate_content(
        model=settings.gemini_model,
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            temperature=0.2,
            max_output_tokens=1024,
            thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
        ),
    )

    # Vertex's GenerativeModel raises ValueError on blocked / empty
    # candidates when you touch `.text`. Catch that specifically —
    # a bare `except Exception` would swallow real bugs (auth
    # refresh failures, transport errors) and hand users a generic
    # "couldn't answer" string with no log trace.
    try:
        answer = resp.text or ""
    except ValueError as exc:
        log.warning("Gemini response had no text (blocked/empty): %s", exc)
        answer = "The model could not produce an answer for this question."

    usage = getattr(resp, "usage_metadata", None)
    tokens_used = int(getattr(usage, "total_token_count", 0)) if usage else None
    return RagResult(answer=answer.strip(), tokens_used=tokens_used)


def dispose() -> None:
    _client.cache_clear()
