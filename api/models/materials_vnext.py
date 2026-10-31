"""A compact read model for admitted, source-scoped Tc observations."""
from typing import Any, Literal

from pydantic import BaseModel, Field

from models.ml_foundation import ProductionAdmissionResponse


class TcEvidenceLocation(BaseModel):
    locator: str
    page: int | None = None
    quote_sha256: str
    field_paths: list[str] = Field(default_factory=list)


class AdmittedTcResult(BaseModel):
    id: str
    material_id: str
    formula: str
    compositions: list[dict[str, str]]
    sample_label: str | None
    sample_form: str | None
    substrate: str | None
    value_kelvin: float | None
    value_lower_kelvin: float | None
    value_upper_kelvin: float | None
    value_relation: str
    quantity: dict[str, Any]
    criterion: str
    criterion_raw: str | None = None
    method: str
    method_raw: str | None
    measurement_context: str | None
    pressure_regime: Literal['explicit_ambient', 'nonambient', 'unknown']
    pressure_gpa: float | None
    pressure_raw: str | None
    paper_id: str
    paper_title: str
    source_url: str
    source_versions: list[str]
    evidence: list[TcEvidenceLocation]
    validity_status: str
    review: ProductionAdmissionResponse


class AdmittedTcPage(BaseModel):
    items: list[AdmittedTcResult]
    total: int
    material_count: int
    paper_count: int
    limit: int
    offset: int
    dataset: Literal['materials-production90/1'] = 'materials-production90/1'
    count_scope: str = 'Matching reported results; source-scoped material identities and papers.'
