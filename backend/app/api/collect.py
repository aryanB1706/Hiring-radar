"""Public signal collection and listing endpoints."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.collectors.base import CollectorError
from app.collectors.hacker_news import fetch_hacker_news
from app.collectors.rss import fetch_rss
from app.core.config import get_rss_feeds
from app.db.models import Post
from app.db.session import get_db
from app.services.signals import save_signals

router = APIRouter(prefix="/api", tags=["signals"])


class CollectResponse(BaseModel):
    """Summary of one collection run."""

    source: str
    fetched: int
    created: int
    skipped: int


class SignalResponse(BaseModel):
    """A stored public job signal."""

    id: uuid.UUID
    source: str
    source_kind: str
    title: str | None
    content: str
    url: str
    content_hash: str
    posted_at: datetime | None
    fetched_at: datetime


@router.post("/collect/hacker-news", response_model=CollectResponse)
def collect_hacker_news(
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
) -> CollectResponse:
    """Fetch recent Hacker News posts and store new signals."""
    try:
        signals = fetch_hacker_news(limit=limit)
    except CollectorError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    created, skipped = save_signals(db, signals)
    return CollectResponse(
        source="hacker-news",
        fetched=len(signals),
        created=created,
        skipped=skipped,
    )


@router.post("/collect/rss", response_model=CollectResponse)
def collect_rss(
    limit_per_feed: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> CollectResponse:
    """Fetch entries from configured RSS feeds and store new signals."""
    feeds = get_rss_feeds()
    if not feeds:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No RSS feeds configured. Set RSS_FEEDS in the environment.",
        )

    try:
        signals = fetch_rss(feeds, limit_per_feed=limit_per_feed)
    except CollectorError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    created, skipped = save_signals(db, signals)
    return CollectResponse(
        source="rss",
        fetched=len(signals),
        created=created,
        skipped=skipped,
    )


@router.get("/signals", response_model=list[SignalResponse])
def list_signals(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[SignalResponse]:
    """Return the most recently fetched signals."""
    posts = db.scalars(
        select(Post)
        .options(joinedload(Post.source))
        .order_by(Post.fetched_at.desc(), Post.created_at.desc())
        .limit(limit)
    ).all()

    return [
        SignalResponse(
            id=post.id,
            source=post.source.name,
            source_kind=post.source.kind.value,
            title=post.title,
            content=post.raw_text,
            url=post.url,
            content_hash=post.content_hash,
            posted_at=post.posted_at,
            fetched_at=post.fetched_at,
        )
        for post in posts
    ]
