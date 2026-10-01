"""Signal persistence helpers."""

import hashlib

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.collectors.base import CollectedSignal
from app.db.models import Post, Source


def save_signals(db: Session, signals: list[CollectedSignal]) -> tuple[int, int]:
    """Store normalized signals and skip duplicates by URL or content hash."""
    created = 0
    skipped = 0
    seen_urls: set[str] = set()
    seen_hashes: set[str] = set()

    for signal in signals:
        content_hash = hashlib.sha256(f"{signal.title}\n{signal.content}".encode()).hexdigest()

        if signal.url in seen_urls or content_hash in seen_hashes:
            skipped += 1
            continue

        source = _get_or_create_source(db, signal)
        exists = db.scalar(
            select(Post.id)
            .where(
                or_(
                    Post.url == signal.url,
                    Post.content_hash == content_hash,
                    and_(
                        Post.source_id == source.id,
                        Post.external_id == signal.external_id,
                    ),
                )
            )
            .limit(1)
        )
        if exists is not None:
            skipped += 1
            continue

        db.add(
            Post(
                source_id=source.id,
                external_id=signal.external_id,
                title=signal.title,
                url=signal.url,
                author_handle=signal.author_handle,
                raw_text=signal.content,
                content_hash=content_hash,
                posted_at=signal.posted_at,
            )
        )
        seen_urls.add(signal.url)
        seen_hashes.add(content_hash)
        created += 1

    db.commit()
    return created, skipped


def _get_or_create_source(db: Session, signal: CollectedSignal) -> Source:
    """Return the source row for a signal, creating it when missing."""
    source = db.scalar(
        select(Source).where(
            Source.kind == signal.source_kind,
            Source.name == signal.source_name,
        )
    )
    if source is not None:
        return source

    source = Source(
        kind=signal.source_kind,
        name=signal.source_name,
        enabled=True,
        config={},
    )
    db.add(source)
    db.flush()
    return source
