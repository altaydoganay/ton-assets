"""Olay akışı, bildirimler, işlemler, pozisyonlar, loglar, ayarlar, sağlık."""
from __future__ import annotations

from datetime import datetime, timezone

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

VERSION = f"BUILD {settings.app_build} — {settings.app_build_label}"


STATS_BASELINE_KEY = "stats_baseline"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None


def _paper_scope_filter(query, scope: str):
    scope = (scope or "all").lower()
    if scope == "ai":
        return query.filter(PaperTrade.wallet_address == "AI_TRADE")
    if scope == "copy":
        return query.filter(PaperTrade.wallet_address != "AI_TRADE")
    return query


def _paper_counts(db: Session, scope: str, since=None) -> dict:
    q = _paper_scope_filter(db.query(PaperTrade), scope)
    if since is not None:
        q = q.filter(PaperTrade.created_at >= since)
    rows = q.all()
    buys = [r for r in rows if r.side == "buy"]
    sells = [r for r in rows if r.side == "sell"]
    open_qty: dict[str, float] = {}
    for r in rows:
        delta = float(r.token_amount or 0.0)
        if r.side == "buy":
            open_qty[r.token_mint] = open_qty.get(r.token_mint, 0.0) + delta
        else:
            open_qty[r.token_mint] = open_qty.get(r.token_mint, 0.0) - delta
    return {
        "rows": len(rows),
        "buys": len(buys),
        "sells": len(sells),
        "open_positions_est": sum(1 for v in open_qty.values() if v > 1e-9),
        "spent_sol": round(sum(float(r.sol_amount or 0.0) for r in buys), 6),
        "realized_pnl_sol": round(sum(float(r.realized_pnl_sol or 0.0) for r in sells), 6),
    }

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
    return {"ok": True, "close_positions": False,
            "detail": "Yeni işlemler durduruldu. Açık pozisyonlar otomatik kapatılmadı; manuel/panelden kapatılmalı."}


@trading_router.post("/resume")
def resume_trading(db: Session = Depends(get_db)):
    """Acil durdurmayı kaldırır ve motoru yeniden açar (atomik + denetim kaydı).

    Emergency-stop'un tersi: `emergency_stop=False`, `enabled=True`. Ana ekrandaki
    kill-switch'in 'Devam Et' aksiyonu bunu çağırır."""
    risk = settings_service.get_setting(db, "risk")
    risk["emergency_stop"] = False
    risk["enabled"] = True
    settings_service.set_setting(db, "risk", risk)
    db.add(AuditLog(level="info", category="trading",
                    message="İşlem motoru yeniden açıldı (acil durdurma kaldırıldı)",
                    context={}))
    db.commit()
    return {"ok": True, "enabled": True, "emergency_stop": False}


@trading_router.get("/reset-status")
def reset_status(scope: str = Query("ai", pattern="^(all|ai|copy)$"), db: Session = Depends(get_db)):
    """Ölçüm dönemi ve paper kayıt özetini döndürür.

    Baseline istatistik sıfırlama gerçek trade kayıtlarını silmez; panellerin
    anlamlı bir "yeni dönem"den itibaren okunmasını sağlar. Hard reset ise
    ayrıca paper kayıtlarını temizler.
    """
    baseline = settings_service.get_setting(db, STATS_BASELINE_KEY) or {}
    scope = scope.lower()
    baseline_iso = baseline.get(scope) or baseline.get("all")
    since = _parse_dt(baseline_iso)
    return {
        "scope": scope,
        "baseline_at": baseline_iso,
        "since_counts": _paper_counts(db, scope, since=since),
        "total_counts": _paper_counts(db, scope, since=None),
        "note": "baseline yalnızca raporlamayı sıfırlar; clear_paper=true verilmedikçe kayıt silmez.",
    }


