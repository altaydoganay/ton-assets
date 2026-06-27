from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Wallet, WalletScore, WalletStatus, WalletRelationship
from ..schemas import WalletDetail, WalletOut, WalletScoreOut
from ..adapters.registry import build_chain_provider
from ..adapters.rpc import RpcUnavailableError
from ..services.analysis_service import get_or_create_wallet
from ..services.pipeline import ingest_wallet, analyze_wallet

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/wallets", tags=["wallets"])


class WalletCreate(BaseModel):
    address: str
    label: str | None = None
    limit: int = 100  # taranacak son işlem sayısı


def _ingest_and_score(db: Session, address: str, limit: int):
    """Cüzdanın işlemlerini çekip puanlar. RPC yoksa açıklayıcı hata döner."""
    provider = build_chain_provider()
    try:
        ingest_wallet(db, provider, address, limit=limit)
    except RpcUnavailableError as exc:
        raise HTTPException(503, f"Zincir sağlayıcıya ulaşılamadı (RPC/Helius): {exc}")
    return analyze_wallet(db, address)


@router.post("/rescan")
def rescan_wallets(db: Session = Depends(get_db)):
    """Mevcut cüzdanları DEPOLANMIŞ swap'larla yeniden puanlar (kredi harcamaz).

    Kriter/eşik değişikliğinden (örn. takip eşiği 55 + gevşeyen uygunluk) sonra
    eski 'rejected/below_threshold/analyzed' kararlarını günceller; artık eşiği
    geçen cüzdanlar TAKİBE alınır. Zincire gitmez. Büyük havuzlarda zaman
    bütçesi (20sn) aşılırsa kalan `remaining` ile döner — tekrar çağrılabilir."""
    from ..services.pipeline import rescore_wallets_from_storage
    return rescore_wallets_from_storage(db)


@router.get("", response_model=list[WalletOut])
def list_wallets(
    status: str | None = Query(None),
    min_score: float | None = Query(None),
    limit: int = Query(100, le=500),
    offset: int = 0,
    db: Session = Depends(get_db),
):
    q = db.query(Wallet)
    if status:
        q = q.filter(Wallet.status == status)
    if min_score is not None:
        q = q.filter(Wallet.latest_score >= min_score)
    q = q.order_by(Wallet.latest_score.desc().nullslast()).offset(offset).limit(limit)
    return q.all()


@router.post("", response_model=WalletDetail, status_code=201)
def add_wallet(body: WalletCreate, db: Session = Depends(get_db)):
    """Cüzdan ekle, son işlemlerini çekip analiz et ve puanla.

    Not: İşlem çekimi RPC/Helius'a bağlıdır; çok sayıda işlemde birkaç dakika
    sürebilir. `limit` ile taranacak işlem sayısı sınırlanır.
    """
    w = get_or_create_wallet(db, body.address, source="manual")
    if body.label:
        w.label = body.label
        db.commit()
    _ingest_and_score(db, body.address, body.limit)
    db.refresh(w)
    return w


@router.post("/{address}/reanalyze", response_model=WalletDetail)
def reanalyze_wallet(address: str, limit: int = Query(100, le=1000), db: Session = Depends(get_db)):
    w = db.query(Wallet).filter(Wallet.address == address).first()
    if not w:
        raise HTTPException(404, "Cüzdan bulunamadı")
    _ingest_and_score(db, address, limit)
    db.refresh(w)
    return w


@router.get("/tracked", response_model=list[WalletOut])
def tracked_wallets(db: Session = Depends(get_db)):
    return (
        db.query(Wallet)
        .filter(Wallet.status == WalletStatus.tracked.value)
        .order_by(Wallet.latest_score.desc())
        .all()
    )


