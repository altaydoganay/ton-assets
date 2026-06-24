"""Ayar deposu servisi (DB tabanlı, varsayılanlarla).

Puan ağırlıkları, eşikler, uygunluk kuralları ve risk/işlem parametreleri
`settings` tablosunda anahtar-değer olarak tutulur. Panelden güncellenebilir.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..core.scoring.token_scoring import DEFAULT_WEIGHTS as TOKEN_WEIGHTS
from ..core.scoring.wallet_scoring import DEFAULT_ELIGIBILITY, DEFAULT_WEIGHTS as WALLET_WEIGHTS
from ..models import Setting

DEFAULTS: dict[str, dict] = {
    "wallet_weights": WALLET_WEIGHTS,
    "wallet_eligibility": DEFAULT_ELIGIBILITY,
    "token_weights": TOKEN_WEIGHTS,
    "thresholds": {"wallet": 70.0, "token": 70.0},
    "risk": {
        "enabled": False,
        "mode": "paper",
        "live_confirmed": False,
        "fixed_sol_amount": 0.05,
        "proportional": False,
        "proportional_factor": 1.0,
        "max_position_sol": 0.5,
        "max_daily_spend_sol": 2.0,
        "max_daily_loss_sol": 1.0,
        "max_slippage": 0.15,
        "priority_fee_sol": 0.0005,
        "min_wallet_score": 70.0,
        "min_token_score": 70.0,
        "max_open_positions_per_token": 1,
        "max_follow_lag_seconds": 60,
        "min_liquidity_sol": 5.0,
        "emergency_stop": False,
        "blocked_wallets": [],
        "blocked_tokens": [],
        "only_wallets": [],
        "close_mode": "proportional",
        "take_profit_pct": 0.0,   # 0 = kapalı; örn. 0.5 = +%50'de sat
        "stop_loss_pct": 0.0,     # 0 = kapalı; örn. 0.3 = -%30'da sat
    },
}


def get_setting(db: Session, key: str) -> dict:
    row = db.query(Setting).filter(Setting.key == key).first()
    if row:
        # Varsayılanların üzerine kaydı uygula (yeni alanlar eklendiğinde uyum)
        base = dict(DEFAULTS.get(key, {}))
        if isinstance(row.value, dict):
            base.update(row.value)
            return base
        return row.value
    return dict(DEFAULTS.get(key, {}))


def set_setting(db: Session, key: str, value: dict) -> dict:
    row = db.query(Setting).filter(Setting.key == key).first()
    if row:
        row.value = value
    else:
        row = Setting(key=key, value=value)
        db.add(row)
    db.commit()
    db.refresh(row)
    return row.value


def seed_defaults(db: Session) -> None:
    for key, value in DEFAULTS.items():
        if not db.query(Setting).filter(Setting.key == key).first():
            db.add(Setting(key=key, value=value))
    db.commit()
    # wallet_eligibility panelden düzenlenemez; ilk kurulumda DB'ye yazılan eski
    # değerler kod güncellemelerini gölgeliyordu. Her açılışta kod değerine
    # senkronla ki güncel (pump.fun'a uyarlı) kriterler uygulansın.
    elig = db.query(Setting).filter(Setting.key == "wallet_eligibility").first()
    if elig and elig.value != DEFAULTS["wallet_eligibility"]:
        elig.value = DEFAULTS["wallet_eligibility"]
        db.commit()


def all_settings(db: Session) -> dict[str, dict]:
    return {key: get_setting(db, key) for key in DEFAULTS}


# Hazır risk profilleri — panelden tek tıkla uygulanır.
RISK_PROFILES: dict[str, dict] = {
    "temkinli": {
        "fixed_sol_amount": 0.02, "max_position_sol": 0.05, "max_daily_spend_sol": 0.3,
        "max_daily_loss_sol": 0.1, "max_slippage": 0.08, "min_wallet_score": 80,
        "min_token_score": 80, "min_liquidity_sol": 15, "max_open_positions_per_token": 1,
    },
    "dengeli": {
        "fixed_sol_amount": 0.05, "max_position_sol": 0.2, "max_daily_spend_sol": 1.0,
        "max_daily_loss_sol": 0.5, "max_slippage": 0.15, "min_wallet_score": 70,
        "min_token_score": 70, "min_liquidity_sol": 5, "max_open_positions_per_token": 1,
    },
    "agresif": {
        "fixed_sol_amount": 0.1, "max_position_sol": 0.5, "max_daily_spend_sol": 3.0,
        "max_daily_loss_sol": 1.5, "max_slippage": 0.25, "min_wallet_score": 65,
        "min_token_score": 65, "min_liquidity_sol": 3, "max_open_positions_per_token": 2,
    },
}


def apply_risk_profile(db: Session, name: str) -> dict:
    preset = RISK_PROFILES.get(name)
    if preset is None:
        raise KeyError(name)
    risk = get_setting(db, "risk")
    risk.update(preset)
    return set_setting(db, "risk", risk)


def set_heartbeat(db: Session, key: str = "listener_heartbeat") -> None:
    from datetime import datetime, timezone
    set_setting(db, "_meta_" + key, {"ts": datetime.now(timezone.utc).isoformat()})


def get_heartbeat(db: Session, key: str = "listener_heartbeat") -> str | None:
    row = db.query(Setting).filter(Setting.key == "_meta_" + key).first()
    return (row.value or {}).get("ts") if row else None
