"""Canlı olay akışı işleyicisi.

PumpPortal'dan gelen GERÇEK al-sat olayını alır ve görev tanımındaki akışı
uygular:

  1. Olayı `swaps` tablosuna idempotent yazar (canlı olay akışı sayfası).
  2. Cüzdan takipte (puan ≥ eşik) değilse durur.
  3. Tokeni anlık analiz eder; token puanı eşik altındaysa / veto varsa
     bildirim ve işlem YAPILMAZ (işlem öncesi son güvenlik kontrolü).
  4. ALIM ise: signature bazlı dedup → Telegram bildirimi → (ayar açıksa)
     kopya işlem motoru (paper veya canlı PumpPortal Lightning).
  5. SATIM ise: paper/canlı yansıtma (kısmi/tam).

Bildirim ile işlem motoru BAĞIMSIZDIR; işlem Telegram'ı beklemez.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..adapters.base import ChainProvider, MarketProvider
from ..adapters.pumpportal import PumpPortalTrade, PumpPortalTrader
from ..adapters.registry import build_chain_provider, build_market_provider
from ..config import settings
from ..core.analysis.swap_detection import DetectedSwap
from ..models import AuditLog, Token, TokenStatus, Wallet, WalletStatus
from ..notifications.telegram import AlertContent, TelegramNotifier, short_addr
from ..trading.engine import CopyTradeEngine, TradeContext, LiveTradingNotConfigured
from ..trading.risk import RiskConfig
from .pipeline import store_swap
from .settings_service import get_setting
from .token_analysis import assess_token

logger = logging.getLogger(__name__)

_engine: CopyTradeEngine | None = None


def _audit(db: Session, level: str, message: str, context: dict) -> None:
    """Takip olayının kararını Loglar sayfasına yazar (şeffaflık/ayar için).
    Başarısız olsa bile akışı bozmaz."""
    try:
        db.add(AuditLog(level=level, category="trading", message=message, context=context))
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()


def _risk_config(db: Session) -> RiskConfig:
    r = get_setting(db, "risk")
    thresholds = get_setting(db, "thresholds")
    return RiskConfig(
        enabled=bool(r.get("enabled")),
        mode=r.get("mode", "paper"),
        live_confirmed=bool(r.get("live_confirmed")),
        fixed_sol_amount=float(r.get("fixed_sol_amount", 0.05)),
        proportional=bool(r.get("proportional")),
        proportional_factor=float(r.get("proportional_factor", 1.0)),
        max_position_sol=float(r.get("max_position_sol", 0.5)),
        max_daily_spend_sol=float(r.get("max_daily_spend_sol", 2.0)),
        max_daily_loss_sol=float(r.get("max_daily_loss_sol", 1.0)),
        max_slippage=float(r.get("max_slippage", 0.15)),
        priority_fee_sol=float(r.get("priority_fee_sol", 0.0005)),
        min_wallet_score=float(r.get("min_wallet_score", thresholds.get("wallet", 70.0))),
        min_token_score=float(r.get("min_token_score", thresholds.get("token", 70.0))),
        token_gate=str(r.get("token_gate", "safety")),
        max_open_positions_per_token=int(r.get("max_open_positions_per_token", 1)),
        max_follow_lag_seconds=int(r.get("max_follow_lag_seconds", 60)),
        min_liquidity_sol=float(r.get("min_liquidity_sol", 5.0)),
        emergency_stop=bool(r.get("emergency_stop")),
        blocked_wallets=list(r.get("blocked_wallets", [])),
        blocked_tokens=list(r.get("blocked_tokens", [])),
        only_wallets=list(r.get("only_wallets", [])),
    )


def get_engine(db: Session, signer=None) -> CopyTradeEngine:
    """Süreç-ömürlü kopya işlem motoru (günlük durum korunur, ayarlar tazelenir)."""
    global _engine
    cfg = _risk_config(db)
    if _engine is None:
        _engine = CopyTradeEngine(cfg, signer=signer)
    else:
        _engine.cfg = cfg  # günlük harcama/zarar ve paper pozisyonları korunur
        if signer is not None:
            _engine.signer = signer
    return _engine


def reset_engine() -> None:
    global _engine
    _engine = None


def _to_detected_swap(t: PumpPortalTrade, block_time: int) -> DetectedSwap:
    price = (t.sol_amount / t.token_amount) if t.token_amount else 0.0
    return DetectedSwap(
        signature=t.signature, wallet_address=t.trader, token_mint=t.mint,
        side=t.side, sol_amount=t.sol_amount, token_amount=t.token_amount,
        price_sol=price, fee_sol=0.0, venue=t.pool or "pumpfun",
        block_time=block_time, slot=None, confirmation="confirmed",
    )


def handle_trade_event(
    db: Session,
    trade: PumpPortalTrade,
    *,
    chain: ChainProvider | None = None,
    market: MarketProvider | None = None,
    notifier: TelegramNotifier | None = None,
    signer: PumpPortalTrader | None = None,
) -> dict:
    """Bir PumpPortal trade olayını uçtan uca işler. Sonuç özetini döner."""
    now = int(datetime.now(timezone.utc).timestamp())
    # Canlı alım yolu: throttle KAPALI (düşük gecikme).
    chain = chain or build_chain_provider(throttle=False)
    market = market or build_market_provider()

    # 1) swap'ı kaydet (transfer değil; PumpPortal yalnızca gerçek swap yayınlar)
    swap = _to_detected_swap(trade, now)
    if swap.signature:
        store_swap(db, swap)

    # 2) cüzdan takipte mi?
    wallet = db.query(Wallet).filter(Wallet.address == trade.trader).first()
    wallet_threshold = get_setting(db, "thresholds").get("wallet", 70.0)
    if not wallet or wallet.status != WalletStatus.tracked.value or (wallet.latest_score or 0) < wallet_threshold:
        return {"action": "ignored", "reason": "cüzdan takipte değil"}

    # 3) tokeni değerlendir (önbellekli, hızlı) — canlı alımda gecikmeyi azaltır
    assessment = assess_token(db, trade.mint, chain, market, settings.token_score_cache_seconds)
    token = assessment.token
    token_threshold = get_setting(db, "thresholds").get("token", 70.0)
    # İşlem kapısı politikası: cüzdan alpha; token bir GÜVENLİK filtresidir.
    #   safety   → veto yoksa geç (taze bonding token'lerin düşük puanı engel değil)
    #   balanced → veto yok + puan ≥ 55
    #   score    → veto yok + puan ≥ eşik (klasik katı)
    # VARSAYILAN safety: taze token'ler adil puanlanamadığından kalite eşiği değil
    # GÜVENLİK vetosu uygulanır; asıl sinyal cüzdandır.
    token_gate = get_setting(db, "risk").get("token_gate", "safety")
    if token_gate == "score":
        token_ok = (not assessment.vetoed) and assessment.total >= token_threshold
    elif token_gate == "balanced":
        token_ok = (not assessment.vetoed) and assessment.total >= 55.0
    else:  # safety
        token_ok = not assessment.vetoed

    market_price_sol = swap.price_sol
    liquidity_sol = assessment.liquidity_sol

    summary = {
        "wallet": short_addr(trade.trader),
        "token": short_addr(trade.mint),
        "side": trade.side,
        "wallet_score": wallet.latest_score,
        "token_score": assessment.total,
        "token_ok": token_ok,
        "cached": assessment.cached,
    }

    if trade.side == "sell":
        # Hedef satışı yansıt (paper/canlı). Yüzde bilgisini bilemediğimiz için
        # tamamı varsayımıyla yansıtırız (FULL); kısmi oran ileride event'ten gelebilir.
        engine = get_engine(db, signer=signer)
        ctx = _ctx(trade, wallet, assessment.total, assessment.vetoed, market_price_sol, liquidity_sol)
        engine.on_leader_sell(db, ctx, leader_sell_fraction=1.0)
        summary["action"] = "mirror_sell"
        return summary

    # ALIM
    if not token_ok:
        summary["action"] = "skipped"
        reason = ("güvenlik vetosu: " + ", ".join(assessment.veto_reasons)) if assessment.vetoed \
            else f"token puanı {assessment.total:.0f} < kapı eşiği ({token_gate})"
        summary["reason"] = reason
        _audit(db, "info", f"Atlandı — {short_addr(trade.trader)} → {short_addr(trade.mint)}: {reason}",
               {"wallet": trade.trader, "token": trade.mint, "wallet_score": wallet.latest_score,
                "token_score": assessment.total, "gate": token_gate, "signature": trade.signature})
        return summary

    # 4) Telegram bildirimi (dedup'lı) — işlemden bağımsız
    notifier = notifier or TelegramNotifier()
    risk_flags = list(assessment.veto_reasons) + list(wallet.risk_flags or [])
    content = AlertContent(
        signature=trade.signature, wallet_address=trade.trader,
        wallet_label=wallet.label, wallet_score=wallet.latest_score or 0,
        token_mint=trade.mint, token_name=token.symbol or token.name,
        token_score=assessment.total, amount_token=trade.token_amount,
        sol_value=trade.sol_amount, usd_value=None,
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        risk_flags=risk_flags, auto_traded=False,
    )
    alert = notifier.notify(db, content)

    # 5) kopya işlem motoru (paper/canlı) — bağımsız tetiklenir
    engine = get_engine(db, signer=signer)
    decision = None
    if engine.cfg.enabled and engine.cfg.mode != "alerts_only":
        ctx = _ctx(trade, wallet, assessment.total, assessment.vetoed, market_price_sol, liquidity_sol)
        try:
            decision = engine.on_leader_buy(db, ctx)
            if alert and decision and decision.allowed:
                alert.auto_traded = True
                db.commit()
        except LiveTradingNotConfigured as exc:
            logger.warning("Canlı işlem yapılandırılmamış: %s", exc)

    summary["action"] = "buy"
    summary["alerted"] = alert is not None
    summary["traded"] = bool(decision and decision.allowed)
    if decision and not decision.allowed:
        summary["trade_blocked"] = decision.reasons
    # Karar logu (Loglar sayfası): işlem yapıldı mı / neden yapılmadı
    if decision and decision.allowed:
        _audit(db, "info",
               f"İşlem AÇILDI — {short_addr(trade.trader)} → {short_addr(trade.mint)} "
               f"({engine.cfg.mode}, {decision.sol_amount:.3f} SOL)",
               {"wallet": trade.trader, "token": trade.mint, "wallet_score": wallet.latest_score,
                "token_score": assessment.total, "sol_amount": decision.sol_amount,
                "mode": engine.cfg.mode, "signature": trade.signature})
    else:
        block = decision.reasons if decision else ["işlem motoru kapalı (yalnızca bildirim)"]
        _audit(db, "info",
               f"Bildirim gönderildi, işlem YOK — {short_addr(trade.trader)} → "
               f"{short_addr(trade.mint)}: {', '.join(block)}",
               {"wallet": trade.trader, "token": trade.mint, "wallet_score": wallet.latest_score,
                "token_score": assessment.total, "blocked": block, "signature": trade.signature})
    return summary


def _ctx(trade: PumpPortalTrade, wallet: Wallet, token_total: float, token_vetoed: bool,
         price_sol: float, liquidity_sol: float) -> TradeContext:
    return TradeContext(
        wallet_address=trade.trader,
        token_mint=trade.mint,
        wallet_score=wallet.latest_score or 0,
        token_score=token_total,
        token_liquidity_sol=liquidity_sol,
        token_sellable=not token_vetoed,
        follow_lag_seconds=0.0,
        market_price_sol=price_sol,
        leader_sol_amount=trade.sol_amount,
        source_signature=trade.signature,
    )
