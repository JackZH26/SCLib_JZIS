"""Section-aware chunker.

Input: ``ParsedPaper``. Output: ``list[Chunk]`` where each chunk is a
~512-token window (with 64-token overlap). Chunks never cross section
boundaries — small sections become a single chunk, and long sections get
split greedily by paragraph with a per-chunk token budget.

Every chunk text is prefixed with::

    Title: {title}
    Section: {section}

so the embedding model (and later the Gemini RAG pass) always has the
paper context even when a chunk lands mid-paragraph.

Token counting uses the ``cl100k_base`` BPE from tiktoken — it's not
exactly the tokenizer Vertex text-embedding-005 uses, but it's close
enough for sizing the input window without risking a request-side error.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import tiktoken

from ingestion.config import get_settings
from ingestion.models import Chunk, ParsedPaper, Section

log = logging.getLogger(__name__)

_PARA_SPLIT = re.compile(r"\n\s*\n")

# cl100k_base is used by text-embedding-3-*, GPT-4, Claude. It is a close
# approximation for sizing Vertex text-embedding-005 requests — we leave a
# generous margin below the 2048 per-input limit.
_ENCODER = tiktoken.get_encoding("cl100k_base")


def _count_tokens(text: str) -> int:
    return len(_ENCODER.encode(text, disallowed_special=()))


#: Public alias so callers outside the chunker (e.g. the embedder's
#: per-request token budgeter) can share the same tokenizer.
count_tokens = _count_tokens


@dataclass
class _Window:
    section: Section
    text: str
    tokens: int


def chunk_paper(parsed: ParsedPaper) -> list[Chunk]:
    settings = get_settings()
    size = settings.chunk_size_tokens
    overlap = settings.chunk_overlap_tokens

    title = parsed.meta.title
    prefix_tmpl = "Title: {t}\nSection: {s}\n\n"

    out: list[Chunk] = []
    idx = 0

    for section in parsed.sections:
        if not section.text.strip():
            continue
        prefix = prefix_tmpl.format(t=title, s=section.name)
        prefix_tokens = _count_tokens(prefix)
        budget = max(32, size - prefix_tokens)

        windows = _pack_paragraphs(section, budget=budget, overlap=overlap)

        for w in windows:
            text = prefix + w.text
            chunk_id = f"{parsed.meta.paper_id}_chunk_{idx:03d}"
            out.append(
                Chunk(
                    id=chunk_id,
                    paper_id=parsed.meta.paper_id,
                    chunk_index=idx,
                    section=section.name,
                    text=text,
                    token_count=prefix_tokens + w.tokens,
                    has_equation=section.has_equation,
                    has_table=section.has_table,
                )
            )
            idx += 1

    if not out:
        # Fall back to abstract-only chunk so the paper still ends up in VS.
        abstract = parsed.meta.abstract or parsed.abstract_override or ""
        if abstract:
            text = f"Title: {title}\nSection: Abstract\n\n{abstract}"
            out.append(
                Chunk(
                    id=f"{parsed.meta.paper_id}_chunk_000",
                    paper_id=parsed.meta.paper_id,
                    chunk_index=0,
                    section="Abstract",
                    text=text,
                    token_count=_count_tokens(text),
                )
            )
    return out


def _pack_paragraphs(
    section: Section,
    *,
    budget: int,
    overlap: int,
) -> list[_Window]:
    """Greedy paragraph packer.

    Adds paragraphs to the current window until the token count would
    exceed ``budget``. When flushing, the tail of the current window is
    re-seeded into the next one to give ~``overlap`` tokens of context.
    """
    paragraphs = [p.strip() for p in _PARA_SPLIT.split(section.text) if p.strip()]
    if not paragraphs:
        return []

    windows: list[_Window] = []
    current_paras: list[str] = []
    current_tokens = 0

    def flush() -> None:
        nonlocal current_paras, current_tokens
        if not current_paras:
            return
        text = "\n\n".join(current_paras)
        windows.append(_Window(section=section, text=text, tokens=current_tokens))
        # Seed the next window with the tail of this one to preserve
        # context across the boundary.
        tail = _tail_by_tokens(text, overlap)
        current_paras = [tail] if tail else []
        current_tokens = _count_tokens(tail) if tail else 0

    for para in paragraphs:
        t = _count_tokens(para)
        # A single oversized paragraph gets hard-split by sentence.
        if t > budget:
            flush()
            for piece in _split_oversized(para, budget, overlap):
                piece_tokens = _count_tokens(piece)
                windows.append(_Window(section=section, text=piece, tokens=piece_tokens))
            continue

        if current_tokens + t > budget and current_paras:
            flush()
        current_paras.append(para)
        current_tokens += t

    flush()
    return windows


_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _split_oversized(para: str, budget: int, overlap: int) -> list[str]:
    """Hard-split a paragraph whose token count exceeds the budget."""
    sentences = _SENT_SPLIT.split(para)
    out: list[str] = []
    buf: list[str] = []
    buf_tokens = 0
    for sent in sentences:
        st = _count_tokens(sent)
        if buf_tokens + st > budget and buf:
            out.append(" ".join(buf))
            tail = _tail_by_tokens(" ".join(buf), overlap)
            buf = [tail, sent] if tail else [sent]
            buf_tokens = _count_tokens(" ".join(buf))
        else:
            buf.append(sent)
            buf_tokens += st
    if buf:
        out.append(" ".join(buf))
    return out


def _tail_by_tokens(text: str, n_tokens: int) -> str:
    if n_tokens <= 0:
        return ""
    ids = _ENCODER.encode(text, disallowed_special=())
    if len(ids) <= n_tokens:
        return text
    return _ENCODER.decode(ids[-n_tokens:])
