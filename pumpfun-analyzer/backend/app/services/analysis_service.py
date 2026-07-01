"""Analiz orkestrasyonu ve kalıcılaştırma.

Cüzdan/token puanlarını hesaplar, geçmişiyle birlikte saklar ve takip durumunu
günceller. 70 puan altına düşen kayıtlar SİLİNMEZ; "below_threshold" durumuna
alınır (denetim için geçmiş korunur, yeni bildirim/işlem durur).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..core.scoring.token_scoring import TokenScoreResult
from ..core.scoring.wallet_scoring import WalletScoreResult
from ..models import (
    Token,
    TokenScore,
    TokenStatus,
    Wallet,
    WalletScore,
    WalletStatus,
)


def persist_wallet_score(db: Session, wallet: Wallet, result: WalletScoreResult,
                         metrics: dict | None = None, demote_below: float = 65.0) -> WalletScore:
    score = WalletScore(
        wallet_id=wallet.id,
        total=result.total,
        performance=result.performance,
        consistency=result.consistency,
        risk=result.risk,
        organic=result.organic,
        hold_quality=result.hold_quality,
        safety=result.safety,
        recency=result.recency,
        breakdown={
            **result.breakdown,
            "eligibility_failures": result.eligibility_failures,
        },
        vetoed=result.vetoed,
        veto_reasons=result.veto_reasons,
        confidence=result.confidence,
    )
    db.add(score)

    wallet.latest_score = result.total
    wallet.confidence = result.confidence
    if metrics is not None:
        wallet.metrics = metrics
    wallet.risk_flags = list(result.veto_reasons)
    wallet.last_analyzed = datetime.now(timezone.utc)

    # Durum geçişi (histerezisli): takibe girmek için tam eşik (≥70 + uygun + veto
    # yok) gerekir; takipten ÇIKMAK için ise puanın `demote_below` (vars. 65) altına
    # düşmesi gerekir. Böylece 65-70 bandında sürekli girip çıkma (flapping) önlenir.
    was_tracked = wallet.status == WalletStatus.tracked.value
    if wallet.status == WalletStatus.blocked.value:
        pass  # kullanıcı engellemesi korunur
    elif result.vetoed:
        wallet.status = WalletStatus.rejected.value
    elif result.tracked:
        wallet.status = WalletStatus.tracked.value
    elif was_tracked and result.eligible and result.total >= demote_below:
        # Takipteydi, hâlâ uygun ve puan histerezis bandında => takipte tut
        wallet.status = WalletStatus.tracked.value
    elif was_tracked:
        # Takipteydi ama artık eşik altında => silme, işaretle
        wallet.status = WalletStatus.below_threshold.value
    else:
        wallet.status = WalletStatus.analyzed.value

    # ÜST SINIR (cap): takip sayısı sınıra ulaştıysa YENİ cüzdanı takibe ALMA
    # (mevcut takip korunur). Aksi halde keşif/analiz akışı eleme sonrası takip
    # sayısını sürekli geri şişiriyordu (150'ye indir, 1 saatte 460'a çık). 0 = sınırsız.
    if wallet.status == WalletStatus.tracked.value and not was_tracked:
        from sqlalchemy import func
        from .settings_service import get_setting
        cap = int((get_setting(db, "thresholds") or {}).get("max_tracked", 0) or 0)
        if cap > 0:
            cnt = (db.query(func.count(Wallet.id))
                   .filter(Wallet.status == WalletStatus.tracked.value, Wallet.id != wallet.id)
                   .scalar() or 0)
            if cnt >= cap:
                wallet.status = WalletStatus.below_threshold.value  # sınır dolu; aday bekler

    db.commit()
    db.refresh(score)
    return score


def persist_token_score(db: Session, token: Token, result: TokenScoreResult, metrics: dict | None = None) -> TokenScore:
    score = TokenScore(
        token_id=token.id,
        total=result.total,
        security=result.security,
        holder_distribution=result.holder_distribution,
        creator_history=result.creator_history,
        liquidity_quality=result.liquidity_quality,
        organic_growth=result.organic_growth,
        trade_behavior=result.trade_behavior,
        breakdown=result.breakdown,
        vetoed=result.vetoed,
        veto_reasons=result.veto_reasons,
        confidence=result.confidence,
    )
    db.add(score)

    token.latest_score = result.total
    token.confidence = result.confidence
    if metrics is not None:
        token.metrics = metrics
    token.risk_flags = list(result.veto_reasons)
    token.last_analyzed = datetime.now(timezone.utc)

    if token.status == TokenStatus.blocked.value:
        pass
    elif result.vetoed:
        token.status = TokenStatus.vetoed.value
    elif result.tracked:
        token.status = TokenStatus.tracked.value
    elif token.status == TokenStatus.tracked.value and result.total < 70:
        token.status = TokenStatus.below_threshold.value
    else:
        token.status = TokenStatus.analyzed.value

    db.commit()
    db.refresh(score)
    return score


def get_or_create_wallet(db: Session, address: str, source: str | None = None) -> Wallet:
    w = db.query(Wallet).filter(Wallet.address == address).first()
    if w is None:
        w = Wallet(address=address, discovery_source=source)
        db.add(w)
        db.commit()
        db.refresh(w)
    return w


def get_or_create_token(db: Session, mint: str, **kwargs) -> Token:
    t = db.query(Token).filter(Token.mint == mint).first()
    if t is None:
        t = Token(mint=mint, **kwargs)
        db.add(t)
        db.commit()
        db.refresh(t)
    return t