@router.get("/leaderboard")
def leaderboard(limit: int = Query(300, le=1000), db: Session = Depends(get_db)):
    """TÜM puanlanmış cüzdanları KENDİ performanslarıyla döner (sıralama sayfası).
    Cüzdanların kendi al-sat sonuçları: başarı oranı, gerçekleşen PnL, profit
    factor, ortalama alım büyüklüğü, vb. (Bizim kopya sonucumuz değil — liderin
    GERÇEK performansı.)"""
    rows = (db.query(Wallet)
            .filter(Wallet.latest_score.isnot(None))
            .order_by(Wallet.latest_score.desc()).limit(limit).all())
    out = []
    for w in rows:
        m = w.metrics or {}
        out.append({
            "address": w.address, "label": w.label, "status": w.status,
            "score": w.latest_score, "confidence": w.confidence,
            "win_rate": m.get("win_rate"),
            "realized_pnl_sol": m.get("realized_pnl_sol"),
            "profit_factor": m.get("profit_factor"),
            "closed_positions": m.get("closed_positions"),
            "token_diversity": m.get("token_diversity"),
            "median_hold_seconds": m.get("median_hold_seconds"),
            "history_days": m.get("history_days"),
            "avg_buy_size_sol": m.get("avg_buy_size_sol"),
            "last_analyzed": w.last_analyzed.isoformat() if w.last_analyzed else None,
        })
    return out


@router.get("/{address}", response_model=WalletDetail)
def get_wallet(address: str, db: Session = Depends(get_db)):
    w = db.query(Wallet).filter(Wallet.address == address).first()
    if not w:
        raise HTTPException(404, "Cüzdan bulunamadı")
    return w


@router.get("/{address}/score-history", response_model=list[WalletScoreOut])
def score_history(address: str, db: Session = Depends(get_db)):
    w = db.query(Wallet).filter(Wallet.address == address).first()
    if not w:
        raise HTTPException(404, "Cüzdan bulunamadı")
    return (
        db.query(WalletScore)
        .filter(WalletScore.wallet_id == w.id)
        .order_by(WalletScore.created_at.asc())
        .all()
    )


@router.get("/{address}/relationships")
def relationships(address: str, db: Session = Depends(get_db)):
    rels = (
        db.query(WalletRelationship)
        .filter(
            (WalletRelationship.source_address == address)
            | (WalletRelationship.target_address == address)
        )
        .all()
    )
    return [
        {
            "source": r.source_address,
            "target": r.target_address,
            "kind": r.kind,
            "confidence": r.confidence,
            "evidence": r.evidence,
        }
        for r in rels
    ]


@router.post("/{address}/block", response_model=WalletOut)
def block_wallet(address: str, db: Session = Depends(get_db)):
    w = db.query(Wallet).filter(Wallet.address == address).first()
    if not w:
        raise HTTPException(404, "Cüzdan bulunamadı")
    w.status = WalletStatus.blocked.value
    db.commit()
    db.refresh(w)
    return w


@router.post("/{address}/approve", response_model=WalletOut)
def approve_wallet(address: str, db: Session = Depends(get_db)):
    w = db.query(Wallet).filter(Wallet.address == address).first()
    if not w:
        raise HTTPException(404, "Cüzdan bulunamadı")
    w.status = WalletStatus.tracked.value
    db.commit()
    db.refresh(w)
    return w


@router.post("/{address}/copy-amount")
def set_copy_amount(address: str, sol: float = Query(...), db: Session = Depends(get_db)):
    """Bu cüzdana özel kopya SOL miktarı ata. sol<=0 => override'ı kaldır (varsayılana
    döner: paper'da sabit miktar, canlıda fixed/orantılı)."""
    from ..services.settings_service import get_setting, set_setting
    overrides = dict(get_setting(db, "copy_overrides") or {})
    if sol and sol > 0:
        overrides[address] = float(sol)
    else:
        overrides.pop(address, None)
    set_setting(db, "copy_overrides", overrides)
    return {"address": address, "copy_override_sol": overrides.get(address)}
