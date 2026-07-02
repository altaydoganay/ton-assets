"""Token puanlama motoru (100 üzerinden).

Ağırlıklar:
  security             %30  — zincir üstü güvenlik
  holder_distribution  %20  — holder dağılımı
  creator_history      %15  — creator geçmişi
  liquidity_quality    %15  — likidite ve piyasa kalitesi
  organic_growth       %10  — organik büyüme
  trade_behavior       %10  — işlem davranışı

Kritik veto (puandan bağımsız):
  - Aktif ve tehlikeli mint/freeze yetkisi
  - Doğrulanmış rugger creator
  - Aşırı insider arzı
  - Honeypot / satılamama belirtisi
  - Sahte likidite
  - Çok kuvvetli wash trading

Token yaşına/aşamasına göre uyarlanır: bonding curve aşamasındaki çok yeni
tokenler mezun olmuş tokenlerle aynı likidite/holder beklentisine tabi
tutulmaz; bunun yerine bonding aşaması için güvenlik ve dağılım ağırlıkları öne
çıkar ve düşük örneklem güveni düşürür.
"""
from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_WEIGHTS = {
    "security": 0.30,
    "holder_distribution": 0.20,
    "creator_history": 0.15,
    "liquidity_quality": 0.15,
    "organic_growth": 0.10,
    "trade_behavior": 0.10,
}


@dataclass
class TokenMetrics:
    stage: str = "unknown"             # bonding | graduating | graduated
    age_seconds: float = 0.0

    # görsel/kimlik (piyasa verisinden — UI token avatarı/adı için)
    name: str | None = None
    symbol: str | None = None
    image_url: str | None = None
    pair_url: str | None = None

    # güvenlik
    mint_authority_active: bool = False
    freeze_authority_active: bool = False
    metadata_mutable: bool = False
    honeypot_suspected: bool = False
    sellable: bool = True

    # holder dağılımı (sistem/LP/bonding hariç hesaplanmış)
    top10_pct: float = 0.0             # 0-1
    top20_pct: float = 0.0
    unique_holders: int = 0
    insider_supply_pct: float = 0.0    # 0-1
    sniper_ratio: float = 0.0          # 0-1

    # creator
    creator_is_rugger: bool = False
    creator_rug_ratio: float = 0.0     # geçmiş tokenlerinin rug oranı 0-1
    creator_prior_tokens: int = 0

    # likidite / piyasa
    price_sol: float = 0.0
    price_usd: float = 0.0
    liquidity_sol: float = 0.0
    liquidity_usd: float = 0.0
    market_cap_usd: float = 0.0
    fdv_usd: float = 0.0
    volume_24h_usd: float = 0.0
    pair_created_at: int = 0
    fake_liquidity_suspected: bool = False

    # organik büyüme
    holder_growth_rate: float = 0.0    # birim zamanda yeni organik holder
    buyer_seller_ratio: float = 1.0

    # işlem davranışı
    wash_trading_score: float = 0.0    # 0-1
    sudden_dump_risk: float = 0.0      # 0-1


