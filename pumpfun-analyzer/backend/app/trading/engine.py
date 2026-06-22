"""Kopya işlem orkestratörü.

Telegram bildiriminden BAĞIMSIZ çalışır: zincir üstü olay akışı bir hedef
cüzdanın alımını yakaladığında bu motor tetiklenir.

Modlar:
  - alerts_only: işlem yapılmaz (yalnızca bildirim akışı çalışır)
  - paper: PaperTradingEngine ile simülasyon, paper_trades'e kayıt
  - live: gerçek işlem; YALNIZCA kullanıcı paneldarisk onayı verdiğinde ve
    keystore açıldığında. İşlem göndermeden hemen önce token güvenliği ve
    satılabilirlik yeniden kontrol edilir.

Güvenlik: özel anahtar yalnızca imzalama anında keystore'dan çözülür; sonuç
loglara/DB'ye yazılmaz.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import LiveTrade, PaperTrade
from .paper import PaperTradingEngine
from .risk import DayState, RiskConfig, RiskDecision, evaluate_buy

logger = logging.getLogger(__name__)


class LiveTradingNotConfigured(RuntimeError):
    pass


@dataclass
class TradeContext:
    wallet_address: str
    token_mint: str
    wallet_score: float
    token_score: float
    token_liquidity_sol: float
    token_sellable: bool
    follow_lag_seconds: float
    market_price_sol: float
    leader_sol_amount: float | None = None
    source_signature: str | None = None


class CopyTradeEngine:
    def __init__(self, cfg: RiskConfig, paper: PaperTradingEngine | None = None, signer=None):
        self.cfg = cfg
        self.paper = paper or PaperTradingEngine(
            slippage=cfg.max_slippage, priority_fee_sol=cfg.priority_fee_sol, close_mode=cfg.__dict__.get("close_mode", "proportional")
        )
        self.signer = signer  # canlı imzalayıcı (enjekte edilir); yoksa live engellenir
        self.day = DayState()

    def _recheck_safety(self, ctx: TradeContext) -> list[str]:
        """İşlem göndermeden hemen önce son güvenlik kontrolü."""
        problems = []
        if not ctx.token_sellable:
            problems.append("Token satılabilir değil (son kontrol)")
        if ctx.token_score < self.cfg.min_token_score:
            problems.append("Token puanı eşik altına düştü (son kontrol)")
        if ctx.token_liquidity_sol < self.cfg.min_liquidity_sol:
            problems.append("Likidite eşik altına düştü (son kontrol)")
        return problems

    def on_leader_buy(self, db: Session, ctx: TradeContext) -> RiskDecision:
        decision = evaluate_buy(
            self.cfg,
            self.day,
            wallet_address=ctx.wallet_address,
            token_mint=ctx.token_mint,
            wallet_score=ctx.wallet_score,
            token_score=ctx.token_score,
            token_liquidity_sol=ctx.token_liquidity_sol,
            token_sellable=ctx.token_sellable,
            follow_lag_seconds=ctx.follow_lag_seconds,
            leader_sol_amount=ctx.leader_sol_amount,
        )
        if not decision.allowed:
            logger.info("İşlem reddedildi: %s", "; ".join(decision.reasons))
            return decision

        # Son güvenlik kontrolü
        problems = self._recheck_safety(ctx)
        if problems:
            decision.allowed = False
            decision.reasons = problems
            return decision

        if self.cfg.mode == "paper":
            self._execute_paper(db, ctx, decision.sol_amount)
        elif self.cfg.mode == "live":
            self._execute_live(db, ctx, decision.sol_amount)
        return decision

    def _execute_paper(self, db: Session, ctx: TradeContext, sol_amount: float) -> PaperTrade:
        fill = self.paper.buy(ctx.token_mint, sol_amount, ctx.market_price_sol, reason="copy-buy")
        self.day.spent_sol += sol_amount
        self.day.open_positions[ctx.token_mint] = self.day.open_positions.get(ctx.token_mint, 0) + 1
        row = PaperTrade(
            wallet_address=ctx.wallet_address,
            token_mint=ctx.token_mint,
            side="buy",
            sol_amount=sol_amount,
            token_amount=fill.token_amount,
            price_sol=fill.price_sol,
            fee_sol=fill.fee_sol,
            slippage_est=fill.slippage,
            is_open=True,
            reason="copy-buy (paper)",
            source_signature=ctx.source_signature,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def _execute_live(self, db: Session, ctx: TradeContext, sol_amount: float) -> LiveTrade:
        if not self.cfg.live_confirmed:
            raise LiveTradingNotConfigured("Canlı işlem onaylanmamış")
        if self.signer is None:
            raise LiveTradingNotConfigured("İmzalayıcı (keystore) yapılandırılmamış")

        row = LiveTrade(
            wallet_address=ctx.wallet_address,
            token_mint=ctx.token_mint,
            side="buy",
            sol_amount=sol_amount,
            status="pending",
            is_open=True,
            source_signature=ctx.source_signature,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        try:
            # signer.submit_buy zincire işlemi gönderir; özel anahtar yalnızca
            # burada çözülür ve fonksiyon dışına çıkmaz.
            sig = self.signer.submit_buy(ctx.token_mint, sol_amount, ctx.market_price_sol,
                                         max_slippage=self.cfg.max_slippage,
                                         priority_fee_sol=self.cfg.priority_fee_sol)
            row.signature = sig
            row.status = "submitted"
            row.token_amount = sol_amount / max(ctx.market_price_sol, 1e-9)
            row.price_sol = ctx.market_price_sol
            self.day.spent_sol += sol_amount
            self.day.open_positions[ctx.token_mint] = self.day.open_positions.get(ctx.token_mint, 0) + 1
        except Exception as exc:  # noqa: BLE001
            row.status = "failed"
            row.error = str(exc)[:240]
            logger.warning("Canlı işlem başarısız: %s", exc)
        row.created_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(row)
        return row

    def on_leader_sell(self, db: Session, ctx: TradeContext, leader_sell_fraction: float):
        """Hedef kısmi/tam satış yaptığında yansıt (paper)."""
        if self.cfg.mode == "paper":
            fill = self.paper.mirror_leader_sell(ctx.token_mint, leader_sell_fraction, ctx.market_price_sol)
            if fill:
                row = PaperTrade(
                    wallet_address=ctx.wallet_address, token_mint=ctx.token_mint, side="sell",
                    sol_amount=fill.sol_amount, token_amount=fill.token_amount, price_sol=fill.price_sol,
                    fee_sol=fill.fee_sol, slippage_est=fill.slippage, realized_pnl_sol=fill.realized_pnl_sol,
                    is_open=self.paper.positions[ctx.token_mint].is_open, reason="mirror-sell (paper)",
                    source_signature=ctx.source_signature,
                )
                db.add(row)
                if fill.realized_pnl_sol < 0:
                    self.day.loss_sol += abs(fill.realized_pnl_sol)
                db.commit()
                db.refresh(row)
                return row
        return None
