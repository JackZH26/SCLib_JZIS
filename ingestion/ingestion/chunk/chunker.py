"""Section-aware, source-preserving chunks with a complete-text token bound.

Bodies are exact contiguous Python-character slices, including whitespace and
overlap. Locators are zero-based, end-exclusive positions in the parsed section,
not a PDF or verified capture. Prefix metadata can be explicitly [truncated];
original metadata and source text remain untouched.

cl100k_base is not the provider tokenizer: the embedding layer must separately
validate provider limits and absence of truncation.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

import tiktoken

from ingestion.config import get_settings
from ingestion.models import Chunk, ParsedPaper, Section
from ingestion.rag_evidence_contract import VERSION as EVIDENCE_VERSION

_ENCODER = tiktoken.get_encoding("cl100k_base")
# No N-token input can contain more than N times this many UTF-8 bytes.
_MAX_TOKEN_BYTES = max(map(len, _ENCODER.token_byte_values()))
_BOUNDARY = re.compile(r"\n[ \t]*\n|[.!?。！？](?:\s+|$)|\n")
_TRUNCATION_MARKER = " [truncated]"
MIN_CHUNK_TOKENS = 64
CHUNKER_VERSION = "sclib-section-chunker/2.0.0"


def count_tokens(text: str) -> int:
    """Count cl100k tokens, not provider tokens, for the complete string."""
    return len(_ENCODER.encode(text, disallowed_special=()))


_count_tokens = count_tokens


def _validate_text(text: str) -> None:
    if type(text) is not str:
        raise ValueError("Chunk input must be text")
    try:
        text.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError("Chunk input must contain valid Unicode characters") from exc


def _validate_limit(max_tokens: int) -> None:
    if type(max_tokens) is not int or max_tokens < MIN_CHUNK_TOKENS:
        raise ValueError(f"Chunk token limit must be an integer >= {MIN_CHUNK_TOKENS}")


def validate_chunk_settings(size: int, overlap: int) -> None:
    """Overlap is a maximum; it may shrink to guarantee forward progress."""
    _validate_limit(size)
    if type(overlap) is not int or not 0 <= overlap < size:
        raise ValueError("Chunk overlap must be an integer >= 0 and below the token limit")


def fits_token_budget(text: str, *, max_tokens: int) -> bool:
    _validate_limit(max_tokens)
    _validate_text(text)
    return count_tokens(text) <= max_tokens


def require_token_budget(text: str, *, max_tokens: int) -> int:
    """Return the actual full-text count or reject; never truncate a claim."""
    _validate_limit(max_tokens)
    _validate_text(text)
    tokens = count_tokens(text)
    if tokens > max_tokens:
        raise ValueError("Complete chunk text exceeds the configured token limit")
    return tokens


def _fitting_prefix_end(stop: int, fits: Callable[[int], bool]) -> int:
    """Find a fitting character prefix, with zero known to fit.

    BPE counts are not strictly monotonic. Binary search may choose a shorter
    than optimal span, but each retained endpoint fits the complete candidate.
    Correctness never assumes token additivity or decodes isolated token bytes.
    """
    if stop == 0:
        return 0
    low, high = 0, min(64, stop)
    # Grow a bounded look-ahead rather than encoding a whole long OCR/CJK
    # section at the start of every window.
    while fits(high):
        low = high
        if high == stop:
            return high
        high = min(stop, high * 2)
    while low + 1 < high:
        middle = (low + high) // 2
        if fits(middle):
            low = middle
        else:
            high = middle
    return low


def _bounded_metadata(value: str, token_limit: int) -> str:
    if count_tokens(value) <= token_limit:
        return value
    stop = min(len(value), token_limit * _MAX_TOKEN_BYTES)
    end = _fitting_prefix_end(
        stop, lambda end: count_tokens(value[:end] + _TRUNCATION_MARKER) <= token_limit,
    )
    return value[:end] + _TRUNCATION_MARKER


def build_bounded_prefix(title: str, section: str, *, max_tokens: int) -> str:
    """Use <= min(128, max_tokens//2) tokens for disclosed context metadata.

    At least half the configured limit is reserved for body text. Callers must
    still recount prefix + body together; counts are not additive.
    """
    _validate_limit(max_tokens)
    _validate_text(title)
    _validate_text(section)
    prefix_limit = min(128, max_tokens // 2)

    def render(first: str, second: str) -> str:
        return f"Title: {first}\nSection: {second}\n\n"

    original = render(title, section)
    if count_tokens(original) <= prefix_limit:
        return original
    marker_tokens = count_tokens(_TRUNCATION_MARKER)
    field_limit = max(marker_tokens, (prefix_limit - count_tokens(render("", ""))) // 2)
    while field_limit >= marker_tokens:
        prefix = render(_bounded_metadata(title, field_limit),
                        _bounded_metadata(section, field_limit))
        if count_tokens(prefix) <= prefix_limit:
            return prefix
        field_limit -= 1
    raise ValueError("Token limit cannot accommodate a disclosed metadata prefix")


def _original_evidence_candidate(kind: str, section: str, section_path: str,
                                 char_start: int, char_end: int) -> dict:
    """Declare parsed-source coordinates, not rights or a verified root."""
    locator: dict[str, str | int] = {
        "section_path": section_path, "char_start": char_start, "char_end": char_end,
    }
    # The index path remains unambiguous for duplicate/long/control headings.
    # Omit an unrepresentable label instead of shortening its source identity.
    if section.strip() and len(section) <= 300 and not any(ord(c) < 32 for c in section):
        locator["section"] = section
    return {
        "version": EVIDENCE_VERSION,
        "chunk_kind": kind,
        "parent_record": None,
        "extraction_version": None,
        "rendering_version": CHUNKER_VERSION,
        "source_capture_id": None,
        "source_locator": locator,
        "unresolved_reason": "original_binding_unreviewed",
        "permission_status": "unresolved",
    }


@dataclass(frozen=True)
class _Window:
    char_start: int
    char_end: int


def _tail_by_tokens(text: str, n_tokens: int) -> str:
    """Return an exact Unicode-safe suffix using at most n_tokens."""
    _validate_text(text)
    if type(n_tokens) is not int or n_tokens < 0:
        raise ValueError("Overlap token count must be a nonnegative integer")
    if n_tokens == 0:
        return ""
    stop = min(len(text), n_tokens * _MAX_TOKEN_BYTES)
    length = _fitting_prefix_end(
        stop, lambda length: count_tokens(text[len(text) - length:]) <= n_tokens,
    )
    return text[len(text) - length:]


def _section_windows(text: str, *, prefix: str, size: int, overlap: int) -> list[_Window]:
    _validate_text(text)
    if len(text) > 1_000_000_000:
        raise ValueError("Section exceeds the supported source-coordinate range")
    windows: list[_Window] = []
    start = 0
    while start < len(text):
        stop = min(len(text) - start, size * _MAX_TOKEN_BYTES)
        length = _fitting_prefix_end(
            stop, lambda length: count_tokens(prefix + text[start:start + length]) <= size,
        )
        minimum_end = windows[-1].char_end + 1 if windows else start + 1
        # The previous iteration admits at least one new character. Retain
        # that known-fitting endpoint even if non-monotonic BPE counts make
        # the binary search choose an unnecessarily short span.
        end = max(start + length, minimum_end)
        if end > len(text) or count_tokens(prefix + text[start:end]) > size:
            raise ValueError("Token budget cannot accommodate the next source character")
        # Prefer a nearby source boundary without rewriting whitespace. A
        # shorter slice still needs a fresh full-text BPE check.
        if end < len(text):
            for match in reversed(list(_BOUNDARY.finditer(text, start + length // 2, end))):
                candidate_end = match.end()
                if candidate_end >= minimum_end and count_tokens(prefix + text[start:candidate_end]) <= size:
                    end = candidate_end
                    break
        windows.append(_Window(start, end))
        if end == len(text):
            break
        tail = _tail_by_tokens(text[start:end], overlap)
        next_start = max(start + 1, end - len(tail))
        # High overlap cannot consume the space needed for new source text.
        # Dropping overlap is safe; dropping source characters is not.
        if (count_tokens(text[next_start:end]) > overlap
                or count_tokens(prefix + text[next_start:end + 1]) > size):
            next_start = end
        start = next_start
    return windows


def chunk_paper(parsed: ParsedPaper) -> list[Chunk]:
    settings = get_settings()
    size, overlap = settings.chunk_size_tokens, settings.chunk_overlap_tokens
    validate_chunk_settings(size, overlap)
    out: list[Chunk] = []

    def append_section(section: Section, kind: str, section_path: str) -> None:
        prefix = build_bounded_prefix(parsed.meta.title, section.name, max_tokens=size)
        for window in _section_windows(section.text, prefix=prefix, size=size, overlap=overlap):
            text = prefix + section.text[window.char_start:window.char_end]
            index = len(out)
            out.append(Chunk(
                id=f"{parsed.meta.paper_id}_chunk_{index:03d}",
                paper_id=parsed.meta.paper_id, chunk_index=index, section=section.name,
                text=text, token_count=require_token_budget(text, max_tokens=size),
                has_equation=section.has_equation, has_table=section.has_table,
                evidence_candidate=_original_evidence_candidate(
                    kind, section.name, section_path, window.char_start, window.char_end,
                ),
            ))

    for index, section in enumerate(parsed.sections):
        # Even whitespace-only sections retain all source positions.
        if section.text:
            append_section(section, "original_passage", f"sections/{index}")
    if not out:
        abstract = parsed.meta.abstract or parsed.abstract_override or ""
        if abstract:
            path = "metadata/abstract" if parsed.meta.abstract else "abstract_override"
            append_section(Section(name="Abstract", text=abstract), "abstract", path)
    return out
