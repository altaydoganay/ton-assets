"""Celery uygulaması — arka plan görevleri."""
from __future__ import annotations

from celery import Celery

from ..config import settings  # noqa: F401  (beat_schedule içinde kullanılır)

celery_app = Celery(
    "pumpfun",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    # Worker başlangıçta görev modülünü import etsin; aksi halde görevler
    # "unregistered task" hatası verir.
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    beat_schedule={
        # Keşfedilen adayları parti parti analiz edip puanla (otomatik keşif)
        "analyze-discovered": {
            "task": "app.workers.tasks.analyze_discovered",
            "schedule": float(settings.discovery_interval_seconds),
        },
        # Takip edilen cüzdanları periyodik yeniden analiz et (puan güncelliği)
        "reanalyze-tracked": {"task": "app.workers.tasks.reanalyze_tracked", "schedule": 900.0},
    },
)

# Görevleri kesin olarak kaydet (include lazy olabildiği için açıkça import et).
# celery_app yukarıda tanımlandığı için bu import döngüsel sorun yaratmaz.
from . import tasks  # noqa: E402,F401
