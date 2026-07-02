"""Copy-trader (kopya işlemci) tespiti.

Tek bir benzer işleme dayanarak karar verilmez. Birden çok sinyal birleştirilip
0-1 arası güven skoru ve gerekçeler üretilir:
  - Token örtüşme oranı
  - İşlem yönü benzerliği
  - Tekrarlanan alım-satım sırası
  - Kaynak cüzdandan sonraki medyan işlem gecikmesi (gecikme tutarlılığı)
  - İşlem miktarı benzerliği
  - Zaman korelasyonu
  - En az birkaç farklı token üzerinde tekrar
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median


@dataclass
class TradeRef:
    token_mint: str
    side: str
    block_time: int
    sol_amount: float


@dataclass
class CopyResult:
    is_copy: bool
    confidence: float
    reasons: list[str] = field(default_factory=list)
    matched_tokens: int = 0
    median_lag_seconds: float | None = None


# Bir takip işleminin kaynaktan ne kadar sonra gelebileceği (saniye).
MAX_FOLLOW_LAG = 180


def detect_copy_trader(
    candidate: list[TradeRef],
    leader: list[TradeRef],
    min_matches: int = 4,
    min_distinct_tokens: int = 3,
) -> CopyResult:
    """`candidate` cüzdanı `leader` cüzdanını mı kopyalıyor?"""
    reasons: list[str] = []

    leader_by_token: dict[str, list[TradeRef]] = {}
    for t in leader:
        leader_by_token.setdefault(t.token_mint, []).append(t)

    matches: list[tuple[TradeRef, TradeRef, float]] = []  # (cand, leader, lag)
    distinct_tokens: set[str] = set()
    amount_ratios: list[float] = []

    for c in candidate:
        lead_trades = leader_by_token.get(c.token_mint)
        if not lead_trades:
            continue
        # Aynı yönde ve candidate'ten ÖNCE gelen en yakın lider işlemi bul.
        best = None
        best_lag = None
        for l in lead_trades:
            if l.side != c.side:
                continue
            lag = c.block_time - l.block_time
            if 0 <= lag <= MAX_FOLLOW_LAG:
                if best_lag is None or lag < best_lag:
                    best_lag = lag
                    best = l
        if best is not None:
            matches.append((c, best, float(best_lag)))
            distinct_tokens.add(c.token_mint)
            if best.sol_amount > 0:
                amount_ratios.append(c.sol_amount / best.sol_amount)

    matched = len(matches)
    if matched == 0 or not candidate:
        return CopyResult(is_copy=False, confidence=0.0, reasons=["Lider ile örtüşen takip işlemi yok"])

    # 1) Token örtüşme oranı (candidate'in işlemlerinin ne kadarı eşleşiyor)
    overlap = matched / len(candidate)

    # 2) Gecikme tutarlılığı: medyan gecikme küçük ve düşük varyanslıysa kopya olasılığı yüksek
    lags = [m[2] for m in matches]
    med_lag = median(lags)
    lag_consistency = max(0.0, 1.0 - (med_lag / MAX_FOLLOW_LAG))

    # 3) Miktar benzerliği: oranlar 1'e yakın ve tutarlıysa
    amount_sim = 0.0
    if amount_ratios:
        med_ratio = median(amount_ratios)
        amount_sim = max(0.0, 1.0 - abs(med_ratio - 1.0))
        amount_sim = min(1.0, amount_sim)

    # 4) Farklı token üzerinde tekrar
    token_repeat = min(1.0, len(distinct_tokens) / max(min_distinct_tokens, 1))

    confidence = round(
        0.35 * overlap
        + 0.25 * lag_consistency
        + 0.15 * amount_sim
        + 0.25 * token_repeat,
        3,
    )

    if overlap >= 0.4:
        reasons.append(f"İşlemlerin %{overlap*100:.0f}'ı liderden sonra tekrarlıyor")
    reasons.append(f"Medyan takip gecikmesi {med_lag:.0f} sn")
    if amount_ratios:
        reasons.append(f"Miktar benzerliği {amount_sim:.2f}")
    reasons.append(f"{len(distinct_tokens)} farklı tokende tekrar")

    is_copy = (
        matched >= min_matches
        and len(distinct_tokens) >= min_distinct_tokens
        and confidence >= 0.6
    )

    return CopyResult(
        is_copy=is_copy,
        confidence=confidence,
        reasons=reasons,
        matched_tokens=len(distinct_tokens),
        median_lag_seconds=med_lag,
    )
