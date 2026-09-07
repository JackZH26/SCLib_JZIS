"""Public DTO guard for newly retained, non-public structure-text proposals.

Source status is not excerpt redistribution permission. Remove stored structure
proposal containers from raw/public DTOs; a separately rebuilt and redacted
top-level structure_evidence envelope is published by its own contract. This is
not a general text/PII/license sanitizer and must run after identity decisions.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_STORED_STRUCTURE_KEYS = frozenset({"structureclaims", "structureevidence"})


def redact_structure_payloads(value: Any) -> Any:
    """Copy without stored proposal containers, including raw_extraction nests."""
    active: set[int] = set()
    budget = 20_000

    def visit(item: Any, depth: int) -> Any:
        nonlocal budget
        budget -= 1
        if budget < 0 or depth > 64:
            return {"redacted": "structure_disclosure_projection_limit"}
        if not isinstance(item, (Mapping, list, tuple)):
            return item
        identity = id(item)
        if identity in active:
            return {"redacted": "cyclic_metadata"}
        active.add(identity)
        try:
            if isinstance(item, Mapping):
                result = {}
                for key, child in item.items():
                    if budget <= 0:
                        result["_projection_warning"] = "structure_disclosure_projection_limit"
                        break
                    budget -= 1
                    normalized = "".join(char for char in key.lower() if char.isalnum()) if isinstance(key, str) else None
                    if normalized in _STORED_STRUCTURE_KEYS:
                        continue
                    result[key] = visit(child, depth + 1)
                return result
            result = []
            for child in item:
                if budget <= 0:
                    result.append({"redacted": "structure_disclosure_projection_limit"})
                    break
                result.append(visit(child, depth + 1))
            return result
        finally:
            active.remove(identity)

    return visit(value, 0)
