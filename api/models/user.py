"""Pydantic schemas for user / auth request and response bodies.

These are the wire format; the SQLAlchemy ORM in db.py is the persistence
format. Kept separate so API shape can evolve without churning the DB.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


# ORCID is always 16 digits grouped 4-4-4-4 with hyphens; the final
# character may be 'X' (ISO 7064 MOD 11-2 check digit). We only enforce
# shape, not checksum — clients that paste the URL get it stripped.
# Pasting lowercase 'x' or a trailing slash is a common copy-paste
# artefact and should normalize, not reject.
_ORCID_RE = r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$"
_ORCID_URL_PREFIXES = (
    "HTTPS://ORCID.ORG/",
    "HTTP://ORCID.ORG/",
    "ORCID.ORG/",
)


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    name: str = Field(..., min_length=2, max_length=255)
    age: int = Field(..., ge=13, le=120)
    institution: str | None = Field(None, max_length=500)
    country: str | None = Field(None, max_length=100)
    research_area: str | None = Field(None, max_length=255)
    purpose: str | None = Field(None, max_length=500)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    email_verified: bool = False
    name: str
    institution: str | None
    country: str | None
    research_area: str | None
    bio: str | None = None
    orcid: str | None = None
    created_at: datetime
    is_active: bool
    auth_provider: str = "local"
    avatar_url: str | None = None
    scopes: list[str] = ["basic", "sclib"]


class UserUpdate(BaseModel):
    """PATCH /me payload — only fields the user is allowed to edit.

    Every field is optional: omit to leave untouched, pass ``null`` to
    clear. ``name`` is a special case because the database enforces
    NOT NULL — passing ``null`` for name is rejected (400) instead of
    being allowed to propagate into a 500. Email / id / auth_provider
    / is_active are intentionally absent — those are system-owned.
    """

    name: str | None = Field(None, min_length=2, max_length=255)
    institution: str | None = Field(None, max_length=500)
    country: str | None = Field(None, max_length=100)
    research_area: str | None = Field(None, max_length=255)
    bio: str | None = Field(None, max_length=2000)
    orcid: str | None = Field(None)

    @model_validator(mode="before")
    @classmethod
    def _reject_null_name(cls, data: object) -> object:
        # Only "explicit null" is a problem — an omitted key leaves the
        # field alone and never touches the DB. We have to peek at the
        # raw input to distinguish omitted vs null, which field_validator
        # can't do on its own.
        if isinstance(data, dict) and "name" in data and data["name"] is None:
            raise ValueError(
                "name cannot be set to null; omit the field to leave it unchanged"
            )
        return data

    @field_validator("orcid")
    @classmethod
    def _validate_orcid(cls, v: str | None) -> str | None:
        if v in (None, ""):
            return None
        import re
        # Accept raw IDs and the orcid.org URL form in any case; strip
        # trailing slash before prefix stripping so "orcid.org/XXXX/"
        # also works. Uppercasing up front lets the regex stay simple.
        v = v.strip().rstrip("/").upper()
        for prefix in _ORCID_URL_PREFIXES:
            if v.startswith(prefix):
                v = v[len(prefix):]
                break
        if not re.match(_ORCID_RE, v):
            raise ValueError(
                "ORCID must look like 0000-0002-1825-0097 (16 digits, last may be X)"
            )
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class ApiKeyCreate(BaseModel):
    name: str | None = Field(None, max_length=100)


class ApiKeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key_prefix: str
    name: str | None
    created_at: datetime
    last_used: datetime | None
    revoked: bool
    revoked_at: datetime | None = None
    total_requests: int = 0


class ApiKeyWithSecret(ApiKeyRead):
    """Response containing the full API key plaintext.

    Only returned once on creation / verification. The hashed form is
    persisted; the plaintext is never retrievable again.
    """
    key: str


class RegisterResponse(BaseModel):
    user: UserRead
    message: str


class VerifyResponse(BaseModel):
    user: UserRead
    api_key: str  # shown once, store client-side


class MessageResponse(BaseModel):
    message: str


class UsageStats(BaseModel):
    """GET /auth/usage — per-user quota + historical counters.

    Today numbers come from Redis (``user_quota:YYYY-MM-DD:{user_id}``),
    week is the sum of the last 7 daily keys, all-time is the SUM of
    ``api_keys.total_requests`` for the user (so API-key traffic is
    canonical; dashboard-originated JWT calls are not counted as
    "query usage" for this metric).
    """

    today_used: int
    today_remaining: int
    daily_limit: int
    week_used: int
    all_time_used: int
