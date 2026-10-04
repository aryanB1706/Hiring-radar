"""Simple LangGraph workflow for processing hiring signals."""

import operator
import time
import uuid
from collections.abc import Callable, Generator
from contextlib import contextmanager
from functools import lru_cache
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import Post
from app.db.session import SessionLocal
from app.llm.classifier import ClassificationError, JobClassification, classify_signal
from app.services.job_embeddings import index_job
from app.services.jobs import save_classification

logger = get_logger("app.workflows.job_workflow")

MAX_STEPS = 5
QUALIFICATION_THRESHOLD = 0.60
LLM_RETRY_ATTEMPTS = 3
LLM_RETRY_DELAY_SECONDS = 0.5
JOB_TYPES = {"internship", "full_time", "contract", "unknown"}


class JobWorkflowState(TypedDict, total=False):
    """Shared state passed between workflow nodes."""

    signal_id: str
    title: str
    content: str
    is_hiring: bool
    company: str | None
    role: str | None
    skills: list[str]
    experience: str | None
    job_type: str
    location: str | None
    application_url: str | None
    confidence: float
    qualification_score: float
    status: str
    step_count: int
    errors: Annotated[list[str], operator.add]


@contextmanager
def _session_scope() -> Generator[Session, None, None]:
    """Open a database session and always close it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _next_step(state: JobWorkflowState) -> int:
    return int(state.get("step_count", 0)) + 1


def _max_steps_reached(state: JobWorkflowState) -> bool:
    return int(state.get("step_count", 0)) >= MAX_STEPS


def _max_steps_error(state: JobWorkflowState) -> dict[str, Any]:
    return {
        "status": "error",
        "errors": ["Maximum workflow steps reached"],
        "step_count": state.get("step_count", 0),
    }


def _with_retry(
    operation: Callable[[], JobClassification],
    attempts: int = LLM_RETRY_ATTEMPTS,
) -> JobClassification:
    """Retry temporary Groq failures a small number of times."""
    last_error: ClassificationError | None = None
    for attempt in range(attempts):
        try:
            return operation()
        except ClassificationError as exc:
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(LLM_RETRY_DELAY_SECONDS * (attempt + 1))
    if last_error is not None:
        raise last_error
    raise ClassificationError("Groq classification failed")


def _clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_skills(value: object) -> list[str]:
    if not value:
        return []
    items = value if isinstance(value, (list, tuple, set)) else [value]
    return list(dict.fromkeys(str(item).strip() for item in items if str(item).strip()))


def _clean_job_type(value: object) -> str:
    text = str(value or "unknown").strip().lower().replace("-", "_").replace(" ", "_")
    return text if text in JOB_TYPES else "unknown"


def _clean_confidence(value: object) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(max(score, 0.0), 1.0)


def _qualification_score(state: JobWorkflowState) -> float:
    score = 0.0
    score += 0.30 if state.get("company") else 0.0
    score += 0.25 if state.get("role") else 0.0
    score += 0.15 if state.get("skills") else 0.0
    score += 0.10 if state.get("location") else 0.0
    score += 0.10 if state.get("application_url") else 0.0
    score += 0.10 * _clean_confidence(state.get("confidence"))
    return round(min(score, 1.0), 2)


def classify_node(state: JobWorkflowState) -> dict[str, Any]:
    """Load one signal and classify whether it is a real hiring post."""
    if _max_steps_reached(state):
        return _max_steps_error(state)

    try:
        post_id = uuid.UUID(str(state.get("signal_id", "")))
    except (TypeError, ValueError):
        return {
            "status": "error",
            "is_hiring": False,
            "errors": ["Invalid signal id"],
            "step_count": _next_step(state),
        }

    try:
        with _session_scope() as db:
            post = db.get(Post, post_id)
            if post is None:
                return {
                    "status": "error",
                    "is_hiring": False,
                    "errors": ["Signal not found"],
                    "step_count": _next_step(state),
                }

            try:
                result = _with_retry(lambda: classify_signal(post))
            except ClassificationError as exc:
                return {
                    "status": "error",
                    "is_hiring": False,
                    "errors": [str(exc)],
                    "step_count": _next_step(state),
                }

            return {
                "title": post.title or "",
                "content": post.raw_text or "",
                "is_hiring": result.is_hiring,
                "company": result.company_name,
                "role": result.job_title,
                "skills": result.skills,
                "experience": result.experience_level,
                "job_type": result.job_type,
                "location": result.location,
                "application_url": result.application_url,
                "confidence": result.confidence,
                "status": "classified" if result.is_hiring else "rejected",
                "step_count": _next_step(state),
            }
    except Exception as exc:
        logger.exception("classify_node_failed", signal_id=state.get("signal_id"))
        return {
            "status": "error",
            "is_hiring": False,
            "errors": [f"classify_node failed: {type(exc).__name__}"],
            "step_count": _next_step(state),
        }


def extract_node(state: JobWorkflowState) -> dict[str, Any]:
    """Clean and normalize the fields extracted by the classifier."""
    if _max_steps_reached(state):
        return _max_steps_error(state)

    try:
        return {
            "company": _clean_text(state.get("company")),
            "role": _clean_text(state.get("role")),
            "skills": _clean_skills(state.get("skills")),
            "experience": _clean_text(state.get("experience")),
            "job_type": _clean_job_type(state.get("job_type")),
            "location": _clean_text(state.get("location")),
            "application_url": _clean_text(state.get("application_url")),
            "confidence": _clean_confidence(state.get("confidence")),
            "status": "extracted",
            "step_count": _next_step(state),
        }
    except Exception as exc:
        logger.exception("extract_node_failed", signal_id=state.get("signal_id"))
        return {
            "status": "error",
            "errors": [f"extract_node failed: {type(exc).__name__}"],
            "step_count": _next_step(state),
        }


def qualify_node(state: JobWorkflowState) -> dict[str, Any]:
    """Score the extracted job and decide whether it should be saved."""
    if _max_steps_reached(state):
        return _max_steps_error(state)

    try:
        score = _qualification_score(state)
        status = "qualified" if score >= QUALIFICATION_THRESHOLD else "needs_human"
        return {
            "qualification_score": score,
            "status": status,
            "step_count": _next_step(state),
        }
    except Exception as exc:
        logger.exception("qualify_node_failed", signal_id=state.get("signal_id"))
        return {
            "status": "error",
            "errors": [f"qualify_node failed: {type(exc).__name__}"],
            "step_count": _next_step(state),
        }


def save_job_node(state: JobWorkflowState) -> dict[str, Any]:
    """Save a qualified job to PostgreSQL and index it for vector search."""
    if _max_steps_reached(state):
        return _max_steps_error(state)

    if state.get("status") != "qualified":
        return {
            "status": "skipped",
            "errors": ["Job did not qualify for saving"],
            "step_count": _next_step(state),
        }

    try:
        post_id = uuid.UUID(str(state.get("signal_id", "")))
        with _session_scope() as db:
            post = db.get(Post, post_id)
            if post is None:
                return {
                    "status": "error",
                    "errors": ["Signal not found"],
                    "step_count": _next_step(state),
                }

            result = JobClassification(
                is_hiring=True,
                company_name=state.get("company"),
                job_title=state.get("role"),
                skills=state.get("skills", []),
                experience_level=state.get("experience"),
                job_type=state.get("job_type", "unknown"),
                location=state.get("location"),
                application_url=state.get("application_url"),
                confidence=state.get("confidence", 0.0),
            )
            lead = save_classification(
                db,
                post,
                result,
                score=state.get("qualification_score"),
            )

            try:
                index_job(db, lead, result)
            except Exception as exc:
                logger.warning(
                    "job_embedding_index_failed",
                    lead_id=str(lead.id),
                    error=type(exc).__name__,
                )

        return {
            "status": "saved",
            "step_count": _next_step(state),
        }
    except Exception as exc:
        logger.exception("save_job_node_failed", signal_id=state.get("signal_id"))
        return {
            "status": "error",
            "errors": [f"save_job_node failed: {type(exc).__name__}"],
            "step_count": _next_step(state),
        }


def _route_after_classify(state: JobWorkflowState) -> str:
    if state.get("status") == "error":
        return "end"
    return "extract_node" if state.get("is_hiring") else "end"


def _route_after_qualify(state: JobWorkflowState) -> str:
    if state.get("status") == "error":
        return "end"
    return "save_job_node" if state.get("status") == "qualified" else "end"


def build_job_workflow():
    """Build and compile the hiring signal workflow."""
    graph = StateGraph(JobWorkflowState)
    graph.add_node("classify_node", classify_node)
    graph.add_node("extract_node", extract_node)
    graph.add_node("qualify_node", qualify_node)
    graph.add_node("save_job_node", save_job_node)

    graph.add_edge(START, "classify_node")
    graph.add_conditional_edges(
        "classify_node",
        _route_after_classify,
        {"extract_node": "extract_node", "end": END},
    )
    graph.add_edge("extract_node", "qualify_node")
    graph.add_conditional_edges(
        "qualify_node",
        _route_after_qualify,
        {"save_job_node": "save_job_node", "end": END},
    )
    graph.add_edge("save_job_node", END)
    return graph.compile()


@lru_cache(maxsize=1)
def get_job_workflow():
    """Return the compiled workflow once per process."""
    return build_job_workflow()


def run_job_workflow(signal_id: str | uuid.UUID) -> JobWorkflowState:
    """Run the workflow for one stored signal."""
    initial_state: JobWorkflowState = {
        "signal_id": str(signal_id),
        "title": "",
        "content": "",
        "is_hiring": False,
        "company": None,
        "role": None,
        "skills": [],
        "experience": None,
        "job_type": "unknown",
        "location": None,
        "application_url": None,
        "confidence": 0.0,
        "qualification_score": 0.0,
        "status": "new",
        "step_count": 0,
        "errors": [],
    }
    return get_job_workflow().invoke(initial_state)
