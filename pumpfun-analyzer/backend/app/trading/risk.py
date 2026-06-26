"""İşlem öncesi risk denetimleri ve limit yönetimi.

Tüm parametreler panelden (settings/risk_rules) değiştirilebilir. Motor her
işlem öncesi bu kontrolleri çalıştırır; başarısız olursa işlem reddedilir ve
gerekçe döner.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RiskConfig:
    enabled: bool = False                  # canlı/paper işlem motoru aktif mi
    mode: str = "paper"                    # paper | alerts_only | live
    live_confirmed: bool = False           # kullanıcı canlı riski onayladı mı

    fixed_sol_amount: float = 0.05         # işlem başına sabit SOL (canlı)
    paper_trade_sol: float = 0.01          # PAPER modunda her işlem SABİT bu kadar
    proportional: bool = False             # hedef cüzdan miktarına orantılı (canlı)
    proportional_factor: float = 1.0
    max_position_sol: float = 0.5
    max_daily_spend_sol: float = 2.0
    max_daily_loss_sol: float = 1.0
    max_slippage: float = 0.15             # %15
    priority_fee_sol: float = 0.0005
    min_wallet_score: float = 70.0
    min_token_score: float = 70.0
    # İşlem kapısı politikası:
    #   "safety"   → token yalnızca GÜVENLİK vetosundan geçer (sat/mint/freeze/
    #                honeypot). Ayrı puan eşiği UYGULANMAZ. Cüzdan = alpha.
    #   "balanced" → güvenlik + düşük kalite tabanı (token ≥ 55).
    #   "score"    → güvenlik + min_token_score (klasik katı mod).
    # VARSAYILAN "safety": taze token'ler adil puanlanamaz; asıl sinyal cüzdandır.
    token_gate: str = "safety"
    max_open_positions_per_token: int = 1
    max_follow_lag_seconds: int = 60
    min_liquidity_sol: float = 5.0

    emergency_stop: bool = False
    blocked_wallets: list[str] = field(default_factory=list)
    blocked_tokens: list[str] = field(default_factory=list)
    only_wallets: list[str] = field(default_factory=list)  # boşsa tümü


@dataclass
class DayState:
    spent_sol: float = 0.0
    loss_sol: float = 0.0
    open_positions: dict[str, int] = field(default_factory=dict)  # token -> adet
    date: str = ""  # YYYY-MM-DD (UTC) — gün değişince harcama/zarar SIFIRLANIR

    def roll_day(self) -> None:
        """Yeni güne geçildiyse günlük harcama/zarar sayaçlarını sıfırla.
        (Açık pozisyonlar korunur.) Aksi halde 'günlük' limit aslında 'süreç-ömrü'
        limiti gibi davranıp bir kez dolunca işlemleri kalıcı durduruyordu."""
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.date != today:
            self.spent_sol = 0.0
            self.loss_sol = 0.0
            self.date = today


@dataclass
class RiskDecision:
    allowed: bool
    reasons: list[str] = field(default_factory=list)
    sol_amount: float = 0.0


def effective_min_token_score(cfg: "RiskConfig") -> float:
    """İşlem kapısı politikasına göre uygulanacak ASGARİ token puanı.

    "safety" modunda token puanı bir engel DEĞİLDİR (güvenlik vetosu yukarıda
    canlı akışta zaten uygulanır); taze bonding token'leri düşük puan alır ama
    güvenliyse işlem yapılır.
    """
    gate = getattr(cfg, "token_gate", "safety")
    if gate == "safety":
        return 0.0
    if gate == "balanced":
        return 55.0
    return cfg.min_token_score  # "score"


def evaluate_buy(
    cfg: RiskConfig,
    day: DayState,
    *,
    wallet_address: str,
    token_mint: str,
    wallet_score: float,
    token_score: float,
    token_liquidity_sol: float,
    token_sellable: bool,
    follow_lag_seconds: float,
    leader_sol_amount: float | None = None,
    forced_amount: float | None = None,
) -> RiskDecision:
    reasons: list[str] = []
    day.roll_day()  # gün değiştiyse günlük sayaçları sıfırla

    if cfg.emergency_stop:
        return RiskDecision(False, ["Acil durdurma aktif"])
    if not cfg.enabled or cfg.mode == "alerts_only":
        return RiskDecision(False, ["İşlem motoru kapalı (yalnızca bildirim)"])
    if cfg.mode == "live" and not cfg.live_confirmed:
        return RiskDecision(False, ["Canlı işlem onaylanmamış"])

    if wallet_address in cfg.blocked_wallets:
        reasons.append("Cüzdan engellenmiş")
    if token_mint in cfg.blocked_tokens:
        reasons.append("Token engellenmiş")
    if cfg.only_wallets and wallet_address not in cfg.only_wallets:
        reasons.append("Cüzdan seçili kopyalama listesinde değil")
    if wallet_score < cfg.min_wallet_score:
        reasons.append(f"Cüzdan puanı < {cfg.min_wallet_score}")
    min_token = effective_min_token_score(cfg)
    if min_token > 0 and token_score < min_token:
        reasons.append(f"Token puanı < {min_token:.0f}")
    if not token_sellable:
        reasons.append("Token satılabilir değil (honeypot riski)")
    # Likidite yalnızca ÖLÇÜLEBİLDİĞİNDE (>0) ve eşik altındaysa engeller. Taze
    # bonding token'leri DexScreener'da olmayabilir (likidite=0=bilinmiyor); eksik
    # veriyi "0 likidite" sayıp reddetmek hatalıdır — güvenlik vetosu + pozisyon
    # limiti korur.
    if 0 < token_liquidity_sol < cfg.min_liquidity_sol:
        reasons.append("Likidite eşik altında")
    if follow_lag_seconds > cfg.max_follow_lag_seconds:
        reasons.append("İşlem gecikmesi izleme penceresini aştı")

    # Miktar hesapla — öncelik: elle override (forced) > PAPER sabit > orantılı/sabit
    if forced_amount is not None and forced_amount > 0:
        amount = forced_amount
    elif cfg.mode == "paper":
        amount = cfg.paper_trade_sol  # paper'da herkes aynı (adil kâr/zarar ölçümü)
    elif cfg.proportional and leader_sol_amount is not None:
        amount = leader_sol_amount * cfg.proportional_factor
    else:
        amount = cfg.fixed_sol_amount
    amount = min(amount, cfg.max_position_sol)

    if day.spent_sol + amount > cfg.max_daily_spend_sol:
        reasons.append("Günlük harcama limiti aşılır")
    if day.loss_sol >= cfg.max_daily_loss_sol:
        reasons.append("Günlük zarar limitine ulaşıldı")
    if day.open_positions.get(token_mint, 0) >= cfg.max_open_positions_per_token:
        reasons.append("Token başına maksimum açık pozisyon")

    if reasons:
        return RiskDecision(False, reasons, amount)
    return RiskDecision(True, ["Tüm risk kontrolleri geçildi"], amount)


def tp_sl_should_close(cost_sol: float, qty: float, price_sol: float,
                       take_profit_pct: float, stop_loss_pct: float) -> str | None:
    """Açık pozisyon için take-profit / stop-loss kararı.

    take_profit_pct / stop_loss_pct: 0-1 arası oran (0 = kapalı). Dönüş: "tp" | "sl" | None.
    """
    if qty <= 0 or cost_sol <= 0 or price_sol <= 0:
        return None
    value = qty * price_sol
    pnl_pct = (value - cost_sol) / cost_sol
    if take_profit_pct > 0 and pnl_pct >= take_profit_pct:
        return "tp"
    if stop_loss_pct > 0 and pnl_pct <= -stop_loss_pct:
        return "sl"
    return None
