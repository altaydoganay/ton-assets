"""Akıllı para sinyalleri — çok cüzdan takip etmenin getirdiği avantaj.

Confluence (mutabakat): aynı token'i KISA bir pencere içinde KAÇ FARKLI takip
cüzdanı aldı. 2+ bağımsız kaliteli cüzdanın aynı token'e girmesi, tek bir
cüzdanın alımından çok daha güçlü bir sinyaldir. İsteğe bağlı olarak işlem kapısı
olarak da kullanılabilir (min_confluence).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..models import Swap, Wallet, WalletStatus


def token_confluence(db: Session, mint: str, window_minutes: int = 30) -> int:
    """Son `window_minutes` içinde bu token'i ALAN farklı TAKİP cüzdanı sayısı."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    rows = (db.query(Swap.wallet_address)
            .filter(Swap.token_mint == mint, Swap.side == "buy", Swap.block_time >= cutoff)
            .distinct().all())
    buyers = {r[0] for r in rows}
    if not buyers:
        return 0
    tracked = {a for (a,) in db.query(Wallet.address)
               .filter(Wallet.status == WalletStatus.tracked.value,
                       Wallet.address.in_(buyers)).all()}
    return len(tracked)
