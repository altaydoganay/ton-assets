"""Kurulum & sağlık kontrol listesi — panelde tek ekranda yeşil/kırmızı."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Wallet
from .settings_service import get_heartbeat, get_setting


def _age_seconds(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds()
    except ValueError:
        return None


def setup_status(db: Session) -> dict:
    risk = get_setting(db, "risk")
    hb = get_heartbeat(db)
    hb_age = _age_seconds(hb)
    last_analyzed = db.query(func.max(Wallet.last_analyzed)).scalar()
    last_analyzed_age = _age_seconds(last_analyzed.isoformat()) if last_analyzed else None

    checks = [
        {
            "key": "helius", "label": "Helius API anahtarı",
            "ok": bool(settings.helius_api_key),
            "detail": "Tanımlı" if settings.helius_api_key else "Eksik — keşif/analiz için gerekli",
        },
        {
            "key": "listener", "label": "Canlı dinleyici (keşif/takip)",
            "ok": hb_age is not None and hb_age < 120,
            "detail": (f"Bağlı ({hb_age:.0f} sn önce)" if hb_age is not None and hb_age < 120
                       else "Sinyal yok — listener çalışmıyor olabilir"),
        },
        {
            "key": "provider", "label": "Dinleyici sağlayıcısı",
            "ok": settings.listener_provider == "helius",
            "detail": settings.listener_provider + (" (ücretsiz)" if settings.listener_provider == "helius" else " (SOL ücreti!)"),
        },
        {
            "key": "telegram", "label": "Telegram bildirimleri",
            "ok": bool(settings.telegram_enabled and settings.telegram_bot_token and settings.telegram_chat_id),
            "detail": "Açık" if settings.telegram_enabled else "Kapalı (opsiyonel)",
        },
        {
            "key": "analysis", "label": "Cüzdan puanlama (arka plan)",
            "ok": last_analyzed_age is not None and last_analyzed_age < 1800,
            "detail": (f"Son analiz {last_analyzed_age/60:.0f} dk önce" if last_analyzed_age is not None
                       else "Henüz analiz yapılmadı"),
        },
        {
            "key": "trading", "label": "İşlem motoru",
            "ok": True,
            "detail": f"Mod: {risk.get('mode','paper')} · Motor: {'açık' if risk.get('enabled') else 'kapalı'}"
                      + (" · CANLI ONAYLI" if risk.get('live_confirmed') else ""),
        },
    ]
    ok_count = sum(1 for c in checks if c["ok"])
    return {
        "checks": checks,
        "ok_count": ok_count,
        "total": len(checks),
        "healthy": all(c["ok"] for c in checks if c["key"] in ("helius", "listener")),
        "trading_mode": risk.get("mode", "paper"),
        "engine_enabled": bool(risk.get("enabled")),
        "live_confirmed": bool(risk.get("live_confirmed")),
        "token_gate": risk.get("token_gate", "balanced"),
        "build": settings.app_build,
        "build_label": settings.app_build_label,
        "discovery_enabled": settings.discovery_enabled,
        "discovery_max_lookups_per_min": settings.discovery_max_lookups_per_min,
    }
