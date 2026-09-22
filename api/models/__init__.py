"""API ORM models and Pydantic schemas.

`db.py` contains SQLAlchemy ORM (the authoritative schema — mirrors
PROJECT_SPEC.md section 4). Per-resource Pydantic schemas live in
sibling modules (user.py, paper.py, material.py, search.py, ask.py).
"""
from .db import (
    ApiKey,
    AuthAuditEvent,
    Base,
    Chunk,
    EmailVerification,
    Material,
    MaterialClaim,
    MlDatasetSnapshot,
    MlExample,
    Paper,
    PaperWorkMap,
    PasswordResetToken,
    SourceSnapshot,
    StatsCache,
    TimelineProjectionPoint,
    TimelineProjectionState,
    User,
    Work,
    get_db,
    get_engine,
    get_session_factory,
)

__all__ = [
    "Base",
    "User",
    "EmailVerification",
    "ApiKey",
    "AuthAuditEvent",
    "PasswordResetToken",
    "Paper",
    "Material",
    "MaterialClaim",
    "MlDatasetSnapshot",
    "MlExample",
    "Chunk",
    "SourceSnapshot",
    "Work",
    "PaperWorkMap",
    "StatsCache",
    "TimelineProjectionPoint",
    "TimelineProjectionState",
    "get_engine",
    "get_session_factory",
    "get_db",
]
