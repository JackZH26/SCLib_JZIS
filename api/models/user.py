"""Pydantic schemas for user / auth request and response bodies.

These are the wire format; the SQLAlchemy ORM in db.py is the persistence
format. Kept separate so API shape can evolve without churning the DB.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


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
    name: str
    institution: str | None
    country: str | None
    research_area: str | None
    created_at: datetime
    is_active: bool
    auth_provider: str = "local"
    avatar_url: str | None = None
    scopes: list[str] = ["basic", "sclib"]


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
