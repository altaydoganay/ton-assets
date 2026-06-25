"""İşlem alımı (ingestion) ve cüzdan analiz hattı (pipeline).

Akış:
  1. Chain provider'dan cüzdanın işlem imzaları + işlemleri çekilir.
  2. Her işlem NormalizedTx'e dönüştürülür; gerçek swap'lar tespit edilir
     (transfer/airdrop ayıklanır).
  3. Swap'lar `swaps` tablosuna idempotent (signature unique) yazılır.
  4. FIFO PnL + metrikler hesaplanır, sınıflandırıcılar çalıştırılır.
  5. Cüzdan puanlanır ve geçmişiyle saklanır.

Provider enjekte edilebilir; bu sayede canlı RPC olmadan, kaydedilmiş geçmiş
işlemlerle (replay) test edilebilir — "gerçek para kullanmadan replay".
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..adapters.base import ChainProvider
from ..adapters.pumpfun import normalize_rpc_transaction
from ..core.analysis.pnl import SwapEvent, compute_performance
from ..core.analysis.swap_detection import NormalizedTx, detect_swap
from ..core.classification.copy_trader import TradeRef, detect_copy_trader
from ..core.classification.sniper import detect_sniper
from ..core.scoring.wallet_scoring import WalletSignals, score_wallet
from ..models import Swap
from .analysis_service import get_or_create_wallet, persist_wallet_score
from .settings_service import get_setting


def store_swap(db: Session, swap) -> Swap | None:
    """Tespit edilmiş swap'ı idempotent yaz (signature benzersiz)."""
    existing = db.query(Swap).filter(Swap.signature == swap.signature).first()
    if existing:
        return existing
    row = Swap(
        signature=swap.signature,
        wallet_address=swap.wallet_address,
        token_mint=swap.token_mint,
        side=swap.side,
        sol_amount=swap.sol_amount,
        token_amount=swap.token_amount,
        price_sol=swap.price_sol,
        fee_sol=swap.fee_sol,
        slippage_est=swap.slippage_est if hasattr(swap, "slippage_est") else 0.0,
        venue=swap.venue,
        block_time=datetime.fromtimestamp(swap.block_time, tz=timezone.utc),
        slot=swap.slot,
        confirmation=swap.confirmation,
    )
    db.add(row)
    db.commit()
    return row


def ingest_wallet(db: Session, provider: ChainProvider, address: str, limit: int = 200) -> int:
    """Cüzdanın işlemlerini çekip swap'ları kaydeder. Kaydedilen swap sayısını döner."""
    sigs = provider.get_signatures_for_address(address, limit=limit)
    count = 0
    for s in sigs:
        sig = s.get("signature") if isinstance(s, dict) else s
        if not sig:
            continue
        raw = provider.get_transaction(sig)
        ntx = normalize_rpc_transaction(raw) if raw else None
        if ntx is None:
            continue
        swap = detect_swap(ntx, address)
        if swap is not None:
            store_swap(db, swap)
            count += 1
    return count


def analyze_wallet(
    db: Session,
    address: str,
    *,
    leader_trades: list[TradeRef] | None = None,
    token_birth_times: dict[str, int] | None = None,
    extra_signals: dict | None = None,
    persist: bool = True,
):
    """Kayıtlı swap'lara göre cüzdanı puanlar. persist=False ise sonucu sadece
    döner (veritabanına yazmaz) — kriter değişiminde toplu yeniden değerlendirme
    için gereksiz kayıt tutmamak adına."""
    swaps = (
        db.query(Swap)
        .filter(Swap.wallet_address == address)
        .order_by(Swap.block_time.asc())
        .all()
    )
    events = [
        SwapEvent(
            token_mint=s.token_mint,
            side=s.side,
            sol_amount=s.sol_amount,
            token_amount=s.token_amount,
            fee_sol=s.fee_sol,
            block_time=int(s.block_time.timestamp()),
        )
        for s in swaps
    ]
    perf = compute_performance(events)

    # --- sinyaller ---
    history_days = 0.0
    days_since_last = 0.0
    if events:
        first = min(e.block_time for e in events)
        last = max(e.block_time for e in events)
        history_days = (last - first) / 86400.0
        days_since_last = (datetime.now(timezone.utc).timestamp() - last) / 86400.0

    # transfer gürültüsü: kaydedilmemiş transferleri tahmin edemeyiz; metrikten gelir
    transfer_noise = (extra_signals or {}).get("transfer_noise_ratio", 0.0)

    # sniper / scalper
    first_buy_offsets = []
    if token_birth_times:
        seen = set()
        for e in events:
            if e.side == "buy" and e.token_mint not in seen and e.token_mint in token_birth_times:
                seen.add(e.token_mint)
                first_buy_offsets.append(e.block_time - token_birth_times[e.token_mint])
    hold_times = [t.hold_seconds for t in perf.closed_trades]
    sn = detect_sniper(first_buy_offsets, hold_times)

    # copy-trader
    copy_conf = 0.0
    if leader_trades:
        cand = [TradeRef(e.token_mint, e.side, e.block_time, e.sol_amount) for e in events]
        cr = detect_copy_trader(cand, leader_trades)
        copy_conf = cr.confidence

    signals = WalletSignals(
        rugger_confidence=(extra_signals or {}).get("rugger_confidence", 0.0),
        copy_confidence=copy_conf,
        sniper_confidence=sn.confidence if sn.is_sniper else sn.confidence * 0.5,
        scalper_confidence=1.0 if sn.is_scalper else 0.0,
        insider_confidence=(extra_signals or {}).get("insider_confidence", 0.0),
        is_token_creator=(extra_signals or {}).get("is_token_creator", False),
        history_days=history_days,
        days_since_last_trade=days_since_last,
        transfer_noise_ratio=transfer_noise,
    )

    weights = get_setting(db, "wallet_weights")
    eligibility = get_setting(db, "wallet_eligibility")
    threshold = get_setting(db, "thresholds").get("wallet", 70.0)

    result = score_wallet(perf, signals, weights=weights, eligibility=eligibility, threshold=threshold)
    wallet = get_or_create_wallet(db, address)
    metrics = {
        "swaps_analyzed": perf.swaps_analyzed,
        "closed_positions": perf.closed_positions,
        "open_positions": perf.open_positions,
        "win_rate": perf.win_rate,
        "realized_pnl_sol": perf.realized_pnl_sol,
        "profit_factor": None if perf.profit_factor == float("inf") else perf.profit_factor,
        "token_diversity": perf.token_diversity,
        "median_hold_seconds": perf.median_hold_seconds,
        "history_days": history_days,
    }
    if persist:
        persist_wallet_score(db, wallet, result, metrics=metrics, demote_below=max(0.0, threshold - 5))
    return result


def replay_transactions(db: Session, address: str, transactions: list[NormalizedTx]) -> int:
    """Kaydedilmiş NormalizedTx listesini hat üzerinden oynatır (test/backtest)."""
    count = 0
    for ntx in transactions:
        swap = detect_swap(ntx, address)
        if swap is not None:
            store_swap(db, swap)
            count += 1
    return count
