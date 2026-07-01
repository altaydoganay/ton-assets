"""Cüzdan ELEME (cull): 500+ takip cüzdanını kaliteye göre süzme.

Cüzdanı KENDİ geçmiş metrikleri + 0.01 SOL gecikmeli copyability ile süzer:
aktiflik, örneklem/çeşitlilik, skor ve özellikle 10 saniye gecikmeli copy PnL.
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
from .wallet_relationships import related_pairs
from .settings_service import get_setting, set_setting

# Preset'ler: sertlik = (aktiflik penceresi, kârlılık, örneklem, çeşitlilik, skor, üst sınır)
CULL_PRESETS: dict[str, dict] = {
    "elite":    {"max_days_inactive": 3, "min_profit_factor": 1.20, "require_positive_pnl": True,
                 "min_closed": 12, "min_diversity": 6, "min_score": 74, "max_keep": 40,
                 "require_positive_copy_pnl": True, "require_copy_sample": True,
                 "copy_min_sample": 12, "min_copy_score": 65, "min_copy_pf": 1.40,
                 "min_copy_coverage": 0.70, "max_entry_jump_10s": 0.15,
                 "min_median_hold_seconds": 300, "max_short_hold_ratio": 0.45,
                 "max_single_trade_pnl_share": 0.55},
    "strict":   {"max_days_inactive": 5, "min_profit_factor": 1.3, "require_positive_pnl": True,
                 "min_closed": 10, "min_diversity": 5, "min_score": 68, "max_keep": 150,
                 "require_positive_copy_pnl": True, "copy_min_sample": 6},
    "balanced": {"max_days_inactive": 7, "min_profit_factor": 1.1, "require_positive_pnl": True,
                 "min_closed": 6, "min_diversity": 3, "min_score": 62, "max_keep": 300,
                 "require_nonnegative_copy_pnl": True, "copy_min_sample": 6},
    "light":    {"max_days_inactive": 7, "min_profit_factor": 0.0, "require_positive_pnl": True,
                 "min_closed": 0, "min_diversity": 0, "min_score": 0, "max_keep": None,
                 "require_nonnegative_copy_pnl": False, "copy_min_sample": 6},
}

ELITE_WALLET_ELIGIBILITY = {
    "min_closed_positions": 10,
    "min_distinct_tokens": 5,
    "min_history_days": 0.0,
    "min_realized_pnl_sol": 0.0,
    "min_profit_factor": 1.15,
    "min_win_rate": 0.40,
    "min_median_hold_seconds": 300,
    "max_short_hold_ratio": 0.55,
    "max_single_trade_pnl_share": 0.60,
    "max_days_since_last_trade": 3,
    "copyability_min_sample": 12,
    "copyability_require_min_sample": True,
    "copyability_min_coverage": 0.70,
    "copyability_max_entry_jump_10s": 0.15,
    "copyability_min_pnl_10s": 0.001,
    "copyability_min_score": 65,
    "copyability_min_profit_factor_10s": 1.40,
    "max_sniper_confidence": 0.45,
    "max_scalper_confidence": 0.45,
}

ELITE_LIVE_RISK = {
    "block_sniper_wallets_live": True,
    "live_min_median_hold_seconds": 300,
    "live_max_short_hold_ratio": 0.45,
    "live_max_sniper_confidence": 0.45,
    "live_max_scalper_confidence": 0.45,
    "live_min_copyability_score": 65,
    "live_min_copy_sample": 12,
    "live_require_copy_sample": True,
    "live_require_positive_copy_pnl_10s": True,
    "live_max_entry_jump_10s": 0.15,
    "live_fresh_token_only": True,
    "live_max_token_age_minutes": 180,
    "live_min_token_age_seconds": 30,
    "live_require_known_token_age": True,
    "live_min_confluence": 1,
    "fixed_sol_amount": 0.01,
    "max_position_sol": 0.01,
}


def apply_elite_wallet_policy(db: Session) -> dict:
    """Canlı kopya için daha sert ama hâlâ işlem üretebilen kalite politikasını uygula."""
    eligibility = get_setting(db, "wallet_eligibility")
    eligibility.update(ELITE_WALLET_ELIGIBILITY)
    set_setting(db, "wallet_eligibility", eligibility)

    risk = get_setting(db, "risk")
    risk.update(ELITE_LIVE_RISK)
    set_setting(db, "risk", risk)

    thresholds = get_setting(db, "thresholds")
    thresholds["wallet"] = max(float(thresholds.get("wallet", 55.0) or 55.0), 74.0)
    thresholds["max_tracked"] = min(int(thresholds.get("max_tracked", 0) or 40), 40) if int(thresholds.get("max_tracked", 0) or 0) > 0 else 40
    set_setting(db, "thresholds", thresholds)
    return {"wallet_eligibility": eligibility, "risk": risk, "thresholds": thresholds}


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
    if cfg.get("min_median_hold_seconds") and (m.get("median_hold_seconds") or 0) < cfg["min_median_hold_seconds"]:
        reasons.append(f"medyan hold kısa ({(m.get('median_hold_seconds') or 0)/60:.1f}dk)")
    if cfg.get("max_short_hold_ratio") is not None and (m.get("short_hold_ratio") or 0) > cfg["max_short_hold_ratio"]:
        reasons.append(f"kısa satış oranı yüksek (%{(m.get('short_hold_ratio') or 0)*100:.0f})")
    if cfg.get("max_single_trade_pnl_share") is not None and (m.get("largest_trade_pnl_share") or 0) > cfg["max_single_trade_pnl_share"]:
        reasons.append("tek işlem kârı baskın")
    copy_sample = int(m.get("copy_sample_size") or 0)
    copy_pnl_10 = float(m.get("copy_pnl_10s_sol") or 0.0)
    copy_score = float(m.get("copyability_score") or 0.0)
    copy_pf = m.get("copy_profit_factor_10s")
    copy_pf_f = float(copy_pf) if copy_pf is not None else float("inf") if copy_pnl_10 > 0 else 0.0
    copy_cov = float(m.get("copy_coverage_ratio") or 0.0)
    entry_jump_10 = float(m.get("avg_entry_jump_10s") or 0.0)
    copy_min_sample = int(cfg.get("copy_min_sample", 12))
    if copy_sample >= copy_min_sample:
        if cfg.get("min_copy_score") and copy_score < cfg["min_copy_score"]:
            reasons.append(f"copy score düşük ({copy_score:.0f})")
        if cfg.get("require_positive_copy_pnl") and copy_pnl_10 <= 0:
            reasons.append(f"10sn copy PnL ≤ 0 ({copy_pnl_10:+.4f})")
        elif cfg.get("require_nonnegative_copy_pnl") and copy_pnl_10 < 0:
            reasons.append(f"10sn copy PnL negatif ({copy_pnl_10:+.4f})")
        if cfg.get("min_copy_pf") and copy_pf_f < cfg["min_copy_pf"]:
            reasons.append(f"10sn copy PF düşük ({copy_pf_f:.2f})")
        if cfg.get("min_copy_coverage") and copy_cov < cfg["min_copy_coverage"]:
            reasons.append(f"copy coverage düşük (%{copy_cov*100:.0f})")
        if cfg.get("max_entry_jump_10s") is not None and entry_jump_10 > cfg["max_entry_jump_10s"]:
            reasons.append(f"10sn entry jump yüksek (%{entry_jump_10*100:.0f})")
    elif cfg.get("require_copy_sample"):
        reasons.append(f"copy örneklemi yetersiz ({copy_sample}/{copy_min_sample})")
    elif cfg.get("require_positive_copy_pnl") and copy_score < 45:
        reasons.append("copyability örneklemi yetersiz / review")
    return reasons


def _rank_key(w: Wallet):
    m = w.metrics or {}
    return (
        m.get("copyability_score") or 0,
        m.get("copy_pnl_10s_sol") or 0,
        m.get("copy_profit_factor_10s") or 0,
        m.get("copy_coverage_ratio") or 0,
        -(m.get("avg_entry_jump_10s") or 0),
        w.latest_score or 0,
        m.get("realized_pnl_sol") or 0,
    )


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

    # Bağımsızlık: birbirine SOL/token göndermiş cüzdanlardan yalnızca en iyi
    # rank_key'e sahip olan kalsın. Böylece takip listesi aynı cluster'a yığılmaz.
    relationship_drops: list[tuple[Wallet, list[str]]] = []
    if len(keep) > 1:
        keep.sort(key=_rank_key, reverse=True)
        pairs = related_pairs(db, [w.address for w in keep])
        selected: list[Wallet] = []
        selected_addrs: set[str] = set()
        for w in keep:
            linked = [a for a in selected_addrs if frozenset((w.address, a)) in pairs]
            if linked:
                relationship_drops.append((w, [f"bağımsız değil: takip adayı {linked[0][:4]}…{linked[0][-4:]} ile SOL/token transfer bağı var"]))
            else:
                selected.append(w)
                selected_addrs.add(w.address)
        keep = selected

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
        "dropped": len(drop) + len(relationship_drops) + len(capped),
        "dropped_quality": len(drop),
        "dropped_relationship": len(relationship_drops),
        "dropped_cap": len(capped),
        "criteria": cfg,
        "examples": [{"wallet": w.address, "reasons": r} for w, r in (drop + relationship_drops)[:8]],
    }
    if dry_run:
        return summary

    for w, _ in drop:
        w.status = WalletStatus.below_threshold.value
    for w, _ in relationship_drops:
        w.status = WalletStatus.below_threshold.value
    for w in capped:
        w.status = WalletStatus.below_threshold.value
    # Barı KALICI yükselt + ÜST SINIR koy ki keşif/yeniden-değerlendirme akışı
    # eleme sonrası takip sayısını geri şişirmesin (asıl "460'a çıkıyor" sorunu).
    th = get_setting(db, "thresholds")
    changed = False
    if cfg["min_score"] and float(th.get("wallet", 55)) < cfg["min_score"]:
        th["wallet"] = float(cfg["min_score"]); changed = True
    # max_tracked = kalan sayısı (üst sınır). light (max_keep None) => 0 (sınırsız).
    new_cap = cfg["max_keep"] if cfg["max_keep"] else len(keep)
    th["max_tracked"] = int(new_cap); changed = True
    if changed:
        set_setting(db, "thresholds", th)
    db.commit()
    summary["max_tracked"] = int(new_cap)
    return summary
