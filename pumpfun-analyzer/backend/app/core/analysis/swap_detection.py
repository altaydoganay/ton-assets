"""Swap (gerçek al-sat) tespiti ve transfer ayrıştırması.

Pump.fun / PumpSwap / Raydium işlem yollarındaki SOL <-> token takaslarını
gerçek swap olarak; airdrop, basit SPL transferi, NFT/spam hareketlerini ve
hesaplar arası kendi-transferleri NON-swap olarak sınıflandırır.

Bu modül zincir-bağımsız bir "InstructionView" / "TransactionView" sözlüğü
üzerinde çalışır. Adapter katmanı (Helius/RPC) ham işlemi bu normalleştirilmiş
yapıya dönüştürür; böylece sınıflandırma mantığı tek bir yerde test edilebilir.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Güncel (doğrulanmış) program adresleri. Adapter katmanı ayrıca ham program
# id'lerini de iletebilir; burada yalnızca sınıflandırma için referans tutarız.
PUMP_FUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMP_SWAP_PROGRAM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
RAYDIUM_AMM_V4 = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
SYSTEM_PROGRAM = "11111111111111111111111111111111"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"

KNOWN_SWAP_VENUES = {
    PUMP_FUN_PROGRAM: "pumpfun",
    PUMP_SWAP_PROGRAM: "pumpswap",
    RAYDIUM_AMM_V4: "raydium",
}

WSOL_MINT = "So11111111111111111111111111111111111111112"


@dataclass
class BalanceDelta:
    """Bir cüzdanın işlem sonucundaki bakiye değişimi."""
    owner: str
    mint: str
    amount: float  # pozitif: arttı, negatif: azaldı


@dataclass
class NormalizedTx:
    signature: str
    block_time: int
    slot: int | None
    fee_sol: float
    programs: list[str]
    sol_deltas: dict[str, float]                 # owner -> net SOL değişimi
    token_deltas: dict[tuple[str, str], float]   # (owner, mint) -> net token değişimi
    confirmation: str = "confirmed"
    raw: dict[str, Any] | None = None


@dataclass
class DetectedSwap:
    signature: str
    wallet_address: str
    token_mint: str
    side: str            # "buy" | "sell"
    sol_amount: float    # mutlak SOL hareketi (ücret hariç)
    token_amount: float
    price_sol: float
    fee_sol: float
    venue: str | None
    block_time: int
    slot: int | None
    confirmation: str


def _is_swap_venue(programs: list[str]) -> str | None:
    for p in programs:
        if p in KNOWN_SWAP_VENUES:
            return KNOWN_SWAP_VENUES[p]
    return None


def detect_swap(tx: NormalizedTx, wallet: str, dust_sol: float = 0.0005) -> DetectedSwap | None:
    """Bir işlemin verilen cüzdan için gerçek bir swap olup olmadığını belirler.

    Kurallar:
    - İşlem bilinen bir swap programını içermeli (pumpfun/pumpswap/raydium).
    - Cüzdanın SOL bakiyesi *ve* bir SPL token bakiyesi ters yönde değişmeli.
      (SOL azalır + token artar => buy; SOL artar + token azalır => sell)
    - Yalnızca token bakiyesi değişip SOL değişmiyorsa bu bir transfer/airdrop
      kabul edilir ve None döner.
    - Çok küçük (dust) SOL hareketleri swap sayılmaz.
    """
    venue = _is_swap_venue(tx.programs)
    if venue is None:
        return None

    sol_delta = tx.sol_deltas.get(wallet, 0.0)
    # Ücreti SOL değişiminden ayır: net ekonomik SOL hareketi.
    # buy'da cüzdan SOL kaybeder (negatif), sell'de SOL kazanır (pozitif).
    # Ücret her zaman cüzdandan çıkar; analiz için fee'yi ayrı raporlarız.

    # Bu cüzdana ait token değişimlerini bul (WSOL hariç).
    token_changes = {
        mint: amt
        for (owner, mint), amt in tx.token_deltas.items()
        if owner == wallet and mint != WSOL_MINT and abs(amt) > 0
    }
    if not token_changes:
        return None

    # En büyük mutlak token değişimi ana takas varlığıdır.
    mint, token_amt = max(token_changes.items(), key=lambda kv: abs(kv[1]))

    sol_moved = abs(sol_delta)
    if sol_moved < dust_sol:
        # SOL hareketi yok => transfer/airdrop, swap değil.
        return None

    if token_amt > 0 and sol_delta < 0:
        side = "buy"
    elif token_amt < 0 and sol_delta > 0:
        side = "sell"
    else:
        # SOL ve token aynı yönde değişti => tutarsız, swap olarak sayma.
        return None

    token_amount = abs(token_amt)
    price = sol_moved / token_amount if token_amount else 0.0

    return DetectedSwap(
        signature=tx.signature,
        wallet_address=wallet,
        token_mint=mint,
        side=side,
        sol_amount=sol_moved,
        token_amount=token_amount,
        price_sol=price,
        fee_sol=tx.fee_sol,
        venue=venue,
        block_time=tx.block_time,
        slot=tx.slot,
        confirmation=tx.confirmation,
    )


def is_transfer(tx: NormalizedTx, wallet: str) -> bool:
    """İşlem bu cüzdan için (swap değil) saf transfer/airdrop mı?"""
    return detect_swap(tx, wallet) is None and any(
        owner == wallet for (owner, _mint) in tx.token_deltas
    )


def extract_buyers(tx: NormalizedTx, dust_sol: float = 0.0005) -> list[tuple[str, str]]:
    """İşlemdeki ALICILARI (cüzdan, mint) döner — keşif için.

    Cüzdan SOL kaybedip (negatif) bir SPL token (WSOL hariç) kazandıysa o tokeni
    satın almıştır. Bilinen bir swap venue içermeyen işlemler (transfer/airdrop)
    elenir.
    """
    if _is_swap_venue(tx.programs) is None:
        return []
    buyers: list[tuple[str, str]] = []
    for (owner, mint), amt in tx.token_deltas.items():
        if mint == WSOL_MINT or amt <= 0:
            continue
        sol = tx.sol_deltas.get(owner, 0.0)
        if sol < -dust_sol:  # SOL harcadı + token aldı => alıcı
            buyers.append((owner, mint))
    return buyers
