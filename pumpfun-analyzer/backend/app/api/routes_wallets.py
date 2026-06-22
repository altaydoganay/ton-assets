from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Wallet, WalletScore, WalletStatus, WalletRelationship
from ..schemas import WalletDetail, WalletOut, WalletScoreOut

router = APIRouter(prefix="/wallets", tags=["wallets"])


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


@router.get("/tracked", response_model=list[WalletOut])
def tracked_wallets(db: Session = Depends(get_db)):
    return (
        db.query(Wallet)
        .filter(Wallet.status == WalletStatus.tracked.value)
        .order_by(Wallet.latest_score.desc())
        .all()
    )


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
