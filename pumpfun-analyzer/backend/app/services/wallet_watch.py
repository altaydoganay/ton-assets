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
from sqlalchemy import case, func

from ..models import Alert, LiveTrade, PaperTrade, Wallet, WalletStatus
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
    max_wallets: int = 150,
) -> dict:
    """Takip edilen cüzdanların taze alımlarını işleme hattına yönlendirir (ucuz).

    Dedup YALNIZCA Alert.signature ile yapılır (gerçek işlem/bildirim oluştuysa
    çift işlem olmaz). Reddedilen (vetolu/motor-bloklu) taze alımlar taze penceresi
    boyunca her döngüde yeniden DEĞERLENDİRİLİR — böylece ret SEBEBİ her zaman
    görünür kalır (Redis dedup'ı sebebi gizliyordu).

    Geniş ağda yüzlerce takip cüzdanı olabilir; bütçe için döngü başına en fazla
    `max_wallets` cüzdan taranır — en yüksek puanlılar ÖNCE (öncelik)."""
    from collections import Counter
    tracked = (
        db.query(Wallet)
        .filter(Wallet.status == WalletStatus.tracked.value)
        .order_by(Wallet.latest_score.desc().nullslast())
        .limit(max_wallets)
        .all()
    )
    now = time.time()
    fresh_txns = 0   # taze + yeni (getTransaction çekilen) işlem sayısı
    triggered = 0    # açılan ALIM sayısı
    mirrored = 0     # yansıtılan SATIŞ sayısı
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
            # TAZELİK filtresi imza listesinden (getTransaction'a GİTMEDEN)
            if block_time is not None and (now - block_time) > fresh_seconds:
                continue
            try:
                raw = chain.get_transaction(sig)  # ~1 kredi
            except Exception as exc:  # noqa: BLE001
                logger.warning("[WATCH] getTransaction hatası %s: %s", sig[:8], exc)
                continue
            ntx = normalize_rpc_transaction(raw) if raw else None
            if ntx is None:
                continue
            swap = detect_swap(ntx, w.address)
            if swap is None:
                continue
            if now - swap.block_time > fresh_seconds:
                continue

            if swap.side == "buy":
                # dedup: bu alımı zaten işlediysek (Alert) atla → çift yok
                if db.query(Alert).filter(Alert.signature == swap.signature).first():
                    continue
            elif swap.side == "sell":
                # Lider SATIŞINI yansıt — ama yalnızca o token'da AÇIK pozisyonumuz varsa.
                net_paper = (db.query(
                    func.coalesce(func.sum(
                        case((PaperTrade.side == "buy", PaperTrade.token_amount),
                             else_=-PaperTrade.token_amount)), 0.0))
                    .filter(PaperTrade.token_mint == swap.token_mint).scalar() or 0.0)
                net_live = (db.query(
                    func.coalesce(func.sum(
                        case((LiveTrade.side == "buy", LiveTrade.token_amount),
                             else_=-LiveTrade.token_amount)), 0.0))
                    .filter(LiveTrade.token_mint == swap.token_mint, LiveTrade.status != "failed")
                    .scalar() or 0.0)
                if net_paper <= 0 and net_live <= 0:
                    continue  # elimizde pozisyon yok — yansıtacak bir şey yok
                # dedup: bu satışı zaten yansıttıysak atla
                if db.query(PaperTrade).filter(PaperTrade.source_signature == swap.signature,
                                               PaperTrade.side == "sell").first():
                    continue
                if db.query(LiveTrade).filter(LiveTrade.source_signature == swap.signature,
                                              LiveTrade.side == "sell").first():
                    continue
            else:
                continue

            fresh_txns += 1
            trade = PumpPortalTrade(
                signature=swap.signature, trader=w.address, mint=swap.token_mint,
                side=swap.side, sol_amount=swap.sol_amount, token_amount=swap.token_amount,
                pool=swap.venue, market_cap_sol=None, raw={},
            )
            try:
                res = handle_trade_event(db, trade, chain=chain, market=market,
                                         notifier=notifier, signer=signer,
                                         block_time=swap.block_time)
                act = res.get("action")
                if act == "buy" and res.get("traded"):
                    triggered += 1  # gerçekten paper/canlı ALIM açıldı
                elif act == "mirror_sell":
                    mirrored += 1   # lider satışı yansıtıldı
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

    logger.info("[WATCH] tracked=%d fresh=%d alım=%d satış=%d reasons=%s",
                len(tracked), fresh_txns, triggered, mirrored, dict(reasons.most_common(5)))
    return {"polled": len(tracked), "fresh_buys": fresh_txns, "triggered": triggered,
            "mirrored_sells": mirrored, "reasons": dict(reasons.most_common(5))}


def run_diagnostic_trade(db: Session, chain: ChainProvider,
                         market: MarketProvider | None = None,
                         max_wallets: int = 8, recent_seconds: int = 3600,
                         budget_seconds: float = 12.0) -> dict:
    """Bir takip cüzdanının EN SON alımını SENKRON işler ve KARARI döner.

    Worker/beat çalışmasa bile panelden ANINDA sonuç verir: işlem açıldı mı, yoksa
    hangi sebeple açılmadı (veto / motor / hata). HIZLI ve SINIRLI: en çok
    `max_wallets` cüzdan, yalnızca SON `recent_seconds` imzalar için getTransaction,
    ve `budget_seconds` zaman bütçesi (zaman aşımı/"Failed to fetch" olmasın)."""
    import time as _t
    from .live_flow import handle_trade_event as _hte

    tracked = (db.query(Wallet).filter(Wallet.status == WalletStatus.tracked.value)
               .order_by(Wallet.latest_score.desc()).limit(max_wallets).all())
    if not tracked:
        return {"ok": False, "reason": "Takip edilen cüzdan yok."}
    start = _t.monotonic()
    now = _t.time()
    checked = 0
    errors = 0
    for w in tracked:
        if _t.monotonic() - start > budget_seconds:
            break
        try:
            sigs = chain.get_signatures_for_address(w.address, limit=8)
        except Exception as exc:  # noqa: BLE001
            errors += 1
            continue
        for s in sigs or []:
            if _t.monotonic() - start > budget_seconds:
                break
            sig = s.get("signature") if isinstance(s, dict) else s
            bt = s.get("blockTime") if isinstance(s, dict) else None
            if not sig:
                continue
            # SADECE taze imzalar için getTransaction (kredi + hız koruması)
            if bt is not None and (now - bt) > recent_seconds:
                continue
            checked += 1
            try:
                raw = chain.get_transaction(sig)
            except Exception:  # noqa: BLE001
                errors += 1
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
    note = f" ({errors} RPC hatası)" if errors else ""
    return {"ok": False, "reason": f"Son {recent_seconds//60} dk içinde ALIM bulunamadı "
                                   f"({checked} taze işlem tarandı{note}). Cüzdanlar şu an "
                                   f"satış/transfer yapıyor olabilir — birkaç saniye sonra tekrar dene."}
