"""İstatistik, kurulum/sağlık, profil, pozisyon yönetimi ve CSV dışa aktarma."""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditLog, PaperTrade, Token, Wallet
from ..services import stats_service
from ..services.setup_service import setup_status
from ..services.settings_service import RISK_PROFILES, apply_risk_profile

stats_router = APIRouter(prefix="/stats", tags=["stats"])
setup_router = APIRouter(prefix="/setup", tags=["setup"])
export_router = APIRouter(prefix="/export", tags=["export"])


@stats_router.get("/overview")
def overview(db: Session = Depends(get_db)):
    return stats_service.overview(db)


@stats_router.get("/timeseries")
def timeseries(days: int = Query(14, le=90), db: Session = Depends(get_db)):
    return stats_service.discovery_timeseries(db, days=days)


@stats_router.get("/performance")
def performance(db: Session = Depends(get_db)):
    return stats_service.performance(db)


@stats_router.get("/trading-summary")
def trading_summary(db: Session = Depends(get_db)):
    return stats_service.trading_summary(db)


@stats_router.get("/positions")
def positions(db: Session = Depends(get_db)):
    return stats_service.open_positions(db)


# --- Kurulum / sağlık ---
@setup_router.get("")
def setup(db: Session = Depends(get_db)):
    return setup_status(db)


# --- Risk profilleri ---
@setup_router.get("/risk-profiles")
def risk_profiles():
    return {"profiles": list(RISK_PROFILES.keys()), "presets": RISK_PROFILES}


@setup_router.post("/risk-profiles/{name}")
def apply_profile(name: str, db: Session = Depends(get_db)):
    try:
        value = apply_risk_profile(db, name)
    except KeyError:
        raise HTTPException(404, "Bilinmeyen profil")
    db.add(AuditLog(level="info", category="settings", message=f"Risk profili uygulandı: {name}"))
    db.commit()
    return {"applied": name, "risk": value}


# --- Manuel pozisyon kapatma (yalnızca paper) ---
@stats_router.post("/positions/{mint}/close")
def close_position(mint: str, price_sol: float = Query(...), db: Session = Depends(get_db)):
    """Açık paper pozisyonunu verilen fiyattan kapatır (manuel sat)."""
    positions = {p["token_mint"]: p for p in stats_service.open_positions(db)}
    p = positions.get(mint)
    if not p:
        raise HTTPException(404, "Açık paper pozisyonu yok")
    qty = p["qty"]
    proceeds = qty * price_sol
    pnl = proceeds - p["cost_sol"]
    row = PaperTrade(
        wallet_address=p["wallet_address"], token_mint=mint, side="sell",
        sol_amount=proceeds, token_amount=qty, price_sol=price_sol, fee_sol=0.0,
        realized_pnl_sol=pnl, is_open=False, reason="manuel kapatma (paper)",
    )
    db.add(row)
    db.add(AuditLog(level="info", category="trading", message=f"Paper pozisyon manuel kapatıldı: {mint}"))
    db.commit()
    return {"closed": mint, "qty": round(qty, 2), "realized_pnl_sol": round(pnl, 4)}


# --- CSV dışa aktarma ---
def _csv_response(rows: list[list], header: list[str], filename: str) -> StreamingResponse:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@export_router.get("/wallets.csv")
def export_wallets(db: Session = Depends(get_db)):
    rows = []
    for w in db.query(Wallet).order_by(Wallet.latest_score.desc().nullslast()).all():
        m = w.metrics or {}
        rows.append([
            w.address, w.label or "", w.status, w.latest_score or "",
            m.get("closed_positions", ""), m.get("win_rate", ""),
            m.get("realized_pnl_sol", ""), m.get("token_diversity", ""),
            ";".join(w.risk_flags or []),
        ])
    return _csv_response(
        rows,
        ["address", "label", "status", "score", "closed_positions", "win_rate",
         "realized_pnl_sol", "token_diversity", "risk_flags"],
        "wallets.csv",
    )


@export_router.get("/trades.csv")
def export_trades(db: Session = Depends(get_db)):
    rows = []
    for t in db.query(PaperTrade).order_by(PaperTrade.created_at.asc()).all():
        rows.append([
            t.created_at.isoformat() if t.created_at else "", t.wallet_address, t.token_mint,
            t.side, t.sol_amount, t.token_amount, t.price_sol, t.realized_pnl_sol,
        ])
    return _csv_response(
        rows,
        ["time", "leader_wallet", "token_mint", "side", "sol_amount", "token_amount",
         "price_sol", "realized_pnl_sol"],
        "paper_trades.csv",
    )
