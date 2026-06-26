"""Takip edilen cüzdanları GÜVENİLİR biçimde izleyen poll (yoklama) servisi.

Neden poll? Helius `logsSubscribe` (WS) olayları sessizce KAÇIRABİLİR ve yoğun
RPC yükünde aç kalabilir — bu yüzden "takipteki cüzdan alım yaptı" sinyali
güvenilmez olur (canlı dinleyiciye tek başına güvenmek 0 işleme yol açtı).

Bu servis bunun yerine her döngüde her takip edilen cüzdanın SON işlemlerini
Helius **Enhanced Transactions** ile (cüzdan başına TEK ucuz istek) çeker ve
yalnızca **taze** (son `fresh_seconds`) ALIMLARI `handle_trade_event`'e yönlendirir.
Böylece WS kaçırsa bile alımlar yakalanır. Çift işlemi önlemek için:
  - Alert.signature ile (işlem/bildirim oluşmuşsa) zaten işlenmiş sayılır,
  - ek olarak `should_process(sig)` (Redis TTL) ile tekrar işleme engellenir.

Yalnızca TAZE alımlar işlenir; cüzdan takibe yeni alındığında geçmiş alımları
kopyalamayız (yalnızca bundan sonra yaptıkları).
"""
from __future__ import annotations

import logging
import time

from sqlalchemy.orm import Session

from ..adapters.base import ChainProvider, MarketProvider
from ..adapters.pumpfun import normalize_enhanced_transaction
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
    per_wallet: int = 8,
    fresh_seconds: int = 900,
    should_process=None,
) -> dict:
    """Takip edilen cüzdanların taze alımlarını işleme hattına yönlendirir."""
    if not hasattr(chain, "get_address_transactions"):
        # Enhanced yoksa (Helius anahtarı yok) bu güvenilir yol devre dışı.
        return {"polled": 0, "fresh_buys": 0, "triggered": 0, "skipped": "no_enhanced"}

    from collections import Counter
    should_process = should_process or (lambda _sig: True)
    tracked = db.query(Wallet).filter(Wallet.status == WalletStatus.tracked.value).all()
    now = time.time()
    fresh_buys = 0
    triggered = 0
    reasons: Counter = Counter()  # işlem AÇILMADIYSA gerçek sebepler (teşhis)

    for w in tracked:
        try:
            txs = chain.get_address_transactions(w.address, limit=per_wallet)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[WATCH] %s işlemleri alınamadı: %s", w.address[:6], exc)
            continue
        for enh in txs or []:
            ntx = normalize_enhanced_transaction(enh)
            if ntx is None:
                continue
            swap = detect_swap(ntx, w.address)
            if swap is None or swap.side != "buy":
                continue
            if now - swap.block_time > fresh_seconds:
                continue  # eski alım — kopyalama (yalnızca taze)
            fresh_buys += 1
            # dedup: işlem/bildirim zaten oluşmuşsa atla (çift işlem yok)
            if db.query(Alert).filter(Alert.signature == swap.signature).first():
                continue
            if not should_process(swap.signature):
                continue
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
                    # token kapısını geçti ama MOTOR açmadı (kapalı/limit/skor)
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
                len(tracked), fresh_buys, triggered, dict(reasons.most_common(5)))
    return {"polled": len(tracked), "fresh_buys": fresh_buys, "triggered": triggered,
            "reasons": dict(reasons.most_common(5))}
