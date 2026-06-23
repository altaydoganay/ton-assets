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
from ..core.analysis.swap_detection import DetectedSwap
from ..models import Token, TokenStatus, Wallet, WalletStatus
from ..notifications.telegram import AlertContent, TelegramNotifier, short_addr
from ..trading.engine import CopyTradeEngine, TradeContext, LiveTradingNotConfigured
from ..trading.risk import RiskConfig
from .pipeline import store_swap
from .settings_service import get_setting
from .token_analysis import analyze_token

logger = logging.getLogger(__name__)

_engine: CopyTradeEngine | None = None


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
    chain = chain or build_chain_provider()
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

    # 3) tokeni anlık analiz et
    token, token_result = analyze_token(db, trade.mint, chain, market)
    token_threshold = get_setting(db, "thresholds").get("token", 70.0)
    token_ok = (not token_result.vetoed) and token_result.total >= token_threshold

    market_price_sol = swap.price_sol
    liquidity_sol = float((token.metrics or {}).get("liquidity_sol", 0.0))

    summary = {
        "wallet": short_addr(trade.trader),
        "token": short_addr(trade.mint),
        "side": trade.side,
        "wallet_score": wallet.latest_score,
        "token_score": token_result.total,
        "token_ok": token_ok,
    }

    if trade.side == "sell":
        # Hedef satışı yansıt (paper/canlı). Yüzde bilgisini bilemediğimiz için
        # tamamı varsayımıyla yansıtırız (FULL); kısmi oran ileride event'ten gelebilir.
        engine = get_engine(db, signer=signer)
        ctx = _ctx(trade, wallet, token_result, market_price_sol, liquidity_sol)
        engine.on_leader_sell(db, ctx, leader_sell_fraction=1.0)
        summary["action"] = "mirror_sell"
        return summary

    # ALIM
    if not token_ok:
        summary["action"] = "skipped"
        summary["reason"] = "token puanı eşik altında / veto"
        return summary

    # 4) Telegram bildirimi (dedup'lı) — işlemden bağımsız
    notifier = notifier or TelegramNotifier()
    risk_flags = list(token_result.veto_reasons) + list(wallet.risk_flags or [])
    content = AlertContent(
        signature=trade.signature, wallet_address=trade.trader,
        wallet_label=wallet.label, wallet_score=wallet.latest_score or 0,
        token_mint=trade.mint, token_name=token.symbol or token.name,
        token_score=token_result.total, amount_token=trade.token_amount,
        sol_value=trade.sol_amount, usd_value=None,
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        risk_flags=risk_flags, auto_traded=False,
    )
    alert = notifier.notify(db, content)

    # 5) kopya işlem motoru (paper/canlı) — bağımsız tetiklenir
    engine = get_engine(db, signer=signer)
    decision = None
    if engine.cfg.enabled and engine.cfg.mode != "alerts_only":
        ctx = _ctx(trade, wallet, token_result, market_price_sol, liquidity_sol)
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
    return summary


def _ctx(trade: PumpPortalTrade, wallet: Wallet, token_result, price_sol: float, liquidity_sol: float) -> TradeContext:
    return TradeContext(
        wallet_address=trade.trader,
        token_mint=trade.mint,
        wallet_score=wallet.latest_score or 0,
        token_score=token_result.total,
        token_liquidity_sol=liquidity_sol,
        token_sellable=not token_result.vetoed,
        follow_lag_seconds=0.0,
        market_price_sol=price_sol,
        leader_sol_amount=trade.sol_amount,
        source_signature=trade.signature,
    )
