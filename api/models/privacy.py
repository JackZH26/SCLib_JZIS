"""Wire schemas for personal-data access and account deletion."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field


class AccountDeletionRequest(BaseModel):
    """Explicit confirmation for the irreversible self-service delete."""

    confirmation: Literal["DELETE"]
    email: EmailStr
    current_password: str | None = Field(None, min_length=1, max_length=128)


class AccountDataExport(BaseModel):
    """Portable JSON snapshot of data directly associated with one account.

    Secret material (password/key/token hashes) is intentionally excluded;
    timestamps and non-secret security metadata remain available to the user.
    """

    schema_version: Literal["1"] = "1"
    generated_at: datetime
    profile: dict[str, Any]
    api_keys: list[dict[str, Any]]
    ask_history: list[dict[str, Any]]
    answer_evidence_access: dict[str, Any] = Field(default_factory=lambda: {
        "version": "ask-history-export-access/1.0.0",
        "inline_receipts_included": False,
        "access": "New saved-answer evidence receipts are available individually at each history entry's evidence_detail_path using the owner's browser session or bearer token. They are not embedded in this account snapshot.",
        "retention": "Receipts follow their history entry's deletion and retention; they are not permanent research archives.",
    })
    bookmarks: list[dict[str, Any]]
    email_verifications: list[dict[str, Any]]
    password_resets: list[dict[str, Any]]
    security_events: list[dict[str, Any]]
