"""Insider / sybil / koordineli küme tespiti.

Cüzdanlar arası fonlama bağlantıları, ortak finansman kaynağı, zaman-senkron
alımlar ve yüksek token örtüşmesi kullanılarak koordineli küme olasılığı
hesaplanır.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InsiderResult:
    is_insider: bool
    confidence: float
    reasons: list[str] = field(default_factory=list)
    cluster_size: int = 0


def detect_insider_cluster(
    funded_by_same_source: bool,
    co_buy_ratio: float,        # aynı tokenlerde eşzamanlı (±1 blok) alım oranı 0-1
    cluster_size: int,          # birlikte hareket eden cüzdan sayısı
    shared_token_ratio: float,  # ortak token oranı 0-1
) -> InsiderResult:
    reasons: list[str] = []
    score = 0.0

    if funded_by_same_source:
        reasons.append("Aynı kaynaktan fonlanmış cüzdan kümesi")
        score += 0.4
    if co_buy_ratio > 0.3:
        reasons.append(f"Eşzamanlı alım oranı %{co_buy_ratio*100:.0f}")
        score += min(0.4, co_buy_ratio * 0.6)
    if cluster_size >= 3:
        reasons.append(f"{cluster_size} cüzdanlık koordineli küme")
        score += min(0.3, cluster_size * 0.05)
    if shared_token_ratio > 0.6:
        reasons.append(f"Ortak token oranı %{shared_token_ratio*100:.0f}")
        score += 0.2

    confidence = round(min(1.0, score), 3)
    is_insider = confidence >= 0.6
    if not reasons:
        reasons.append("Insider/sybil bağlantısı tespit edilmedi")
    return InsiderResult(
        is_insider=is_insider, confidence=confidence, reasons=reasons, cluster_size=cluster_size
    )
