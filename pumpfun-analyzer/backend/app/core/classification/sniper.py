"""Sniper / bot / scalper tespiti.

- İlk blok / bundle alıcıları (token doğumundan saniyeler içinde alım)
- İşlemlerinin çoğunu birkaç dakika içinde kapatan bot/scalper davranışı
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SniperResult:
    is_sniper: bool
    is_scalper: bool
    confidence: float
    reasons: list[str] = field(default_factory=list)


SNIPE_WINDOW_SECONDS = 20      # token doğumundan bu kadar sonrası snipe sayılır
SCALP_HOLD_SECONDS = 300       # 5 dk altı kapanışlar scalp


def detect_sniper(
    first_buy_offsets: list[float],   # her token için: (alım zamanı - token doğum zamanı) sn
    hold_times: list[float],          # kapanmış işlemlerin tutma süreleri sn
    first_block_buys: int = 0,        # ilk blokta yapılan alım sayısı
) -> SniperResult:
    reasons: list[str] = []
    n_offsets = len(first_buy_offsets)

    snipe_count = sum(1 for o in first_buy_offsets if 0 <= o <= SNIPE_WINDOW_SECONDS)
    snipe_ratio = (snipe_count / n_offsets) if n_offsets else 0.0

    scalp_ratio = 0.0
    if hold_times:
        scalp_ratio = sum(1 for h in hold_times if h < SCALP_HOLD_SECONDS) / len(hold_times)

    confidence = round(min(1.0, 0.6 * snipe_ratio + 0.4 * scalp_ratio + 0.2 * (first_block_buys > 0)), 3)

    is_sniper = snipe_ratio >= 0.4 or first_block_buys >= 3
    is_scalper = scalp_ratio >= 0.5

    if snipe_ratio > 0:
        reasons.append(f"Alımların %{snipe_ratio*100:.0f}'ı token doğumundan ≤{SNIPE_WINDOW_SECONDS}sn sonra")
    if first_block_buys:
        reasons.append(f"{first_block_buys} ilk-blok alımı")
    if scalp_ratio > 0:
        reasons.append(f"İşlemlerin %{scalp_ratio*100:.0f}'ı <5 dk içinde kapanmış (scalp)")
    if not reasons:
        reasons.append("Sniper/scalper davranışı tespit edilmedi")

    return SniperResult(is_sniper=is_sniper, is_scalper=is_scalper, confidence=confidence, reasons=reasons)
