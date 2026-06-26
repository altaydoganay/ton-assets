"""Akıllı para mutabakatı (confluence) sinyali."""
from datetime import datetime, timedelta, timezone

from app.models import Swap, Wallet, WalletStatus
from app.services.signals import token_confluence

MINT = "CONFLUENCEMINT11111111111111111111111111111"


def _wallet(db, addr, status):
    db.add(Wallet(address=addr, status=status))


def _buy(db, addr, mint, when):
    db.add(Swap(signature=f"cf-{addr}-{mint}", wallet_address=addr, token_mint=mint, side="buy",
                sol_amount=1.0, token_amount=100, price_sol=0.01, fee_sol=0.0, venue="pumpfun",
                block_time=when, confirmation="confirmed"))


def test_confluence_counts_only_tracked_in_window(db):
    db.query(Swap).delete()
    db.query(Wallet).filter(Wallet.address.like("Conf%")).delete()
    a = "ConfAaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    b = "ConfBbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    c = "ConfCcccccccccccccccccccccccccccccccccccccc"  # takip DEĞİL
    d = "ConfDdddddddddddddddddddddddddddddddddddddd"  # takip ama ESKİ alım
    _wallet(db, a, WalletStatus.tracked.value)
    _wallet(db, b, WalletStatus.tracked.value)
    _wallet(db, c, WalletStatus.analyzed.value)
    _wallet(db, d, WalletStatus.tracked.value)
    db.commit()
    now = datetime.now(timezone.utc)
    _buy(db, a, MINT, now)
    _buy(db, b, MINT, now - timedelta(minutes=5))
    _buy(db, c, MINT, now)                       # takip değil => sayılmaz
    _buy(db, d, MINT, now - timedelta(minutes=90))  # pencere dışı => sayılmaz
    db.commit()
    assert token_confluence(db, MINT, window_minutes=30) == 2  # yalnızca a + b
