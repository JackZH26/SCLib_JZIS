"""Closed operational input-budget metadata, never source or billing evidence."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

INPUT_PROFILE = "sclib-gemini-text-rag/1.0.0"
DEFAULT_BYTE_LIMIT = 256 * 1024
HARD_BYTE_LIMIT = 1024 * 1024
DEFAULT_INPUT_TOKEN_LIMIT = 16384
HARD_INPUT_TOKEN_LIMIT = 131072


class RagInputBudgetReport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    status: Literal["not_requested", "counted", "rejected", "unavailable"] = "not_requested"
    model: str | None = Field(default=None, pattern=r"^gemini-[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
    profile: Literal["sclib-gemini-text-rag/1.0.0"] = INPUT_PROFILE
    request_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    payload_bytes: int | None = Field(default=None, ge=1)
    byte_limit: int = Field(default=DEFAULT_BYTE_LIMIT, ge=1, le=HARD_BYTE_LIMIT)
    input_tokens: int | None = Field(default=None, ge=1, le=2147483647)
    max_input_tokens: int | None = Field(default=None, ge=1, le=HARD_INPUT_TOKEN_LIMIT)
    count_method: Literal["provider_count_tokens"] = "provider_count_tokens"
    generation_started: bool | None = None
    scientific_acceptance: Literal[False] = False

    @field_validator("scientific_acceptance", mode="before")
    @classmethod
    def no_acceptance_coercion(cls, value):
        if value is not False:
            raise ValueError("A budget observation is never scientific acceptance")
        return value

    @model_validator(mode="after")
    def consistent_state(self):
        if self.status == "not_requested" and any(value is not None for value in (
                self.model, self.request_sha256, self.payload_bytes, self.input_tokens,
                self.max_input_tokens, self.generation_started)):
            raise ValueError("An unrequested count cannot describe provider work")
        if self.status == "counted" and self.generation_started is not True:
            raise ValueError("A completed budget pipeline must report generation start")
        if self.status == "counted" or self.generation_started:
            if (self.model is None or self.request_sha256 is None or self.payload_bytes is None
                    or self.payload_bytes > self.byte_limit or self.input_tokens is None
                    or self.max_input_tokens is None or self.input_tokens > self.max_input_tokens):
                raise ValueError("Generation requires the complete bounded request count")
        if self.status == "rejected" and self.generation_started:
            raise ValueError("A rejected request cannot start generation")
        return self
