"""Olay akışı, bildirimler, işlemler, pozisyonlar, loglar, ayarlar, sağlık."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db, engine
from ..models import (
    Alert,
    AuditLog,
    LiveTrade,
    PaperTrade,
    Position,
    Swap,
)
from ..schemas import (
    AlertOut,
    HealthOut,
    LiveTradeOut,
    PaperTradeOut,
    SettingIn,
    SwapOut,
)
from ..services import settings_service

VERSION = "0.1.0"

events_router = APIRouter(prefix="/events", tags=["events"])
alerts_router = APIRouter(prefix="/alerts", tags=["alerts"])
trading_router = APIRouter(prefix="/trading", tags=["trading"])
settings_router = APIRouter(prefix="/settings", tags=["settings"])
health_router = APIRouter(tags=["system"])
logs_router = APIRouter(prefix="/logs", tags=["logs"])


# --- Canlı olay akışı (son swap'lar) ---
@events_router.get("", response_model=list[SwapOut])
def recent_events(limit: int = Query(100, le=500), db: Session = Depends(get_db)):
    return db.query(Swap).order_by(Swap.block_time.desc()).limit(limit).all()


# --- Telegram bildirimleri ---
@alerts_router.get("", response_model=list[AlertOut])
def list_alerts(limit: int = Query(100, le=500), db: Session = Depends(get_db)):
    return db.query(Alert).order_by(Alert.created_at.desc()).limit(limit).all()


@alerts_router.post("/{alert_id}/resend")
def resend_alert(alert_id: int, db: Session = Depends(get_db)):
    """Gönderilememiş bir bildirimi yeniden gönder."""
    from datetime import datetime, timezone
    from ..notifications.telegram import TelegramNotifier

    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(404, "Bildirim bulunamadı")
    text = (alert.payload or {}).get("message", "")
    if not text:
        raise HTTPException(400, "Bildirim metni yok")
    sent = TelegramNotifier().send_text(text)
    alert.sent = sent
    if sent:
        alert.sent_at = datetime.now(timezone.utc)
    db.commit()
    return {"id": alert_id, "sent": sent}


# --- Paper trades ---
@trading_router.get("/paper", response_model=list[PaperTradeOut])
def paper_trades(limit: int = Query(200, le=1000), db: Session = Depends(get_db)):
    return db.query(PaperTrade).order_by(PaperTrade.created_at.desc()).limit(limit).all()


# --- Live trades ---
@trading_router.get("/live", response_model=list[LiveTradeOut])
def live_trades(limit: int = Query(200, le=1000), db: Session = Depends(get_db)):
    return db.query(LiveTrade).order_by(LiveTrade.created_at.desc()).limit(limit).all()


# --- Açık pozisyonlar (paper + live birleşik özet) ---
@trading_router.get("/positions")
def open_positions(db: Session = Depends(get_db)):
    rows = db.query(Position).filter(Position.is_open == True).all()  # noqa: E712
    return [
        {
            "wallet_address": p.wallet_address,
            "token_mint": p.token_mint,
            "qty_open": p.qty_open,
            "cost_basis_sol": p.cost_basis_sol,
            "unrealized_pnl_sol": p.unrealized_pnl_sol,
            "opened_at": p.opened_at,
        }
        for p in rows
    ]


# --- Acil durdurma ---
@trading_router.post("/emergency-stop")
def emergency_stop(close_positions: bool = False, db: Session = Depends(get_db)):
    risk = settings_service.get_setting(db, "risk")
    risk["emergency_stop"] = True
    risk["enabled"] = False
    settings_service.set_setting(db, "risk", risk)
    db.add(AuditLog(level="warning", category="trading",
                    message="Acil durdurma etkinleştirildi",
                    context={"close_positions": close_positions}))
    db.commit()
    return {"ok": True, "close_positions": close_positions,
            "detail": "Yeni işlemler durduruldu" + (" ve açık pozisyonlar kapatılacak" if close_positions else "")}


# --- Ayarlar ---
@settings_router.get("")
def get_all_settings(db: Session = Depends(get_db)):
    return settings_service.all_settings(db)


@settings_router.get("/{key}")
def get_one_setting(key: str, db: Session = Depends(get_db)):
    if key not in settings_service.DEFAULTS:
        raise HTTPException(404, "Bilinmeyen ayar anahtarı")
    return {"key": key, "value": settings_service.get_setting(db, key)}


@settings_router.put("/{key}")
def update_setting(key: str, body: SettingIn, db: Session = Depends(get_db)):
    if key not in settings_service.DEFAULTS:
        raise HTTPException(404, "Bilinmeyen ayar anahtarı")
    value = settings_service.set_setting(db, key, body.value)
    db.add(AuditLog(level="info", category="settings", message=f"Ayar güncellendi: {key}", context={"key": key}))
    db.commit()
    return {"key": key, "value": value}


# --- Loglar ---
@logs_router.get("")
def list_logs(level: str | None = None, category: str | None = None,
              limit: int = Query(200, le=1000), db: Session = Depends(get_db)):
    q = db.query(AuditLog)
    if level:
        q = q.filter(AuditLog.level == level)
    if category:
        q = q.filter(AuditLog.category == category)
    rows = q.order_by(AuditLog.created_at.desc()).limit(limit).all()
    return [
        {"id": r.id, "level": r.level, "category": r.category, "message": r.message,
         "context": r.context, "created_at": r.created_at}
        for r in rows
    ]


# --- Sağlık ---
@health_router.get("/health", response_model=HealthOut)
def health(db: Session = Depends(get_db)):
    db_ok = True
    try:
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    redis_ok: bool | None = None
    try:
        import redis  # type: ignore
        r = redis.from_url(settings.redis_url, socket_connect_timeout=1)
        redis_ok = bool(r.ping())
    except Exception:
        redis_ok = False

    return HealthOut(
        status="ok" if db_ok else "degraded",
        database=db_ok,
        redis=redis_ok,
        chain_provider=settings.chain_provider,
        market_provider=settings.market_provider,
        trading_mode=settings.trading_mode,
        telegram_enabled=settings.telegram_enabled,
        version=VERSION,
    )
