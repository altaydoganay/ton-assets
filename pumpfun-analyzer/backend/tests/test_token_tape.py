"""Erken-token tape: sinyal türetme + erken kalite skoru."""
from app.services.token_tape import TokenTape, early_quality_score


def test_tape_signals_basic():
    t = TokenTape(window_seconds=120)
    now = 1000.0
    t.record("M", "a", "buy", 1.0, now)
    t.record("M", "b", "buy", 1.0, now + 1)
    t.record("M", "c", "buy", 1.0, now + 2)
    t.record("M", "d", "buy", 1.0, now + 35)   # 30sn dışında
    t.record("M", "a", "sell", 0.5, now + 40)
    sig = t.signals("M", now=now + 41)
    assert sig["unique_buyers"] == 4
    assert sig["buyers_first_30s"] == 3
    assert sig["buys"] == 4 and sig["sells"] == 1
    assert sig["top_buyer_share"] == 0.25       # her cüzdan 1.0 / toplam 4.0


def test_tape_single_wallet_pump_is_low_quality():
    t = TokenTape()
    now = 1000.0
    for i in range(8):
        t.record("W", "whale", "buy", 1.0, now + i)   # tek cüzdan
    sig = t.signals("W", now=now + 9)
    assert sig["top_buyer_share"] == 1.0
    assert early_quality_score(sig) < 40           # tek cüzdan cezalandırılır


def test_tape_window_prunes_old_trades():
    t = TokenTape(window_seconds=60)
    now = 1000.0
    t.record("X", "a", "buy", 1.0, now - 120)      # pencere dışı
    t.record("X", "b", "buy", 1.0, now)
    sig = t.signals("X", now=now)
    assert sig["unique_buyers"] == 1


def test_early_quality_neutral_when_thin():
    assert early_quality_score(None) == 50.0
    assert early_quality_score({"trades": 2}) == 50.0


def test_dev_sold_detection():
    t = TokenTape()
    now = 1000.0
    t.record("D", "dev", "buy", 1.0, now)
    t.record("D", "x", "buy", 1.0, now + 1)
    assert t.dev_sold("D", "dev", now=now + 2) is False
    t.record("D", "dev", "sell", 0.5, now + 3)
    assert t.dev_sold("D", "dev", now=now + 4) is True
