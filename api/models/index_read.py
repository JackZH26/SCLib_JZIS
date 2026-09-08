"""Public retrieval identity, never an index-quality or scientific approval."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class IndexReadMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    version: Literal["index-read/1.0.0"] = "index-read/1.0.0"
    mode: Literal["generation_snapshot", "legacy_lexical_only"] = "legacy_lexical_only"
    generation_id: str | None = None
    activation_event_id: str | None = None
    manifest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("generation_id", "activation_event_id")
    @classmethod
    def exact_uuid(cls, value):
        if value is not None and str(UUID(value)) != value:
            raise ValueError("A canonical retrieval UUID is required")
        return value

    @model_validator(mode="after")
    def complete_identity(self):
        fields = (self.generation_id, self.activation_event_id, self.manifest_sha256)
        if self.mode == "generation_snapshot":
            if any(value is None for value in fields):
                raise ValueError("A complete generation read identity is required")
        elif any(value is not None for value in fields):
            raise ValueError("Legacy lexical retrieval has no generation identity")
        return self


def generation_read_metadata(pin=None) -> IndexReadMetadata:
    if pin is None:
        return IndexReadMetadata()
    return IndexReadMetadata(mode="generation_snapshot", **{
        key: pin[key] for key in ("generation_id", "activation_event_id", "manifest_sha256")
    })
