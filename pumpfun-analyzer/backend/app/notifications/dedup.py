"""Bildirim deduplication.

Aynı işlem (transaction signature) için tekrar bildirim gönderilmez.
Dedup anahtarı: signature + wallet + token'ın SHA-256 özeti (sabit 64 karakter).

ÖNEMLİ: Düz metin "imza:cüzdan:token" ~178 karakterdi ve alerts.dedup_key
kolonu (varchar 160) için TAŞIYORDU → her alert insert'i StringDataRightTruncation
ile çöküyor, böylece tüm işlem akışı hata verip 0 işleme yol açıyordu. Özet (hash)
hem sabit kısa boylu hem de aynı (imza,cüzdan,token) için deterministiktir.
"""
from __future__ import annotations

import hashlib


def make_dedup_key(signature: str, wallet_address: str, token_mint: str) -> str:
    raw = f"{signature}:{wallet_address}:{token_mint}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()  # 64 karakter
