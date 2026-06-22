"""Celery uygulaması — arka plan görevleri."""
from __future__ import annotations

from celery import Celery

from ..config import settings

celery_app = Celery(
    "pumpfun",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    beat_schedule={
        "discover-wallets": {"task": "app.workers.tasks.discover_candidates", "schedule": 300.0},
        "reanalyze-tracked": {"task": "app.workers.tasks.reanalyze_tracked", "schedule": 900.0},
    },
)
