"""Rugger / geliştirici / likidite-çekici davranış tespiti.

Cüzdanın token oluşturucu (creator) olup olmadığı, geçmiş rug pull'ları,
takipçilerin üzerine satış (dump) ve çok sayıda token oluşturup terk etme
davranışları değerlendirilir. Sonuç: risk etiketleri + 0-1 güven skoru.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CreatedToken:
    mint: str
    created_at: int
    abandoned: bool          # likidite çekildi / terk edildi
    dumped_on_holders: bool  # creator erken büyük satış yaptı
    survived_days: float


@dataclass
class RuggerResult:
    is_rugger: bool
    confidence: float
    reasons: list[str] = field(default_factory=list)
    veto: bool = False  # token analizinde kritik veto tetikler


def detect_rugger(
    wallet: str,
    created_tokens: list[CreatedToken],
    is_creator_of_analyzed: bool = False,
) -> RuggerResult:
    reasons: list[str] = []
    score = 0.0

    if is_creator_of_analyzed:
        reasons.append("Analiz edilen tokenin oluşturucusu (creator)")
        score += 0.5

    total = len(created_tokens)
    if total:
        rugged = [t for t in created_tokens if t.abandoned or t.dumped_on_holders]
        rug_ratio = len(rugged) / total
        if rug_ratio > 0:
            reasons.append(f"Oluşturduğu {total} tokenin %{rug_ratio*100:.0f}'ı terk/dump")
            score += min(0.6, rug_ratio * 0.8)

        short_lived = [t for t in created_tokens if t.survived_days < 1.0]
        if total >= 5 and len(short_lived) / total > 0.5:
            reasons.append("Çok sayıda kısa ömürlü token oluşturup terk etmiş")
            score += 0.3

        if any(t.dumped_on_holders for t in created_tokens):
            reasons.append("Takipçilerin üzerine satış (dump) geçmişi")
            score += 0.3

    confidence = round(min(1.0, score), 3)
    is_rugger = confidence >= 0.6
    veto = is_creator_of_analyzed or confidence >= 0.7
    if not reasons:
        reasons.append("Rug/creator riski tespit edilmedi")
    return RuggerResult(is_rugger=is_rugger, confidence=confidence, reasons=reasons, veto=veto)
