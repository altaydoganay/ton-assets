"""Helius Enhanced Transactions yolu — derin + ucuz alım doğrulaması.

Gerçek ağ/kredi kullanmadan: Helius enhanced şemasına benzer sahte sayfalar
üreten bir sağlayıcı ile `ingest_wallet`'ın tek istekte 100 işlem yolunu test
eder. Aynı `detect_swap` mantığının enhanced veriden de doğru swap çıkardığını
ve eleme kriterlerini karşılayan bir geçmişin `tracked` olduğunu doğrular.
"""
import time

from app.adapters.base import ChainProvider
from app.adapters.pumpfun import normalize_enhanced_transaction
from app.core.analysis.swap_detection import PUMP_FUN_PROGRAM, detect_swap
from app.services.pipeline import ingest_wallet, analyze_wallet

WALLET = "EnhWallet1111111111111111111111111111111111"
_NOW = int(time.time())


def _enh(sig, ts, sol_lamports, tok_raw, mint, decimals=6, source="PUMP_FUN"):
    """Bir enhanced işlem (accountData tabanlı net değişimler)."""
    return {
        "signature": sig,
        "timestamp": ts,
        "slot": ts,
        "fee": 5000,
        "source": source,
        "transactionError": None,
        "instructions": [{"programId": PUMP_FUN_PROGRAM, "innerInstructions": []}],
        "accountData": [
            {
                "account": WALLET,
                "nativeBalanceChange": sol_lamports,
                "tokenBalanceChanges": [
                    {
                        "userAccount": WALLET,
                        "mint": mint,
                        "rawTokenAmount": {"tokenAmount": str(tok_raw), "decimals": decimals},
                    }
                ],
            }
        ],
    }


def test_normalize_enhanced_buy():
    enh = _enh("eb1", 1_700_000_000, -1_000_000_000, 100_000_000, "MintE")
    ntx = normalize_enhanced_transaction(enh)
    assert ntx is not None
    swap = detect_swap(ntx, WALLET)
    assert swap is not None
    assert swap.side == "buy"
    assert swap.venue == "pumpfun"
    assert abs(swap.token_amount - 100.0) < 1e-6   # 100_000_000 / 10^6
    assert abs(swap.sol_amount - 1.0) < 1e-6


def test_normalize_enhanced_skips_errored():
    enh = _enh("eb2", 1_700_000_000, -1_000_000_000, 100_000_000, "MintE")
    enh["transactionError"] = {"InstructionError": [0, "Custom"]}
    assert normalize_enhanced_transaction(enh) is None


class FakeEnhancedProvider(ChainProvider):
    """Enhanced address-history destekleyen sahte Helius sağlayıcı (sayfalı)."""
    name = "fake-enhanced"

    def __init__(self, txs):
        # en yeniden eskiye sıralı (Helius gibi)
        self._txs = list(reversed(txs))
        self.calls = 0

    def get_address_transactions(self, address, limit=100, before=None, until=None, tx_type=None):
        self.calls += 1
        start = 0
        if before:
            for i, t in enumerate(self._txs):
                if t["signature"] == before:
                    start = i + 1
                    break
        return self._txs[start:start + limit]

    # ChainProvider zorunlu yüzeyleri (bu testte kullanılmaz)
    def get_signatures_for_address(self, address, limit=100):
        return []

    def get_transaction(self, signature):
        return None

    def get_token_supply(self, mint):
        return None

    def get_mint_info(self, mint):
        return None


def _good_history():
    """6 token üzerinde 12 kapalı pozisyon (~her birinde 1 buy + 1 sell).

    İmzalar/mint'ler bu dosyaya ÖZGÜ önekle (ENH-) tutulur; store_swap imza
    bazlı idempotent olduğundan diğer testlerle çakışma (izolasyon) önlenir.
    """
    txs = []
    t = _NOW - 5_000_000  # ~58 gün önce başla; son işlem ~2 gün önce (aktif)
    for i in range(8):
        mint = f"MintENH{i}"
        for _ in range(3):
            txs.append(_enh(f"ENH-buy-{i}-{t}", t, -1_000_000_000, 100_000_000, mint))
            txs.append(_enh(f"ENH-sell-{i}-{t}", t + 3600, 1_400_000_000, -100_000_000, mint))
            t += 200_000  # geçmiş günlere yayılır
    return txs


def test_enhanced_ingest_uses_single_request_path(db):
    provider = FakeEnhancedProvider(_good_history())
    count = ingest_wallet(db, provider, WALLET, limit=150)
    assert count == 48                 # 24 buy + 24 sell (8 token × 3 tur)
    assert provider.calls <= 2         # 48 işlem tek/çift istekte; per-sig DEĞİL
    res = analyze_wallet(db, WALLET)
    assert res.eligible is True
    assert res.tracked is True
    assert res.total >= 70
