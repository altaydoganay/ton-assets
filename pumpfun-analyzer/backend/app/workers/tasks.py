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


@celery_app.task(name="app.workers.tasks.discover_candidates")
def discover_candidates() -> dict:
    """Aday cüzdan keşfi (başarılı tokenlerin erken-fakat-ilk-blok-olmayan alıcıları).

    Gerçek keşif RPC/Helius üzerinden token alıcılarını tarar. Burada hattın
    iskeleti vardır; ağ yoksa boş döner.
    """
    db = SessionLocal()
    try:
        # NOT: Gerçek keşif mantığı discovery modülünde; ağ gerektirir.
        from ..core.discovery.wallet_discovery import discover_from_recent_tokens
        try:
            provider = build_chain_provider()
            candidates = discover_from_recent_tokens(provider)
        except Exception as exc:  # noqa: BLE001
            logger.info("Keşif atlandı (ağ yok?): %s", exc)
            candidates = []
        return {"candidates": len(candidates)}
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
