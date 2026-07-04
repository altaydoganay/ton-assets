"""AI 8 bileşenli avcı token skoru: bant/veto/veri-yoksa nötr davranış."""
from app.core.scoring.ai_token_scoring import score_ai_token, band_for, WEIGHTS


def test_weights_sum_to_100():
    assert abs(sum(WEIGHTS.values()) - 100.0) < 1e-6


def test_bands():
    assert band_for(50) == "reject"
    assert band_for(72) == "watch"
    assert band_for(83) == "scout"
    assert band_for(90) == "confirm"
    assert band_for(96) == "strong"


def test_thin_data_is_neutral_not_zero():
    # tape yok, metrics yok → nötr (~50-65), 0 değil, 100 değil
    res = score_ai_token({}, None, age_seconds=0, sellable=True)
    assert 45 <= res["total"] <= 70
    assert res["have_tape"] is False
    assert set(res["breakdown"].keys()) == set(WEIGHTS.keys())


def test_healthy_early_token_scores_high():
    metrics = {"name": "Sonic", "symbol": "SONIC", "image_url": "x",
               "top10_pct": 0.18, "unique_holders": 60, "curve_sol_est": 20.0,
               "creator_prior_tokens": 3, "creator_rug_ratio": 0.0}
    tape = {"trades": 40, "buys": 30, "sells": 10, "unique_buyers": 24,
            "buyers_first_30s": 10, "top_buyer_share": 0.12, "net_sol": 6.0,
            "buy_sell_ratio": 3.0}
    res = score_ai_token(metrics, tape, age_seconds=120, sellable=True)
    assert res["total"] >= 80          # scout+ bandı
    assert res["breakdown"]["organic_buyers"]["value"] >= 80


def test_single_wallet_pump_scores_low():
    metrics = {"top10_pct": 0.8, "unique_holders": 3}
    tape = {"trades": 30, "buys": 28, "sells": 0, "unique_buyers": 2,
            "buyers_first_30s": 1, "top_buyer_share": 0.9, "net_sol": 5.0,
            "buy_sell_ratio": 28.0}
    res = score_ai_token(metrics, tape, age_seconds=60, sellable=True)
    assert res["total"] < 70           # reject/watch
    assert res["breakdown"]["sellability"]["value"] <= 30   # hiç satış yok


def test_not_sellable_zeros_sellability():
    res = score_ai_token({}, {"trades": 10, "buys": 8, "sells": 2}, sellable=False)
    assert res["breakdown"]["sellability"]["value"] == 0.0
