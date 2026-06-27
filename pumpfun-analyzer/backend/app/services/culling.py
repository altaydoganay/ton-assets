"""Cüzdan ELEME (cull): 500+ takip cüzdanını kaliteye göre süzme.

Cüzdanı KENDİ geçmiş metrikleriyle (analizden) süzer: aktiflik (son işlem ne kadar
yakın), kârlılık (realized PnL + profit factor), örneklem/çeşitlilik ve skor.
Düşenler `below_threshold`'a alınır (silinmez/bloklanmaz) — toparlarsa geri dönebilir.

KALICILIK: eleme yalnızca demote ederse, yeniden-değerlendirme beat'i gevşek barla
onları geri yükseltir. Bu yüzden uygulama, `thresholds.wallet`'ı preset skoruna
YÜKSELTİR; tightened DEFAULT_ELIGIBILITY (recency/örneklem) ile birlikte eleme kalıcı olur.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Swap, Wallet, WalletStatus
from .settings_service import get_setting, set_setting

# Preset'ler: sertlik = (aktiflik penceresi, kârlılık, örneklem, çeşitlilik, skor, üst sınır)
CULL_PRESETS: dict[str, dict] = {
    "strict":   {"max_days_inactive": 5, "min_profit_factor": 1.3, "require_positive_pnl": True,
                 "min_closed": 10, "min_diversity": 5, "min_score": 68, "max_keep": 150},
    "balanced": {"max_days_inactive": 7, "min_profit_factor": 1.1, "require_positive_pnl": True,
                 "min_closed": 6, "min_diversity": 3, "min_score": 62, "max_keep": 300},
    "light":    {"max_days_inactive": 7, "min_profit_factor": 0.0, "require_positive_pnl": True,
                 "min_closed": 0, "min_diversity": 0, "min_score": 0, "max_keep": None},
}


def _last_trade_map(db: Session) -> dict[str, datetime]:
    rows = (db.query(Swap.wallet_address, func.max(Swap.block_time))
            .group_by(Swap.wallet_address).all())
    out: dict[str, datetime] = {}
    for addr, bt in rows:
        if bt is not None:
            out[addr] = bt if bt.tzinfo else bt.replace(tzinfo=timezone.utc)
    return out


def _judge(w: Wallet, cfg: dict, last: dict[str, datetime], now: datetime) -> list[str]:
    """Bir cüzdanın eleme gerekçeleri (boşsa KALIR)."""
    m = w.metrics or {}
    reasons: list[str] = []
    lt = last.get(w.address)
    days_inactive = (now - lt).total_seconds() / 86400 if lt else 9999.0
    if cfg["max_days_inactive"] and days_inactive > cfg["max_days_inactive"]:
        reasons.append(f"uyuyan ({days_inactive:.0f}g)")
    if cfg["require_positive_pnl"] and (m.get("realized_pnl_sol") or 0) <= 0:
        reasons.append("PnL ≤ 0")
    pf = m.get("profit_factor")  # None = sonsuz (hiç zarar yok) => iyi, geçer
    if cfg["min_profit_factor"] and pf is not None and pf < cfg["min_profit_factor"]:
        reasons.append(f"profit factor {pf:.2f}")
    if cfg["min_closed"] and (m.get("closed_positions") or 0) < cfg["min_closed"]:
        reasons.append(f"az örneklem ({m.get('closed_positions') or 0})")
    if cfg["min_diversity"] and (m.get("token_diversity") or 0) < cfg["min_diversity"]:
        reasons.append(f"az çeşitlilik ({m.get('token_diversity') or 0})")
    if cfg["min_score"] and (w.latest_score or 0) < cfg["min_score"]:
        reasons.append(f"skor {w.latest_score or 0:.0f}")
    return reasons


def _rank_key(w: Wallet):
    return ((w.latest_score or 0), (w.metrics or {}).get("realized_pnl_sol") or 0)


def cull_wallets(db: Session, preset: str, *, dry_run: bool = True) -> dict:
    """Takip cüzdanlarını preset'e göre süz. dry_run=True önizleme (yazmaz)."""
    cfg = CULL_PRESETS.get(preset)
    if cfg is None:
        raise KeyError(preset)
    tracked = db.query(Wallet).filter(Wallet.status == WalletStatus.tracked.value).all()
    last = _last_trade_map(db)
    now = datetime.now(timezone.utc)

    keep: list[Wallet] = []
    drop: list[tuple[Wallet, list[str]]] = []
    for w in tracked:
        reasons = _judge(w, cfg, last, now)
        (drop.append((w, reasons)) if reasons else keep.append(w))

    # Üst sınır: kalanlar çoksa en zayıf (skor+PnL) olanları da ele
    capped: list[Wallet] = []
    if cfg["max_keep"] and len(keep) > cfg["max_keep"]:
        keep.sort(key=_rank_key, reverse=True)
        capped = keep[cfg["max_keep"]:]
        keep = keep[: cfg["max_keep"]]

    summary = {
        "preset": preset, "dry_run": dry_run,
        "tracked_before": len(tracked),
        "kept": len(keep),
        "dropped": len(drop) + len(capped),
        "dropped_quality": len(drop),
        "dropped_cap": len(capped),
        "criteria": cfg,
        "examples": [{"wallet": w.address, "reasons": r} for w, r in drop[:8]],
    }
    if dry_run:
        return summary

    for w, _ in drop:
        w.status = WalletStatus.below_threshold.value
    for w in capped:
        w.status = WalletStatus.below_threshold.value
    # Barı KALICI yükselt ki yeniden-değerlendirme demote'ları geri yüklemesin
    if cfg["min_score"]:
        th = get_setting(db, "thresholds")
        if float(th.get("wallet", 55)) < cfg["min_score"]:
            th["wallet"] = float(cfg["min_score"])
            set_setting(db, "thresholds", th)
    db.commit()
    return summary
