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
from ..adapters.pumpfun import normalize_enhanced_transaction, normalize_rpc_transaction
from ..core.analysis.copyability import compute_copyability
from ..core.analysis.pnl import SwapEvent, compute_performance
from ..core.analysis.swap_detection import NormalizedTx, detect_swap
from ..core.classification.copy_trader import TradeRef, detect_copy_trader
from ..core.classification.sniper import detect_sniper
from ..core.scoring.wallet_scoring import WalletSignals, score_wallet
from ..models import Swap
from .analysis_service import get_or_create_wallet, persist_wallet_score
from .settings_service import get_setting
from .wallet_relationships import record_transfer_relationships_from_enhanced, relationship_summary


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
    """Cüzdanın işlemlerini çekip swap'ları kaydeder. Kaydedilen swap sayısını döner.

    Sağlayıcı Helius Enhanced Transactions destekliyorsa (tek istekte 100 parse
    edilmiş işlem) o yol kullanılır — derin geçmiş + ~100× daha az kredi. Aksi
    halde imza-başına `getTransaction` yoluna düşülür (RPC).
    """
    if hasattr(provider, "get_address_transactions"):
        return _ingest_wallet_enhanced(db, provider, address, limit)
    return _ingest_wallet_rpc(db, provider, address, limit)


def _ingest_wallet_enhanced(db: Session, provider, address: str, limit: int) -> int:
    """Helius Enhanced Transactions History ile derin, ucuz alım.

    En yeniden eskiye sayfalanır (`before=<son imza>`). 100'er işlemlik tek
    isteklerle `limit` işleme kadar taranır.
    """
    count = 0
    fetched = 0
    before: str | None = None
    while fetched < limit:
        page_size = min(100, limit - fetched)
        try:
            page = provider.get_address_transactions(address, limit=page_size, before=before)
        except Exception:  # noqa: BLE001 — enhanced erişilemezse RPC'ye düş
            if fetched == 0:
                return _ingest_wallet_rpc(db, provider, address, limit)
            break
        if not page:
            break
        record_transfer_relationships_from_enhanced(db, address, page)
        for enh in page:
            ntx = normalize_enhanced_transaction(enh)
            if ntx is None:
                continue
            swap = detect_swap(ntx, address)
            if swap is not None:
                store_swap(db, swap)
                count += 1
        fetched += len(page)
        last_sig = page[-1].get("signature") if isinstance(page[-1], dict) else None
        if not last_sig or len(page) < page_size:
            break
        before = last_sig
    return count


def _ingest_wallet_rpc(db: Session, provider: ChainProvider, address: str, limit: int) -> int:
    """İmza-başına getTransaction yolu (Helius dışı RPC sağlayıcılar için)."""
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
    risk_settings = get_setting(db, "risk")
    copyability_metrics: dict = {}
    if risk_settings.get("copyability_enabled", True):
        mints = sorted({s.token_mint for s in swaps if s.token_mint})
        market_swaps = []
        if mints:
            market_swaps = (
                db.query(Swap)
                .filter(Swap.token_mint.in_(mints), Swap.price_sol > 0)
                .order_by(Swap.block_time.asc())
                .all()
            )
        copyability_metrics = compute_copyability(
            address,
            swaps,
            market_swaps,
            copy_amount_sol=float(risk_settings.get("copyability_amount_sol", 0.01)),
            delays_seconds=risk_settings.get("copyability_delays_seconds", [5, 10, 30]),
            slippage=float(risk_settings.get("max_slippage", 0.0) or 0.0),
            priority_fee_sol=float(risk_settings.get("priority_fee_sol", 0.0005) or 0.0),
        ).as_metrics()

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

    rel_summary = relationship_summary(db, address)

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
        insider_confidence=max(
            (extra_signals or {}).get("insider_confidence", 0.0),
            1.0 if rel_summary["related_tracked_wallet_count"] > 0 else 0.0,
        ),
        is_token_creator=(extra_signals or {}).get("is_token_creator", False),
        history_days=history_days,
        days_since_last_trade=days_since_last,
        transfer_noise_ratio=transfer_noise,
    )

    weights = get_setting(db, "wallet_weights")
    eligibility = get_setting(db, "wallet_eligibility")
    eligibility.update({
        "copyability_min_sample": int(risk_settings.get("copyability_min_sample", 12)),
        "copyability_require_min_sample": bool(risk_settings.get("copyability_require_min_sample", True)),
        "copyability_min_coverage": float(risk_settings.get("copyability_min_coverage", 0.70)),
        "copyability_max_entry_jump_10s": float(risk_settings.get("copyability_max_entry_jump_10s", 0.15)),
        "copyability_min_pnl_10s": float(risk_settings.get("copyability_min_pnl_10s", 0.001)),
    })
    threshold = get_setting(db, "thresholds").get("wallet", 70.0)

    result = score_wallet(
        perf,
        signals,
        copyability_metrics=copyability_metrics,
        weights=weights,
        eligibility=eligibility,
        threshold=threshold,
    )
    wallet = get_or_create_wallet(db, address)
    # Liderin ORTALAMA alım büyüklüğü (SOL) — 10 SOL'lük trader ile 0.01'lik dust'ı
    # ayırt etmek için (kopyalama miktarımızı değiştirmez; sınıflandırma sinyali).
    buy_sizes = [e.sol_amount for e in events if e.side == "buy" and e.sol_amount]
    avg_buy = sum(buy_sizes) / len(buy_sizes) if buy_sizes else 0.0
    metrics = {
        "swaps_analyzed": perf.swaps_analyzed,
        "closed_positions": perf.closed_positions,
        "open_positions": perf.open_positions,
        "win_rate": perf.win_rate,
        "realized_pnl_sol": perf.realized_pnl_sol,
        "profit_factor": None if perf.profit_factor == float("inf") else perf.profit_factor,
        "token_diversity": perf.token_diversity,
        "avg_hold_seconds": perf.avg_hold_seconds,
        "median_hold_seconds": perf.median_hold_seconds,
        "short_hold_ratio": perf.short_hold_ratio,
        "largest_trade_pnl_share": perf.largest_trade_pnl_share,
        "sniper_confidence": signals.sniper_confidence,
        "scalper_confidence": signals.scalper_confidence,
        "history_days": history_days,
        "avg_buy_size_sol": round(avg_buy, 4),
        **rel_summary,
        **copyability_metrics,
    }
    if persist:
        persist_wallet_score(db, wallet, result, metrics=metrics, demote_below=max(0.0, threshold - 5))
    return result


