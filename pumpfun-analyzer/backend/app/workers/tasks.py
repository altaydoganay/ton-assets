"""Arka plan görevleri.

Görevler kısa ve idempotenttir; gerçek RPC çağrıları adapter registry üzerinden
yapılır. Ağ erişimi yoksa görevler güvenli biçimde no-op döner ve loglar.
"""
from __future__ import annotations

import logging

from .celery_app import celery_app
from ..database import SessionLocal
from ..adapters.registry import build_chain_provider
from ..adapters.rpc import RpcUnavailableError
from ..models import Wallet, WalletStatus
from ..services.pipeline import ingest_wallet, analyze_wallet

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.tasks.ingest_and_analyze_wallet")
def ingest_and_analyze_wallet(address: str) -> dict:
    db = SessionLocal()
    try:
        provider = build_chain_provider()
        try:
            n = ingest_wallet(db, provider, address)
        except RpcUnavailableError as exc:
            logger.warning("RPC erişilemedi, analiz atlandı: %s", exc)
            return {"address": address, "ingested": 0, "error": "rpc_unavailable"}
        res = analyze_wallet(db, address)
        return {"address": address, "ingested": n, "score": res.total, "tracked": res.tracked}
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.analyze_discovered")
def analyze_discovered() -> dict:
    """Listener'ın keşfettiği aday cüzdanları parti parti analiz edip puanlar.

    Aday toplama canlı dinleyicide (PumpPortal) yapılır; bu görev `discovered`
    durumundaki cüzdanları Helius ile analiz eder ve uygunları `tracked` yapar.
    """
    from ..config import settings
    from ..services.discovery import analyze_discovered_batch

    db = SessionLocal()
    try:
        try:
            provider = build_chain_provider()
        except Exception as exc:  # noqa: BLE001
            logger.info("Zincir sağlayıcı kurulamadı: %s", exc)
            return {"analyzed": 0, "error": "provider"}
        try:
            results = analyze_discovered_batch(
                db, provider,
                limit=settings.discovery_batch_size,
                ingest_limit=settings.discovery_ingest_limit,
            )
        except RpcUnavailableError as exc:
            logger.warning("Keşif analizi atlandı (RPC): %s", exc)
            return {"analyzed": 0, "error": "rpc_unavailable"}
        tracked = sum(1 for r in results if r.get("tracked"))
        return {"analyzed": len(results), "tracked": tracked, "results": results}
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.reanalyze_tracked")
def reanalyze_tracked() -> dict:
    db = SessionLocal()
    try:
        tracked = db.query(Wallet).filter(Wallet.status == WalletStatus.tracked.value).all()
        for w in tracked:
            ingest_and_analyze_wallet.delay(w.address)
        return {"queued": len(tracked)}
    finally:
        db.close()
