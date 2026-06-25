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
        # Paper (simülasyon) işlem motoru varsayılan AÇIK — risksizdir; CANLI
        # (gerçek para) ayrı bir onaya bağlıdır (live_confirmed) ve KAPALI kalır.
        "enabled": True,
        "mode": "paper",
        "live_confirmed": False,
        # İşlem kapısı: token bir GÜVENLİK filtresidir, kalite notu DEĞİL — taze
        # pump.fun token'leri (likidite/holder verisi henüz yok) adil puanlanamaz;
        # asıl sinyal CÜZDANDIR. "safety" = güvenlik vetosu (rug/honeypot/aktif
        # mint-freeze/sahte likidite) yoksa işlem açılır; arbitrer bir puan eşiği
        # DAYATILMAZ. Bu "her token" değildir — scam token'leri yine elenir.
        # "safety" | "balanced" (+≥55) | "score" (+tam eşik). Bkz. trading/risk.py.
        "token_gate": "safety",
        "fixed_sol_amount": 0.05,
        "proportional": False,
        "proportional_factor": 1.0,
        "max_position_sol": 0.2,
        "max_daily_spend_sol": 1.0,
        "max_daily_loss_sol": 0.5,
        "max_slippage": 0.15,
        "priority_fee_sol": 0.0005,
        "min_wallet_score": 70.0,
        "min_token_score": 70.0,   # yalnızca token_gate="score" modunda uygulanır
        "max_open_positions_per_token": 1,
        "max_follow_lag_seconds": 60,
        "min_liquidity_sol": 5.0,  # yalnızca ölçülebildiğinde uygulanır
        "emergency_stop": False,
        "blocked_wallets": [],
        "blocked_tokens": [],
        "only_wallets": [],
        "close_mode": "proportional",
        "take_profit_pct": 0.6,   # +%60'da sat (dengeli)
        "stop_loss_pct": 0.3,     # -%30'da sat (dengeli)
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


def get_runtime_flag(db: Session, name: str, default: bool) -> bool:
    """Panelden açılıp kapatılabilen çalışma-zamanı bayrağı (DB). Kayıt yoksa
    `default` (genelde .env değeri) döner. Örn. keşif akışını (firehose) canlıyken
    durdurmak için — yeniden derlemeye gerek kalmadan."""
    row = db.query(Setting).filter(Setting.key == "runtime").first()
    if row and isinstance(row.value, dict) and name in row.value:
        return bool(row.value[name])
    return default


def set_runtime_flag(db: Session, name: str, value: bool) -> dict:
    row = db.query(Setting).filter(Setting.key == "runtime").first()
    val = dict(row.value) if row and isinstance(row.value, dict) else {}
    val[name] = bool(value)
    return set_setting(db, "runtime", val)


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

    # Tek seferlik risk politikası yükseltmesi (v5): GÜVENLİK (safety) işlem kapısı.
    # Saha verisi gösterdi ki "balanced" (≥55) eşiği, takip cüzdanlarının aldığı
    # TAZE token'leri (henüz likidite/holder verisi yok) geçiremiyor → 0 işlem.
    # safety = scam vetosu yoksa işlem aç (cüzdan = alpha). Paper motoru açık.
    # Yalnızca BİR KEZ uygulanır; sonradan paneldeki tercih ezilmez, CANLI'ya
    # (live_confirmed) dokunulmaz.
    if not db.query(Setting).filter(Setting.key == "_meta_risk_policy_v5").first():
        risk = get_setting(db, "risk")
        risk["token_gate"] = "safety"
        if not risk.get("live_confirmed"):
            risk["enabled"] = True
            risk["mode"] = "paper"
        if not risk.get("take_profit_pct"):
            risk["take_profit_pct"] = 0.6
        if not risk.get("stop_loss_pct"):
            risk["stop_loss_pct"] = 0.3
        if risk.get("max_daily_spend_sol", 0) > 1.0:
            risk["max_daily_spend_sol"] = 1.0
        set_setting(db, "risk", risk)
        set_setting(db, "_meta_risk_policy_v5", {"applied": True})


def all_settings(db: Session) -> dict[str, dict]:
    return {key: get_setting(db, key) for key in DEFAULTS}


# Hazır risk profilleri — panelden tek tıkla uygulanır.
RISK_PROFILES: dict[str, dict] = {
    "temkinli": {
        "fixed_sol_amount": 0.02, "max_position_sol": 0.05, "max_daily_spend_sol": 0.3,
        "max_daily_loss_sol": 0.1, "max_slippage": 0.08, "min_wallet_score": 80,
        "min_token_score": 80, "min_liquidity_sol": 15, "max_open_positions_per_token": 1,
        "take_profit_pct": 0.4, "stop_loss_pct": 0.25,
    },
    "dengeli": {
        "fixed_sol_amount": 0.05, "max_position_sol": 0.2, "max_daily_spend_sol": 1.0,
        "max_daily_loss_sol": 0.5, "max_slippage": 0.15, "min_wallet_score": 70,
        "min_token_score": 70, "min_liquidity_sol": 5, "max_open_positions_per_token": 1,
        "take_profit_pct": 0.6, "stop_loss_pct": 0.3,
    },
    "agresif": {
        "fixed_sol_amount": 0.1, "max_position_sol": 0.5, "max_daily_spend_sol": 3.0,
        "max_daily_loss_sol": 1.5, "max_slippage": 0.25, "min_wallet_score": 65,
        "min_token_score": 65, "min_liquidity_sol": 3, "max_open_positions_per_token": 2,
        "take_profit_pct": 1.0, "stop_loss_pct": 0.35,
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
