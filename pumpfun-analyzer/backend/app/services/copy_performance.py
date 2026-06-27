"""Kopya (copy-trade) performansı: BİZİM paper sonuçlarımıza göre cüzdan elemesi.

Takip listesine bir cüzdan, GEÇMİŞ analiziyle girer. Ama onu KOPYALADIKTAN sonra
elimizde gerçek geri bildirim olur: bu cüzdanı kopyalamak bize kazandırdı mı?
Bu, "takip etmeye değer mi" sorusunun en doğrudan ölçüsüdür.

Burada her cüzdanın kapanmış paper işlemlerinden (sell satırları, realized_pnl_sol)
kümülatif PnL, kazanç/kayıp ve ARDIŞIK ZARAR hesaplanır; eşikleri aşan cüzdanlar
otomatik ENGELLENİR (status=blocked) — böylece gerçek paraya geçmeden önce
başarısızlar paper aşamasında elenir.
"""
from __future__ import annotations

import logging

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import AuditLog, PaperTrade, Wallet, WalletStatus

logger = logging.getLogger(__name__)


def _short(a: str) -> str:
    return f"{a[:4]}…{a[-4:]}" if a and len(a) > 10 else a


def wallet_copy_stats(db: Session, address: str) -> dict:
    """Bir cüzdanı kopyalamanın BİZE getirdiği sonuç (paper)."""
    sells = (db.query(PaperTrade)
             .filter(PaperTrade.wallet_address == address, PaperTrade.side == "sell")
             .order_by(PaperTrade.created_at.asc()).all())
    realized = [float(s.realized_pnl_sol or 0.0) for s in sells]
    closed = len(realized)
    wins = sum(1 for r in realized if r > 0)
    losses = sum(1 for r in realized if r < 0)
    total_pnl = sum(realized)
    consec = 0
    for r in reversed(realized):
        if r < 0:
            consec += 1
        else:
            break
    open_buys = (db.query(func.count(PaperTrade.id))
                 .filter(PaperTrade.wallet_address == address,
                         PaperTrade.side == "buy", PaperTrade.is_open.is_(True)).scalar() or 0)
    return {
        "wallet": address,
        "closed_trades": closed,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / closed, 3) if closed else 0.0,
        "total_pnl_sol": round(total_pnl, 4),
        "consecutive_losses": consec,
        "open_positions": int(open_buys),
        "last_trade_at": sells[-1].created_at.isoformat() if sells else None,
    }


def tracked_copy_stats(db: Session, include_blocked: bool = False) -> list[dict]:
    """Takip edilen (ve istenirse engellenen) cüzdanların kopya performansı —
    en kötüden en iyiye değil, PnL'e göre sıralı (en iyi üstte)."""
    from .settings_service import get_setting
    overrides = get_setting(db, "copy_overrides")
    statuses = [WalletStatus.tracked.value]
    if include_blocked:
        statuses.append(WalletStatus.blocked.value)
    wallets = db.query(Wallet).filter(Wallet.status.in_(statuses)).all()
    rows = []
    for w in wallets:
        st = wallet_copy_stats(db, w.address)
        st["status"] = w.status
        st["score"] = w.latest_score
        st["label"] = w.label
        st["avg_buy_size_sol"] = (w.metrics or {}).get("avg_buy_size_sol")
        st["copy_override_sol"] = overrides.get(w.address)
        rows.append(st)
    rows.sort(key=lambda r: r["total_pnl_sol"], reverse=True)
    return rows


