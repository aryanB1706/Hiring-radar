from collections.abc import AsyncIterator
from datetime import datetime

from app.collectors.base import RawPost, SourceAdapter
from app.collectors.errors import DisabledSourceError
from app.db.enums import SourceKind

ADR = "docs/adr/0001-no-social-scraping.md"


class _DisabledAdapter(SourceAdapter):
    """Skeleton for a platform we deliberately do not collect from. It can never be enabled."""

    enabled = False
    platform: str

    async def fetch(self, since: datetime | None = None) -> AsyncIterator[RawPost]:
        raise DisabledSourceError(
            f"{self.platform} collection is not enabled because of platform terms. "
            f"Only user-initiated capture is supported. See {ADR}."
        )
        yield  # pragma: no cover  (makes this an async generator)


class LinkedInAdapter(_DisabledAdapter):
    kind = SourceKind.LINKEDIN_USER_CAPTURE
    platform = "LinkedIn"


class InstagramAdapter(_DisabledAdapter):
    kind = None  # no storable source kind exists for it, on purpose
    platform = "Instagram"
