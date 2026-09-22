"""CLI: python -m app.jobs.classify --limit 50 [--show]"""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine

from app.classifier.batch import BatchSummary, classify_pending
from app.classifier.service import ClassifierService
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.session import make_session_factory
from app.embeddings.factory import get_embedder
from app.llm.errors import LLMConfigError
from app.llm.factory import build_llm_client


async def run_classify_batch(settings: Settings, batch_size: int) -> BatchSummary:
    engine = create_async_engine(settings.database_url)
    redis = Redis.from_url(settings.redis_url)
    session_factory = make_session_factory(engine)
    try:
        llm = build_llm_client(settings, redis, session_factory)  # logs each call to llm_call_log
        async with session_factory() as session:
            service = ClassifierService(
                session,
                llm,
                get_embedder(settings),
                dedupe_threshold=settings.dedupe_threshold,
            )
            return await classify_pending(session, service, batch_size)
    finally:
        await redis.aclose()
        await engine.dispose()


def _show(summary: BatchSummary) -> None:
    for lead in summary.leads:
        quote = (lead.evidence_quote or "").replace("\n", " ")[:70]
        dup = f" DUP-OF={str(lead.duplicate_of_lead_id)[:8]}" if lead.duplicate_of_lead_id else ""
        print(
            f"{lead.lead_type.value:<13} {lead.confidence:.2f} {lead.status.value:<8}{dup} "
            f'| {lead.role_title or "-"} | {",".join(lead.skills[:5])} | "{quote}"'
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify posts that have no lead yet.")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--show", action="store_true", help="print one line per classified post")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level, settings.app_env)
    try:
        summary = asyncio.run(run_classify_batch(settings, args.limit))
    except LLMConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.show:
        _show(summary)
    print(json.dumps({k: v for k, v in asdict(summary).items() if k != "leads"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
