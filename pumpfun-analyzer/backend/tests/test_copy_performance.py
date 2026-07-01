"""Kopya performansı + otomatik eleme testleri."""
from app.models import PaperTrade, Wallet, WalletStatus
from app.services.copy_performance import (
    prune_underperformers,
    tracked_copy_stats,
    wallet_copy_stats,
)


def _clean(db):
    """Bu modüldeki testler prune'u TÜM takip cüzdanlarında çalıştırır; izolasyon
    için paylaşılan DB'deki takip cüzdanlarını ve paper işlemleri temizle."""
    db.query(PaperTrade).delete()
    db.query(Wallet).filter(Wallet.status == WalletStatus.tracked.value).delete()
    db.commit()


def _w(db, addr, score=80.0):
    w = Wallet(address=addr, status=WalletStatus.tracked.value, latest_score=score, risk_flags=[])
    db.add(w); db.commit()
    return w


def _sell(db, addr, mint, pnl):
    db.add(PaperTrade(wallet_address=addr, token_mint=mint, side="sell",
                      sol_amount=1.0, token_amount=100, price_sol=0.01,
                      realized_pnl_sol=pnl, is_open=False))
    db.commit()


def test_copy_stats_consecutive_losses(db):
    _clean(db)
    addr = "CopyStatW1111111111111111111111111111111111"
    _w(db, addr)
    # kâr, sonra 3 ardışık zarar
    _sell(db, addr, "M1", 0.5)
    _sell(db, addr, "M2", -0.2)
    _sell(db, addr, "M3", -0.1)
    _sell(db, addr, "M4", -0.3)
    st = wallet_copy_stats(db, addr)
    assert st["closed_trades"] == 4
    assert st["wins"] == 1 and st["losses"] == 3
    assert st["consecutive_losses"] == 3
    assert round(st["total_pnl_sol"], 4) == round(0.5 - 0.2 - 0.1 - 0.3, 4)


def test_prune_blocks_on_consecutive_losses(db):
    _clean(db)
    addr = "PruneLoser11111111111111111111111111111111"
    _w(db, addr)
    for i in range(5):  # 5 ardışık zarar
        _sell(db, addr, f"L{i}", -0.1)
    res = prune_underperformers(db, max_consecutive_losses=5, min_closed_trades=6, min_pnl_sol=0.0)
    assert res["pruned"] == 1
    db.refresh(db.query(Wallet).filter(Wallet.address == addr).first())
    assert db.query(Wallet).filter(Wallet.address == addr).first().status == WalletStatus.blocked.value


def test_prune_pnl_respects_min_closed(db):
    _clean(db)
    addr = "PruneTooFew2222222222222222222222222222222"
    _w(db, addr)
    # 3 kayıp (PnL < 0) ama < min_closed 6 => yargılanmaz (ardışık devre dışı)
    _sell(db, addr, "A", -0.1); _sell(db, addr, "B", -0.1); _sell(db, addr, "C", -0.1)
    res = prune_underperformers(db, max_consecutive_losses=99, min_closed_trades=6, min_pnl_sol=0.0)
    assert res["pruned"] == 0
    assert db.query(Wallet).filter(Wallet.address == addr).first().status == WalletStatus.tracked.value


def test_prune_blocks_on_negative_pnl(db):
    _clean(db)
    addr = "PruneNegPnl333333333333333333333333333333"
    _w(db, addr)
    # 8 işlem, toplam PnL negatif (-0.4) => ele (ardışık devre dışı: max_consec=99)
    for pnl in [0.1, -0.1, 0.1, -0.1, -0.1, -0.1, -0.1, -0.1]:
        _sell(db, addr, "M", pnl)
    res = prune_underperformers(db, max_consecutive_losses=99, min_closed_trades=6, min_pnl_sol=0.0)
    assert res["pruned"] == 1


def test_prune_keeps_low_winrate_but_profitable(db):
    """ASIL NOKTA: düşük isabet ama bize PARA KAZANDIRAN cüzdan ELENMEZ.
    %25 başarı (2/8) ama yüksek kazanç/kayıp oranı => toplam PnL pozitif."""
    _clean(db)
    addr = "KeepProfit77777777777777777777777777777777"
    _w(db, addr)
    # 6 küçük kayıp (-0.05 each = -0.30) + 2 büyük kazanç (+0.40 each = +0.80) => +0.50
    for pnl in [0.4, -0.05, 0.4, -0.05, -0.05, -0.05, -0.05, -0.05]:
        _sell(db, addr, "M", pnl)
    st = wallet_copy_stats(db, addr)
    assert st["win_rate"] < 0.30 and st["total_pnl_sol"] > 0  # düşük isabet, pozitif PnL
    res = prune_underperformers(db, max_consecutive_losses=99, min_closed_trades=6, min_pnl_sol=0.0)
    assert res["pruned"] == 0
    assert db.query(Wallet).filter(Wallet.address == addr).first().status == WalletStatus.tracked.value


def test_prune_disabled_noop(db):
    _clean(db)
    addr = "PruneDisabled44444444444444444444444444444"
    _w(db, addr)
    for i in range(6):
        _sell(db, addr, f"X{i}", -0.1)
    res = prune_underperformers(db, enabled=False)
    assert res["pruned"] == 0
    assert db.query(Wallet).filter(Wallet.address == addr).first().status == WalletStatus.tracked.value


def test_tracked_copy_stats_sorted(db):
    _clean(db)
    a, b = "SortA55555555555555555555555555555555555555", "SortB66666666666666666666666666666666666666"
    _w(db, a); _w(db, b)
    _sell(db, a, "M", -0.3)
    _sell(db, b, "M", 0.4)
    rows = tracked_copy_stats(db)
    addrs = [r["wallet"] for r in rows if r["wallet"] in (a, b)]
    assert addrs.index(b) < addrs.index(a)  # kazançlı üstte
