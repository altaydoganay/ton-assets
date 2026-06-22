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


def all_settings(db: Session) -> dict[str, dict]:
    return {key: get_setting(db, key) for key in DEFAULTS}
