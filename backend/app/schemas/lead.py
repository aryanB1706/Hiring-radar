import datetime as dt
import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.enums import LeadStatus, LeadType


class Urgency(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        return None
    return value.strip() if isinstance(value, str) else value


class LeadExtraction(BaseModel):
    """What the model must return for one post. Validated before anything is stored."""

    model_config = ConfigDict(extra="ignore")

    lead_type: LeadType
    confidence: float = Field(ge=0, le=1)
    evidence_quote: str
    is_hiring: bool | None = None
    role_title: str | None = None
    skills: list[str] = Field(default_factory=list)
    seniority: str | None = None
    location: str | None = None
    is_remote: bool | None = None
    budget_text: str | None = None
    budget_min: float | None = Field(default=None, ge=0)
    budget_max: float | None = Field(default=None, ge=0)
    currency: str | None = None
    urgency: Urgency = Urgency.UNKNOWN
    contact_method: str | None = None
    company_name: str | None = None

    @field_validator(
        "role_title",
        "seniority",
        "location",
        "budget_text",
        "contact_method",
        "company_name",
        mode="before",
    )
    @classmethod
    def _clean_strings(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @field_validator("skills")
    @classmethod
    def _normalize_skills(cls, value: list[str]) -> list[str]:
        seen: dict[str, None] = {}
        for skill in value:
            name = " ".join(skill.lower().split())
            if name and len(name) <= 60:
                seen.setdefault(name)
        return list(seen)[:20]

    @field_validator("currency", mode="before")
    @classmethod
    def _normalize_currency(cls, value: Any) -> Any:
        value = _blank_to_none(value)
        if value is None:
            return None
        code = str(value).upper()
        return code if len(code) <= 8 else None  # lead.currency is a short code

    @model_validator(mode="after")
    def _order_budget(self) -> "LeadExtraction":
        if self.budget_min is not None and self.budget_max is not None:
            if self.budget_min > self.budget_max:
                self.budget_min, self.budget_max = self.budget_max, self.budget_min
        return self


# --- API responses ----------------------------------------------------------------------------


class PostSummary(BaseModel):
    id: uuid.UUID
    url: str
    author_handle: str | None
    posted_at: dt.datetime | None
    source_kind: str


class LeadOut(BaseModel):
    id: uuid.UUID
    lead_type: LeadType
    status: LeadStatus
    confidence: float
    role_title: str | None
    company_name: str | None
    skills: list[str]
    seniority: str | None
    location: str | None
    is_remote: bool | None
    budget_text: str | None
    budget_min: float | None
    budget_max: float | None
    currency: str | None
    urgency: str | None
    contact_method: str | None
    evidence_quote: str | None
    score: float | None
    scam_risk: float | None
    duplicate_of_lead_id: uuid.UUID | None
    classified_at: dt.datetime
    post: PostSummary


class LeadDetail(LeadOut):
    raw_text: str
    flags: list[str]


class LeadPage(BaseModel):
    items: list[LeadOut]
    total: int
    limit: int
    offset: int
