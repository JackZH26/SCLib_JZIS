"""API ORM models and Pydantic schemas.

`db.py` contains SQLAlchemy ORM (the authoritative schema — mirrors
PROJECT_SPEC.md section 4). Per-resource Pydantic schemas live in
sibling modules (user.py, paper.py, material.py, search.py, ask.py).
"""
from .db import (
    ApiKey,
    Base,
    Chunk,
    EmailVerification,
    Material,
    Paper,
    StatsCache,
    User,
    get_db,
    get_engine,
    get_session_factory,
)

__all__ = [
    "Base",
    "User",
    "EmailVerification",
    "ApiKey",
    "Paper",
    "Material",
    "Chunk",
    "StatsCache",
    "get_engine",
    "get_session_factory",
    "get_db",
]
