"""Akıllı çıkış motoru (paper pozisyonlar) — kârı belirleyen yer.

İki mod vardır:

COPY (ve AI hunter kapalıyken): klasik öncelikli çıkış —
  1. Sert stop-loss  2. Sert take-profit  3. Takip eden stop  4. Kademeli TP
  5. Likidite watchdog  6. Durgunluk çıkışı  7. Zaman çıkışı.

AI PUMP.FUN AVCISI (strategy_mode="ai" + ai_hunter_enabled): faz makinesi —
  - accum fazı (ana para HENÜZ çıkmadı): SERT stop, momentum/2x zaman çıkışı,
    dar trailing. Değer `ai_principal_mult`'e ulaşınca ANA PARA + fee/slippage
    tamponu geri alınır → kalan pozisyon RİSKSİZ, faz "moonbag" olur.
  - moonbag fazı (ana para çıktı): panik yok. 10x'te kalanın %25'i, opsiyonel
    25x'te bir kısmı daha satılır; kalan GENİŞ trailing ile yüksek X için taşınır.
    Yalnızca ciddi risk (likidite çekilmesi) veya moonbag trailing kırılırsa çıkar.

`position_state` (DB) pozisyon başına faz/zirve bilgisini tutar. Miktar DAİMA
`qty_raw` (yuvarlanmamış) ile işlenir; aksi halde küçük pozisyonlar 0'a
yuvarlanıp satış kaydı 0 adet yazar ve pozisyon hiç kapanmazdı.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..adapters.base import MarketProvider
from ..models import AuditLog, PaperTrade, Token
from .settings_service import get_setting, set_setting
from .stats_service import open_positions

logger = logging.getLogger(__name__)


def _market_snapshot(db: Session, market: MarketProvider, mint: str) -> tuple[float, float]:
    """(fiyat_sol, likidite_usd). Likidite ölçülemiyorsa 0 (watchdog atlar)."""
    try:
        md = market.get_token_market(mint)
        if md.ok and md.price_sol:
            return float(md.price_sol), float(md.liquidity_usd or 0.0)
    except Exception:  # noqa: BLE001
        pass
    token = db.query(Token).filter(Token.mint == mint).first()
    m = (token.metrics or {}) if token else {}
    return float(m.get("price_sol", 0.0)), float(m.get("liquidity_usd", 0.0) or 0.0)


def _curve_sol(db: Session, mint: str) -> float:
    """Token'ın tahmini bonding-curve SOL'ü (migration yakınlığı). Bilinmiyorsa 0."""
    token = db.query(Token).filter(Token.mint == mint).first()
    m = (token.metrics or {}) if token else {}
    try:
        return float(m.get("curve_sol_est") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _decide(pnl_pct: float, peak_pnl_pct: float, drop_from_peak: float, held_min: float,
            tp: float, sl: float, trail: float, trail_act: float, max_hold_min: float,
            stagnant_min: float = 0.0, stagnant_max_pnl: float = 0.0) -> str | None:
    """Klasik (copy) çıkış kararı. Dönüş: sl|tp|trailing|stagnant|time|None."""
    if sl > 0 and pnl_pct <= -sl:
        return "sl"
    if tp > 0 and pnl_pct >= tp:
        return "tp"
    if trail > 0 and peak_pnl_pct >= trail_act and drop_from_peak >= trail:
        return "trailing"
    if stagnant_min > 0 and held_min >= stagnant_min and pnl_pct <= stagnant_max_pnl:
        return "stagnant"
    if max_hold_min > 0 and held_min >= max_hold_min:
        return "time"
    return None


_LABEL = {
    "sl": "stop-loss", "tp": "take-profit", "trailing": "takip eden stop",
    "time": "zaman çıkışı", "no_price_time": "zaman çıkışı / fiyat yok",
    "liq_pull": "LİKİDİTE ÇEKİLDİ (acil çıkış)", "stagnant": "momentum yok (erken çıkış)",
    "partial_tp": "kademeli kâr alımı",
    # --- hunter ---
    "principal_out": "ANA PARA ÇIKARILDI (kalan risksiz)",
    "tp10": "10x KÂR ALINDI (%25)", "tp25": "25x KÂR ALINDI",
    "hard_stop": "SERT STOP (ana para öncesi)",
    "time_momentum": "MOMENTUM YOK (erken çıkış)",
    "time_2x": "2x GELMEDİ (zaman çıkışı)",
    "trailing_moon": "MOONBAG TRAILING KIRILDI",
    "hard_exit": "HARD EXIT (risk bozuldu)",
}


def _as_utc(dt: datetime | None, fallback: datetime) -> datetime:
    if dt is None:
        return fallback
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _sell(db: Session, wallet: str, mint: str, sell_qty: float, price: float,
          full_qty: float, full_cost: float, reason: str, held_min: float,
          extra_msg: str = "") -> dict:
    """Paper satış kaydı yazar (kısmi veya tam). PnL, satılan miktarın maliyet
    payına göre hesaplanır (FIFO netleme kalan pozisyonu buna göre günceller)."""
    frac = min(1.0, sell_qty / full_qty) if full_qty > 0 else 1.0
    proceeds = sell_qty * price
    cost_part = full_cost * frac
    pnl = proceeds - cost_part
    db.add(PaperTrade(
        wallet_address=wallet, token_mint=mint, side="sell",
        sol_amount=proceeds, token_amount=sell_qty, price_sol=price, fee_sol=0.0,
        realized_pnl_sol=pnl, is_open=False, reason=f"{_LABEL.get(reason, reason)} (paper)",
    ))
    mult = (price * full_qty / full_cost) if full_cost > 0 else 0.0
    db.add(AuditLog(level="info", category="trading",
                    message=f"{_LABEL.get(reason, reason)}: {mint[:6]}… "
                            f"{round(mult, 2)}x · PnL {round(pnl, 4)} SOL · {round(held_min)}dk{extra_msg}",
                    context={"reason": reason, "exit_reason": reason,
                             "exit_label": _LABEL.get(reason, reason), "strategy": "ai",
                             "wallet": wallet, "token": mint, "pnl_sol": round(pnl, 4),
                             "mult": round(mult, 3), "fraction": round(frac, 3),
                             "held_min": round(held_min, 1), "exit_price_sol": price}))
    return {"token_mint": mint, "reason": reason, "pnl_sol": round(pnl, 4),
            "fraction": round(frac, 3), "held_min": round(held_min, 1)}


def _hunter_step(db: Session, r: dict, p: dict, st: dict, price: float, liq_usd: float,
                 held_min: float) -> tuple[list[dict], bool]:
    """Bir AI pozisyonu için avcı faz makinesini bir tur çalıştırır.

    Dönüş: (bu turda yazılan kapanış olayları, pozisyon_tam_kapandı_mı).
    `st` yerinde güncellenir (peak / principal_out / tp10_done / tp25_done)."""
    mint = p["token_mint"]
    wallet = p["wallet_address"]
    cost = float(p["cost_sol"])
    qty = float(p.get("qty_raw") or p["qty"])
    events: list[dict] = []
    if cost <= 0 or qty <= 0 or price <= 0:
        return events, False

    value = qty * price
    mult = value / cost
    st["peak"] = max(float(st.get("peak", price)), price)
    peak = float(st["peak"])
    peak_mult = qty * peak / cost
    drop_from_peak = (peak - price) / peak if peak > 0 else 0.0

    principal_out = bool(st.get("principal_out"))

    # HARD EXIT — likidite çekilmesi (her fazda, en yüksek öncelik)
    liq_drop = float(r.get("exit_liq_drop_pct", 0) or 0)
    if liq_usd > 0:
        st["peak_liq"] = max(float(st.get("peak_liq", liq_usd)), liq_usd)
        if liq_drop > 0 and float(st["peak_liq"]) >= 500.0 and liq_usd <= float(st["peak_liq"]) * (1.0 - liq_drop):
            events.append(_sell(db, wallet, mint, qty, price, qty, cost, "liq_pull", held_min))
            return events, True

    if not principal_out:
        # ---- ACCUM FAZI: ana para henüz çıkmadı → SERT koruma ----
        stop_pre = float(r.get("ai_stop_pre_pct", 0.35) or 0)
        if stop_pre > 0 and (mult - 1.0) <= -stop_pre:
            events.append(_sell(db, wallet, mint, qty, price, qty, cost, "hard_stop", held_min))
            return events, True
        mom_min = float(r.get("ai_momentum_minutes", 4.0) or 0)
        mom_mult = float(r.get("ai_momentum_min_mult", 1.3) or 0)
        if mom_min > 0 and held_min >= mom_min and mult < mom_mult:
            events.append(_sell(db, wallet, mint, qty, price, qty, cost, "time_momentum", held_min))
            return events, True
        twox_min = float(r.get("ai_twox_minutes", 10.0) or 0)
        twox_mult = float(r.get("ai_twox_min_mult", 2.0) or 0)
        if twox_min > 0 and held_min >= twox_min and mult < twox_mult:
            events.append(_sell(db, wallet, mint, qty, price, qty, cost, "time_2x", held_min))
            return events, True
        trail_pre = float(r.get("ai_trail_pre_pct", 0.28) or 0)
        trail_act = float(r.get("trail_activate_pct", 0.15) or 0)
        if trail_pre > 0 and (peak_mult - 1.0) >= trail_act and drop_from_peak >= trail_pre:
            events.append(_sell(db, wallet, mint, qty, price, qty, cost, "trailing", held_min))
            return events, True
        # ANA PARA ÇIKIŞI — değer principal_mult'e ulaştıysa ana para + tamponu geri al.
        # MIGRATION de-risk: token mezuniyet bölgesine girdiyse (curve_sol_est yüksek)
        # ve pozisyon kârdaysa, principal_mult'i beklemeden ana parayı ERKEN çıkar
        # (PumpSwap geçişinde slippage/likidite riski için risksize al).
        principal_mult = float(r.get("ai_principal_mult", 2.5) or 0)
        trigger_principal = principal_mult > 0 and mult >= principal_mult
        trigger_migration = False
        if (bool(r.get("ai_migration_guard_enabled", True)) and bool(r.get("ai_migration_derisk", True))):
            mig_floor = float(r.get("ai_migration_curve_sol", 75.0) or 0)
            derisk_min = float(r.get("ai_migration_derisk_min_mult", 1.2) or 0)
            if mig_floor > 0 and mult >= derisk_min and _curve_sol(db, mint) >= mig_floor:
                trigger_migration = True
        if trigger_principal or trigger_migration:
            buffer = float(r.get("ai_principal_fee_buffer", 0.08) or 0)
            recover_sol = cost * (1.0 + buffer)
            sell_qty = min(qty, recover_sol / price)
            note = " · MOONBAG aktif" + (" · MIGRATION de-risk" if trigger_migration and not trigger_principal else "")
            if sell_qty >= qty * 0.98:
                # ana para ~tüm pozisyona denk (çok düşük mult) — tam çıkış
                events.append(_sell(db, wallet, mint, qty, price, qty, cost, "principal_out", held_min))
                return events, True
            events.append(_sell(db, wallet, mint, sell_qty, price, qty, cost, "principal_out",
                                held_min, extra_msg=note))
            st["principal_out"] = True
            return events, False
        return events, False

    # ---- MOONBAG FAZI: ana para çıktı → panik yok, yüksek X kovala ----
    tp10_mult = float(r.get("ai_tp10_mult", 10.0) or 0)
    tp10_frac = float(r.get("ai_tp10_fraction", 0.25) or 0)
    if tp10_mult > 0 and mult >= tp10_mult and not st.get("tp10_done"):
        sell_qty = qty * min(0.9, max(0.05, tp10_frac))
        events.append(_sell(db, wallet, mint, sell_qty, price, qty, cost, "tp10", held_min))
        st["tp10_done"] = True
        return events, False
    if bool(r.get("ai_tp25_enabled", False)):
        tp25_mult = float(r.get("ai_tp25_mult", 25.0) or 0)
        tp25_frac = float(r.get("ai_tp25_fraction", 0.18) or 0)
        if tp25_mult > 0 and mult >= tp25_mult and not st.get("tp25_done"):
            sell_qty = qty * min(0.9, max(0.05, tp25_frac))
            events.append(_sell(db, wallet, mint, sell_qty, price, qty, cost, "tp25", held_min))
            st["tp25_done"] = True
            return events, False
    # MOONBAG geniş trailing — kalan pozisyonu ancak zirveden büyük dönüşte kapat
    trail_moon = float(r.get("ai_trail_moon_pct", 0.45) or 0)
    if trail_moon > 0 and drop_from_peak >= trail_moon:
        events.append(_sell(db, wallet, mint, qty, price, qty, cost, "trailing_moon", held_min))
        return events, True
    return events, False


def manage_positions(db: Session, market: MarketProvider) -> list[dict]:
    """Akıllı çıkış kurallarını uygular; tetiklenen paper pozisyonlarını kapatır."""
    risk = get_setting(db, "risk")
    if risk.get("pure_mirror_mode") and str(risk.get("strategy_mode", "copy")) != "ai":
        return []  # SAF KOPYA: otomatik çıkış yok; yalnızca lider satınca satılır.
    active_strategy = str(risk.get("strategy_mode", "copy") or "copy")
    hunter = active_strategy == "ai" and bool(risk.get("ai_hunter_enabled", True))

    tp = float(risk.get("take_profit_pct", 0) or 0)
    sl = float(risk.get("stop_loss_pct", 0) or 0)
    trail = float(risk.get("trailing_stop_pct", 0) or 0)
    trail_act = float(risk.get("trail_activate_pct", 0.15) or 0)
    max_hold_min = float(risk.get("max_hold_minutes", 0) or 0)
    partial_tp = float(risk.get("partial_tp_pct", 0) or 0)
    partial_frac = min(0.9, max(0.1, float(risk.get("partial_tp_fraction", 0.5) or 0.5)))
    liq_drop = float(risk.get("exit_liq_drop_pct", 0) or 0)
    stagnant_min = float(risk.get("stagnant_exit_minutes", 0) or 0)
    stagnant_max_pnl = float(risk.get("stagnant_max_pnl_pct", 0.0) or 0.0)
    # hunter modunda kurallar risk dict'inden okunur; klasik anahtarlar kapalı olsa
    # bile avcı çalışır. Klasik modda hiçbir kural yoksa erken çık.
    if not hunter and (tp <= 0 and sl <= 0 and trail <= 0 and max_hold_min <= 0
                       and partial_tp <= 0 and liq_drop <= 0 and stagnant_min <= 0):
        return []

    state = dict(get_setting(db, "position_state") or {})
    now = datetime.now(timezone.utc)
    closed: list[dict] = []
    open_pos = [p for p in open_positions(db) if p.get("mode", "paper") == "paper"]
    if active_strategy == "ai":
        open_pos = [p for p in open_pos if p.get("wallet_address") == "AI_TRADE"]
    else:
        open_pos = [p for p in open_pos if p.get("wallet_address") != "AI_TRADE"]
    open_keys = {p.get("position_id") or p["token_mint"] for p in open_pos}
    state = {m: s for m, s in state.items() if m in open_keys}

    for p in open_pos:
        mint = p["token_mint"]
        key = p.get("position_id") or mint
        cost = float(p["cost_sol"])
        qty = float(p.get("qty_raw") or p["qty"])  # DAİMA ham miktar (kapanış hatası fix)
        if cost <= 0 or qty <= 0:
            continue
        entry = _as_utc(p.get("first_buy") or p.get("opened_at"), now)
        held_min = max(0.0, (now - entry).total_seconds() / 60.0)
        price, liq_usd = _market_snapshot(db, market, mint)

        # ---- AI HUNTER YOLU ----
        if hunter:
            if price <= 0:
                # fiyat yok: 2x zaman penceresi dolduysa güvenli kapat, yoksa bekle
                twox_min = float(risk.get("ai_twox_minutes", 10.0) or 0)
                if not state.get(key, {}).get("principal_out") and twox_min > 0 and held_min >= twox_min:
                    proceeds = 0.0
                    db.add(PaperTrade(wallet_address=p["wallet_address"], token_mint=mint, side="sell",
                                      sol_amount=proceeds, token_amount=qty, price_sol=0.0, fee_sol=0.0,
                                      realized_pnl_sol=-cost, is_open=False,
                                      reason=f"{_LABEL['no_price_time']} (paper)"))
                    db.add(AuditLog(level="info", category="trading",
                                    message=f"{_LABEL['no_price_time']}: {mint[:6]}… fiyat gelmedi, kapatıldı",
                                    context={"reason": "no_price_time", "exit_reason": "no_price_time",
                                             "exit_label": _LABEL["no_price_time"], "strategy": "ai",
                                             "wallet": p["wallet_address"], "token": mint,
                                             "pnl_sol": round(-cost, 4), "held_min": round(held_min, 1)}))
                    state.pop(key, None)
                    closed.append({"token_mint": mint, "reason": "no_price_time", "pnl_sol": round(-cost, 4)})
                continue
            st = state.setdefault(key, {"peak": price})
            events, done = _hunter_step(db, risk, p, st, price, liq_usd, held_min)
            closed.extend(events)
            if done:
                state.pop(key, None)
            continue

        # ---- KLASİK (copy / hunter kapalı) YOL ----
        if price <= 0:
            if max_hold_min > 0 and held_min >= max_hold_min:
                decision = "no_price_time"
                price = 0.0
                pnl_pct = -1.0
            else:
                continue
        else:
            st = state.setdefault(key, {"peak": price})
            st["peak"] = max(float(st.get("peak", price)), price)
            peak = float(st["peak"])
            pnl_pct = (qty * price - cost) / cost
            peak_pnl_pct = (qty * peak - cost) / cost
            drop_from_peak = (peak - price) / peak if peak > 0 else 0.0
            decision = None
            if liq_usd > 0:
                st["peak_liq"] = max(float(st.get("peak_liq", liq_usd)), liq_usd)
                peak_liq = float(st["peak_liq"])
                if liq_drop > 0 and peak_liq >= 500.0 and liq_usd <= peak_liq * (1.0 - liq_drop):
                    decision = "liq_pull"
            in_partial_band = pnl_pct >= partial_tp and (tp <= 0 or pnl_pct < tp)
            if decision is None and partial_tp > 0 and in_partial_band and not st.get("partial_done"):
                part_qty = qty * partial_frac
                part_cost = cost * partial_frac
                part_proceeds = part_qty * price
                part_pnl = part_proceeds - part_cost
                db.add(PaperTrade(
                    wallet_address=p["wallet_address"], token_mint=mint, side="sell",
                    sol_amount=part_proceeds, token_amount=part_qty, price_sol=price, fee_sol=0.0,
                    realized_pnl_sol=part_pnl, is_open=False, reason=f"{_LABEL['partial_tp']} (paper)",
                ))
                st["partial_done"] = True
                db.add(AuditLog(level="info", category="trading",
                                message=f"KADEMELİ kâr alımı: {mint[:6]}… %{int(partial_frac*100)} satıldı, "
                                        f"PnL {round(part_pnl,4)} SOL (+{round(pnl_pct*100)}%), kalan trailing'de",
                                context={"reason": "partial_tp", "exit_reason": "partial_tp",
                                         "exit_label": _LABEL["partial_tp"],
                                         "strategy": "copy", "wallet": p.get("wallet_address"),
                                         "token": mint, "pnl_sol": round(part_pnl, 4),
                                         "pnl_pct": round(pnl_pct, 4), "fraction": partial_frac,
                                         "held_min": round(held_min, 1)}))
                closed.append({"token_mint": mint, "reason": "partial_tp",
                               "pnl_sol": round(part_pnl, 4), "held_min": round(held_min, 1)})
                continue
            if decision is None:
                decision = _decide(pnl_pct, peak_pnl_pct, drop_from_peak, held_min,
                                   tp, sl, trail, trail_act, max_hold_min,
                                   stagnant_min, stagnant_max_pnl)
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
