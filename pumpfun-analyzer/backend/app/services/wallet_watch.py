"""Takip edilen cüzdanları GÜVENİLİR ve UCUZ izleyen poll (yoklama) servisi.

Neden poll? Helius `logsSubscribe` (WS) olayları sessizce KAÇIRABİLİR ve yoğun
RPC yükünde aç kalabilir — bu yüzden "takipteki cüzdan alım yaptı" sinyali tek
başına WS'e bağlı olduğunda güvenilmez olur (0 işleme yol açtı).

KREDİ KRİTİK: Bu servis UCUZ RPC çağrılarını kullanır:
  - `getSignaturesForAddress` (1 kredi) ile her cüzdanın SON imzalarını çeker,
  - yalnızca TAZE (son `fresh_seconds`) ve daha önce İŞLENMEMİŞ imzalar için
    `getTransaction` (1 kredi) çağırır.
Böylece pahalı `getEnhancedTransactionsByAddress` (10+ kredi/çağrı) KULLANILMAZ;
boştaki bir cüzdan döngü başına yalnızca ~1 kredi tüketir.

Çift işlemi önlemek için: Alert.signature + `should_process(sig)` (Redis TTL).
Yalnızca TAZE alımlar işlenir (cüzdan yeni takibe alındığında geçmiş alımları
kopyalamayız).
"""
from __future__ import annotations

import logging
import time

from sqlalchemy.orm import Session

from ..adapters.base import ChainProvider, MarketProvider
from ..adapters.pumpfun import normalize_rpc_transaction
from ..adapters.pumpportal import PumpPortalTrade, PumpPortalTrader
from ..core.analysis.swap_detection import detect_swap
from ..models import Alert, Wallet, WalletStatus
from ..notifications.telegram import TelegramNotifier
from .live_flow import handle_trade_event

logger = logging.getLogger(__name__)


def poll_tracked_wallets(
    db: Session,
    chain: ChainProvider,
    *,
    market: MarketProvider | None = None,
    notifier: TelegramNotifier | None = None,
    signer: PumpPortalTrader | None = None,
    per_wallet: int = 6,
    fresh_seconds: int = 900,
) -> dict:
    """Takip edilen cüzdanların taze alımlarını işleme hattına yönlendirir (ucuz).

    Dedup YALNIZCA Alert.signature ile yapılır (gerçek işlem/bildirim oluştuysa
    çift işlem olmaz). Reddedilen (vetolu/motor-bloklu) taze alımlar taze penceresi
    boyunca her döngüde yeniden DEĞERLENDİRİLİR — böylece ret SEBEBİ her zaman
    görünür kalır (Redis dedup'ı sebebi gizliyordu)."""
    from collections import Counter
    tracked = db.query(Wallet).filter(Wallet.status == WalletStatus.tracked.value).all()
    now = time.time()
    fresh_txns = 0   # taze + yeni (getTransaction çekilen) işlem sayısı
    triggered = 0
    reasons: Counter = Counter()  # işlem AÇILMADIYSA gerçek sebepler (teşhis)

    for w in tracked:
        try:
            sigs = chain.get_signatures_for_address(w.address, limit=per_wallet)  # ~1 kredi
        except Exception as exc:  # noqa: BLE001
            logger.warning("[WATCH] %s imzaları alınamadı: %s", w.address[:6], exc)
            continue
        for s in sigs or []:
            sig = s.get("signature") if isinstance(s, dict) else s
            block_time = s.get("blockTime") if isinstance(s, dict) else None
            if not sig:
                continue
            # TAZELİK filtresi imza listesinden (getTransaction'a GİTMEDEN) — kredi koruması
            if block_time is not None and (now - block_time) > fresh_seconds:
                continue
            # dedup: gerçek işlem/bildirim oluştuysa (Alert) tekrar işleme — çift yok
            if db.query(Alert).filter(Alert.signature == sig).first():
                continue
            try:
                raw = chain.get_transaction(sig)  # ~1 kredi (yalnızca taze+Alert'siz için)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[WATCH] getTransaction hatası %s: %s", sig[:8], exc)
                continue
            ntx = normalize_rpc_transaction(raw) if raw else None
            if ntx is None:
                continue
            swap = detect_swap(ntx, w.address)
            if swap is None or swap.side != "buy":
                continue
            if now - swap.block_time > fresh_seconds:
                continue
            fresh_txns += 1
            trade = PumpPortalTrade(
                signature=swap.signature, trader=w.address, mint=swap.token_mint,
                side="buy", sol_amount=swap.sol_amount, token_amount=swap.token_amount,
                pool=swap.venue, market_cap_sol=None, raw={},
            )
            try:
                res = handle_trade_event(db, trade, chain=chain, market=market,
                                         notifier=notifier, signer=signer)
                act = res.get("action")
                if act == "buy" and res.get("traded"):
                    triggered += 1  # gerçekten paper/canlı işlem açıldı
                elif act == "buy":
                    tb = res.get("trade_blocked")
                    reasons["motor: " + (", ".join(tb) if tb else "motor kapalı veya limit")[:80]] += 1
                elif act == "skipped":
                    reasons[str(res.get("reason", "?"))[:90]] += 1
                elif act == "ignored":
                    reasons["cüzdan takipte değil"] += 1
                else:
                    reasons[f"sonuç: {act}"[:90]] += 1
            except Exception as exc:  # noqa: BLE001
                logger.exception("[WATCH] işlem akışı hatası %s: %s", swap.signature[:8], exc)
                reasons[f"HATA {type(exc).__name__}: {exc}"[:90]] += 1

    logger.info("[WATCH] tracked=%d fresh_buys=%d triggered=%d reasons=%s",
                len(tracked), fresh_txns, triggered, dict(reasons.most_common(5)))
    return {"polled": len(tracked), "fresh_buys": fresh_txns, "triggered": triggered,
            "reasons": dict(reasons.most_common(5))}


