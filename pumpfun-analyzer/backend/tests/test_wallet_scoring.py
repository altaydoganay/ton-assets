from app.core.analysis.pnl import compute_performance, SwapEvent
from app.core.scoring.wallet_scoring import WalletSignals, score_wallet


def _build_good_swaps(n_tokens=12, trades_per_token=2):
    """Tutarlı, 30dk+ tutma, yüksek başarı oranlı sentetik geçmiş."""
    swaps = []
    t = 0
    for i in range(n_tokens):
        mint = f"MINT{i}"
        # iki tur al-sat (kâr)
        for _ in range(trades_per_token):
            swaps.append(SwapEvent(mint, "buy", 1.0, 100, 0.01, t))
            swaps.append(SwapEvent(mint, "sell", 1.4, 100, 0.01, t + 3600))  # 1 saat tut, kâr
            t += 7200
    return swaps


def test_strong_wallet_is_tracked():
    perf = compute_performance(_build_good_swaps())
    signals = WalletSignals(history_days=45, days_since_last_trade=1, transfer_noise_ratio=0.05)
    res = score_wallet(perf, signals)
    assert res.eligible is True
    assert res.vetoed is False
    assert res.total >= 70
    assert res.tracked is True
    # alt kırılımlar mevcut
    assert "performance" in res.breakdown
    assert res.breakdown["performance"]["win_rate"] == 1.0


def test_creator_is_vetoed():
    perf = compute_performance(_build_good_swaps())
    signals = WalletSignals(history_days=45, is_token_creator=True)
    res = score_wallet(perf, signals)
    assert res.vetoed is True
    assert res.tracked is False
    assert any("oluşturucu" in r for r in res.veto_reasons)


def test_copy_trader_vetoed():
    perf = compute_performance(_build_good_swaps())
    signals = WalletSignals(history_days=45, copy_confidence=0.85)
    res = score_wallet(perf, signals)
    assert res.vetoed is True
    assert res.tracked is False


def test_insufficient_sample_not_eligible():
    swaps = [
        SwapEvent("A", "buy", 1.0, 10, 0.0, 0),
        SwapEvent("A", "sell", 1.5, 10, 0.0, 3600),
    ]
    perf = compute_performance(swaps)
    signals = WalletSignals(history_days=5)
    res = score_wallet(perf, signals)
    assert res.eligible is False
    assert res.tracked is False
    assert len(res.eligibility_failures) > 0


def test_short_history_does_not_fail_by_itself():
    perf = compute_performance(_build_good_swaps())
    signals = WalletSignals(history_days=0.05, days_since_last_trade=1, transfer_noise_ratio=0.05)
    res = score_wallet(perf, signals)
    assert res.eligible is True
    assert not any("Geçmiş <" in f for f in res.eligibility_failures)


def test_idle_wallet_not_eligible():
    """Aktif cüzdana öncelik: uzun süredir işlem yapmamış cüzdan takibe alınmaz."""
    perf = compute_performance(_build_good_swaps())
    idle = score_wallet(perf, WalletSignals(history_days=45, days_since_last_trade=20))
    assert idle.eligible is False
    assert any("aktif değil" in f for f in idle.eligibility_failures)
    active = score_wallet(perf, WalletSignals(history_days=45, days_since_last_trade=3))
    assert active.eligible is True


def test_weights_are_configurable():
    perf = compute_performance(_build_good_swaps())
    # copy riski var (veto eşiğinin altında) => safety alt puanı düşük
    sig = WalletSignals(history_days=45, days_since_last_trade=1, copy_confidence=0.6)
    default = score_wallet(perf, sig)
    # Ağırlığı tamamen güvenliğe verirsek toplam düşmeli
    safety_heavy = score_wallet(
        perf, sig,
        weights={"performance": 0.0, "consistency": 0.0, "risk": 0.0,
                 "organic": 0.0, "hold_quality": 0.0, "safety": 1.0, "recency": 0.0},
    )
    assert safety_heavy.total < default.total
