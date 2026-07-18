"""Wire models for liveness, readiness, dependency, and data health."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class LiveHealth(BaseModel):
    status: Literal["ok"] = "ok"
    service: str = "sclib-api"
    version: str = "0.1.0"


class DependencyCheck(BaseModel):
    status: Literal["ok", "error"]
    required: bool = True
    latency_ms: int = Field(ge=0)


class DependencyHealth(BaseModel):
    status: Literal["ok", "unavailable"]
    checked_at: datetime
    dependencies: dict[str, DependencyCheck]


class DataComponentHealth(BaseModel):
    status: str
    updated_at: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class DataHealth(BaseModel):
    status: Literal["ok", "degraded", "unavailable"]
    checked_at: datetime
    components: dict[str, DataComponentHealth]
