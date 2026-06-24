"""Otomatik cüzdan keşfi servisi.

İki parça:
  1. Aday TOPLAMA (listener içinde): canlı akıştan yeni Pump.fun tokenleri
     izlenir, bu tokenleri ALAN cüzdanlar toplanır. Birden fazla farklı token
     üzerinde alım yapan (tutarlılık sinyali) cüzdanlar `discovered` durumuyla
     veritabanına yazılır.
  2. Aday ANALİZİ (Celery beat): `discovered` durumundaki cüzdanlar parti parti
     Helius ile analiz edilir; puanı ≥ eşik ve uygun olanlar otomatik `tracked`
     yapılır, diğerleri `analyzed`/`rejected` olur.

Not: Keşif yalnızca "kim alım yapıyor" sinyalini üretir; GÜVENİLİRLİK kararını
puanlama + eleme + veto kuralları verir. Yani her keşfedilen cüzdan takip
edilmez — sadece kriterleri geçenler.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..adapters.base import ChainProvider
from ..adapters.rpc import RpcUnavailableError
from ..models import Wallet, WalletStatus
from .pipeline import analyze_wallet, ingest_wallet

logger = logging.getLogger(__name__)


def record_candidate(db: Session, address: str, source: str = "auto") -> bool:
    """Yeni aday cüzdanı `discovered` olarak ekler. Zaten varsa False döner."""
    if not address:
        return False
    existing = db.query(Wallet).filter(Wallet.address == address).first()
    if existing:
        return False
    db.add(Wallet(address=address, status=WalletStatus.discovered.value, discovery_source=source))
    db.commit()
    return True


def pending_candidates(db: Session, limit: int) -> list[Wallet]:
    """Henüz analiz edilmemiş keşfedilmiş cüzdanlar.

    EN YENİ önce: güncel/aktif trader'ları öncelikle analiz ederiz; eski (ör.
    önceki dönemden kalma) stale adaylar boşta kalan kapasitede işlenir. Böylece
    şu an işlem yapan kaliteli cüzdanlar daha hızlı yüzeye çıkar.
    """
    return (
        db.query(Wallet)
        .filter(Wallet.status == WalletStatus.discovered.value, Wallet.last_analyzed.is_(None))
        .order_by(Wallet.first_seen.desc())
        .limit(limit)
        .all()
    )


def analyze_discovered_batch(
    db: Session, chain: ChainProvider, limit: int = 5, ingest_limit: int = 80
) -> list[dict]:
    """Bir parti keşfedilmiş cüzdanı analiz edip puanlar."""
    results: list[dict] = []
    for w in pending_candidates(db, limit):
        try:
            ingest_wallet(db, chain, w.address, limit=ingest_limit)
            res = analyze_wallet(db, w.address)
            results.append({"address": w.address, "score": res.total, "tracked": res.tracked})
        except RpcUnavailableError as exc:
            logger.warning("Aday analiz edilemedi (RPC): %s", exc)
            # transient; last_analyzed'i değiştirme ki tekrar denensin
            break
        except Exception as exc:  # noqa: BLE001
            logger.exception("Aday analiz hatası %s: %s", w.address, exc)
            # kalıcı hata: sonsuz döngüyü önlemek için işaretle
            w.last_analyzed = datetime.now(timezone.utc)
            w.status = WalletStatus.analyzed.value
            db.commit()
    return results
