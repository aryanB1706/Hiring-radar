"""CLI: python -m app.jobs.ingest --source hn [--feed URL ...] [--full]"""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict

import httpx

from app.collectors.errors import CollectorError
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.jobs.runner import DEFAULT_SOURCES, run_ingest_by_name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch one source and store its posts.")
    parser.add_argument("--source", required=True, choices=sorted(DEFAULT_SOURCES))
    parser.add_argument("--feed", action="append", help="RSS feed URL (repeatable, rss only)")
    parser.add_argument("--full", action="store_true", help="ignore the incremental cut-off")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level, settings.app_env)
    try:
        counts = asyncio.run(
            run_ingest_by_name(args.source, settings, feeds=args.feed, full=args.full)
        )
    except CollectorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except httpx.HTTPError as exc:
        print(f"error: network problem: {exc!r}", file=sys.stderr)
        return 3
    print(json.dumps(asdict(counts)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