def rescore_wallets_from_storage(db: Session, *, budget_seconds: float = 20.0,
                                 max_wallets: int = 5000) -> dict:
    """Mevcut cüzdanları DEPOLANMIŞ swap'larla yeniden puanlar (kriter/eşik değişince).

    ZİNCİRE GİTMEZ, KREDİ HARCAMAZ: yalnızca elimizdeki swap geçmişini yeni
    uygunluk kuralları + eşikle (örn. takip eşiği 55, gevşeyen kriterler)
    yeniden değerlendirir. Önceden 'rejected/below_threshold/analyzed' olan ama
    artık eşiği geçen cüzdanlar TAKİBE alınır. `blocked` HARİÇ (kullanıcı/eleme
    kararı korunur). Zaman bütçesi aşılırsa kalan sayısı `remaining` ile döner.
    """
    import time as _t
    from ..models import Wallet, WalletStatus

    statuses = [WalletStatus.rejected.value, WalletStatus.below_threshold.value,
                WalletStatus.analyzed.value, WalletStatus.tracked.value,
                WalletStatus.discovered.value]
    wallets = (db.query(Wallet).filter(Wallet.status.in_(statuses))
               .order_by(Wallet.latest_score.desc().nullslast()).limit(max_wallets).all())
    before_tracked = sum(1 for w in wallets if w.status == WalletStatus.tracked.value)

    start = _t.monotonic()
    s = {"scanned": 0, "skipped_no_data": 0, "to_tracked": 0, "to_below": 0,
         "to_rejected": 0, "promoted": [], "remaining": 0}
    for i, w in enumerate(wallets):
        if _t.monotonic() - start > budget_seconds:
            s["remaining"] = len(wallets) - i
            break
        has_data = db.query(Swap.id).filter(Swap.wallet_address == w.address).first()
        if not has_data:
            s["skipped_no_data"] += 1  # discovered ama henüz işlem çekilmemiş (ingest gerekir)
            continue
        before = w.status
        analyze_wallet(db, w.address)  # persist=True; w.status yerinde güncellenir
        after = w.status
        s["scanned"] += 1
        if before != after:
            if after == WalletStatus.tracked.value:
                s["to_tracked"] += 1
                if len(s["promoted"]) < 50:
                    s["promoted"].append(w.address)
            elif after == WalletStatus.below_threshold.value:
                s["to_below"] += 1
            elif after == WalletStatus.rejected.value:
                s["to_rejected"] += 1
    after_tracked = (db.query(Wallet)
                     .filter(Wallet.status == WalletStatus.tracked.value).count())
    s["before_tracked"] = before_tracked
    s["after_tracked"] = after_tracked
    return s


def replay_transactions(db: Session, address: str, transactions: list[NormalizedTx]) -> int:
    """Kaydedilmiş NormalizedTx listesini hat üzerinden oynatır (test/backtest)."""
    count = 0
    for ntx in transactions:
        swap = detect_swap(ntx, address)
        if swap is not None:
            store_swap(db, swap)
            count += 1
    return count
