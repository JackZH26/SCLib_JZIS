"""Shared helpers for formatting a paper's authors JSONB blob.

Papers store authors in two shapes depending on ingestion source:

* arXiv OAI-PMH parsing → ``["Alice Smith", "Bob Jones"]``
* NIMS SuperCon / hand-entered → ``[{"name": "Alice Smith"}, ...]`` or
  ``[{"family": "Smith", "given": "Alice"}, ...]``

Each consumer (RAG prompt builder, bookmark list hydrator, search
hit renderer …) used to carry its own flatten logic. Centralizing
here means one bug-fix propagates everywhere and tests can pin the
behaviour in one place.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def names(authors: Iterable[Any] | None) -> list[str]:
    """Flatten a JSONB authors list to plain display strings.

    Accepts either a list of strings or a list of dicts and returns
    whichever ``name`` the upstream data carried. Unknown shapes are
    skipped rather than raised so a single malformed row cannot break
    a whole list page.
    """
    if not authors:
        return []
    out: list[str] = []
    for a in authors:
        if isinstance(a, str):
            cleaned = a.strip()
            if cleaned:
                out.append(cleaned)
        elif isinstance(a, dict):
            n = a.get("name") or a.get("family") or ""
            n = str(n).strip()
            if n:
                out.append(n)
    return out


def short(authors: Iterable[Any] | None) -> str:
    """'Smith et al.' for >2 authors, 'Smith & Jones' for 2, 'Smith' for 1.

    Used by the RAG prompt builder and anywhere we need a compact
    author credit (search hits, bookmark rows that show inline
    attribution).
    """
    all_names = names(authors)
    if not all_names:
        return "Unknown"
    # Use surname only ("A. Smith, B. Jones" → "Smith"). First comma
    # splits "Last, First" entries from the NIMS import.
    surnames = [n.split(",")[0].strip() for n in all_names]
    surnames = [s for s in surnames if s]
    if not surnames:
        return "Unknown"
    if len(surnames) == 1:
        return surnames[0]
    # Only flip to "et al." when the *original* list had more than two
    # entries; "Smith & Jones" is more readable than "Smith et al."
    # for a pair.
    if len(all_names) > 2:
        return f"{surnames[0]} et al."
    return " & ".join(surnames[:2])