@trading_router.post("/reset-stats")
def reset_stats(
    scope: str = Query("ai", pattern="^(all|ai|copy)$"),
    clear_paper: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Yeni ölçüm dönemi başlatır; istenirse paper alım/satım kayıtlarını da temizler.

    Canlı trade kayıtlarına ve gerçek cüzdana dokunmaz. Bu endpoint özellikle
    çok sayıda güncellemeden sonra AI/COPY performansını temiz okumak için var.
    """
    import time as _t

    scope = scope.lower()
    now_iso = _now_iso()
    baseline = dict(settings_service.get_setting(db, STATS_BASELINE_KEY) or {})
    baseline[scope] = now_iso
    baseline["last_scope"] = scope
    baseline["last_reset_at"] = now_iso
    settings_service.set_setting(db, STATS_BASELINE_KEY, baseline)

    deleted = 0
    deleted_mints: set[str] = set()
    if clear_paper:
        rows = _paper_scope_filter(db.query(PaperTrade), scope).all()
        deleted_mints = {r.token_mint for r in rows}
        deleted = len(rows)
        for r in rows:
            db.delete(r)
        # Sadece temizlenen paper tokenlarının trailing/peak durumunu sil.
        # Tam scope=all ise zaten tüm position_state boşalır.
        state = dict(settings_service.get_setting(db, "position_state") or {})
        if scope == "all":
            state = {}
        else:
            keys_to_drop = set()
            for mint in deleted_mints:
                keys_to_drop.add(mint)
                keys_to_drop.add(f"paper:{mint}")
            state = {k: v for k, v in state.items() if k not in keys_to_drop}
        settings_service.set_setting(db, "position_state", state)
        settings_service.set_setting(db, "paper_reset", {"token": str(_t.time()), "scope": scope})
        try:
            from ..services.live_flow import reset_engine
            reset_engine()
        except Exception:  # noqa: BLE001
            pass

    db.add(AuditLog(
        level="warning",
        category="trading",
        message=(
            f"Ölçüm dönemi sıfırlandı: {scope}"
            + (f" · {deleted} paper kayıt temizlendi" if clear_paper else " · kayıtlar saklandı")
        ),
        context={"scope": scope, "clear_paper": clear_paper, "deleted_paper_rows": deleted, "baseline_at": now_iso},
    ))
    db.commit()
    return {
        "ok": True,
        "scope": scope,
        "baseline_at": now_iso,
        "clear_paper": clear_paper,
        "deleted_paper_rows": deleted,
        "deleted_tokens": len(deleted_mints),
        "status": reset_status(scope=scope, db=db),
    }


@trading_router.post("/reset-paper")
def reset_paper(scope: str = Query("all", pattern="^(all|ai|copy)$"), db: Session = Depends(get_db)):
    """Geriye uyumluluk endpoint'i. Varsayılan olarak tüm paper işlemleri temizler.

    Yeni arayüz /reset-stats kullanır; bu endpoint eski buton/komutlar bozulmasın
    diye korunur.
    """
    return reset_stats(scope=scope, clear_paper=True, db=db)


@trading_router.get("/decisions")
def trade_decisions(strategy: str = Query("ai", pattern="^(ai|copy)$"), limit: int = Query(100, le=500), db: Session = Depends(get_db)):
    """Sade karar akışı. Teknik logları kullanıcı ekranları için okunur hale getirir.

    strategy=ai  -> AI Trade neden aldı / neden almadı
    strategy=copy -> Copy Trade neden aldı / neden almadı
    """
    rows = (
        db.query(AuditLog)
        .filter(AuditLog.category.in_(["trading", "leader_watch"]))
        .order_by(AuditLog.id.desc())
        .limit(1500)
        .all()
    )
    out = []
    for r in rows:
        ctx = r.context or {}
        msg = r.message or ""
        ctx_strategy = str(ctx.get("strategy") or "")
        is_ai = ctx_strategy == "ai" or "AI" in msg or ctx.get("wallet") == "AI_TRADE"
        if strategy == "ai" and not is_ai:
            continue
        if strategy == "copy" and is_ai:
            continue
        low = msg.lower()
        if "işlem açıldı" in low:
            action = "opened"
            title = "İşlem açıldı"
        elif "engellendi" in low or "işlem yok" in low or "blok" in low or "reddedildi" in low:
            action = "blocked"
            title = "İşlem açılmadı"
        elif "sattı" in low or "kapat" in low:
            action = "exit"
            title = "Çıkış / kapatma"
        else:
            action = "info"
            title = "Bilgi"
        reason = ctx.get("reason") or ctx.get("blocked") or ctx.get("trade_blocked")
        if isinstance(reason, list):
            reason = ", ".join(str(x) for x in reason)
        out.append({
            "id": r.id,
            "level": r.level,
            "category": r.category,
            "action": action,
            "title": title,
            "message": msg,
            "reason": reason or msg,
            "token": ctx.get("token"),
            "wallet": ctx.get("wallet"),
            "token_score": ctx.get("token_score"),
            "wallet_score": ctx.get("wallet_score"),
            "mode": ctx.get("mode"),
            "signature": ctx.get("signature"),
            "created_at": r.created_at,
            "context": ctx,
        })
        if len(out) >= limit:
            break
    return out


@trading_router.post("/ai-exit/run")
def ai_exit_run(db: Session = Depends(get_db)):
    """AI paper pozisyonlarında TP/SL/trailing/max-hold çıkışını hemen çalıştır.

    Normalde Celery beat bunu arka planda periyodik yapar. Panelden teşhis ve
    acil kontrol için manuel endpoint. Gerçek para işlemi yapmaz; yalnızca
    AI/Paper açık pozisyonlarını kapatır.
    """
    from ..adapters.registry import build_market_provider
    from ..services.position_manager import manage_positions
    try:
        closed = manage_positions(db, build_market_provider())
        return {"ok": True, "closed": len(closed), "details": closed}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"AI çıkış kontrolü çalışamadı: {type(exc).__name__}: {str(exc)[:240]}")


@trading_router.get("/ai-exit/status")
def ai_exit_status(db: Session = Depends(get_db)):
    """AI paper çıkış yöneticisinin okunur durumu."""
    from datetime import datetime, timezone
    from ..services.stats_service import open_positions as _open_positions

    risk = settings_service.get_setting(db, "risk")
    rows = [p for p in _open_positions(db) if p.get("mode") == "paper" and p.get("wallet_address") == "AI_TRADE"]
    last_exit = (db.query(AuditLog)
                 .filter(AuditLog.category == "trading", AuditLog.message.ilike("%kapatıldı%"))
                 .order_by(AuditLog.id.desc()).first())
    now = datetime.now(timezone.utc)
    return {
        "enabled": (bool(risk.get("enabled", True))
                    and str(risk.get("mode", "paper")) == "paper"
                    and str(risk.get("strategy_mode", "copy") or "copy") == "ai"),
        "strategy_mode": str(risk.get("strategy_mode", "copy") or "copy"),
        "open_ai_paper_positions": len(rows),
        "take_profit_pct": risk.get("take_profit_pct"),
        "stop_loss_pct": risk.get("stop_loss_pct"),
        "trailing_stop_pct": risk.get("trailing_stop_pct"),
        "trail_activate_pct": risk.get("trail_activate_pct"),
        "max_hold_minutes": risk.get("max_hold_minutes"),
        "oldest_age_minutes": max([float(p.get("age_minutes") or 0) for p in rows], default=0),
        "positions": rows[:20],
        "last_exit_log": {
            "message": last_exit.message,
            "created_at": last_exit.created_at,
            "context": last_exit.context,
        } if last_exit else None,
        "server_time": now.isoformat(),
    }


@trading_router.get("/ai-center")
def ai_center(minutes: int = Query(60, ge=5, le=1440), limit: int = Query(50, ge=5, le=200), db: Session = Depends(get_db)):
    """AI Trade Karar Merkezi.

    AI motorunun son kararlarını, neden almadığını, paper sonuçlarını, çıkış
    sebeplerini ve okunur önerileri tek JSON içinde verir. Log ekranındaki teknik
    gürültüyü günlük kullanıma uygun özetler.
    """
    from ..services.ai_decision_center import ai_decision_center
    return ai_decision_center(db, minutes=minutes, limit=limit)



def _norm_decision_text(text: str | None) -> str:
    table = str.maketrans({
        "İ": "i", "I": "i", "ı": "i",
        "Ş": "s", "ş": "s", "Ğ": "g", "ğ": "g",
        "Ü": "u", "ü": "u", "Ö": "o", "ö": "o",
        "Ç": "c", "ç": "c",
    })
    return str(text or "").translate(table).lower()


@trading_router.get("/decision-funnel")
def decision_funnel(strategy: str = Query("ai", pattern="^(ai|copy)$"), minutes: int = Query(60, ge=5, le=1440), db: Session = Depends(get_db)):
    """Önemli karar hunisi: son N dakikada neden işlem açıldı/açılmadı.

    Log kalabalığını tek ekranda özetlemek için kullanılır. Özellikle AI modunda
    "neden almadı" sorusunu cevaplar.
    """
    from collections import Counter
    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    rows = (db.query(AuditLog)
            .filter(AuditLog.category == "trading", AuditLog.created_at >= cutoff)
            .order_by(AuditLog.id.desc())
            .limit(5000).all())
    reasons: Counter[str] = Counter()
    opened = blocked = info = 0
    samples = []
    for r in rows:
        ctx = r.context or {}
        msg = r.message or ""
        ctx_strategy = str(ctx.get("strategy") or "")
        is_ai = ctx_strategy == "ai" or ctx.get("wallet") == "AI_TRADE" or "AI" in msg
        if strategy == "ai" and not is_ai:
            continue
        if strategy == "copy" and is_ai:
            continue
        low = _norm_decision_text(msg)
        if ctx.get("opened_reason") or "islem acildi" in low:
            opened += 1
            bucket = "İşlem açıldı"
        elif ctx.get("blocked") or ctx.get("trade_blocked") or any(x in low for x in ("almadi", "engellendi", "blok", "islem yok", "reddedildi", "skip", "skipped")):
            blocked += 1
            raw = ctx.get("reason") or ctx.get("blocked") or ctx.get("trade_blocked") or msg
            if isinstance(raw, list):
                raw = raw[0] if raw else "Bilinmeyen"
            bucket = str(raw or "Bilinmeyen")[:120]
            reasons[bucket] += 1
        else:
            info += 1
            bucket = "Bilgi / diğer"
        if len(samples) < 12:
            samples.append({
                "id": r.id, "message": msg, "reason": bucket, "token": ctx.get("token"),
                "score": ctx.get("token_score"), "created_at": r.created_at,
            })
    total = opened + blocked + info
    return {
        "strategy": strategy, "minutes": minutes, "total": total,
        "opened": opened, "blocked": blocked, "info": info,
        "top_reasons": [{"reason": k, "count": v} for k, v in reasons.most_common(12)],
        "samples": samples,
    }


@trading_router.get("/mode-status")
def mode_status(db: Session = Depends(get_db)):
    risk = settings_service.get_setting(db, "risk")
    mode = str(risk.get("strategy_mode", "copy") or "copy")
    return {
        "strategy_mode": "ai" if mode == "ai" else "copy",
        "copy_workers_active": mode != "ai",
        "ai_workers_active": mode == "ai",
        "message": (
            "AI Trade aktif: copy cüzdan arama/izleme/leader-watch durur."
            if mode == "ai" else
            "Copy Trade aktif: AI token motoru işlem üretmez."
        ),
    }


@trading_router.get("/copy-performance")
def copy_performance(include_blocked: bool = True, db: Session = Depends(get_db)):
    """Cüzdan-bazlı KOPYA performansı: bizim paper sonuçlarımıza göre her takip
    (ve engellenen) cüzdanın PnL'i, kazanç/kayıp, ardışık zarar."""
    from ..services.copy_performance import tracked_copy_stats
    return tracked_copy_stats(db, include_blocked=include_blocked)


@trading_router.get("/token-performance")
def token_performance(db: Session = Depends(get_db)):
    """BİZİM token bazlı sonucumuz: hangi token kâr/zarar getirdi (paper)."""
    from ..services.copy_performance import token_copy_stats
    return token_copy_stats(db)


@trading_router.post("/test-run")
def test_run(db: Session = Depends(get_db)):
    """ANINDA teşhis. Copy modunda takip cüzdanı test edilir. AI modunda copy
    teşhisi çalışmaz; AI kararları canlı token akışından ve karar hunisinden izlenir."""
    risk = settings_service.get_setting(db, "risk")
    if str(risk.get("strategy_mode", "copy") or "copy") == "ai":
        return {"ok": False, "reason": "AI Trade aktif: copy test çalıştırılmaz. AI testi için canlı token akışını ve Neden Almadım hunisini izle.", "strategy_mode": "ai"}
    from ..adapters.registry import build_chain_provider, build_market_provider
    from ..services.wallet_watch import run_diagnostic_trade
    try:
        chain = build_chain_provider(throttle=False)
        return run_diagnostic_trade(db, chain, market=build_market_provider())
    except Exception as exc:  # noqa: BLE001 — her durumda JSON dön (CORS'lu)
        return {"ok": False, "reason": f"Test çalıştırılamadı: {type(exc).__name__}: {str(exc)[:200]}"}


@trading_router.post("/leader-watch/run")
def leader_watch_run(db: Session = Depends(get_db)):
    """Lider elde tutma bekçisini anında çalıştır. Açık copy pozisyonlarında
    kopyalanan lider tokenı artık taşımıyorsa pozisyonu kapatır."""
    from ..adapters.registry import build_chain_provider, build_market_provider
    from ..services.leader_hold_watch import run_leader_hold_watch
    try:
        chain = build_chain_provider(throttle=False)
        try:
            market = build_market_provider()
        except Exception:  # noqa: BLE001
            market = None
        return run_leader_hold_watch(db, chain, market=market)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Lider elde tutma kontrolü çalışamadı: {type(exc).__name__}: {str(exc)[:200]}")


@trading_router.get("/leader-watch/status")
def leader_watch_status(db: Session = Depends(get_db)):
    """Son lider elde tutma kontrol durumunu döndürür."""
    risk = settings_service.get_setting(db, "risk")
    state = settings_service.get_setting(db, "leader_hold_watch_state")
    last = (db.query(AuditLog).filter(AuditLog.category == "leader_watch")
            .order_by(AuditLog.id.desc()).first())
    return {
        "enabled": bool(risk.get("leader_hold_watch_enabled", True)),
        "grace_seconds": risk.get("leader_hold_grace_seconds"),
        "cooldown_seconds": risk.get("leader_hold_cooldown_seconds"),
        "exit_ratio": risk.get("leader_hold_exit_ratio"),
        "verify_own_balance": risk.get("leader_hold_verify_own_balance"),
        "own_zero_confirmations": risk.get("leader_hold_own_zero_confirmations"),
        "tracked_positions_in_state": len(state or {}),
        "last_log": {
            "message": last.message,
            "level": last.level,
            "created_at": last.created_at,
            "context": last.context,
        } if last else None,
    }


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
    old_value = settings_service.get_setting(db, key)
    value = settings_service.set_setting(db, key, body.value)
    ctx = {"key": key}
    if key == "risk":
        old_mode = str((old_value or {}).get("strategy_mode", "copy"))
        new_mode = str((value or {}).get("strategy_mode", "copy"))
        if old_mode != new_mode:
            ctx.update({"old_strategy_mode": old_mode, "new_strategy_mode": new_mode})
            try:
                from ..services.live_flow import reset_engine
                reset_engine()
            except Exception:  # noqa: BLE001
                pass
    db.add(AuditLog(level="info", category="settings", message=f"Ayar güncellendi: {key}", context=ctx))
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

    from ..services import provider_health
    providers = provider_health.snapshot()
    data_status = provider_health.overall_status()
    reliable = provider_health.market_data_reliable()

    # Genel durum: DB down ise 'degraded'; veri sağlayıcılar down ise de kullanıcı
    # bunu üst düzeyde görmeli (kötü veriyle işlem yapmama felsefesi).
    status = "ok"
    if not db_ok:
        status = "degraded"
    elif data_status == "down":
        status = "degraded"

    return HealthOut(
        status=status,
        database=db_ok,
        redis=redis_ok,
        chain_provider=settings.chain_provider,
        market_provider=settings.market_provider,
        trading_mode=settings.trading_mode,
        telegram_enabled=settings.telegram_enabled,
        version=VERSION,
        data_status=data_status,
        market_data_reliable=reliable,
        providers=providers,
    )


@health_router.get("/providers")
def providers_health():
    """Veri sağlayıcı sağlık dökümü (market + chain), panelde ayrı kart olarak
    gösterilir. Process ömürlü in-process kayıttan gelir."""
    from ..services import provider_health
    return {
        "data_status": provider_health.overall_status(),
        "market_data_reliable": provider_health.market_data_reliable(),
        "providers": provider_health.snapshot(),
    }