def token_copy_stats(db: Session) -> list[dict]:
    """BİZİM token bazlı sonucumuz: hangi token'de ne kadar kâr/zarar ettik
    (paper). Kapanmış realized PnL + açık pozisyon. En kazandıran üstte."""
    from ..models import Token
    trades = (db.query(PaperTrade).order_by(PaperTrade.created_at.asc()).all())
    agg: dict[str, dict] = {}
    for t in trades:
        a = agg.setdefault(t.token_mint, {"mint": t.token_mint, "buys": 0, "sells": 0,
                                          "realized_pnl_sol": 0.0, "wins": 0, "losses": 0,
                                          "qty": 0.0, "cost": 0.0, "last": None})
        a["last"] = t.created_at.isoformat()
        if t.side == "buy":
            a["buys"] += 1; a["qty"] += t.token_amount; a["cost"] += t.sol_amount
        else:
            a["sells"] += 1
            a["realized_pnl_sol"] += float(t.realized_pnl_sol or 0.0)
            if (t.realized_pnl_sol or 0) > 0: a["wins"] += 1
            elif (t.realized_pnl_sol or 0) < 0: a["losses"] += 1
            if a["qty"] > 0:
                frac = min(1.0, t.token_amount / a["qty"]) if a["qty"] else 0
                a["cost"] -= a["cost"] * frac; a["qty"] -= t.token_amount
                if a["qty"] < 1e-9: a["qty"] = 0.0; a["cost"] = 0.0
    rows = []
    for mint, a in agg.items():
        tok = db.query(Token).filter(Token.mint == mint).first()
        closed = a["wins"] + a["losses"]
        rows.append({
            "mint": mint, "symbol": (tok.symbol or tok.name) if tok else None,
            "score": tok.latest_score if tok else None,
            "realized_pnl_sol": round(a["realized_pnl_sol"], 4),
            "closed_trades": closed, "wins": a["wins"], "losses": a["losses"],
            "win_rate": round(a["wins"] / closed, 3) if closed else 0.0,
            "open_qty": round(a["qty"], 2), "open_cost_sol": round(a["cost"], 4),
            "buys": a["buys"], "last": a["last"],
        })
    rows.sort(key=lambda r: r["realized_pnl_sol"], reverse=True)
    return rows


def prune_underperformers(db: Session, *, enabled: bool = True, max_consecutive_losses: int = 5,
                          min_closed_trades: int = 6, min_pnl_sol: float = 0.0) -> dict:
    """Kopya performansı kötü cüzdanları ENGELLE (status=blocked).

    Eleme ölçütü BAŞARI ORANI DEĞİL, BİZE GETİRDİĞİ KOPYA PnL'idir (beklenti).
    Taze pump.fun token'lerinde ödeme asimetriktir: kârlı bir cüzdan %5-10 başarıyla
    ama yüksek kazanç/kayıp oranıyla kazanabilir. Win-rate'e göre eleme, bize PARA
    KAZANDIRAN bu düşük-isabetli cüzdanları yanlışlıkla atardı. Bu yüzden:

    Yeterli örneklem (>= `min_closed_trades` kapanmış işlem) sonrası:
      - kopya PnL < `min_pnl_sol` (vars. 0 = bize zarar ettiren) => ELE, VEYA
      - `max_consecutive_losses` (vars. 5) ARDIŞIK zarar => ELE (rug/bozulma sinyali;
        örneklemden bağımsız çünkü hızlı bir uyarıdır).

    Win-rate yalnızca bilgilendirme amaçlı tutulur (panelde görünür), elemeyi
    tetiklemez. Engellenen cüzdan tekrar takibe ALINMAZ; panelden elle çözülebilir.
    """
    if not enabled:
        return {"enabled": False, "checked": 0, "pruned": 0, "details": []}
    tracked = db.query(Wallet).filter(Wallet.status == WalletStatus.tracked.value).all()
    pruned = []
    for w in tracked:
        st = wallet_copy_stats(db, w.address)
        reason = None
        if max_consecutive_losses > 0 and st["consecutive_losses"] >= max_consecutive_losses:
            reason = f"{st['consecutive_losses']} ardışık zarar"
        elif st["closed_trades"] >= min_closed_trades and st["total_pnl_sol"] < min_pnl_sol:
            reason = (f"kopya PnL {st['total_pnl_sol']:+.4f} SOL "
                      f"(< {min_pnl_sol:+.4f}, {st['closed_trades']} işlem, başarı %{round(st['win_rate']*100)})")
        if reason:
            w.status = WalletStatus.blocked.value
            db.add(AuditLog(
                level="warning", category="prune",
                message=(f"Cüzdan ELENDİ (kopya performansı): {_short(w.address)} — {reason} · "
                         f"{st['wins']}K/{st['losses']}Z · PnL {st['total_pnl_sol']} SOL"),
                context=st))
            pruned.append({"wallet": w.address, "reason": reason, **st})
    if pruned:
        db.commit()
        logger.info("[PRUNE] checked=%d pruned=%d", len(tracked), len(pruned))
    return {"enabled": True, "checked": len(tracked), "pruned": len(pruned), "details": pruned}
