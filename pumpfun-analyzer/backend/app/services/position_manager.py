"""Akıllı çıkış motoru (paper pozisyonlar) — kârı belirleyen yer.

Açık paper pozisyonları için her döngüde mevcut fiyatla şu çıkış kurallarını
ÖNCELİK sırasıyla uygular:

  1. Sert stop-loss (`stop_loss_pct`)         — zararı kes
  2. Sert take-profit (`take_profit_pct`)      — sabit kâr al
  3. TAKİP EDEN STOP (`trailing_stop_pct`)      — fiyat zirveden bu kadar düşerse
     sat (yalnızca pozisyon `trail_activate_pct` kâra ulaştıktan SONRA aktifleşir):
     yükselişi yakala, dönüşte kârı kilitle.
  4. ZAMAN ÇIKIŞI (`max_hold_minutes`)          — pump.fun token'leri hızlı söner;
     bu süre dolunca pozisyonu kapat.

Zirve fiyat `position_state` ayarında (DB) pozisyon başına tutulur.
Tutma süresi artık yöneticinin pozisyonu ilk gördüğü andan değil, gerçek buy
kaydının `created_at` zamanından hesaplanır. Fiyat verisi gelmese bile max hold
dolduysa paper pozisyon güvenli şekilde kapatılır.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..adapters.base import MarketProvider
from ..models import AuditLog, PaperTrade, Token
from ..trading.risk import tp_sl_should_close
from .settings_service import get_setting, set_setting
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


def _decide(pnl_pct: float, peak_pnl_pct: float, drop_from_peak: float, held_min: float,
            tp: float, sl: float, trail: float, trail_act: float, max_hold_min: float) -> str | None:
    """Çıkış kararı (öncelik sırasıyla). Dönüş: sl|tp|trailing|time|None."""
    if sl > 0 and pnl_pct <= -sl:
        return "sl"
    if tp > 0 and pnl_pct >= tp:
        return "tp"
    if trail > 0 and peak_pnl_pct >= trail_act and drop_from_peak >= trail:
        return "trailing"
    if max_hold_min > 0 and held_min >= max_hold_min:
        return "time"
    return None


_LABEL = {"sl": "stop-loss", "tp": "take-profit", "trailing": "takip eden stop", "time": "zaman çıkışı", "no_price_time": "zaman çıkışı / fiyat yok"}


def _as_utc(dt: datetime | None, fallback: datetime) -> datetime:
    if dt is None:
        return fallback
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def manage_positions(db: Session, market: MarketProvider) -> list[dict]:
    """Akıllı çıkış kurallarını uygular; tetiklenen paper pozisyonlarını kapatır."""
    risk = get_setting(db, "risk")
    if risk.get("pure_mirror_mode") and str(risk.get("strategy_mode", "copy")) != "ai":
        return []  # SAF KOPYA: otomatik çıkış yok; yalnızca lider satınca satılır. AI modunda lider yoktur; TP/SL şarttır.
    tp = float(risk.get("take_profit_pct", 0) or 0)
    sl = float(risk.get("stop_loss_pct", 0) or 0)
    trail = float(risk.get("trailing_stop_pct", 0) or 0)
    trail_act = float(risk.get("trail_activate_pct", 0.15) or 0)
    max_hold_min = float(risk.get("max_hold_minutes", 0) or 0)
    if tp <= 0 and sl <= 0 and trail <= 0 and max_hold_min <= 0:
        return []

    state = dict(get_setting(db, "position_state") or {})
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    closed = []
    # Bu yönetici yalnızca PAPER simülasyonunu kapatır. open_positions() canlı
    # pozisyonları da döndürür; canlıyı burada paper trade yazarak kapatmak hem
    # gerçek satış yapmaz hem de panelde yanlış PnL üretir.
    # Mod izolasyonu: AI modundayken yalnızca AI paper pozisyonları; Copy
    # modundayken yalnızca copy paper pozisyonları yönetilir. Böylece mod
    # değişince diğer motor arka planda pozisyon kapatmaya devam etmez.
    active_strategy = str(risk.get("strategy_mode", "copy") or "copy")
    open_pos = [p for p in open_positions(db) if p.get("mode", "paper") == "paper"]
    if active_strategy == "ai":
        open_pos = [p for p in open_pos if p.get("wallet_address") == "AI_TRADE"]
    else:
        open_pos = [p for p in open_pos if p.get("wallet_address") != "AI_TRADE"]
    open_keys = {p.get("position_id") or p["token_mint"] for p in open_pos}
    # kapanmış pozisyonların durumunu temizle
    state = {m: s for m, s in state.items() if m in open_keys}

    for p in open_pos:
        mint = p["token_mint"]
        key = p.get("position_id") or mint
        cost = float(p["cost_sol"]); qty = float(p["qty"])
        if cost <= 0 or qty <= 0:
            continue

        # Kritik düzeltme: hold süresi yöneticinin ilk gördüğü andan değil,
        # pozisyonun gerçek ilk buy zamanından hesaplanır. Aksi halde worker
        # gecikirse AI pozisyonu max-hold'a rağmen açık kalır.
        entry = _as_utc(p.get("first_buy") or p.get("opened_at"), now)
        held_min = max(0.0, (now - entry).total_seconds() / 60.0)

        price = _price(db, market, mint)
        if price <= 0:
            # Pump.fun tokenlerinde DexScreener/RPC fiyatı geç veya hiç gelmeyebilir.
            # Fiyat yok diye pozisyonu sonsuza kadar açık bırakmak paper sonuçlarını
            # çarpıtır. Max hold dolduysa konservatif olarak 0 fiyatla kapatılır.
            if max_hold_min > 0 and held_min >= max_hold_min:
                decision = "no_price_time"
                price = 0.0
                pnl_pct = -1.0
                peak_pnl_pct = -1.0
                drop_from_peak = 1.0
            else:
                continue
        else:
            st = state.setdefault(key, {"peak": price})
            st["peak"] = max(float(st.get("peak", price)), price)
            peak = float(st["peak"])
            pnl_pct = (qty * price - cost) / cost
            peak_pnl_pct = (qty * peak - cost) / cost
            drop_from_peak = (peak - price) / peak if peak > 0 else 0.0
            decision = _decide(pnl_pct, peak_pnl_pct, drop_from_peak, held_min,
                               tp, sl, trail, trail_act, max_hold_min)
            if decision is None:
                continue

        proceeds = qty * price
        pnl = proceeds - cost
        db.add(PaperTrade(
            wallet_address=p["wallet_address"], token_mint=mint, side="sell",
            sol_amount=proceeds, token_amount=qty, price_sol=price, fee_sol=0.0,
            realized_pnl_sol=pnl, is_open=False, reason=f"{_LABEL[decision]} (paper)",
        ))
        strategy = "ai" if p.get("wallet_address") == "AI_TRADE" else "copy"
        db.add(AuditLog(level="info", category="trading",
                        message=f"{_LABEL[decision].upper()} ile kapatıldı: {mint[:6]}… "
                                f"PnL {round(pnl,4)} SOL ({round(pnl_pct*100)}% · {round(held_min)}dk)",
                        context={"reason": decision, "exit_reason": decision,
                                 "exit_label": _LABEL[decision], "strategy": strategy,
                                 "wallet": p.get("wallet_address"), "token": mint,
                                 "pnl_sol": round(pnl, 4),
                                 "pnl_pct": round(pnl_pct, 4), "held_min": round(held_min, 1),
                                 "entry_cost_sol": round(cost, 6), "exit_value_sol": round(proceeds, 6),
                                 "exit_price_sol": price}))
        state.pop(key, None)
        closed.append({"token_mint": mint, "reason": decision, "pnl_sol": round(pnl, 4), "held_min": round(held_min, 1)})

    set_setting(db, "position_state", state)
    if closed:
        db.commit()
        logger.info("[EXIT] closed=%d reasons=%s", len(closed), [c["reason"] for c in closed])
    return closed
