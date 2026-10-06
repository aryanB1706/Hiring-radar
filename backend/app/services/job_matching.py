"""Semantic job matching with sentence-transformers and pgvector."""

import re

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.job_embeddings import embed_text, embedding_literal

_TOKEN_PATTERN = re.compile(r"[a-z0-9+#.]+")
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "developer",
    "engineer",
    "for",
    "from",
    "in",
    "is",
    "job",
    "lead",
    "level",
    "mid",
    "of",
    "on",
    "or",
    "position",
    "principal",
    "role",
    "senior",
    "staff",
    "the",
    "to",
    "with",
}


class JobSeekerProfile(BaseModel):
    """Job seeker skills and preferences used for semantic matching."""

    skills: list[str] = Field(default_factory=list)
    preferred_roles: list[str] = Field(default_factory=list)
    experience_level: str | None = None
    preferences: str | None = None


class JobMatch(BaseModel):
    """One ranked job match with its score components."""

    lead_id: str
    company: str | None
    role: str | None
    skills: list[str]
    location: str | None
    application_url: str | None
    semantic_similarity: float
    role_compatibility: float
    experience_compatibility: float
    match_score: float


def profile_embedding_text(profile: JobSeekerProfile) -> str:
    """Build the text embedded for a job seeker profile."""
    parts = [
        f"Skills: {', '.join(profile.skills)}" if profile.skills else None,
        f"Preferred roles: {', '.join(profile.preferred_roles)}"
        if profile.preferred_roles
        else None,
        f"Experience: {profile.experience_level}" if profile.experience_level else None,
        f"Preferences: {profile.preferences}" if profile.preferences else None,
    ]
    return "\n".join(part for part in parts if part)


def find_matching_jobs(
    db: Session,
    profile: JobSeekerProfile,
    similarity_threshold: float | None = None,
    limit: int = 5,
    candidate_limit: int = 50,
) -> list[JobMatch]:
    """Return the best matching jobs using cosine similarity and simple scoring."""
    profile_text = profile_embedding_text(profile)
    if not profile_text:
        return []

    if similarity_threshold is None:
        similarity_threshold = get_settings().JOB_MATCH_SIMILARITY_THRESHOLD
    threshold = min(max(float(similarity_threshold), 0.0), 1.0)

    safe_limit = max(1, min(int(limit), 50))
    safe_candidates = max(safe_limit, min(int(candidate_limit), 200))
    max_distance = 1.0 - threshold

    rows = (
        db.execute(
            text(
                """
                SELECT l.id AS lead_id,
                       l.company_name,
                       l.role_title,
                       l.skills,
                       l.seniority,
                       l.location,
                       l.application_url,
                       e.embedding <=> CAST(:embedding AS vector) AS distance
                FROM job_embedding e
                JOIN lead l ON l.id = e.lead_id
                WHERE l.is_hiring IS TRUE
                  AND e.embedding <=> CAST(:embedding AS vector) <= :max_distance
                ORDER BY e.embedding <=> CAST(:embedding AS vector)
                LIMIT :candidate_limit
                """
            ),
            {
                "embedding": embedding_literal(embed_text(profile_text)),
                "max_distance": max_distance,
                "candidate_limit": safe_candidates,
            },
        )
        .mappings()
        .all()
    )

    matches: list[JobMatch] = []
    for row in rows:
        semantic_similarity = min(max(1.0 - float(row["distance"]), 0.0), 1.0)
        role_compatibility = _role_compatibility(
            profile,
            row["role_title"],
            row["skills"] or [],
        )
        experience_compatibility = _experience_compatibility(
            profile.experience_level,
            row["seniority"],
            row["role_title"],
        )
        match_score = round(
            100.0
            * (
                0.70 * semantic_similarity
                + 0.20 * role_compatibility
                + 0.10 * experience_compatibility
            ),
            1,
        )
        matches.append(
            JobMatch(
                lead_id=str(row["lead_id"]),
                company=row["company_name"],
                role=row["role_title"],
                skills=row["skills"] or [],
                location=row["location"],
                application_url=row["application_url"],
                semantic_similarity=round(semantic_similarity, 4),
                role_compatibility=round(role_compatibility, 4),
                experience_compatibility=round(experience_compatibility, 4),
                match_score=match_score,
            )
        )

    matches.sort(key=lambda item: (item.match_score, item.semantic_similarity), reverse=True)
    return matches[:safe_limit]


def _tokens(value: str | None) -> set[str]:
    if not value:
        return set()
    return {
        token
        for token in _TOKEN_PATTERN.findall(value.lower())
        if token not in _STOP_WORDS and len(token) > 1
    }


def _role_compatibility(
    profile: JobSeekerProfile,
    role_title: str | None,
    job_skills: list[str],
) -> float:
    job_terms = _tokens(role_title) | _tokens(" ".join(job_skills))
    profile_terms = _tokens(" ".join([*profile.preferred_roles, *profile.skills]))
    if not job_terms or not profile_terms:
        return 0.0
    return len(job_terms & profile_terms) / len(job_terms)


def _experience_compatibility(
    profile_level: str | None,
    job_seniority: str | None,
    job_title: str | None,
) -> float:
    profile_rank = _experience_rank(profile_level)
    job_rank = _experience_rank(job_seniority)
    if job_rank is None:
        job_rank = _experience_rank(job_title)
    if profile_rank is None or job_rank is None:
        return 0.5

    difference = abs(profile_rank - job_rank)
    if difference == 0:
        return 1.0
    if difference == 1:
        return 0.75
    if difference == 2:
        return 0.5
    return 0.0


def _experience_rank(value: str | None) -> int | None:
    text_value = (value or "").lower()
    if any(word in text_value for word in ("intern", "trainee")):
        return 0
    if any(word in text_value for word in ("junior", "entry", "graduate")):
        return 1
    if any(word in text_value for word in ("mid", "intermediate")):
        return 2
    if any(word in text_value for word in ("senior", "sr")):
        return 3
    if any(word in text_value for word in ("lead", "staff", "principal", "head")):
        return 4
    return None
