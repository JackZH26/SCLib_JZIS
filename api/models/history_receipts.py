"""Private history transport; checksums never confer scientific authority."""
from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class HistorySaveDisposition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    version: Literal["ask-history-save/1.0.0"] = "ask-history-save/1.0.0"
    status: Literal["saved", "not_saved", "unknown", "not_requested"] = "not_requested"
    history_id: str | None = None
    receipt_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    reason_code: Literal["guest_request", "capture_unavailable", "storage_unavailable",
                         "session_no_longer_authorized", "commit_unconfirmed"] | None = None

    @field_validator("history_id")
    @classmethod
    def exact_history_id(cls, value):
        if value is not None and str(UUID(value)) != value:
            raise ValueError("A canonical history UUID is required")
        return value

    @model_validator(mode="after")
    def coherent_disposition(self):
        if self.status == "saved":
            if self.history_id is None or self.receipt_sha256 is None or self.reason_code is not None:
                raise ValueError("Saved history requires a confirmed ID and receipt checksum")
        elif self.status == "unknown":
            if self.history_id is None or self.receipt_sha256 is not None or self.reason_code != "commit_unconfirmed":
                raise ValueError("An unknown commit retains only its original recovery ID")
        elif self.history_id is not None or self.receipt_sha256 is not None:
            raise ValueError("Unconfirmed history cannot claim a saved receipt")
        elif self.status == "not_requested" and self.reason_code not in {None, "guest_request"}:
            raise ValueError("History was not requested")
        elif self.status == "not_saved" and self.reason_code not in {
            "capture_unavailable", "storage_unavailable", "session_no_longer_authorized",
        }:
            raise ValueError("A rejected save needs a bounded reason")
        return self


class HistoryReceiptSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    version: Literal["ask-history-receipt-summary/1.0.0"] = "ask-history-receipt-summary/1.0.0"
    status: Literal["legacy_unpinned", "recorded", "unavailable"] = "legacy_unpinned"
    receipt_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def coherent_record(self):
        if (self.status == "recorded") != (self.receipt_sha256 is not None):
            raise ValueError("Only a recorded receipt has a checksum")
        return self


class HistoryEvidenceDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    status: Literal["verified", "legacy_unpinned", "unavailable"]
    binding_scope: Literal["generation_members", "legacy_snapshot", "no_selected_evidence"] | None = None
    receipt: dict[str, Any] | None = None
    historical_integrity_verified: bool = False
    scientific_acceptance: Literal[False] = False
    ml_training_approved: Literal[False] = False
    public_release_authorized: Literal[False] = False
    currentness_revalidated: Literal[False] = False
    reason_codes: list[Literal["legacy_receipt_not_recorded", "receipt_unavailable"]] = Field(default_factory=list, max_length=1)

    @field_validator("scientific_acceptance", "ml_training_approved", "public_release_authorized",
                     "currentness_revalidated", mode="before")
    @classmethod
    def no_authority(cls, value):
        if value is not False:
            raise ValueError("Historical integrity does not establish currentness or scientific authority")
        return value

    @model_validator(mode="after")
    def coherent_detail(self):
        if self.status == "verified":
            if self.receipt is None or self.binding_scope is None or not self.historical_integrity_verified or self.reason_codes:
                raise ValueError("Verified historical integrity requires the complete checked receipt")
        elif self.receipt is not None or self.binding_scope is not None or self.historical_integrity_verified:
            raise ValueError("Unchecked history cannot supply a verified receipt")
        elif self.reason_codes != ["legacy_receipt_not_recorded" if self.status == "legacy_unpinned" else "receipt_unavailable"]:
            raise ValueError("Unchecked history needs its exact reason")
        return self
