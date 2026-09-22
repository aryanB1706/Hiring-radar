import datetime as dt
import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.classifier.dedupe import embedding_text, find_original
from app.classifier.prefilter import prefilter
from app.classifier.prompt import SYSTEM_PROMPT, build_user_prompt
from app.core.text import normalize_for_hash
from app.db.enums import LeadStatus, LeadType
from app.db.models import Enrichment, Lead, Post
from app.embeddings.base import Embedder
from app.llm import LLMClient, ModelTier
from app.schemas.lead import LeadExtraction
from app.services.parties import get_or_create_organization

log = structlog.get_logger()

FLAGS_KIND = "classifier_flags"
QUOTE_PENALTY = 0.5  # confidence multiplier when the evidence quote is not in the post


@dataclass
class ClassifierStats:
    already_classified: int = 0
    prefiltered: int = 0
    llm_calls: int = 0
    flagged: int = 0
    duplicates_linked: int = 0


class ClassifierService:
    """post -> lead. The caller owns the session and the transaction."""

    def __init__(
        self,
        session: AsyncSession,
        llm: LLMClient,
        embedder: Embedder,
        *,
        dedupe_threshold: float,
    ) -> None:
        self._session = session
        self._llm = llm
        self._embedder = embedder
        self._threshold = dedupe_threshold
        self.stats = ClassifierStats()

    async def classify(self, post: Post) -> Lead:
        """Idempotent per post: a post that already has a lead returns that lead untouched."""
        if (existing := await self._existing(post.id)) is not None:
            self.stats.already_classified += 1
            return existing

        decision = prefilter(post.raw_text)
        if decision.skip:
            self.stats.prefiltered += 1
            log.info("classifier_prefiltered", post_id=str(post.id), reason=decision.reason)
            return await self._store(
                post,
                values={
                    "lead_type": LeadType.NOT_A_LEAD,
                    "is_hiring": False,
                    "confidence": 1.0,  # decided by a rule, not by a model
                    "status": LeadStatus.REJECTED,
                },
                flags=[f"prefiltered:{decision.reason}"],
            )

        self.stats.llm_calls += 1
        extraction, _ = await self._llm.generate_structured(
            build_user_prompt(post.raw_text),
            LeadExtraction,
            system=SYSTEM_PROMPT,
            purpose="classify_post",
            tier=ModelTier.FAST,
        )
        confidence, flags = self._check_evidence(extraction, post.raw_text)
        is_lead = extraction.lead_type != LeadType.NOT_A_LEAD

        party_id = None
        if extraction.company_name:
            party_id = (await get_or_create_organization(self._session, extraction.company_name)).id

        embedding = None
        duplicate_of = None
        if is_lead and (text := embedding_text(extraction)):
            embedding = (await self._embedder.embed([text]))[0]
            duplicate_of = await find_original(
                self._session,
                embedding,
                post_time=post.posted_at or post.fetched_at,
                threshold=self._threshold,
            )
            if duplicate_of is not None:
                self.stats.duplicates_linked += 1

        return await self._store(
            post,
            values={
                "party_id": party_id,
                "is_hiring": extraction.is_hiring,
                "lead_type": extraction.lead_type,
                "role_title": extraction.role_title,
                "skills": extraction.skills,
                "seniority": extraction.seniority,
                "location": extraction.location,
                "is_remote": extraction.is_remote,
                "budget_text": extraction.budget_text,
                "budget_min": extraction.budget_min,
                "budget_max": extraction.budget_max,
                "currency": extraction.currency,
                "urgency": extraction.urgency.value,
                "contact_method": extraction.contact_method,
                "confidence": confidence,
                "evidence_quote": extraction.evidence_quote,
                "status": LeadStatus.NEW if is_lead else LeadStatus.REJECTED,
                "duplicate_of_lead_id": duplicate_of,
                "embedding": embedding,
            },
            flags=flags,
            original_confidence=extraction.confidence if flags else None,
        )

    def _check_evidence(self, extraction: LeadExtraction, text: str) -> tuple[float, list[str]]:
        """The model must quote the post; if the quote is not in it, trust the answer less."""
        quote = normalize_for_hash(extraction.evidence_quote)
        if quote and quote in normalize_for_hash(text):
            return extraction.confidence, []
        self.stats.flagged += 1
        flag = "evidence_quote_missing" if not quote else "evidence_quote_not_in_post"
        return extraction.confidence * QUOTE_PENALTY, [flag]

    async def _existing(self, post_id: uuid.UUID) -> Lead | None:
        return (
            await self._session.execute(select(Lead).where(Lead.post_id == post_id))
        ).scalar_one_or_none()

    async def _store(
        self,
        post: Post,
        *,
        values: dict[str, object],
        flags: list[str],
        original_confidence: float | None = None,
    ) -> Lead:
        inserted = (
            await self._session.execute(
                insert(Lead)
                .values(post_id=post.id, classified_at=dt.datetime.now(dt.UTC), **values)
                .on_conflict_do_nothing(index_elements=["post_id"])
                .returning(Lead.id)
            )
        ).scalar_one_or_none()
        if inserted is None:  # another worker classified this post first
            existing = await self._existing(post.id)
            assert existing is not None
            return existing
        if flags:
            data: dict[str, object] = {"flags": flags}
            if original_confidence is not None:
                data["original_confidence"] = original_confidence
            self._session.add(Enrichment(lead_id=inserted, kind=FLAGS_KIND, data=data))
        await self._session.flush()
        lead = await self._session.get(Lead, inserted, populate_existing=True)
        assert lead is not None
        return lead
