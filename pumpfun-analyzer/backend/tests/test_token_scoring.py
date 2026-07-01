from app.core.scoring.token_scoring import TokenMetrics, score_token


def _healthy_graduated():
    return TokenMetrics(
        stage="graduated",
        age_seconds=7 * 86400,
        mint_authority_active=False,
        freeze_authority_active=False,
        metadata_mutable=False,
        sellable=True,
        top10_pct=0.18,
        top20_pct=0.28,
        unique_holders=800,
        insider_supply_pct=0.05,
        sniper_ratio=0.05,
        creator_is_rugger=False,
        creator_rug_ratio=0.0,
        creator_prior_tokens=3,
        liquidity_sol=120,
        market_cap_usd=500000,
        volume_24h_usd=200000,
        holder_growth_rate=2.0,
        buyer_seller_ratio=1.2,
        wash_trading_score=0.05,
        sudden_dump_risk=0.1,
    )


def test_healthy_token_tracked():
    res = score_token(_healthy_graduated())
    assert res.vetoed is False
    assert res.total >= 70
    assert res.tracked is True
    assert res.breakdown["security"]["value"] == 100.0


def test_mint_authority_vetoes():
    m = _healthy_graduated()
    m.mint_authority_active = True
    res = score_token(m)
    assert res.vetoed is True
    assert "Aktif mint yetkisi" in res.veto_reasons
    assert res.tracked is False


def test_honeypot_vetoes():
    m = _healthy_graduated()
    m.sellable = False
    res = score_token(m)
    assert res.vetoed is True
    assert res.tracked is False


def test_rugger_creator_vetoes():
    m = _healthy_graduated()
    m.creator_is_rugger = True
    res = score_token(m)
    assert res.vetoed is True
    assert res.breakdown["creator_history"]["value"] == 0.0


def test_excessive_insider_supply_vetoes():
    m = _healthy_graduated()
    m.insider_supply_pct = 0.6
    res = score_token(m)
    assert res.vetoed is True
    assert "Aşırı insider arzı" in res.veto_reasons


def test_bonding_token_lower_liquidity_expectation():
    # Aynı düşük likidite bonding'de mezuna göre daha az cezalandırılmalı
    m_bond = _healthy_graduated()
    m_bond.stage = "bonding"
    m_bond.liquidity_sol = 4
    m_bond.age_seconds = 600
    m_bond.unique_holders = 40
    m_grad = _healthy_graduated()
    m_grad.liquidity_sol = 4
    res_bond = score_token(m_bond)
    res_grad = score_token(m_grad)
    assert res_bond.liquidity_quality > res_grad.liquidity_quality
