"""Cüzdan puanlama motoru (100 üzerinden).

Ağırlıklar (varsayılan, panelden değiştirilebilir):
  copyability   %25  — 0.01 SOL ile gecikmeli kopyalanabilirlik
  performance   %15  — liderin kendi işlem başarısı ve örneklem kalitesi
  consistency   %15  — tutarlılık
  risk          %15  — risk ve maksimum düşüş
  organic       %10  — organik işlem davranışı
  hold_quality  %5   — tutma süresi kalitesi
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
    "copyability": 0.25,
    "performance": 0.15,
    "consistency": 0.15,
    "risk": 0.15,
    "organic": 0.10,
    "hold_quality": 0.05,
    "safety": 0.10,
    "recency": 0.05,
}

# Pump.fun gerçeğine uyarlanmış eşikler: pump.fun degen/hızlı bir ortamdır;
# tokenler dakikalar-saatler yaşar. "30 gün geçmiş / 30 dk medyan tutma" gibi
# katı kriterler gerçek pump.fun trader'larını bile eler. Geçmiş gün sayısı artık
# takip eligibility filtresi değildir; örneklem/copyability asıl karar vericidir.
# Bu değerler hızlı ama
# TUTARLI trader'ları geçirip tek-atışlık/rug cüzdanları elemeye dengelenmiştir.
# Tümü panelden değiştirilebilir (API ve RPC Ayarları).
DEFAULT_ELIGIBILITY = {
    # KALİTE AŞAMASI: geniş ağ ile 500+ aday toplandı; artık daha seçiciyiz.
    # Bu kriterler hem yeni takibe alımı hem de yeniden değerlendirmeyi (eleme
    # KALICI olsun diye) bağlar. Daha gevşek değerler keşif/havuz-büyütme içindi.
    "min_closed_positions": 10,        # yeterli örneklem (tek-iki işlem değil)
    "min_distinct_tokens": 5,          # birden çok tokende tutarlılık (şans değil)
    "min_history_days": 0.0,
    "min_realized_pnl_sol": 0.0,       # liderin kendi geçmişi de en az zarar yazmamalı
    "min_profit_factor": 1.20,         # marjı çok ince cüzdanları canlıya taşıma
    # Kârlı pump.fun trader'ları çoğu zaman %40-50 isabetle ama yüksek profit
    # factor ile kazanır; yüksek eşik bu profilleri sessizce eliyordu. Kaliteyi
    # win-rate değil; profit factor + organik/sniper/veto + toplam puan belirler.
    # Win-rate yalnızca tam tersine (rug/tek-atış) karşı taban filtre.
    "min_win_rate": 0.40,
    "min_median_hold_seconds": 300,    # 5 dk altı davranış follower için çoğu zaman gecikme zararıdır
    "max_short_hold_ratio": 0.45,      # <10 dk kapanışlar
    "max_single_trade_pnl_share": 0.55,
    # AKTİF cüzdana öncelik: kopya-ticarette uyuyan (son N gün işlem yapmamış)
    # bir cüzdanı takip etmek anlamsızdır — yeni alımı gelmez. 7 gün = pump.fun
    # için makul "hâlâ aktif" penceresi (eski 14 çok gevşekti).
    "max_days_since_last_trade": 3,
    "copyability_min_sample": 12,
    "copyability_require_min_sample": True,
    "copyability_min_coverage": 0.70,
    "copyability_max_entry_jump_10s": 0.15,
    "copyability_min_pnl_10s": 0.001,
    "copyability_min_score": 65,
    "copyability_min_profit_factor_10s": 1.40,
    "max_sniper_confidence": 0.45,
    "max_scalper_confidence": 0.45,
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
    copyability: float = 0.0
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
    copyability_metrics: dict | None = None,
    weights: dict | None = None,
    eligibility: dict | None = None,
    threshold: float = 70.0,
) -> WalletScoreResult:
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    weight_total = sum(float(v) for v in w.values()) or 1.0
    w = {k: float(v) / weight_total for k, v in w.items()}
    elig = {**DEFAULT_ELIGIBILITY, **(eligibility or {})}
    breakdown: dict = {}

    copy_m = copyability_metrics or {}

    # --- copyability (%25): 0.01 SOL gecikmeli kopya simülasyonu ---
    copyability = float(copy_m.get("copyability_score") if copy_m.get("copyability_score") is not None else 50.0)
    c_sample = int(copy_m.get("copy_sample_size") or 0)
    c_cov = float(copy_m.get("copy_coverage_ratio") or 0.0)
    c_pnl_5 = float(copy_m.get("copy_pnl_5s_sol") or 0.0)
    c_pnl_10 = float(copy_m.get("copy_pnl_10s_sol") or 0.0)
    c_pnl_30 = float(copy_m.get("copy_pnl_30s_sol") or 0.0)
    c_pf_10 = copy_m.get("copy_profit_factor_10s")
    c_pf_10_float = float(c_pf_10) if c_pf_10 is not None else float("inf") if c_pnl_10 > 0 else 0.0
    c_jump_10 = float(copy_m.get("avg_entry_jump_10s") or 0.0)
    breakdown["copyability"] = {
        "copyability_score": round(copyability, 1),
        "copy_pnl_5s_sol": round(c_pnl_5, 6),
        "copy_pnl_10s_sol": round(c_pnl_10, 6),
        "copy_pnl_30s_sol": round(c_pnl_30, 6),
        "copy_profit_factor_10s": None if c_pf_10_float == float("inf") else round(c_pf_10_float, 3),
        "copy_sample_size": c_sample,
        "copy_coverage_ratio": round(c_cov, 3),
        "avg_entry_jump_10s": round(c_jump_10, 3),
        "value": round(copyability, 1),
    }

    # --- performance (%20): win_rate + profit_factor + örneklem ---
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
        w["copyability"] * copyability
        + w["performance"] * performance
        + w["consistency"] * consistency
        + w["risk"] * risk
        + w["organic"] * organic
        + w["hold_quality"] * hold_quality
        + w["safety"] * safety
        + w["recency"] * recency
    )

    # Güvene göre nötr (50) değere doğru çek: az veri => temkinli puan.
    if copy_m:
        copy_confidence = min(1.0, c_cov) if c_sample >= 1 else 0.0
        if c_sample < int(elig.get("copyability_min_sample", 12)):
            copy_confidence *= 0.65
        confidence = min(1.0, max(0.0, perf.confidence * 0.75 + copy_confidence * 0.25))
    else:
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
    max_sniper = float(elig.get("max_sniper_confidence", 1.0) or 1.0)
    max_scalper = float(elig.get("max_scalper_confidence", 1.0) or 1.0)
    if signals.sniper_confidence > max_sniper:
        veto_reasons.append(f"Sniper davranışı canlı kopya için yüksek ({signals.sniper_confidence:.2f})")
    if signals.scalper_confidence > max_scalper:
        veto_reasons.append(f"Scalper davranışı canlı kopya için yüksek ({signals.scalper_confidence:.2f})")
    vetoed = bool(veto_reasons)

    # --- Uygunluk (eleme) kuralları ---
    failures: list[str] = []
    if perf.closed_positions < elig["min_closed_positions"]:
        failures.append(f"Kapalı pozisyon < {elig['min_closed_positions']}")
    if perf.token_diversity < elig["min_distinct_tokens"]:
        failures.append(f"Farklı token < {elig['min_distinct_tokens']}")
    min_history_days = float(elig.get("min_history_days", 0.0) or 0.0)
    if min_history_days > 0 and signals.history_days < min_history_days:
        failures.append(f"Geçmiş < {min_history_days} gün")
    if perf.win_rate < elig["min_win_rate"]:
        failures.append(f"Başarı oranı < %{elig['min_win_rate']*100:.0f}")
    min_realized = float(elig.get("min_realized_pnl_sol", 0.0) or 0.0)
    if perf.realized_pnl_sol <= min_realized:
        failures.append(f"Lider realized PnL yetersiz ({perf.realized_pnl_sol:+.4f} SOL)")
    min_pf = float(elig.get("min_profit_factor", 0.0) or 0.0)
    if min_pf and perf.profit_factor != float("inf") and perf.profit_factor < min_pf:
        failures.append(f"Lider profit factor düşük ({perf.profit_factor:.2f})")
    if perf.median_hold_seconds < elig["min_median_hold_seconds"]:
        failures.append("Medyan tutma süresi çok kısa")
    if perf.short_hold_ratio > elig["max_short_hold_ratio"]:
        failures.append("Kısa süreli kapanış oranı çok yüksek")
    if perf.largest_trade_pnl_share > elig["max_single_trade_pnl_share"]:
        failures.append("Tek işlem kârın aşırı büyük bölümünü oluşturuyor")
    max_idle = elig.get("max_days_since_last_trade", 0)
    if max_idle and signals.days_since_last_trade > max_idle:
        failures.append(f"Son işlemden {signals.days_since_last_trade:.0f} gün geçti (>{max_idle:.0f}) — aktif değil")
    min_copy_sample = int(elig.get("copyability_min_sample", 12))
    if c_sample >= min_copy_sample:
        if copyability < float(elig.get("copyability_min_score", 0.0) or 0.0):
            failures.append(f"Copyability score düşük ({copyability:.0f})")
        if c_pnl_10 <= float(elig.get("copyability_min_pnl_10s", 0.0)):
            failures.append("10sn gecikmeli 0.01 SOL copy PnL pozitif değil")
        if c_pf_10_float < float(elig.get("copyability_min_profit_factor_10s", 1.1) or 1.1):
            failures.append("10sn copy profit factor düşük")
        if c_jump_10 > float(elig.get("copyability_max_entry_jump_10s", 0.15)):
            failures.append("Geç girince tepeden aldırıyor (10sn entry jump yüksek)")
        if c_cov < float(elig.get("copyability_min_coverage", 0.70)):
            failures.append("Copyability coverage düşük — inceleme gerekli")
    elif bool(elig.get("copyability_require_min_sample", False)):
        failures.append(f"Copyability örneklemi yetersiz ({c_sample}/{min_copy_sample})")

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
        copyability=round(copyability, 1),
        breakdown=breakdown,
        vetoed=vetoed,
        veto_reasons=veto_reasons,
        eligible=eligible,
        eligibility_failures=failures,
        confidence=confidence,
        tracked=tracked,
    )
