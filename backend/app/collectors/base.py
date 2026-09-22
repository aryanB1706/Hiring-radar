from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.db.enums import SourceKind


class RawPost(BaseModel):
    """One post as a source returned it, before normalization and storage."""

    external_id: str
    url: str
    author_handle: str | None = None
    raw_text: str
    posted_at: datetime | None = None  # timezone-aware when present
    extra: dict[str, Any] = Field(default_factory=dict)  # source-specific details, not stored


class SourceAdapter(ABC):
    """One adapter per source. `fetch` yields posts newer than `since` (or all, if None)."""

    kind: SourceKind | None
    enabled: bool = True

    @abstractmethod
    def fetch(self, since: datetime | None = None) -> AsyncIterator[RawPost]: ...
