"""Current source assertions, with explicit paper-date precision."""
from typing import Literal

from pydantic import BaseModel, Field
from models.materials_display_policy import TcDisplayPolicy


class MaterialsTimelinePoint(BaseModel):
    id: str
    material_id: str
    paper_id: str
    formula: str
    family: str
    date: str
    date_basis: Literal['paper_submission', 'arxiv_identifier_month']
    date_precision: Literal['day', 'month']
    value_kelvin: float | None
    value_lower_kelvin: float | None
    value_upper_kelvin: float | None
    value_relation: Literal['exact', 'interval', 'lt', 'le', 'gt', 'ge']
    approximate: bool
    criterion: str
    pressure_gpa: float | None
    pressure_regime: Literal['explicit_ambient', 'nonambient', 'unknown']


class MaterialsTimeline(BaseModel):
    display_policy: TcDisplayPolicy = Field(default_factory=TcDisplayPolicy)
    dataset: Literal['materials-production90/1'] = 'materials-production90/1'
    date_policy: Literal['paper-submission-or-identifier-month/1'] = 'paper-submission-or-identifier-month/1'
    points: list[MaterialsTimelinePoint]
    total_results: int
    total_materials: int
    total_papers: int
    plotted_results: int
    omitted_without_date: int
    omitted_invalid_quantity: int
    sampled: bool
    families: dict[str, int]
    date_min: str | None
    date_max: str | None
