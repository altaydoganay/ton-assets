"""Bildirim deduplication.

Aynı işlem (transaction signature) için tekrar bildirim gönderilmez.
Dedup anahtarı: signature + wallet + token. Yeniden başlatma sonrasında da
çalışır çünkü gönderilen bildirimler `alerts` tablosunda kalıcıdır.
"""
from __future__ import annotations


def make_dedup_key(signature: str, wallet_address: str, token_mint: str) -> str:
    return f"{signature}:{wallet_address}:{token_mint}"
