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


class RetrievalEmbeddingProfile(BaseModel):
    """Exact retained embedding space; dimensionality alone is insufficient."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    version: Literal["sclib-index-profile/1.0.0"]
    provider: Literal["google-vertex-ai"]
    model: Literal["text-embedding-005"]
    output_dimensionality: Literal[768]
    document_task: Literal["RETRIEVAL_DOCUMENT"]
    query_task: Literal["RETRIEVAL_QUERY"]

    @field_validator("output_dimensionality", mode="before")
    @classmethod
    def integer_dimension(cls, value):
        if type(value) is not int:
            raise ValueError("An exact integer embedding dimensionality is required")
        return value


class ContentReadMetadata(BaseModel):
    """V2 content/backend identity, with no invented provider generation."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    version: Literal["index-read/2.0.0"] = "index-read/2.0.0"
    mode: Literal["content_snapshot"] = "content_snapshot"
    content_id: str
    build_id: str
    activation_event_id: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile: RetrievalEmbeddingProfile

    @field_validator("content_id", "build_id", "activation_event_id")
    @classmethod
    def exact_uuid(cls, value):
        if str(UUID(value)) != value:
            raise ValueError("A canonical retrieval UUID is required")
        return value


RetrievalReadMetadata = IndexReadMetadata | ContentReadMetadata


def retrieval_read_metadata(pin=None) -> RetrievalReadMetadata:
    """Format an already resolved pin; this is not database authorization.

    Preserve the v1 serializer and its historical field set byte-for-byte.
    A v2 mapping supplied by a caller cannot substitute for the internal pin.
    """
    import json

    from services.retrieval_activation import RetrievalPinV2

    if type(pin) is RetrievalPinV2:
        return ContentReadMetadata(content_id=pin.content_id, build_id=pin.build_id,
            activation_event_id=pin.activation_event_id, manifest_sha256=pin.manifest_sha256,
            policy_artifact_sha256=pin.policy_artifact_sha256, profile=json.loads(pin.profile_json))
    if pin is not None and (type(pin) is not dict or "version" in pin):
        raise ValueError("A database-resolved retrieval pin is required")
    return generation_read_metadata(pin)
