"""Explicit private response projection; no public identity or history receipt.

Public selectors/metadata stay closed to engineering candidates. Only the
loopback rehearsal app supplies this exact context to the shared orchestrators.
"""
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from config import get_settings
from models.index_read import RetrievalEmbeddingProfile, retrieval_read_metadata
from models.search import AskResponse, SearchResponse
from services.retrieval_candidate import EngineeringCandidatePin


class EngineeringReadMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    version: Literal["sclib-engineering-candidate-pin/1.0.0"]
    scope: Literal["owned_restore_not_activated"]
    # Describes immutable content, while the distinct version/scope explicitly
    # denies an activated public read identity. There is no activation field.
    mode: Literal["content_snapshot"] = "content_snapshot"
    logical_index: str
    content_id: str
    build_id: str
    validation_id: str
    manifest_sha256: str
    policy_artifact_sha256: str
    profile: RetrievalEmbeddingProfile
    source_v1_predecessor: dict
    build_record_sha256: str
    validation_record_sha256: str


class EngineeringSearchResponse(SearchResponse):
    retrieval_generation: EngineeringReadMetadata


class EngineeringAskResponse(AskResponse):
    retrieval_generation: EngineeringReadMetadata


@dataclass(frozen=True)
class CandidateContext:
    reader: object
    pin: EngineeringCandidatePin

    def __post_init__(self):
        self.require_reader(self.reader)

    def require_reader(self, reader):
        from services.candidate_runtime import CandidateRetriever
        if (type(self) is not CandidateContext or type(reader) is not CandidateRetriever
                or reader is not self.reader or get_settings().environment == "production"):
            raise ValueError("Explicit private non-production reader context required")
        reader._pin(self.pin)

    def require_pin(self, pin):
        self.require_reader(self.reader)
        if type(pin) is not EngineeringCandidatePin or pin != self.pin:
            raise ValueError("The exact prepared engineering identity changed")


def search_response(pin, **values):
    if type(pin) is EngineeringCandidatePin:
        return EngineeringSearchResponse(retrieval_generation=EngineeringReadMetadata.model_validate(pin.metadata()), **values)
    return SearchResponse(retrieval_generation=retrieval_read_metadata(pin), **values)


def ask_response(pin, **values):
    if type(pin) is EngineeringCandidatePin:
        return EngineeringAskResponse(retrieval_generation=EngineeringReadMetadata.model_validate(pin.metadata()), **values)
    return AskResponse(retrieval_generation=retrieval_read_metadata(pin), **values)
