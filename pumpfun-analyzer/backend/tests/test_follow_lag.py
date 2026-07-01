"""Geç-giriş (follow-lag) kapısının MODA duyarlılığı.

CANLI: sıkı (chasing = gerçek para riski). PAPER/alerts: cömert (test görünürlüğü).
Gerçek-zamanlı WS yoksa copy olayları RPC poll ile dakikalar gecikmeyle gelir;
tek sıkı limit paper testinde tüm copy'leri boğuyordu.
"""
from app.trading.risk import RiskConfig, DayState, evaluate_buy


def _eval(mode: str, lag: float, **cfg_kw):
    cfg = RiskConfig(enabled=True, mode=mode, live_confirmed=True,
                     min_wallet_score=0, min_liquidity_sol=5, token_gate="safety",
                     max_follow_lag_seconds=30, max_follow_lag_seconds_paper=300,
                     paper_trade_sol=0.1, fixed_sol_amount=0.1, max_position_sol=1.0,
                     max_daily_spend_sol=10.0, **cfg_kw)
    return evaluate_buy(
        cfg, DayState(), wallet_address="Lead1", token_mint="Tok1",
        wallet_score=85, token_score=80, token_liquidity_sol=50,
        token_sellable=True, follow_lag_seconds=lag,
    )


def _has_lag_block(dec):
    return any("gecikmesi izleme penceresini aştı" in r for r in dec.reasons)


def test_paper_allows_late_copy_within_paper_window():
    # 120sn gecikme: canlı 30sn'yi aşar ama paper 300sn içinde → lag engeli YOK
    dec = _eval("paper", lag=120)
    assert not _has_lag_block(dec)
    assert dec.allowed is True


def test_live_blocks_late_copy_strictly():
    # aynı 120sn gecikme CANLI'da sıkı 30sn'yi aşar → engellenir
    dec = _eval("live", lag=120)
    assert _has_lag_block(dec)
    assert dec.allowed is False


def test_paper_still_blocks_ancient_copy():
    # 400sn: paper penceresini (300) de aşar → engellenir (sonsuz chasing değil)
    dec = _eval("paper", lag=400)
    assert _has_lag_block(dec)


def test_fresh_copy_allowed_both_modes():
    assert not _has_lag_block(_eval("paper", lag=5))
    assert not _has_lag_block(_eval("live", lag=5))


def test_lag_reason_includes_numbers():
    dec = _eval("live", lag=120)
    lag_reasons = [r for r in dec.reasons if "gecikmesi" in r]
    assert lag_reasons and "120sn" in lag_reasons[0] and "30sn" in lag_reasons[0]