def run_diagnostic_trade(db: Session, chain: ChainProvider,
                         market: MarketProvider | None = None) -> dict:
    """Bir takip cüzdanının EN SON alımını SENKRON işler ve KARARI döner.

    Worker/beat çalışmasa bile panelden ANINDA sonuç verir: işlem açıldı mı, yoksa
    hangi sebeple açılmadı (veto / motor / hata). Teşhis amaçlı — gerçek paper
    işlem açılabilir (risksiz). Alert dedup'ı atlanır ki karar her zaman görünsün."""
    import time as _t
    from .live_flow import handle_trade_event as _hte

    tracked = (db.query(Wallet).filter(Wallet.status == WalletStatus.tracked.value)
               .order_by(Wallet.latest_score.desc()).all())
    if not tracked:
        return {"ok": False, "reason": "Takip edilen cüzdan yok."}
    now = _t.time()
    checked = 0
    for w in tracked:
        try:
            sigs = chain.get_signatures_for_address(w.address, limit=10)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "reason": f"İmza alınamadı: {type(exc).__name__}: {exc}"}
        for s in sigs or []:
            sig = s.get("signature") if isinstance(s, dict) else s
            bt = s.get("blockTime") if isinstance(s, dict) else None
            if not sig:
                continue
            checked += 1
            try:
                raw = chain.get_transaction(sig)
            except Exception:  # noqa: BLE001
                continue
            ntx = normalize_rpc_transaction(raw) if raw else None
            if ntx is None:
                continue
            swap = detect_swap(ntx, w.address)
            if swap is None or swap.side != "buy":
                continue
            trade = PumpPortalTrade(
                signature="TEST-" + (swap.signature or sig), trader=w.address,
                mint=swap.token_mint, side="buy", sol_amount=swap.sol_amount,
                token_amount=swap.token_amount, pool=swap.venue, market_cap_sol=None, raw={},
            )
            res = _hte(db, trade, chain=chain, market=market)
            age_min = (now - swap.block_time) / 60.0 if swap.block_time else None
            return {"ok": True, "wallet": w.address, "wallet_score": w.latest_score,
                    "token": swap.token_mint, "buy_age_min": round(age_min, 1) if age_min else None,
                    "result": res}
    return {"ok": False, "reason": f"Son işlemlerde ALIM bulunamadı ({checked} imza tarandı). "
                                   f"Cüzdanlar şu an satış/transfer yapıyor olabilir."}