@dataclass
class TokenScoreResult:
    total: float
    security: float
    holder_distribution: float
    creator_history: float
    liquidity_quality: float
    organic_growth: float
    trade_behavior: float
    breakdown: dict = field(default_factory=dict)
    vetoed: bool = False
    veto_reasons: list[str] = field(default_factory=list)
    confidence: float = 0.0
    tracked: bool = False


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def score_token(
    m: TokenMetrics,
    weights: dict | None = None,
    threshold: float = 70.0,
) -> TokenScoreResult:
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    breakdown: dict = {}
    is_bonding = m.stage in ("bonding", "graduating", "unknown")

    # --- security (%30) ---
    security = 100.0
    if m.mint_authority_active:
        security -= 45
    if m.freeze_authority_active:
        security -= 45
    if m.metadata_mutable:
        security -= 10
    if m.honeypot_suspected or not m.sellable:
        security -= 60
    security = _clamp(security)
    breakdown["security"] = {
        "mint_authority_active": m.mint_authority_active,
        "freeze_authority_active": m.freeze_authority_active,
        "metadata_mutable": m.metadata_mutable,
        "sellable": m.sellable,
        "value": round(security, 1),
    }

    # --- holder_distribution (%20) ---
    hd = 100.0
    hd -= _clamp(m.top10_pct * 100, 0, 100) * 0.6
    hd -= _clamp(m.insider_supply_pct * 100, 0, 100) * 0.8
    hd -= m.sniper_ratio * 40
    # az holder cezası (bonding'de daha hoşgörülü)
    min_holders = 30 if is_bonding else 100
    if m.unique_holders < min_holders:
        hd -= (1 - m.unique_holders / max(min_holders, 1)) * 30
    holder_distribution = _clamp(hd)
    breakdown["holder_distribution"] = {
        "top10_pct": round(m.top10_pct, 3),
        "top20_pct": round(m.top20_pct, 3),
        "unique_holders": m.unique_holders,
        "insider_supply_pct": round(m.insider_supply_pct, 3),
        "sniper_ratio": round(m.sniper_ratio, 3),
        "value": round(holder_distribution, 1),
    }

    # --- creator_history (%15) ---
    ch = 100.0
    if m.creator_is_rugger:
        ch = 0.0
    else:
        ch -= m.creator_rug_ratio * 100
        if m.creator_prior_tokens == 0:
            ch -= 15  # geçmiş yok => belirsizlik
    creator_history = _clamp(ch)
    breakdown["creator_history"] = {
        "creator_is_rugger": m.creator_is_rugger,
        "creator_rug_ratio": round(m.creator_rug_ratio, 3),
        "creator_prior_tokens": m.creator_prior_tokens,
        "value": round(creator_history, 1),
    }

    # --- liquidity_quality (%15) — aşamaya göre ölçek ---
    if is_bonding:
        # bonding'de likidite bonding curve'e bağlı; daha düşük referans
        liq_ref = 5.0
    else:
        liq_ref = 50.0
    lq = _clamp((m.liquidity_sol / liq_ref) * 100)
    if m.fake_liquidity_suspected:
        lq *= 0.2
    liquidity_quality = _clamp(lq)
    breakdown["liquidity_quality"] = {
        "liquidity_sol": round(m.liquidity_sol, 3),
        "market_cap_usd": round(m.market_cap_usd, 2),
        "volume_24h_usd": round(m.volume_24h_usd, 2),
        "fake_liquidity_suspected": m.fake_liquidity_suspected,
        "value": round(liquidity_quality, 1),
    }

    # --- organic_growth (%10) ---
    og = _clamp(50 + m.holder_growth_rate * 10)
    # alıcı/satıcı dengesi: 1 civarı sağlıklı; aşırı satıcı kötü
    if m.buyer_seller_ratio < 1:
        og -= (1 - m.buyer_seller_ratio) * 40
    organic_growth = _clamp(og)
    breakdown["organic_growth"] = {
        "holder_growth_rate": round(m.holder_growth_rate, 3),
        "buyer_seller_ratio": round(m.buyer_seller_ratio, 3),
        "value": round(organic_growth, 1),
    }

    # --- trade_behavior (%10) ---
    tb = _clamp(100 - m.wash_trading_score * 70 - m.sudden_dump_risk * 50)
    trade_behavior = _clamp(tb)
    breakdown["trade_behavior"] = {
        "wash_trading_score": round(m.wash_trading_score, 3),
        "sudden_dump_risk": round(m.sudden_dump_risk, 3),
        "value": round(trade_behavior, 1),
    }

    raw_total = (
        w["security"] * security
        + w["holder_distribution"] * holder_distribution
        + w["creator_history"] * creator_history
        + w["liquidity_quality"] * liquidity_quality
        + w["organic_growth"] * organic_growth
        + w["trade_behavior"] * trade_behavior
    )

    # Güven: çok yeni token => düşük güven, puanı nötr 50'ye çek.
    confidence = _token_confidence(m)
    total = round(_clamp(raw_total * confidence + 50.0 * (1 - confidence)), 1)

    # --- Kritik vetolar ---
    veto_reasons: list[str] = []
    if m.mint_authority_active:
        veto_reasons.append("Aktif mint yetkisi")
    if m.freeze_authority_active:
        veto_reasons.append("Aktif freeze yetkisi")
    if m.creator_is_rugger:
        veto_reasons.append("Doğrulanmış rugger creator")
    if m.insider_supply_pct >= 0.5:
        veto_reasons.append("Aşırı insider arzı")
    if m.honeypot_suspected or not m.sellable:
        veto_reasons.append("Honeypot / satılamama belirtisi")
    if m.fake_liquidity_suspected:
        veto_reasons.append("Sahte likidite")
    if m.wash_trading_score >= 0.8:
        veto_reasons.append("Çok kuvvetli wash trading")
    vetoed = bool(veto_reasons)

    tracked = (not vetoed) and total >= threshold

    return TokenScoreResult(
        total=total,
        security=round(security, 1),
        holder_distribution=round(holder_distribution, 1),
        creator_history=round(creator_history, 1),
        liquidity_quality=round(liquidity_quality, 1),
        organic_growth=round(organic_growth, 1),
        trade_behavior=round(trade_behavior, 1),
        breakdown=breakdown,
        vetoed=vetoed,
        veto_reasons=veto_reasons,
        confidence=confidence,
        tracked=tracked,
    )


def _token_confidence(m: TokenMetrics) -> float:
    age_factor = min(1.0, m.age_seconds / 3600.0)  # 1 saat ve üzeri tam güven (yaş yönü)
    holder_factor = min(1.0, m.unique_holders / 50.0)
    vol_factor = min(1.0, m.volume_24h_usd / 5000.0)
    return round(0.3 + 0.3 * age_factor + 0.2 * holder_factor + 0.2 * vol_factor, 3)
