"""Take-profit / stop-loss otomasyonu (paper pozisyonlar).

Açık paper pozisyonlarını mevcut fiyatla karşılaştırır; TP/SL eşiği aşılırsa
pozisyonu (paper) kapatır. Karar mantığı `trading.risk.tp_sl_should_close`'da;
burada veri toplama + kapatma yapılır.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from ..adapters.base import MarketProvider
from ..models import AuditLog, PaperTrade, Token
from ..trading.risk import tp_sl_should_close
from .settings_service import get_setting
from .stats_service import open_positions

logger = logging.getLogger(__name__)


def _price(db: Session, market: MarketProvider, mint: str) -> float:
    try:
        md = market.get_token_market(mint)
        if md.ok and md.price_sol:
            return float(md.price_sol)
    except Exception:  # noqa: BLE001
        pass
    token = db.query(Token).filter(Token.mint == mint).first()
    return float((token.metrics or {}).get("price_sol", 0.0)) if token else 0.0


def manage_positions(db: Session, market: MarketProvider) -> list[dict]:
    """TP/SL eşiklerini kontrol eder, tetiklenen paper pozisyonlarını kapatır."""
    risk = get_setting(db, "risk")
    tp = float(risk.get("take_profit_pct", 0) or 0)
    sl = float(risk.get("stop_loss_pct", 0) or 0)
    if tp <= 0 and sl <= 0:
        return []
    closed = []
    for p in open_positions(db):
        price = _price(db, market, p["token_mint"])
        if price <= 0:
            continue
        decision = tp_sl_should_close(p["cost_sol"], p["qty"], price, tp, sl)
        if decision is None:
            continue
        proceeds = p["qty"] * price
        pnl = proceeds - p["cost_sol"]
        db.add(PaperTrade(
            wallet_address=p["wallet_address"], token_mint=p["token_mint"], side="sell",
            sol_amount=proceeds, token_amount=p["qty"], price_sol=price, fee_sol=0.0,
            realized_pnl_sol=pnl, is_open=False,
            reason=f"{'take-profit' if decision=='tp' else 'stop-loss'} (paper)",
        ))
        db.add(AuditLog(level="info", category="trading",
                        message=f"{decision.upper()} ile pozisyon kapatıldı: {p['token_mint']}",
                        context={"pnl_sol": round(pnl, 4)}))
        closed.append({"token_mint": p["token_mint"], "reason": decision, "pnl_sol": round(pnl, 4)})
    if closed:
        db.commit()
    return closed
