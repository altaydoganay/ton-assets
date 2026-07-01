from app.core.classification.copy_trader import TradeRef, detect_copy_trader
from app.core.classification.rugger import CreatedToken, detect_rugger
from app.core.classification.sniper import detect_sniper
from app.core.classification.insider import detect_insider_cluster


def test_copy_trader_detected_across_tokens():
    leader = []
    candidate = []
    for i in range(5):
        mint = f"M{i}"
        leader.append(TradeRef(mint, "buy", block_time=i * 1000, sol_amount=1.0))
        # candidate aynı tokeni ~30sn sonra aynı yönde, benzer miktarla alır
        candidate.append(TradeRef(mint, "buy", block_time=i * 1000 + 30, sol_amount=1.0))
    res = detect_copy_trader(candidate, leader)
    assert res.is_copy is True
    assert res.confidence >= 0.6
    assert res.matched_tokens >= 3
    assert res.median_lag_seconds == 30


def test_single_match_not_copy():
    leader = [TradeRef("M0", "buy", 1000, 1.0)]
    candidate = [TradeRef("M0", "buy", 1030, 1.0)]
    res = detect_copy_trader(candidate, leader)
    assert res.is_copy is False  # tek eşleşme yeterli değil


def test_unrelated_wallet_not_copy():
    leader = [TradeRef(f"L{i}", "buy", i * 100, 1.0) for i in range(5)]
    candidate = [TradeRef(f"C{i}", "buy", i * 100, 1.0) for i in range(5)]
    res = detect_copy_trader(candidate, leader)
    assert res.is_copy is False


def test_rugger_creator_vetoes():
    res = detect_rugger("W", [], is_creator_of_analyzed=True)
    assert res.veto is True


def test_rugger_history():
    tokens = [CreatedToken(f"M{i}", i, abandoned=True, dumped_on_holders=True, survived_days=0.2) for i in range(6)]
    res = detect_rugger("W", tokens)
    assert res.is_rugger is True
    assert res.confidence >= 0.6


def test_sniper_detection():
    res = detect_sniper(first_buy_offsets=[2, 5, 1, 3, 8], hold_times=[60, 120, 90], first_block_buys=2)
    assert res.is_sniper is True
    assert res.is_scalper is True


def test_clean_wallet_not_sniper():
    res = detect_sniper(first_buy_offsets=[3600, 7200], hold_times=[5000, 8000], first_block_buys=0)
    assert res.is_sniper is False
    assert res.is_scalper is False


def test_insider_cluster():
    res = detect_insider_cluster(funded_by_same_source=True, co_buy_ratio=0.6, cluster_size=4, shared_token_ratio=0.8)
    assert res.is_insider is True
