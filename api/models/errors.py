"""Stable public error response contract."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ApiErrorResponse(BaseModel):
    """Additive envelope used for all HTTP and validation errors.

    ``detail`` preserves the original FastAPI-compatible value so existing
    clients continue to work. New clients should use ``error_code`` for
    branching and include ``request_id`` in support reports.
    """

    detail: Any
    error_code: str
    request_id: str
