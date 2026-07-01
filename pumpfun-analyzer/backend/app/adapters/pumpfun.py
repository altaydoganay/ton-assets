"""Pump.fun / PumpSwap program referansları ve işlem normalleştirme.

ÖNEMLİ: Program adresleri tahmin edilmez; aşağıdaki adresler Pump.fun'ın
doğrulanmış mainnet program id'leridir ve `swap_detection` ile paylaşılır.
Pump.fun arayüzü scrape edilmez — öncelik zincir üstü veri ve bu program
id'leridir. Yeni/değişen yollar için adresler tek bir yerden güncellenir.

Mezuniyet (graduation): Pump.fun bonding curve dolunca likidite PumpSwap'e
taşınır. `infer_stage` token verisinden aşamayı çıkarır.
"""
from __future__ import annotations

from ..core.analysis.swap_detection import (  # tek kaynak
    PUMP_FUN_PROGRAM,
    PUMP_SWAP_PROGRAM,
    RAYDIUM_AMM_V4,
    NormalizedTx,
    detect_swap,
)


def normalize_rpc_transaction(raw: dict, fee_lamports_per_sol: int = 1_000_000_000) -> NormalizedTx | None:
    """jsonParsed RPC işlemini NormalizedTx'e dönüştürür.

    pre/postBalances ve pre/postTokenBalances kullanılarak owner bazlı net
    SOL ve token değişimleri hesaplanır.
    """
    if not raw:
        return None
    meta = raw.get("meta") or {}
    tx = raw.get("transaction") or {}
    message = tx.get("message") or {}
    sig = (tx.get("signatures") or [None])[0]
    block_time = raw.get("blockTime") or 0
    slot = raw.get("slot")
    fee = (meta.get("fee") or 0) / fee_lamports_per_sol

    account_keys = message.get("accountKeys") or []
    def _key(i):
        k = account_keys[i] if i < len(account_keys) else None
        return k.get("pubkey") if isinstance(k, dict) else k

    # SOL deltaları (lamports -> SOL)
    sol_deltas: dict[str, float] = {}
    pre = meta.get("preBalances") or []
    post = meta.get("postBalances") or []
    for i in range(min(len(pre), len(post))):
        owner = _key(i)
        if owner is None:
            continue
        sol_deltas[owner] = sol_deltas.get(owner, 0.0) + (post[i] - pre[i]) / fee_lamports_per_sol

    # Token deltaları
    token_deltas: dict[tuple[str, str], float] = {}
    pre_tb = {(b.get("owner"), b.get("mint")): b for b in (meta.get("preTokenBalances") or [])}
    post_tb = {(b.get("owner"), b.get("mint")): b for b in (meta.get("postTokenBalances") or [])}
    keys = set(pre_tb) | set(post_tb)
    for k in keys:
        owner, mint = k
        if owner is None or mint is None:
            continue
        pre_amt = float((pre_tb.get(k, {}).get("uiTokenAmount") or {}).get("uiAmount") or 0)
        post_amt = float((post_tb.get(k, {}).get("uiTokenAmount") or {}).get("uiAmount") or 0)
        token_deltas[(owner, mint)] = post_amt - pre_amt

    # Programlar
    programs: list[str] = []
    for ix in message.get("instructions") or []:
        pid = ix.get("programId")
        if pid:
            programs.append(pid)
    for inner in meta.get("innerInstructions") or []:
        for ix in inner.get("instructions") or []:
            pid = ix.get("programId")
            if pid:
                programs.append(pid)

    return NormalizedTx(
        signature=sig or "",
        block_time=block_time,
        slot=slot,
        fee_sol=fee,
        programs=programs,
        sol_deltas=sol_deltas,
        token_deltas=token_deltas,
        confirmation="finalized" if raw.get("blockTime") else "confirmed",
        raw=raw,
    )


# Helius enhanced `source` -> doğrulanmış program id eşlemesi (venue tespiti için).
_SOURCE_PROGRAM = {
    "PUMP_FUN": PUMP_FUN_PROGRAM,
    "PUMP_AMM": PUMP_SWAP_PROGRAM,
    "PUMPSWAP": PUMP_SWAP_PROGRAM,
    "RAYDIUM": RAYDIUM_AMM_V4,
}


def normalize_enhanced_transaction(enh: dict, fee_lamports_per_sol: int = 1_000_000_000) -> NormalizedTx | None:
    """Helius Enhanced Transactions formatını NormalizedTx'e dönüştürür.

    `accountData[].nativeBalanceChange` ve `tokenBalanceChanges[]` alanları zaten
    owner bazlı net SOL/token değişimini verir; bu sayede aynı `detect_swap` /
    `extract_buyers` mantığı (tek kaynak) yeniden kullanılır. Tek bir enhanced
    istek 100 işlem döndürdüğünden cüzdan başına ~100 ayrı RPC çağrısı yapılmaz.
    """
    if not enh or enh.get("transactionError"):
        return None

    sig = enh.get("signature") or ""
    block_time = int(enh.get("timestamp") or 0)
    slot = enh.get("slot")
    fee = (enh.get("fee") or 0) / fee_lamports_per_sol

    sol_deltas: dict[str, float] = {}
    token_deltas: dict[tuple[str, str], float] = {}
    for ad in enh.get("accountData") or []:
        acct = ad.get("account")
        nbc = ad.get("nativeBalanceChange")
        if acct and nbc:
            sol_deltas[acct] = sol_deltas.get(acct, 0.0) + nbc / fee_lamports_per_sol
        for tbc in ad.get("tokenBalanceChanges") or []:
            owner = tbc.get("userAccount")
            mint = tbc.get("mint")
            raw = tbc.get("rawTokenAmount") or {}
            try:
                amount = int(raw.get("tokenAmount") or 0)
                decimals = int(raw.get("decimals") or 0)
            except (TypeError, ValueError):
                continue
            if not owner or not mint or amount == 0:
                continue
            val = amount / (10 ** decimals)
            token_deltas[(owner, mint)] = token_deltas.get((owner, mint), 0.0) + val

    # Programlar: instructions + inner + source eşlemesi (venue tespiti garanti).
    programs: list[str] = []
    for ix in enh.get("instructions") or []:
        pid = ix.get("programId")
        if pid:
            programs.append(pid)
        for inner in ix.get("innerInstructions") or []:
            ipid = inner.get("programId")
            if ipid:
                programs.append(ipid)
    src_prog = _SOURCE_PROGRAM.get(enh.get("source") or "")
    if src_prog:
        programs.append(src_prog)

    return NormalizedTx(
        signature=sig,
        block_time=block_time,
        slot=slot,
        fee_sol=fee,
        programs=programs,
        sol_deltas=sol_deltas,
        token_deltas=token_deltas,
        confirmation="finalized",
        raw=enh,
    )


def infer_stage(graduated: bool | None, has_pumpswap_pool: bool, bonding_complete_pct: float | None) -> str:
    if graduated or has_pumpswap_pool:
        return "graduated"
    if bonding_complete_pct is not None and bonding_complete_pct >= 0.9:
        return "graduating"
    return "bonding"


__all__ = [
    "PUMP_FUN_PROGRAM",
    "PUMP_SWAP_PROGRAM",
    "RAYDIUM_AMM_V4",
    "normalize_rpc_transaction",
    "normalize_enhanced_transaction",
    "infer_stage",
    "detect_swap",
]
