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
        rows.append(st)
    rows.sort(key=lambda r: r["total_pnl_sol"], reverse=True)
    return rows


def prune_underperformers(db: Session, *, enabled: bool = True, max_consecutive_losses: int = 5,
                          min_closed_trades: int = 4, max_drawdown_sol: float = -0.5) -> dict:
    """Kopya performansı kötü cüzdanları ENGELLE (status=blocked).

    Kriterler (yeterli örneklem -- en az `min_closed_trades` kapanmış işlem sonrası):
      - `max_consecutive_losses` (vars. 5) ardışık zarar, VEYA
      - kümülatif kopya PnL <= `max_drawdown_sol` (vars. -0.5 SOL).
    Engellenen cüzdan tekrar takibe ALINMAZ (persist_wallet_score blocked'ı korur);
    kullanıcı isterse panelden elle çözebilir.
    """
    if not enabled:
        return {"enabled": False, "checked": 0, "pruned": 0, "details": []}
    tracked = db.query(Wallet).filter(Wallet.status == WalletStatus.tracked.value).all()
    pruned = []
    for w in tracked:
        st = wallet_copy_stats(db, w.address)
        if st["closed_trades"] < min_closed_trades:
            continue
        reason = None
        if max_consecutive_losses > 0 and st["consecutive_losses"] >= max_consecutive_losses:
            reason = f"{st['consecutive_losses']} ardışık zarar"
        elif st["total_pnl_sol"] <= max_drawdown_sol:
            reason = f"kümülatif kopya PnL {st['total_pnl_sol']} SOL (≤ {max_drawdown_sol})"
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
