"""Auth primitives: password hashing, JWT, API key lifecycle.

All stateless utilities — no DB access here; routers compose these with
the ORM. bcrypt cost=12 per spec section 5.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import bcrypt
import jwt

from config import get_settings


# --- passwords ------------------------------------------------------------

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


# --- JWT ------------------------------------------------------------------

def create_access_token(user_id: UUID) -> tuple[str, int]:
    """Return (token, expires_in_seconds)."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=settings.jwt_expiry_hours)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    return token, settings.jwt_expiry_hours * 3600


def decode_access_token(token: str) -> dict[str, Any]:
    """Raises jwt.PyJWTError on invalid/expired tokens."""
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])


# --- API keys -------------------------------------------------------------

def generate_api_key() -> tuple[str, str, str]:
    """Return (plain_key, sha256_hash, key_prefix).

    Plain key format: API_KEY_PREFIX + 40 urlsafe chars.
    Store only the sha256_hash; display the key_prefix (first 12 chars).
    """
    settings = get_settings()
    # token_urlsafe(n) returns ~1.33n chars; slice to exactly 40
    body = secrets.token_urlsafe(32)[:40]
    plain = f"{settings.api_key_prefix}{body}"
    return plain, hash_api_key(plain), plain[:12]


def hash_api_key(plain: str) -> str:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def generate_verification_token() -> str:
    """64-char urlsafe token for email verification."""
    return secrets.token_urlsafe(48)[:64]
