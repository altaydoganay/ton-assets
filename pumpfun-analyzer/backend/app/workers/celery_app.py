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
        "reanalyze-tracked": {"task": "app.workers.tasks.reanalyze_tracked", "schedule": 300.0},
        # Takip edilen cüzdanların TAZE alımlarını güvenilir biçimde yakala (poll)
        # — canlı WS olayları kaçırabildiğinden işlem tetikleyici GÜVENCESİ budur.
        "poll-tracked-wallets": {
            "task": "app.workers.tasks.poll_tracked_wallets",
            "schedule": float(settings.tracked_poll_seconds),
        },
        # Açık paper pozisyonlarında take-profit / stop-loss kontrolü
        "manage-positions": {"task": "app.workers.tasks.manage_positions", "schedule": 15.0},
        # Canlı/paper açık copy pozisyonlarında lider hâlâ token tutuyor mu kontrol et.
        # Lider sell olayı kaçarsa rug yemeden acil çıkış güvenlik ağıdır.
        "watch-leader-holdings": {
            "task": "app.workers.tasks.watch_leader_holdings",
            "schedule": float(settings.leader_hold_watch_seconds),
        },
        # Analiz edilmiş umut vadeden cüzdanları güncel kriterlerle yeniden değerlendir
        "reevaluate-analyzed": {"task": "app.workers.tasks.reevaluate_analyzed", "schedule": 60.0},
        # Kopya performansı kötü cüzdanları otomatik ele (ardışık zarar / drawdown)
        "prune-underperformers": {"task": "app.workers.tasks.prune_underperformers", "schedule": 60.0},
        # Takip sayısını üst sınırda tut (eleme sonrası keşif akışı geri şişirmesin)
        "enforce-tracked-cap": {"task": "app.workers.tasks.enforce_tracked_cap", "schedule": 30.0},
    },
)

# Görevleri kesin olarak kaydet (include lazy olabildiği için açıkça import et).
# celery_app yukarıda tanımlandığı için bu import döngüsel sorun yaratmaz.
from . import tasks  # noqa: E402,F401
