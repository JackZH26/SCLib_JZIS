"""Privacy-minimized browser telemetry wire model."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ClientTelemetryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: Literal["web_vital", "js_error", "unhandled_rejection"]
    name: Literal["CLS", "FCP", "INP", "LCP", "TTFB", "error", "rejection"]
    value: float | None = Field(None, ge=0, le=1_000_000)
    rating: Literal["good", "needs-improvement", "poor", "unknown"] = "unknown"

    @model_validator(mode="after")
    def validate_event_shape(self) -> ClientTelemetryEvent:
        vital_names = {"CLS", "FCP", "INP", "LCP", "TTFB"}
        if self.event_type == "web_vital":
            if self.name not in vital_names or self.value is None:
                raise ValueError("web_vital events require a vital name and value")
        elif self.event_type == "js_error":
            if self.name != "error" or self.value is not None or self.rating != "unknown":
                raise ValueError("js_error events only accept the aggregate error signal")
        elif (
            self.name != "rejection"
            or self.value is not None
            or self.rating != "unknown"
        ):
            raise ValueError(
                "unhandled_rejection events only accept the aggregate rejection signal"
            )
        return self
