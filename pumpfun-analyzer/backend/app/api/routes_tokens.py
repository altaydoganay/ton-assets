from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Token, TokenScore, TokenStatus, TokenHolder
from ..schemas import TokenDetail, TokenOut, TokenScoreOut
from ..adapters.registry import build_chain_provider, build_market_provider
from ..services.token_analysis import analyze_token

router = APIRouter(prefix="/tokens", tags=["tokens"])


class TokenCreate(BaseModel):
    mint: str


@router.post("", response_model=TokenDetail, status_code=201)
def add_token(body: TokenCreate, db: Session = Depends(get_db)):
    """Bir tokeni elle ekleyip anlık analiz et (bağımsız izleme listesi)."""
    chain = build_chain_provider(throttle=False)
    market = build_market_provider()
    token, _ = analyze_token(db, body.mint.strip(), chain, market)
    db.refresh(token)
    return token


@router.post("/{mint}/reanalyze", response_model=TokenDetail)
def reanalyze_token(mint: str, db: Session = Depends(get_db)):
    t = db.query(Token).filter(Token.mint == mint).first()
    if not t:
        raise HTTPException(404, "Token bulunamadı")
    chain = build_chain_provider(throttle=False)
    market = build_market_provider()
    analyze_token(db, mint, chain, market)
    db.refresh(t)
    return t


@router.get("", response_model=list[TokenOut])
def list_tokens(
    status: str | None = Query(None),
    stage: str | None = Query(None),
    min_score: float | None = Query(None),
    limit: int = Query(100, le=500),
    offset: int = 0,
    db: Session = Depends(get_db),
):
    q = db.query(Token)
    if status:
        q = q.filter(Token.status == status)
    if stage:
        q = q.filter(Token.stage == stage)
    if min_score is not None:
        q = q.filter(Token.latest_score >= min_score)
    q = q.order_by(Token.latest_score.desc().nullslast()).offset(offset).limit(limit)
    return q.all()


@router.get("/tracked", response_model=list[TokenOut])
def tracked_tokens(db: Session = Depends(get_db)):
    return (
        db.query(Token)
        .filter(Token.status == TokenStatus.tracked.value)
        .order_by(Token.latest_score.desc())
        .all()
    )


@router.get("/{mint}", response_model=TokenDetail)
def get_token(mint: str, db: Session = Depends(get_db)):
    t = db.query(Token).filter(Token.mint == mint).first()
    if not t:
        raise HTTPException(404, "Token bulunamadı")
    return t


@router.get("/{mint}/score-history", response_model=list[TokenScoreOut])
def score_history(mint: str, db: Session = Depends(get_db)):
    t = db.query(Token).filter(Token.mint == mint).first()
    if not t:
        raise HTTPException(404, "Token bulunamadı")
    return (
        db.query(TokenScore)
        .filter(TokenScore.token_id == t.id)
        .order_by(TokenScore.created_at.asc())
        .all()
    )


@router.get("/{mint}/holders")
def holders(mint: str, db: Session = Depends(get_db)):
    t = db.query(Token).filter(Token.mint == mint).first()
    if not t:
        raise HTTPException(404, "Token bulunamadı")
    rows = (
        db.query(TokenHolder)
        .filter(TokenHolder.token_id == t.id)
        .order_by(TokenHolder.rank.asc())
        .all()
    )
    return [
        {
            "address": h.address,
            "amount": h.amount,
            "pct": h.pct,
            "rank": h.rank,
            "is_system": h.is_system,
            "is_insider": h.is_insider,
        }
        for h in rows
    ]


@router.post("/{mint}/block", response_model=TokenOut)
def block_token(mint: str, db: Session = Depends(get_db)):
    t = db.query(Token).filter(Token.mint == mint).first()
    if not t:
        raise HTTPException(404, "Token bulunamadı")
    t.status = TokenStatus.blocked.value
    db.commit()
    db.refresh(t)
    return t
