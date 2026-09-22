from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.core.text import MAX_TEXT_CHARS, html_to_text

SourceHint = Literal["manual_paste", "linkedin_user_capture"]

MAX_CSV_BYTES = 1_000_000
MAX_CSV_ROWS = 500


def _clean(value: str) -> str:
    cleaned = html_to_text(value)
    if not cleaned:
        raise ValueError("text is empty after removing HTML")
    return cleaned


class CaptureIn(BaseModel):
    """A post the user pasted. Nothing is fetched from the URL."""

    model_config = ConfigDict(str_strip_whitespace=True)

    url: HttpUrl
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    source_hint: SourceHint = "manual_paste"
    author_handle: str | None = Field(default=None, max_length=200)

    @field_validator("url")
    @classmethod
    def _url_length(cls, value: HttpUrl) -> HttpUrl:
        if len(str(value)) > 2048:
            raise ValueError("url is too long")
        return value

    @field_validator("text")
    @classmethod
    def _strip_html(cls, value: str) -> str:
        return _clean(value)


class CaptureOut(BaseModel):
    status: Literal["inserted", "duplicate"]


class CsvRowError(BaseModel):
    row: int  # 1-based data row (the header is row 0)
    error: str


class CsvImportOut(BaseModel):
    rows: int
    inserted: int
    skipped_duplicate: int
    rejected: list[CsvRowError]
