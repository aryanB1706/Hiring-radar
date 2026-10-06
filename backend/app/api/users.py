"""Job seeker profile management endpoints."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from app.db.models import JobSeeker
from app.db.session import get_db

router = APIRouter(prefix="/api/users", tags=["users"])

PreferredJobType = Literal["internship", "full_time", "contract", "unknown"]


def _normalize_string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        value = [value]

    seen: set[str] = set()
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


class JobSeekerCreate(BaseModel):
    """Validated payload for creating a job seeker profile."""

    name: str = Field(min_length=1, max_length=255)
    skills: list[str] = Field(default_factory=list)
    preferred_roles: list[str] = Field(default_factory=list)
    experience_level: str | None = Field(default=None, max_length=50)
    preferred_job_type: PreferredJobType | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("name must not be blank")
        return text

    @field_validator("skills", "preferred_roles", mode="before")
    @classmethod
    def normalize_lists(cls, value: object) -> list[str]:
        if value is None:
            raise ValueError("must be a list of strings")
        return _normalize_string_list(value)

    @field_validator("experience_level", mode="before")
    @classmethod
    def normalize_experience(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("preferred_job_type", mode="before")
    @classmethod
    def normalize_job_type(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "intern": "internship",
            "internship": "internship",
            "fulltime": "full_time",
            "full_time": "full_time",
            "contract": "contract",
            "contractor": "contract",
            "freelance": "contract",
            "unknown": "unknown",
        }
        return aliases.get(text, text)


class JobSeekerUpdate(BaseModel):
    """Validated payload for updating a job seeker profile."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    skills: list[str] = Field(default_factory=list)
    preferred_roles: list[str] = Field(default_factory=list)
    experience_level: str | None = Field(default=None, max_length=50)
    preferred_job_type: PreferredJobType | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("name must not be blank")
        return text

    @field_validator("skills", "preferred_roles", mode="before")
    @classmethod
    def normalize_lists(cls, value: object) -> list[str]:
        if value is None:
            raise ValueError("must be a list of strings")
        return _normalize_string_list(value)

    @field_validator("experience_level", mode="before")
    @classmethod
    def normalize_experience(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("preferred_job_type", mode="before")
    @classmethod
    def normalize_job_type(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "intern": "internship",
            "internship": "internship",
            "fulltime": "full_time",
            "full_time": "full_time",
            "contract": "contract",
            "contractor": "contract",
            "freelance": "contract",
            "unknown": "unknown",
        }
        return aliases.get(text, text)

    @model_validator(mode="after")
    def reject_null_name(self) -> "JobSeekerUpdate":
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name must not be null")
        return self


class JobSeekerResponse(BaseModel):
    """Saved job seeker profile."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    skills: list[str]
    preferred_roles: list[str]
    experience_level: str | None
    preferred_job_type: str | None
    created_at: datetime


def _get_user(db: Session, user_id: uuid.UUID) -> JobSeeker:
    user = db.get(JobSeeker, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.post("", response_model=JobSeekerResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: JobSeekerCreate,
    db: Session = Depends(get_db),
) -> JobSeeker:
    """Create a job seeker profile."""
    user = JobSeeker(**payload.model_dump())
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/{user_id}", response_model=JobSeekerResponse)
def get_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> JobSeeker:
    """Get one job seeker profile."""
    return _get_user(db, user_id)


@router.put("/{user_id}", response_model=JobSeekerResponse)
def update_user(
    user_id: uuid.UUID,
    payload: JobSeekerUpdate,
    db: Session = Depends(get_db),
) -> JobSeeker:
    """Update a job seeker profile. Omitted fields are left unchanged."""
    user = _get_user(db, user_id)
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user
