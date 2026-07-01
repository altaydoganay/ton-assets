"""İstatistik, kurulum/sağlık, profil, pozisyon yönetimi ve CSV dışa aktarma."""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditLog, LiveTrade, PaperTrade, Token, Wallet
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
    """Açık pozisyonlar + CANLI gerçekleşmemiş PnL (anlık fiyatla)."""
    from ..adapters.registry import build_market_provider
    try:
        market = build_market_provider()
    except Exception:  # noqa: BLE001
        market = None
    return stats_service.open_positions(db, market=market)


@stats_router.get("/wallet-portfolio")
def wallet_portfolio(
    response: Response,
    address: str | None = Query(None),
    fresh: bool = Query(True),
    history_fallback: bool = Query(False),
    das_balance: bool = Query(False),
    _: int | None = Query(None, alias="_"),
):
    """Gerçek trading cüzdanı portföyü.

    Bu veri DB'deki trade kayıtlarından değil, doğrudan Solana RPC'den gelir.
    Paneldeki açık pozisyon defteriyle uyuşmazsa gerçek cüzdan snapshot'ı referans
    kabul edilmelidir.
    """
    from ..adapters.registry import build_chain_provider, build_market_provider
    from ..services.wallet_portfolio import fetch_wallet_portfolio, resolve_trading_wallet_address

    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    resolved, source = (address, "query") if address else resolve_trading_wallet_address()
    if not resolved:
        raise HTTPException(
            400,
            "Portföy adresi bulunamadı. .env içine TRADING_WALLET_ADDRESS=<public wallet> ekle veya ?address= ile ver.",
        )
    try:
        chain = build_chain_provider(throttle=False)
        try:
            market = build_market_provider()
        except Exception:  # noqa: BLE001
            market = None
        out = fetch_wallet_portfolio(
            chain,
            market,
            resolved,
            commitment="processed" if fresh else "confirmed",
            include_history_fallback=history_fallback,
            include_das_balances=das_balance,
        )
        out["address_source"] = source
        return out
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"Cüzdan portföyü okunamadı: {str(exc)[:180]}")


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
        "trading_wallet_address": _s.trading_wallet_address or keystore_addr,
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
        "autodrain": get_runtime_flag(db, "backlog_autodrain", True),
    }


@setup_router.post("/backlog/autodrain")
def toggle_autodrain(enabled: bool = Query(...), db: Session = Depends(get_db)):
    """Otomatik backlog analizi (sürekli, arka planda) aç/kapat. Açıkken her beat
    tikinde sık aralıklarla zaman bütçesi kadar çok cüzdan analiz edilir → backlog hızlı
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
    positions = {
        p["token_mint"]: p
        for p in stats_service.open_positions(db)
        if p.get("mode", "paper") == "paper"
    }
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


@stats_router.post("/positions/{mint}/sell")
def sell_position(mint: str, fraction: float = Query(1.0, gt=0.0, le=1.0),
                  db: Session = Depends(get_db)):
    """Açık paper/live pozisyonunun `fraction` (0-1) kadarını canlı fiyattan satar."""
    from ..adapters.registry import build_market_provider
    from ..services.settings_service import get_setting
    try:
        market = build_market_provider()
    except Exception:  # noqa: BLE001
        market = None
    matches = [x for x in stats_service.open_positions(db, market=market) if x["token_mint"] == mint]
    p = next((x for x in matches if x.get("mode") == "live"), None) or (matches[0] if matches else None)
    if not p:
        raise HTTPException(404, "Açık pozisyon yok")
    if p.get("suspicious_reason") == "unrealistic_unrealized_pnl":
        raise HTTPException(400, "Pozisyon fiyatı/verisi tutarsız görünüyor — otomatik satış durduruldu")
    price = p.get("current_price_sol")
    if not price:
        raise HTTPException(400, "Canlı fiyat alınamadı — aşağıdaki manuel fiyatla kapatmayı kullan")
    qty_sell = p["qty"] * fraction
    proceeds = qty_sell * float(price)
    cost_part = p["cost_sol"] * fraction
    pnl = proceeds - cost_part
    if p.get("mode") == "live":
        from ..adapters.pumpportal import PumpPortalTrader
        risk = get_setting(db, "risk")
        row = LiveTrade(
            wallet_address=p["wallet_address"], token_mint=mint, side="sell",
            sol_amount=proceeds, token_amount=qty_sell, price_sol=float(price),
            status="pending", is_open=False, realized_pnl_sol=pnl,
        )
        db.add(row); db.commit(); db.refresh(row)
        try:
            sig = PumpPortalTrader().submit_sell(
                mint, fraction, float(price),
                max_slippage=float(risk.get("max_slippage", 0.15)),
                priority_fee_sol=float(risk.get("priority_fee_sol", 0.0005)),
            )
            row.signature = sig
            row.status = "submitted"
        except Exception as exc:  # noqa: BLE001
            row.status = "failed"
            row.error = str(exc)[:240]
            db.commit()
            raise HTTPException(400, f"Canlı satış gönderilemedi: {str(exc)[:160]}")
        db.add(AuditLog(level="warning", category="trading",
                        message=f"CANLI pozisyon manuel %{int(round(fraction*100))} satıldı: {mint}"))
        db.commit()
        return {"sold": mint, "mode": "live", "fraction": fraction, "qty": round(qty_sell, 2),
                "price_sol": float(price), "realized_pnl_sol": round(pnl, 4),
                "signature": row.signature}
    db.add(PaperTrade(
        wallet_address=p["wallet_address"], token_mint=mint, side="sell",
        sol_amount=proceeds, token_amount=qty_sell, price_sol=float(price), fee_sol=0.0,
        realized_pnl_sol=pnl, is_open=False,
        reason=f"manuel %{int(round(fraction*100))} sat (paper, canlı fiyat)"))
    db.add(AuditLog(level="info", category="trading",
                    message=f"Paper pozisyon %{int(round(fraction*100))} satıldı: {mint} · PnL {pnl:+.4f} SOL"))
    db.commit()
    return {"sold": mint, "mode": "paper", "fraction": fraction, "qty": round(qty_sell, 2),
            "price_sol": float(price), "realized_pnl_sol": round(pnl, 4)}


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
