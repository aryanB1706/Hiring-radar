"""Shared collector data model and helpers."""

import html
import re
from datetime import datetime

from pydantic import BaseModel

from app.db.enums import SourceKind


class CollectorError(Exception):
    """Raised when a collector cannot fetch or parse a source."""


class CollectedSignal(BaseModel):
    """Normalized signal returned by every collector."""

    external_id: str
    title: str
    content: str
    url: str
    source_kind: SourceKind
    source_name: str
    author_handle: str | None = None
    posted_at: datetime | None = None


def clean_html(value: str | None) -> str:
    """Remove HTML tags and collapse whitespace."""
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()
