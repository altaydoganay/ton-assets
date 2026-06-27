"""Panel istatistikleri: genel bakış, keşif hunisi, performans, pozisyonlar.

Tüm metrikler veritabanından TÜRETİLİR (süreçler arası bellek durumuna bağlı
değil) — listener/worker/api hepsi aynı sonucu görür.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (
    Alert,
    LiveTrade,
    PaperTrade,
    Token,
    TokenStatus,
    Wallet,
    WalletStatus,
)


def _utc_date(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).date().isoformat()


def wallet_status_counts(db: Session) -> dict[str, int]:
    rows = db.query(Wallet.status, func.count(Wallet.id)).group_by(Wallet.status).all()
    return {s: c for s, c in rows}


def token_status_counts(db: Session) -> dict[str, int]:
    rows = db.query(Token.status, func.count(Token.id)).group_by(Token.status).all()
    return {s: c for s, c in rows}


def overview(db: Session) -> dict:
    wc = wallet_status_counts(db)
    tc = token_status_counts(db)
    now = datetime.now(timezone.utc)
    today = now.date()

    discovered_today = (
        db.query(func.count(Wallet.id))
        .filter(Wallet.first_seen >= datetime(today.year, today.month, today.day, tzinfo=timezone.utc))
        .scalar()
    ) or 0
    analyzed_today = (
        db.query(func.count(Wallet.id))
        .filter(Wallet.last_analyzed >= datetime(today.year, today.month, today.day, tzinfo=timezone.utc))
        .scalar()
    ) or 0
    alerts_today = (
        db.query(func.count(Alert.id))
        .filter(Alert.created_at >= datetime(today.year, today.month, today.day, tzinfo=timezone.utc))
        .scalar()
    ) or 0

    paper_pnl = db.query(func.coalesce(func.sum(PaperTrade.realized_pnl_sol), 0.0)).scalar() or 0.0
    live_pnl = db.query(func.coalesce(func.sum(LiveTrade.realized_pnl_sol), 0.0)).scalar() or 0.0

    return {
        "wallets": {
            "total": sum(wc.values()),
            "tracked": wc.get(WalletStatus.tracked.value, 0),
            "discovered": wc.get(WalletStatus.discovered.value, 0),
            "analyzed": wc.get(WalletStatus.analyzed.value, 0),
            "rejected": wc.get(WalletStatus.rejected.value, 0),
            "below_threshold": wc.get(WalletStatus.below_threshold.value, 0),
            "blocked": wc.get(WalletStatus.blocked.value, 0),
        },
        "tokens": {
            "total": sum(tc.values()),
            "tracked": tc.get(TokenStatus.tracked.value, 0),
            "vetoed": tc.get(TokenStatus.vetoed.value, 0),
        },
        "funnel": {
            "discovered_today": discovered_today,
            "analyzed_today": analyzed_today,
            "tracked_total": wc.get(WalletStatus.tracked.value, 0),
        },
        "alerts": {
            "total": db.query(func.count(Alert.id)).scalar() or 0,
            "today": alerts_today,
        },
        "pnl": {
            "paper_sol": round(float(paper_pnl), 4),
            "live_sol": round(float(live_pnl), 4),
        },
    }


def discovery_timeseries(db: Session, days: int = 14) -> list[dict]:
    """Son N gün: günlük keşfedilen ve takibe alınan cüzdan sayısı."""
    start = datetime.now(timezone.utc) - timedelta(days=days)
    wallets = db.query(Wallet.first_seen, Wallet.last_analyzed, Wallet.status).filter(
        Wallet.first_seen >= start
    ).all()
    disc = defaultdict(int)
    trk = defaultdict(int)
    for first_seen, last_analyzed, status in wallets:
        disc[_utc_date(first_seen)] += 1
        if status == WalletStatus.tracked.value and last_analyzed:
            trk[_utc_date(last_analyzed)] += 1
    out = []
    for i in range(days, -1, -1):
        d = (datetime.now(timezone.utc) - timedelta(days=i)).date().isoformat()
        out.append({"date": d, "discovered": disc.get(d, 0), "tracked": trk.get(d, 0)})
    return out


def performance(db: Session) -> dict:
    trades = db.query(PaperTrade).order_by(PaperTrade.created_at.asc()).all()
    sells = [t for t in trades if t.side == "sell"]
    curve = []
    cum = 0.0
    for t in sells:
        cum += t.realized_pnl_sol or 0.0
        curve.append({"t": _utc_date(t.created_at), "pnl": round(cum, 4)})
    wins = [t for t in sells if (t.realized_pnl_sol or 0) > 0]
    losses = [t for t in sells if (t.realized_pnl_sol or 0) < 0]
    best = max((t.realized_pnl_sol or 0 for t in sells), default=0.0)
    worst = min((t.realized_pnl_sol or 0 for t in sells), default=0.0)
    return {
        "closed_trades": len(sells),
        "win_rate": round(len(wins) / len(sells), 3) if sells else 0.0,
        "total_pnl_sol": round(sum(t.realized_pnl_sol or 0 for t in sells), 4),
        "best_sol": round(best, 4),
        "worst_sol": round(worst, 4),
        "wins": len(wins),
        "losses": len(losses),
        "curve": curve,
    }


def open_positions(db: Session, market=None) -> list[dict]:
    """Paper işlemlerden TÜRETİLMİŞ açık pozisyonlar (FIFO net).

    Bizim kopya hesabımızın token başına net açık miktarı ve maliyeti.
    `market` verilirse her açık token için CANLI fiyat çekilir ve gerçekleşmemiş
    PnL (SOL + %) hesaplanır — "şu an ne kadar artıda/eksideyiz". Canlı fiyat
    alınamazsa son analizdeki fiyata düşülür; o da yoksa PnL None döner.
    """
    trades = db.query(PaperTrade).order_by(PaperTrade.created_at.asc()).all()
    pos: dict[str, dict] = {}
    for t in trades:
        p = pos.setdefault(t.token_mint, {"qty": 0.0, "cost": 0.0, "wallet": t.wallet_address})
        if t.side == "buy":
            p["qty"] += t.token_amount
            p["cost"] += t.sol_amount
        else:  # sell
            if p["qty"] > 0:
                frac = min(1.0, t.token_amount / p["qty"]) if p["qty"] else 0
                p["cost"] -= p["cost"] * frac
                p["qty"] -= t.token_amount
                if p["qty"] < 1e-9:
                    p["qty"] = 0.0
                    p["cost"] = 0.0
    out = []
    for mint, p in pos.items():
        if p["qty"] <= 1e-9:
            continue
        price = 0.0
        liq_sol = 0.0
        if market is not None:
            try:
                md = market.get_token_market(mint)
                if md and getattr(md, "ok", False) and getattr(md, "price_sol", None):
                    price = float(md.price_sol)
                    # likiditeyi SOL'a çevir (gerçekçi çıkış tavanı için)
                    pu, lu = getattr(md, "price_usd", None), getattr(md, "liquidity_usd", None)
                    if price > 0 and pu and lu:
                        sol_usd = float(pu) / price
                        if sol_usd > 0:
                            liq_sol = float(lu) / sol_usd
            except Exception:  # noqa: BLE001 — canlı fiyat alınamazsa cache'e düş
                price = 0.0
        if not price:
            token = db.query(Token).filter(Token.mint == mint).first()
            price = float((token.metrics or {}).get("price_sol", 0.0)) if token else 0.0
        qty, cost = p["qty"], p["cost"]
        avg_cost = (cost / qty) if qty else 0.0
        value = (qty * price) if price else None
        # GERÇEKÇİLİK TAVANI: bir pozisyonun değeri havuzdan çıkarılabilecek SOL'dan
        # (likidite) fazla olamaz. Bozuk giriş (parse glitch) imkânsız PnL üretirse
        # burada sınırlanır ve "suspicious" işaretlenir.
        suspicious = False
        if value is not None and liq_sol > 0 and value > liq_sol:
            value = liq_sol
            suspicious = True
        unreal = (value - cost) if value is not None else None
        unreal_pct = (unreal / cost) if (unreal is not None and cost > 0) else None
        out.append({
            "token_mint": mint,
            "wallet_address": p["wallet"],
            "qty": round(qty, 2),
            "cost_sol": round(cost, 4),
            "avg_cost_sol": avg_cost,
            "current_price_sol": price or None,
            "current_value_sol": round(value, 4) if value is not None else None,
            "unrealized_pnl_sol": round(unreal, 4) if unreal is not None else None,
            "unrealized_pnl_pct": round(unreal_pct, 4) if unreal_pct is not None else None,
            "suspicious": suspicious,
        })
    # En çok zararda olanlar üstte (dikkat gereken pozisyonlar önce)
    out.sort(key=lambda r: (r["unrealized_pnl_sol"] if r["unrealized_pnl_sol"] is not None else 0.0))
    return out


def trading_summary(db: Session) -> dict:
    """Bugünkü harcama/zarar/PnL ve açık pozisyon özeti."""
    today = datetime.now(timezone.utc).date()
    start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    today_trades = db.query(PaperTrade).filter(PaperTrade.created_at >= start).all()
    spent = sum(t.sol_amount for t in today_trades if t.side == "buy")
    realized = sum(t.realized_pnl_sol or 0 for t in today_trades if t.side == "sell")
    loss = sum(-(t.realized_pnl_sol or 0) for t in today_trades if (t.realized_pnl_sol or 0) < 0)
    positions = open_positions(db)
    exposure = sum(p["cost_sol"] for p in positions)
    return {
        "today_spent_sol": round(spent, 4),
        "today_realized_pnl_sol": round(realized, 4),
        "today_loss_sol": round(loss, 4),
        "open_positions": len(positions),
        "open_exposure_sol": round(exposure, 4),
    }
