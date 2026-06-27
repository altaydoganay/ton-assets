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
from ..services.settings_service import RISK_PROFILES, apply_risk_profile, set_runtime_flag

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


@setup_router.get("/live")
def live_setup(db: Session = Depends(get_db)):
    """Canlı işlem kurulum durumu (henüz aktif değilse de hazırlığı gösterir).
    Canlı yol = PumpPortal Lightning cüzdanı (api-key). Yerel keystore opsiyoneldir."""
    from ..config import settings as _s
    from ..services.settings_service import get_setting
    risk = get_setting(db, "risk")
    keystore_addr = None
    try:
        from ..security.keystore import Keystore
        ks = Keystore(_s.keystore_path)
        keystore_addr = ks.public_address() if ks.exists() else None
    except Exception:  # noqa: BLE001
        keystore_addr = None
    pumpportal = bool(_s.pumpportal_api_key)
    mode = risk.get("mode", "paper")
    live_confirmed = bool(risk.get("live_confirmed"))
    engine_on = bool(risk.get("enabled"))
    ready = pumpportal  # canlı için en azından PumpPortal anahtarı gerekir
    return {
        "trade_provider": _s.trade_provider,
        "pumpportal_key": pumpportal,
        "keystore_exists": keystore_addr is not None,
        "keystore_address": keystore_addr,
        "mode": mode,
        "engine_enabled": engine_on,
        "live_confirmed": live_confirmed,
        "is_live_now": engine_on and mode == "live" and live_confirmed,
        "ready_for_live": ready,
        "default_pool": _s.pumpportal_default_pool,
        "max_position_sol": risk.get("max_position_sol"),
        "max_daily_spend_sol": risk.get("max_daily_spend_sol"),
    }


@setup_router.post("/discovery")
def toggle_discovery(enabled: bool = Query(...), db: Session = Depends(get_db)):
    """Keşif akışını (pump.fun firehose) aç/kapat. Kapalıyken WS streaming kredisi
    (MB başına) durur; analiz mevcut aday backlog'u üzerinde devam eder. Dinleyici
    ~30 sn içinde uygular."""
    val = set_runtime_flag(db, "discovery_enabled", enabled)
    return {"discovery_enabled": bool(val.get("discovery_enabled"))}


@setup_router.post("/listener")
def toggle_listener(enabled: bool = Query(...), db: Session = Depends(get_db)):
    """Canlı WS dinleyicisini TÜMÜYLE aç/kapat (ana kredi anahtarı). Kapalıyken
    keşif firehose'u VE cüzdan-başına abonelikler durur → Helius streaming kredisi
    ≈0. Kopya işlem POLL ile sürer (her ~60 sn takip cüzdanları taranır). Dinleyici
    ~30 sn içinde uygular. "Canlı Olay Akışı" gerçek-zaman görünürlüğü için; kopya
    işlem için GEREKLİ DEĞİLDİR."""
    val = set_runtime_flag(db, "listener_enabled", enabled)
    db.add(AuditLog(level="info", category="settings",
                    message=f"Canlı dinleyici {'AÇILDI' if enabled else 'KAPATILDI (kredi koruması; kopya işlem POLL ile sürer)'}"))
    db.commit()
    return {"listener_enabled": bool(val.get("listener_enabled"))}


@setup_router.get("/backlog")
def backlog_status(db: Session = Depends(get_db)):
    """Keşif backlog'u: analiz bekleyen (yalnızca ADRES olarak elimizdeki) cüzdan
    sayısı + son toplu analiz özeti. Bu cüzdanların işlem geçmişi henüz ZİNCİRDEN
    çekilmedi; analiz Helius kredisi harcar (~10 kredi/cüzdan)."""
    from ..services.discovery import count_pending
    from ..services.settings_service import get_setting, get_runtime_flag
    pending = count_pending(db)
    return {
        "pending": pending,
        "est_credits": pending * 10,  # kaba tahmin: ~1 Enhanced isteği/cüzdan
        "last_drain": get_setting(db, "_meta_backlog_drain"),
        "autodrain": get_runtime_flag(db, "backlog_autodrain", False),
    }


@setup_router.post("/backlog/autodrain")
def toggle_autodrain(enabled: bool = Query(...), db: Session = Depends(get_db)):
    """Otomatik backlog analizi (sürekli, arka planda) aç/kapat. Açıkken her beat
    tikinde (~2 dk) zaman bütçesi kadar çok cüzdan analiz edilir → backlog hızlı
    ve GÖRÜNÜR şekilde erir. KREDİ HARCAR; bitince ya da kredi azalınca kapat.
    Beat tabanlı: deploy/restart'a dayanıklı (kaldığı yerden sürer)."""
    from ..services.settings_service import set_runtime_flag
    val = set_runtime_flag(db, "backlog_autodrain", enabled)
    db.add(AuditLog(level="info", category="discovery",
                    message=f"Otomatik backlog analizi {'AÇILDI' if enabled else 'KAPATILDI'}"))
    db.commit()
    return {"autodrain": bool(val.get("backlog_autodrain"))}


@setup_router.post("/backlog/analyze")
def analyze_backlog(count: int = Query(2000, ge=1, le=20000), db: Session = Depends(get_db)):
    """Backlog'tan `count` cüzdanı toplu analiz et (ingest + puanla). Arka planda
    (Celery) çalışır; HTTP hemen döner. İlerleme /setup/backlog'tan izlenir.
    KREDİ HARCAR: her cüzdan ~10 Helius kredisi. Kullanıcı miktarı kendi seçer."""
    from ..services.discovery import count_pending
    from ..workers.tasks import drain_backlog
    pending = count_pending(db)
    if pending == 0:
        return {"started": False, "pending": 0, "message": "Backlog boş — analiz bekleyen cüzdan yok."}
    target = min(count, pending)
    try:
        drain_backlog.delay(target=target)
        started = True
    except Exception as exc:  # noqa: BLE001 — worker/Redis yoksa açıklayıcı dön
        raise HTTPException(503, f"Arka plan işçisine ulaşılamadı (worker/Redis): {exc}")
    db.add(AuditLog(level="info", category="discovery",
                    message=f"Backlog analizi başlatıldı: {target} cüzdan (~{target*10} kredi)"))
    db.commit()
    return {"started": started, "target": target, "pending": pending, "est_credits": target * 10}


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
