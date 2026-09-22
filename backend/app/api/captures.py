import csv
import hashlib
import io
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.base import RawPost
from app.db.enums import SourceKind
from app.db.session import get_session
from app.schemas.captures import (
    MAX_CSV_BYTES,
    MAX_CSV_ROWS,
    CaptureIn,
    CaptureOut,
    CsvImportOut,
    CsvRowError,
)
from app.services.ingest import IngestService
from app.services.sources import get_or_create_source

router = APIRouter(prefix="/captures", tags=["captures"])

Session = Annotated[AsyncSession, Depends(get_session)]

_CAPTURE_SOURCES = {
    "manual_paste": (SourceKind.MANUAL_PASTE, "manual-paste"),
    "linkedin_user_capture": (SourceKind.LINKEDIN_USER_CAPTURE, "linkedin-user-capture"),
}


def _raw_post(item: CaptureIn) -> RawPost:
    url = str(item.url)
    return RawPost(
        # Same link pasted twice is the same capture, even if the text was edited.
        external_id=hashlib.sha256(url.encode()).hexdigest(),
        url=url,
        author_handle=item.author_handle,
        raw_text=item.text,
    )


@router.post("", response_model=CaptureOut, status_code=201)
async def create_capture(body: CaptureIn, session: Session) -> CaptureOut:
    kind, name = _CAPTURE_SOURCES[body.source_hint]
    source = await get_or_create_source(session, kind, name)
    counts = await IngestService(session).ingest_posts(source.id, [_raw_post(body)])
    return CaptureOut(status="inserted" if counts.inserted else "duplicate")


@router.post("/csv", response_model=CsvImportOut)
async def import_csv(request: Request, session: Session) -> CsvImportOut:
    """Body is raw CSV (Content-Type: text/csv) with a header row: url,text[,author_handle]."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_CSV_BYTES:
        raise HTTPException(413, f"CSV is larger than {MAX_CSV_BYTES} bytes")
    raw = await request.body()
    if len(raw) > MAX_CSV_BYTES:
        raise HTTPException(413, f"CSV is larger than {MAX_CSV_BYTES} bytes")
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise HTTPException(422, f"could not read CSV: {exc}") from exc
    if not {"url", "text"} <= set(reader.fieldnames or []):
        raise HTTPException(422, "CSV needs a header row with at least: url,text")
    if len(rows) > MAX_CSV_ROWS:
        raise HTTPException(422, f"CSV has more than {MAX_CSV_ROWS} rows")

    posts: list[RawPost] = []
    rejected: list[CsvRowError] = []
    for number, row in enumerate(rows, start=1):
        try:
            item = CaptureIn(
                url=row["url"],  # type: ignore[arg-type]
                text=row["text"],
                author_handle=(row.get("author_handle") or None),
            )
        except ValidationError as exc:
            first = exc.errors()[0]
            rejected.append(CsvRowError(row=number, error=f"{first['loc'][0]}: {first['msg']}"))
            continue
        posts.append(_raw_post(item))

    source = await get_or_create_source(session, SourceKind.CSV_IMPORT, "csv-import")
    counts = await IngestService(session).ingest_posts(source.id, posts)
    return CsvImportOut(
        rows=len(rows),
        inserted=counts.inserted,
        skipped_duplicate=counts.skipped_duplicate,
        rejected=rejected,
    )
