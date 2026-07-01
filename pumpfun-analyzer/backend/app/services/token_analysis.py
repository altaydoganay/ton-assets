"""Anlık (on-the-fly) token analizi.

Canlı akışta takip edilen bir cüzdan bir tokeni aldığında, o token henüz
puanlanmamış olabilir. Bu servis mevcut sağlayıcılarla (Helius/RPC + market)
token için **hafif** ama gerçek bir analiz üretir ve `token_scoring` ile puanlar:

  - Güvenlik (%30): mint/freeze authority (zincir üstü mint info)
  - Likidite/piyasa (%15): DexScreener/Birdeye likidite, hacim, MC/FDV
  - Holder yoğunluğu (kısmi, %20'nin parçası): getTokenLargestAccounts ile ilk-10/20

Elde edilemeyen alanlar (insider arzı, sniper oranı, wash trading) güvenli/nötr
bırakılır ve **düşük güven (confidence)** ile raporlanır — eksik veri kesin bilgi
gibi sunulmaz. Tam holder de-etiketleme ileride genişletilebilir.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..adapters.base import ChainProvider, MarketProvider
from ..adapters.pumpfun import infer_stage
from ..core.scoring.token_scoring import TokenMetrics, TokenScoreResult, score_token
from ..models import Token, TokenStatus
from .analysis_service import get_or_create_token, persist_token_score
from .settings_service import get_setting

logger = logging.getLogger(__name__)


@dataclass
class TokenAssessment:
    token: Token
    total: float
    vetoed: bool
    veto_reasons: list
    liquidity_sol: float
    cached: bool


def assess_token(
    db: Session, mint: str, chain: ChainProvider, market: MarketProvider, cache_seconds: int = 45
) -> TokenAssessment:
    """Canlı alım yolu için hızlı token değerlendirmesi.

    Token son `cache_seconds` içinde puanlandıysa yeniden analiz ETMEZ; saklı
    puanı kullanır (anında karar = düşük gecikme). Aksi halde anlık analiz yapar.
    """
    token = db.query(Token).filter(Token.mint == mint).first()
    if token and token.latest_score is not None and token.last_analyzed is not None:
        la = token.last_analyzed
        if la.tzinfo is None:
            la = la.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - la).total_seconds()
        if age < cache_seconds:
            return TokenAssessment(
                token=token,
                total=token.latest_score,
                vetoed=(token.status == TokenStatus.vetoed.value),
                veto_reasons=list(token.risk_flags or []),
                liquidity_sol=float((token.metrics or {}).get("liquidity_sol", 0.0)),
                cached=True,
            )
    token, result = analyze_token(db, mint, chain, market)
    return TokenAssessment(
        token=token,
        total=result.total,
        vetoed=result.vetoed,
        veto_reasons=result.veto_reasons,
        liquidity_sol=float((token.metrics or {}).get("liquidity_sol", 0.0)),
        cached=False,
    )


def build_token_metrics(mint: str, chain: ChainProvider, market: MarketProvider) -> TokenMetrics:
    m = TokenMetrics(mint_authority_active=False, freeze_authority_active=False)

    # --- Zincir üstü güvenlik ---
    try:
        info = chain.get_mint_info(mint) or {}
        m.mint_authority_active = bool(info.get("mintAuthority"))
        m.freeze_authority_active = bool(info.get("freezeAuthority"))
    except Exception as exc:  # noqa: BLE001
        logger.info("mint info alınamadı %s: %s", mint, exc)

    # --- Holder yoğunluğu (kısmi) ---
    try:
        supply_res = chain.get_token_supply(mint) or {}
        supply = float((supply_res.get("value") or {}).get("uiAmount") or 0) if isinstance(supply_res, dict) else 0
        largest = getattr(chain, "get_token_largest_accounts", lambda _m: [])(mint)
        amounts = sorted(
            (float((a.get("uiAmount") if "uiAmount" in a else (a.get("amount") or 0)) or 0) for a in largest),
            reverse=True,
        )
        if supply > 0 and amounts:
            m.top10_pct = min(1.0, sum(amounts[:10]) / supply)
            m.top20_pct = min(1.0, sum(amounts[:20]) / supply)
        m.unique_holders = len(amounts)  # en az ilk-N; gerçek toplam daha yüksek olabilir
    except Exception as exc:  # noqa: BLE001
        logger.info("holder verisi alınamadı %s: %s", mint, exc)

    # --- Piyasa / likidite ---
    try:
        md = market.get_token_market(mint)
        # görsel/kimlik: veri varsa (ok olmasa bile isim/resim gelebilir) yakala
        m.name = md.name or m.name
        m.symbol = md.symbol or m.symbol
        m.image_url = md.image_url or m.image_url
        m.pair_url = md.pair_url or m.pair_url
        if md.ok:
            m.price_sol = float(md.price_sol or 0.0)
            m.price_usd = float(md.price_usd or 0.0)
            m.liquidity_usd = float(md.liquidity_usd or 0.0)
            m.market_cap_usd = md.market_cap_usd or 0.0
            m.fdv_usd = md.fdv_usd or 0.0
            m.volume_24h_usd = md.volume_24h_usd or 0.0
            m.pair_created_at = int(md.pair_created_at or 0)
            # likidite SOL'a çevir: sol_usd = price_usd / price_sol
            if md.liquidity_usd and md.price_usd and md.price_sol:
                sol_usd = md.price_usd / md.price_sol if md.price_sol else 0
                m.liquidity_sol = (md.liquidity_usd / sol_usd) if sol_usd else 0.0
            elif md.liquidity_sol:
                m.liquidity_sol = md.liquidity_sol
            # DexScreener'da çift varsa muhtemelen DEX'e mezun olmuş
            m.stage = infer_stage(graduated=(md.liquidity_usd or 0) > 0, has_pumpswap_pool=False, bonding_complete_pct=None)
            if md.pair_created_at:
                import time
                m.age_seconds = max(0.0, time.time() - md.pair_created_at / 1000.0)
        else:
            m.stage = "bonding"
    except Exception as exc:  # noqa: BLE001
        logger.info("market verisi alınamadı %s: %s", mint, exc)
        m.stage = "unknown"

    return m


def analyze_token(db: Session, mint: str, chain: ChainProvider, market: MarketProvider) -> tuple[Token, TokenScoreResult]:
    metrics = build_token_metrics(mint, chain, market)
    weights = get_setting(db, "token_weights")
    threshold = get_setting(db, "thresholds").get("token", 70.0)
    result = score_token(metrics, weights=weights, threshold=threshold)

    token = get_or_create_token(db, mint, stage=metrics.stage)
    token.stage = metrics.stage
    if metrics.name:
        token.name = metrics.name[:128]
    if metrics.symbol:
        token.symbol = metrics.symbol[:32]
    metrics_dict = {
        "name": metrics.name,
        "symbol": metrics.symbol,
        "image_url": metrics.image_url,
        "pair_url": metrics.pair_url,
        "liquidity_sol": metrics.liquidity_sol,
        "price_sol": metrics.price_sol,
        "price_usd": metrics.price_usd,
        "liquidity_usd": metrics.liquidity_usd,
        "market_cap_usd": metrics.market_cap_usd,
        "fdv_usd": metrics.fdv_usd,
        "volume_24h_usd": metrics.volume_24h_usd,
        "pair_created_at": metrics.pair_created_at,
        "unique_holders": metrics.unique_holders,
        "top10_pct": metrics.top10_pct,
        "insider_supply_pct": metrics.insider_supply_pct,
        "mint_authority_active": metrics.mint_authority_active,
        "freeze_authority_active": metrics.freeze_authority_active,
    }
    persist_token_score(db, token, result, metrics=metrics_dict)
    return token, result
