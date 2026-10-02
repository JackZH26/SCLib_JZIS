"""Literal catalogue formula text search; no scientific identity matching.

PostgreSQL's UTF8 NFKC normalization is applied to stored formula text, while
the query receives the same normalization before literal LIKE escaping. This
does not supply aliases, stoichiometric equivalence, phase or sample identity.
"""
from __future__ import annotations

import unicodedata

from sqlalchemy import func, literal_column

MAX_FORMULA_QUERY_CHARS = 200


class FormulaTextQueryError(ValueError):
    """Static query validation failure; never echo user input."""


def _validate_text(value):
    if len(value) > MAX_FORMULA_QUERY_CHARS:
        raise FormulaTextQueryError("q must contain at most 200 characters before and after NFKC normalization")
    if any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):
        raise FormulaTextQueryError("q must not contain C0 or C1 control characters")


def formula_text_pattern(query: str | None) -> str | None:
    if query is None:
        return None
    if type(query) is not str:
        raise FormulaTextQueryError("q must be formula text")
    _validate_text(query)
    normalized = unicodedata.normalize("NFKC", query)
    _validate_text(normalized)
    normalized = normalized.strip()
    if not normalized:
        return None
    literal = normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return "%" + literal + "%"


def formula_text_contains(column, query: str | None):
    pattern = formula_text_pattern(query)
    if pattern is None:
        return None
    # The normalization form is a fixed SQL grammar token. Only the escaped
    # text pattern is bound data; no user input becomes SQL syntax.
    return func.normalize(column, literal_column("NFKC")).ilike(pattern, escape="\\")
