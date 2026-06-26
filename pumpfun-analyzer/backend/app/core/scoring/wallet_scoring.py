"""Cüzdan puanlama motoru (100 üzerinden).

Ağırlıklar (varsayılan, panelden değiştirilebilir):
  performance   %25  — işlem başarısı ve örneklem kalitesi
  consistency   %20  — tutarlılık
  risk          %15  — risk ve maksimum düşüş
  organic       %15  — organik işlem davranışı
  hold_quality  %10  — tutma süresi kalitesi
  safety        %10  — rug/copy/insider güvenliği
  recency       %5   — güncellik ve aktiflik

Eşik: toplam >= 70 ve hiçbir kritik veto yok => takip listesine alınır.

Her alt puanın 0-100 normalize edilmiş değeri ve gerekçesi `breakdown`
içinde döner. Düşük örneklemde güven (confidence) düşer ve nihai puan güvene
göre nötr (50) değere doğru çekilir — böylece az veriyle yüksek puan verilmez.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..analysis.pnl import WalletPerformance

DEFAULT_WEIGHTS = {
    "performance": 0.25,
    "consistency": 0.20,
    "risk": 0.15,
    "organic": 0.15,
    "hold_quality": 0.10,
    "safety": 0.10,
    "recency": 0.05,
}

# Pump.fun gerçeğine uyarlanmış eşikler: pump.fun degen/hızlı bir ortamdır;
# tokenler dakikalar-saatler yaşar. "30 gün geçmiş / 30 dk medyan tutma" gibi
# katı kriterler gerçek pump.fun trader'larını bile eler. Bu değerler hızlı ama
# TUTARLI trader'ları geçirip tek-atışlık/rug cüzdanları elemeye dengelenmiştir.
# Tümü panelden değiştirilebilir (API ve RPC Ayarları).
DEFAULT_ELIGIBILITY = {
    # GENİŞ AĞ (paper aşaması): daha az geçmişle aday kabul et — filtrelerimize
    # takılan ama kâr eden cüzdanları da takibe alıp kopya performansıyla ölç.
    # Canlıya geçerken bu kriterler sıkılaştırılabilir.
    "min_closed_positions": 4,
    "min_distinct_tokens": 2,
    "min_history_days": 0.5,
    # Kârlı pump.fun trader'ları çoğu zaman %40-50 isabetle ama yüksek profit
    # factor ile kazanır; yüksek eşik bu profilleri sessizce eliyordu. Kaliteyi
    # win-rate değil; profit factor + organik/sniper/veto + toplam puan belirler.
    # Win-rate yalnızca tam tersine (rug/tek-atış) karşı taban filtre.
    "min_win_rate": 0.40,
    "min_median_hold_seconds": 180,    # 3 dk (pump.fun hızlı; sniper saniyeler içinde flip eder)
    "max_short_hold_ratio": 0.70,      # <10 dk kapanışlar
    "max_single_trade_pnl_share": 0.75,
    # AKTİF cüzdana öncelik: kopya-ticarette uyuyan (son N gün işlem yapmamış)
    # bir cüzdanı takip etmek anlamsızdır — yeni alımı gelmez. Bu kadar gün
    # işlem yapmamış cüzdan takibe ALINMAZ (geçmişi iyi olsa bile).
    "max_days_since_last_trade": 14,
}


@dataclass
class WalletSignals:
    """Sınıflandırıcı çıktıları (0-1 güven skorları)."""
    rugger_confidence: float = 0.0
    copy_confidence: float = 0.0
    sniper_confidence: float = 0.0
    scalper_confidence: float = 0.0
    insider_confidence: float = 0.0
    is_token_creator: bool = False
    history_days: float = 0.0
    days_since_last_trade: float = 0.0
    transfer_noise_ratio: float = 0.0   # transfer/airdrop oranı (organik için)


@dataclass
class WalletScoreResult:
    total: float
    performance: float
    consistency: float
    risk: float
    organic: float
    hold_quality: float
    safety: float
    recency: float
    breakdown: dict = field(default_factory=dict)
    vetoed: bool = False
    veto_reasons: list[str] = field(default_factory=list)
    eligible: bool = False
    eligibility_failures: list[str] = field(default_factory=list)
    confidence: float = 0.0
    tracked: bool = False


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def score_wallet(
    perf: WalletPerformance,
    signals: WalletSignals,
    weights: dict | None = None,
    eligibility: dict | None = None,
    threshold: float = 70.0,
) -> WalletScoreResult:
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    elig = {**DEFAULT_ELIGIBILITY, **(eligibility or {})}
    breakdown: dict = {}

    # --- performance (%25): win_rate + profit_factor + örneklem ---
    pf = perf.profit_factor
    pf_norm = 100.0 if pf == float("inf") else _clamp((pf / 3.0) * 100.0)
    sample_norm = _clamp((perf.closed_positions / 30.0) * 100.0)
    performance = _clamp(0.5 * perf.win_rate * 100 + 0.3 * pf_norm + 0.2 * sample_norm)
    breakdown["performance"] = {
        "win_rate": round(perf.win_rate, 3),
        "profit_factor": None if pf == float("inf") else round(pf, 3),
        "closed_positions": perf.closed_positions,
        "value": round(performance, 1),
    }

    # --- consistency (%20): tutar tutarlılığı + frekans makullüğü ---
    freq_score = 100.0
    if perf.trade_frequency_per_day > 50:  # aşırı yüksek frekans bot benzeri
        freq_score = _clamp(100 - (perf.trade_frequency_per_day - 50) * 2)
    consistency = _clamp(0.6 * perf.amount_consistency * 100 + 0.4 * freq_score)
    breakdown["consistency"] = {
        "amount_consistency": round(perf.amount_consistency, 3),
        "trade_frequency_per_day": round(perf.trade_frequency_per_day, 2),
        "value": round(consistency, 1),
    }

    # --- risk (%15): max drawdown ve tek-işlem yoğunlaşması ---
    # düşük drawdown / düşük yoğunlaşma => yüksek puan
    dd_ref = abs(perf.realized_pnl_sol) + 1e-9
    dd_ratio = min(1.0, perf.max_drawdown_sol / dd_ref) if perf.realized_pnl_sol > 0 else 1.0
    concentration_penalty = perf.largest_trade_pnl_share
    risk = _clamp(100 * (1 - 0.6 * dd_ratio - 0.4 * concentration_penalty))
    breakdown["risk"] = {
        "max_drawdown_sol": round(perf.max_drawdown_sol, 4),
        "largest_trade_pnl_share": round(perf.largest_trade_pnl_share, 3),
        "value": round(risk, 1),
    }

    # --- organic (%15): transfer gürültüsü + sniper/scalper cezası ---
    organic = _clamp(
        100
        - signals.transfer_noise_ratio * 40
        - signals.sniper_confidence * 50
        - signals.scalper_confidence * 40
    )
    breakdown["organic"] = {
        "transfer_noise_ratio": round(signals.transfer_noise_ratio, 3),
        "sniper_confidence": round(signals.sniper_confidence, 3),
        "scalper_confidence": round(signals.scalper_confidence, 3),
        "value": round(organic, 1),
    }

    # --- hold_quality (%10): medyan tutma süresi (30dk-24s ideal bandı) ---
    med_min = perf.median_hold_seconds / 60.0
    if med_min < 10:
        hq = _clamp(med_min / 10 * 40)
    elif med_min < 30:
        hq = _clamp(40 + (med_min - 10) / 20 * 30)
    elif med_min <= 1440:
        hq = _clamp(70 + min(30, (med_min - 30) / 1410 * 30))
    else:
        hq = 85.0
    hold_quality = hq - perf.short_hold_ratio * 30
    hold_quality = _clamp(hold_quality)
    breakdown["hold_quality"] = {
        "median_hold_min": round(med_min, 1),
        "short_hold_ratio": round(perf.short_hold_ratio, 3),
        "value": round(hold_quality, 1),
    }

    # --- safety (%10): rug/copy/insider güvenliği ---
    danger = max(
        signals.rugger_confidence,
        signals.copy_confidence,
        signals.insider_confidence,
    )
    safety = _clamp(100 * (1 - danger))
    breakdown["safety"] = {
        "rugger": round(signals.rugger_confidence, 3),
        "copy": round(signals.copy_confidence, 3),
        "insider": round(signals.insider_confidence, 3),
        "value": round(safety, 1),
    }

    # --- recency (%5): son işlem güncelliği ---
    recency = _clamp(100 - signals.days_since_last_trade * 3)
    breakdown["recency"] = {
        "days_since_last_trade": round(signals.days_since_last_trade, 1),
        "value": round(recency, 1),
    }

    raw_total = (
        w["performance"] * performance
        + w["consistency"] * consistency
        + w["risk"] * risk
        + w["organic"] * organic
        + w["hold_quality"] * hold_quality
        + w["safety"] * safety
        + w["recency"] * recency
    )

    # Güvene göre nötr (50) değere doğru çek: az veri => temkinli puan.
    confidence = perf.confidence
    total = raw_total * confidence + 50.0 * (1 - confidence)
    total = round(_clamp(total), 1)

    # --- Kritik veto kuralları ---
    veto_reasons: list[str] = []
    if signals.is_token_creator:
        veto_reasons.append("Cüzdan analiz edilen tokenin oluşturucusu")
    if signals.rugger_confidence >= 0.7:
        veto_reasons.append("Yüksek rugger güveni")
    if signals.copy_confidence >= 0.7:
        veto_reasons.append("Yüksek copy-trader güveni")
    if signals.insider_confidence >= 0.7:
        veto_reasons.append("Yüksek insider/sybil güveni")
    if signals.sniper_confidence >= 0.7:
        veto_reasons.append("Yüksek sniper güveni")
    vetoed = bool(veto_reasons)

    # --- Uygunluk (eleme) kuralları ---
    failures: list[str] = []
    if perf.closed_positions < elig["min_closed_positions"]:
        failures.append(f"Kapalı pozisyon < {elig['min_closed_positions']}")
    if perf.token_diversity < elig["min_distinct_tokens"]:
        failures.append(f"Farklı token < {elig['min_distinct_tokens']}")
    if signals.history_days < elig["min_history_days"]:
        failures.append(f"Geçmiş < {elig['min_history_days']} gün")
    if perf.win_rate < elig["min_win_rate"]:
        failures.append(f"Başarı oranı < %{elig['min_win_rate']*100:.0f}")
    if perf.median_hold_seconds < elig["min_median_hold_seconds"]:
        failures.append("Medyan tutma süresi çok kısa")
    if perf.short_hold_ratio > elig["max_short_hold_ratio"]:
        failures.append("Kısa süreli kapanış oranı çok yüksek")
    if perf.largest_trade_pnl_share > elig["max_single_trade_pnl_share"]:
        failures.append("Tek işlem kârın aşırı büyük bölümünü oluşturuyor")
    max_idle = elig.get("max_days_since_last_trade", 0)
    if max_idle and signals.days_since_last_trade > max_idle:
        failures.append(f"Son işlemden {signals.days_since_last_trade:.0f} gün geçti (>{max_idle:.0f}) — aktif değil")

    eligible = not failures
    tracked = eligible and not vetoed and total >= threshold

    return WalletScoreResult(
        total=total,
        performance=round(performance, 1),
        consistency=round(consistency, 1),
        risk=round(risk, 1),
        organic=round(organic, 1),
        hold_quality=round(hold_quality, 1),
        safety=round(safety, 1),
        recency=round(recency, 1),
        breakdown=breakdown,
        vetoed=vetoed,
        veto_reasons=veto_reasons,
        eligible=eligible,
        eligibility_failures=failures,
        confidence=confidence,
        tracked=tracked,
    )
