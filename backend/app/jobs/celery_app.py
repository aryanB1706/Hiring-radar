from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery("hiring_radar", broker=settings.redis_url, include=["app.jobs.tasks"])
celery_app.conf.update(
    timezone="UTC",
    task_serializer="json",
    accept_content=["json"],
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "ingest-all-sources": {
            "task": "app.jobs.tasks.ingest_all_sources",
            "schedule": settings.ingest_interval_hours * 3600,
        }
    },
)
