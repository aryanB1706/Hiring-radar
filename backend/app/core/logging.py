import logging

import structlog


def configure_logging(log_level: str, app_env: str) -> None:
    """JSON logs in prod, readable console logs elsewhere."""
    renderer = (
        structlog.processors.JSONRenderer()
        if app_env == "prod"
        else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(log_level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=False,
    )
