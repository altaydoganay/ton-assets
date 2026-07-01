"""Panel istatistikleri: genel bakış, keşif hunisi, performans, pozisyonlar.

Tüm metrikler veritabanından TÜRETİLİR (süreçler arası bellek durumuna bağlı
değil) — listener/worker/api hepsi aynı sonucu görür.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from .settings_service import get_setting

from ..models import (
    Alert,
    LiveTrade,
    PaperTrade,
    Token,
    TokenStatus,
    Wallet,
    WalletStatus,
)

MAX_DISPLAY_VALUE_MULTIPLIER = 20.0


def _stats_baseline(db: Session):
    raw = get_setting(db, "stats_baseline") or {}
    value = raw.get("all")
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None


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

    baseline = _stats_baseline(db)
    paper_q = db.query(func.coalesce(func.sum(PaperTrade.realized_pnl_sol), 0.0))
    live_q = db.query(func.coalesce(func.sum(LiveTrade.realized_pnl_sol), 0.0)).filter(LiveTrade.status != "failed")
    if baseline is not None:
        paper_q = paper_q.filter(PaperTrade.created_at >= baseline)
        live_q = live_q.filter(LiveTrade.created_at >= baseline)
    paper_pnl = paper_q.scalar() or 0.0
    live_pnl = live_q.scalar() or 0.0

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
    q = db.query(PaperTrade)
    baseline = _stats_baseline(db)
    if baseline is not None:
        q = q.filter(PaperTrade.created_at >= baseline)
    trades = q.order_by(PaperTrade.created_at.asc()).all()
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
    """Paper + live işlemlerden TÜRETİLMİŞ açık pozisyonlar (FIFO net)."""
    pos: dict[str, dict] = {}

    def _bucket(mode: str, mint: str, wallet: str):
        return pos.setdefault(f"{mode}:{mint}", {
            "mode": mode,
            "token_mint": mint,
            "qty": 0.0,
            "cost": 0.0,          # fee dahil maliyet
            "notional": 0.0,      # fee hariç, gerçekleşen giriş fiyatı * miktar
            "fees": 0.0,
            "slippage_weight": 0.0,
            "buy_count": 0,
            "wallet": wallet,
            "first_buy": None,
            "last_buy": None,
        })

    for t in db.query(PaperTrade).order_by(PaperTrade.created_at.asc()).all():
        p = _bucket("paper", t.token_mint, t.wallet_address)
        if t.side == "buy":
            qty_add = float(t.token_amount or 0)
            p["qty"] += qty_add
            p["cost"] += float(t.sol_amount or 0)
            p["notional"] += qty_add * float(t.price_sol or 0)
            p["fees"] += float(t.fee_sol or 0)
            p["slippage_weight"] += float(t.slippage_est or 0) * qty_add
            p["buy_count"] += 1
            if p.get("first_buy") is None:
                p["first_buy"] = t.created_at
            p["last_buy"] = t.created_at
        elif p["qty"] > 0:
            frac = min(1.0, t.token_amount / p["qty"]) if p["qty"] else 0
            p["cost"] -= p["cost"] * frac
            p["notional"] -= p["notional"] * frac
            p["fees"] -= p["fees"] * frac
            p["slippage_weight"] -= p["slippage_weight"] * frac
            p["qty"] -= t.token_amount
            if p["qty"] < 1e-9:
                p["qty"] = 0.0
                p["cost"] = 0.0
                p["notional"] = 0.0
                p["fees"] = 0.0
                p["slippage_weight"] = 0.0

    live_rows = (
        db.query(LiveTrade)
        .filter(LiveTrade.status != "failed")
        .order_by(LiveTrade.created_at.asc())
        .all()
    )
    for t in live_rows:
        p = _bucket("live", t.token_mint, t.wallet_address)
        if t.side == "buy":
            qty_add = float(t.token_amount or 0)
            p["qty"] += qty_add
            p["cost"] += float(t.sol_amount or 0)
            p["notional"] += qty_add * float(t.price_sol or 0)
            p["fees"] += float(t.fee_sol or 0)
            p["buy_count"] += 1
            if p.get("first_buy") is None:
                p["first_buy"] = t.created_at
            p["last_buy"] = t.created_at
        elif p["qty"] > 0:
            frac = min(1.0, t.token_amount / p["qty"]) if p["qty"] else 0
            p["cost"] -= p["cost"] * frac
            p["notional"] -= p["notional"] * frac
            p["fees"] -= p["fees"] * frac
            p["slippage_weight"] -= p["slippage_weight"] * frac
            p["qty"] -= t.token_amount
            if p["qty"] < 1e-9:
                p["qty"] = 0.0
                p["cost"] = 0.0
                p["notional"] = 0.0
                p["fees"] = 0.0
                p["slippage_weight"] = 0.0

    out = []
    for key, p in pos.items():
        if p["qty"] <= 1e-9:
            continue
        mint = p["token_mint"]
        token = db.query(Token).filter(Token.mint == mint).first()
        tm = (token.metrics or {}) if token else {}
        price = 0.0
        liq_sol = 0.0
        market_source = None
        market_as_of = datetime.now(timezone.utc).isoformat()
        market_cap_usd = None
        fdv_usd = None
        volume_24h_usd = None
        price_usd = None
        pair_created_at = None
        pair_url = None
        token_name = token.name if token else None
        token_symbol = token.symbol if token else None
        token_image = tm.get("image") or tm.get("image_url") or tm.get("logo")
        if market is not None:
            try:
                md = market.get_token_market(mint)
                if md and getattr(md, "ok", False):
                    market_source = getattr(md, "source", None)
                    token_name = getattr(md, "name", None) or token_name
                    token_symbol = getattr(md, "symbol", None) or token_symbol
                    token_image = getattr(md, "image_url", None) or token_image
                    pair_url = getattr(md, "pair_url", None)
                    market_cap_usd = getattr(md, "market_cap_usd", None)
                    fdv_usd = getattr(md, "fdv_usd", None)
                    volume_24h_usd = getattr(md, "volume_24h_usd", None)
                    price_usd = getattr(md, "price_usd", None)
                    pair_created_at = getattr(md, "pair_created_at", None)
                    if getattr(md, "price_sol", None):
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
            price = float(tm.get("price_sol", 0.0)) if token else 0.0
            market_source = market_source or ("token-cache" if price else None)
            price_usd = price_usd or tm.get("price_usd")
            market_cap_usd = market_cap_usd or tm.get("market_cap_usd")
            volume_24h_usd = volume_24h_usd or tm.get("volume_24h_usd")
            pair_created_at = pair_created_at or tm.get("pair_created_at")
        qty, cost = p["qty"], p["cost"]
        avg_exec_price = (p.get("notional", 0.0) / qty) if qty and p.get("notional", 0.0) > 0 else 0.0
        avg_cost = (cost / qty) if qty else 0.0
        fee_drag_pct = ((avg_cost / avg_exec_price) - 1.0) if avg_exec_price > 0 else None
        market_move_pct = ((price / avg_exec_price) - 1.0) if (price and avg_exec_price > 0) else None
        value = (qty * price) if price else None
        # GERÇEKÇİLİK TAVANI: bir pozisyonun değeri havuzdan çıkarılabilecek SOL'dan
        # (likidite) fazla olamaz. Bozuk giriş (parse glitch) imkânsız PnL üretirse
        # burada sınırlanır ve "suspicious" işaretlenir.
        suspicious = False
        suspicious_reason = None
        if value is not None and liq_sol > 0 and value > liq_sol:
            value = liq_sol
            suspicious = True
            suspicious_reason = "value_capped_by_liquidity"
        if value is not None and cost > 0 and value > cost * MAX_DISPLAY_VALUE_MULTIPLIER:
            # Bu genelde giriş fiyatı parse hatasıdır: paper motoru çok fazla token
            # almış gibi hesaplar ve canlı fiyatla imkansız açık PnL üretir. Açık
            # PnL'i gerçek kâr gibi göstermeyip konservatif olarak bilinmiyor yap.
            value = None
            suspicious = True
            suspicious_reason = "unrealistic_unrealized_pnl"
        unreal = (value - cost) if value is not None else None
        unreal_pct = (unreal / cost) if (unreal is not None and cost > 0) else None
        out.append({
            "position_id": key,
            "mode": p["mode"],
            "estimated": p["mode"] == "live",
            "estimation_note": (
                "Canlı PnL PumpPortal fill/on-chain reconcile yoksa tahmindir; "
                "gerçek cüzdan bakiyesi referanstır."
                if p["mode"] == "live" else None
            ),
            "token_mint": mint,
            "wallet_address": p["wallet"],
            "first_buy": p.get("first_buy"),
            "opened_at": p.get("first_buy"),
            "age_minutes": (
                round((datetime.now(timezone.utc) - (p.get("first_buy") if (p.get("first_buy") and p.get("first_buy").tzinfo) else (p.get("first_buy").replace(tzinfo=timezone.utc) if p.get("first_buy") else datetime.now(timezone.utc)))).total_seconds() / 60.0, 1)
                if p.get("first_buy") else None
            ),
            "token_name": token_name,
            "token_symbol": token_symbol,
            "token_image": token_image,
            "pair_url": pair_url,
            "price_source": market_source,
            "price_as_of": market_as_of,
            "price_usd": price_usd,
            "market_cap_usd": market_cap_usd,
            "fdv_usd": fdv_usd,
            "volume_24h_usd": volume_24h_usd,
            "liquidity_sol": round(liq_sol, 4) if liq_sol else None,
            "pair_created_at": pair_created_at,
            "last_buy": p.get("last_buy"),
            "buy_count": p.get("buy_count", 0),
            "qty": round(qty, 2),
            "qty_raw": qty,
            "cost_sol": round(cost, 4),
            "avg_entry_price_sol": avg_exec_price or None,
            "effective_entry_price_sol": avg_cost or None,
            "avg_cost_sol": avg_cost,
            "fee_sol_open": round(float(p.get("fees", 0.0)), 6),
            "avg_slippage_est": round((float(p.get("slippage_weight", 0.0)) / qty), 6) if qty and p.get("slippage_weight", 0.0) else 0.0,
            "fee_drag_pct": round(fee_drag_pct, 4) if fee_drag_pct is not None else None,
            "market_move_pct": round(market_move_pct, 4) if market_move_pct is not None else None,
            "current_price_sol": price or None,
            "current_value_sol": round(value, 4) if value is not None else None,
            "unrealized_pnl_sol": round(unreal, 4) if unreal is not None else None,
            "unrealized_pnl_pct": round(unreal_pct, 4) if unreal_pct is not None else None,
            "pnl_explainer": (
                "PnL; mevcut fiyatın giriş fiyatına göre hareketinden ayrı olarak paper priority fee ve slippage maliyetini de içerir."
                if p["mode"] == "paper" else
                "Canlı PnL tahminidir; gerçek fill ve cüzdan bakiyesiyle doğrulanmalıdır."
            ),
            "suspicious": suspicious,
            "suspicious_reason": suspicious_reason,
        })
    # En çok zararda olanlar üstte (dikkat gereken pozisyonlar önce)
    out.sort(key=lambda r: (r["unrealized_pnl_sol"] if r["unrealized_pnl_sol"] is not None else 0.0))
    return out


def trading_summary(db: Session) -> dict:
    """Bugünkü harcama/zarar/PnL ve açık pozisyon özeti.

    Paper PnL kesin simülasyon sonucudur. LiveTrade PnL ise PumpPortal Lightning
    kesin fill detayı dönmediği için yalnızca tahmindir; gerçek cüzdan bakiyesiyle
    birebir eşleşmesi beklenmez. Bu yüzden ayrı alan olarak döner.
    """
    today = datetime.now(timezone.utc).date()
    start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    baseline = _stats_baseline(db)
    if baseline is not None and baseline > start:
        start = baseline
    today_paper = db.query(PaperTrade).filter(PaperTrade.created_at >= start).all()
    today_live = (
        db.query(LiveTrade)
        .filter(LiveTrade.created_at >= start, LiveTrade.status != "failed")
        .all()
    )
    paper_spent = sum(float(t.sol_amount or 0) for t in today_paper if t.side == "buy")
    paper_realized = sum(float(t.realized_pnl_sol or 0) for t in today_paper if t.side == "sell")
    paper_loss = sum(-(float(t.realized_pnl_sol or 0)) for t in today_paper if (t.realized_pnl_sol or 0) < 0)
    live_spent = sum(float(t.sol_amount or 0) for t in today_live if t.side == "buy")
    live_estimated = sum(float(t.realized_pnl_sol or 0) for t in today_live if t.side == "sell")
    positions = open_positions(db)
    exposure = sum(p["cost_sol"] for p in positions)
    return {
        "today_spent_sol": round(paper_spent + live_spent, 4),
        "today_paper_spent_sol": round(paper_spent, 4),
        "today_live_spent_sol": round(live_spent, 4),
        "today_realized_pnl_sol": round(paper_realized, 4),
        "today_live_estimated_pnl_sol": round(live_estimated, 4),
        "today_loss_sol": round(paper_loss, 4),
        "open_positions": len(positions),
        "open_exposure_sol": round(exposure, 4),
    }
