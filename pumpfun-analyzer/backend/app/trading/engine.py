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
from .risk import DayState, RiskConfig, RiskDecision, effective_min_token_score, evaluate_buy

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
    forced_sol_amount: float | None = None  # cüzdan-bazlı elle override / paper sabiti
    strategy: str = "copy"                  # copy | ai


class CopyTradeEngine:
    def __init__(self, cfg: RiskConfig, paper: PaperTradingEngine | None = None, signer=None):
        self.cfg = cfg
        self.paper = paper or PaperTradingEngine(
            slippage=cfg.max_slippage, priority_fee_sol=cfg.priority_fee_sol, close_mode=cfg.__dict__.get("close_mode", "proportional")
        )
        self.signer = signer  # canlı imzalayıcı (enjekte edilir); yoksa live engellenir
        self.day = DayState()

    def hydrate_from_db(self, db: Session) -> dict:
        """Worker yeniden başladığında bellek-içi durumu DB'den yeniden kurar.

        İki sorunu çözer:
          1) AÇIK POZİSYON KURTARMA: paper pozisyonları (qty/maliyet) açık
             alımlardan yeniden kurulur — yoksa restart sonrası lider satınca
             yansıtma çalışmaz ve açık pozisyonlar yetim kalırdı.
          2) DEVRE KESİCİ DAYANIKLILIĞI: bugünkü harcama/zarar sayaçları DB'den
             doldurulur — yoksa restart günlük zarar limitini (devre kesici)
             sıfırlayıp koruma penceresini açık bırakırdı.

        Paper ve live trade kayıtlarından kurar; canlı modda da restart sonrası
        token başına açık pozisyon limiti korunur.
        """
        from datetime import datetime, timezone

        self.paper.positions.clear()
        rows = db.query(PaperTrade).order_by(PaperTrade.created_at.asc()).all()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        def _is_today(created) -> bool:
            if not created:
                return False
            dt = created.astimezone(timezone.utc) if created.tzinfo else created
            return dt.strftime("%Y-%m-%d") == today

        agg: dict[str, list[float]] = {}  # mint -> [bought_qty, bought_cost, sold_qty]
        spent_today = 0.0
        loss_today = 0.0
        for r in rows:
            a = agg.setdefault(r.token_mint, [0.0, 0.0, 0.0])
            is_today = _is_today(getattr(r, "created_at", None))
            if r.side == "buy":
                a[0] += r.token_amount or 0.0
                a[1] += r.sol_amount or 0.0
                if is_today:
                    spent_today += r.sol_amount or 0.0
            else:
                a[2] += r.token_amount or 0.0
                if is_today and (r.realized_pnl_sol or 0.0) < 0:
                    loss_today += abs(r.realized_pnl_sol or 0.0)

        recovered = 0
        open_positions: dict[str, int] = {}
        for mint, (bq, bc, sq) in agg.items():
            rem = bq - sq
            if rem > 1e-9 and bq > 1e-12:
                pos = self.paper._pos(mint)
                pos.qty = rem
                pos.cost_sol = bc * (rem / bq)  # ortalama-maliyet yaklaşımı
                open_positions[mint] = 1
                recovered += 1

        live_rows = (
            db.query(LiveTrade)
            .filter(LiveTrade.status != "failed")
            .order_by(LiveTrade.created_at.asc())
            .all()
        )
        live_agg: dict[str, float] = {}
        for r in live_rows:
            delta = float(r.token_amount or 0.0)
            if r.side == "buy":
                live_agg[r.token_mint] = live_agg.get(r.token_mint, 0.0) + delta
                if _is_today(getattr(r, "created_at", None)):
                    spent_today += float(r.sol_amount or 0.0)
            elif r.side == "sell":
                live_agg[r.token_mint] = live_agg.get(r.token_mint, 0.0) - delta
                if _is_today(getattr(r, "created_at", None)) and (r.realized_pnl_sol or 0.0) < 0:
                    loss_today += abs(r.realized_pnl_sol or 0.0)
        for mint, qty in live_agg.items():
            if qty > 1e-9:
                open_positions[mint] = max(open_positions.get(mint, 0), 1)

        self.day.date = today
        self.day.spent_sol = round(spent_today, 9)
        self.day.loss_sol = round(loss_today, 9)
        self.day.open_positions = open_positions
        return {"recovered_positions": recovered + sum(1 for q in live_agg.values() if q > 1e-9),
                "spent_today": self.day.spent_sol,
                "loss_today": self.day.loss_sol}

    def _recheck_safety(self, ctx: TradeContext) -> list[str]:
        """İşlem göndermeden hemen önce son güvenlik kontrolü (kapı politikasına
        duyarlı; "safety" modunda token puanı engel değildir)."""
        problems = []
        if not ctx.token_sellable:
            problems.append("Token satılabilir değil (son kontrol)")
        min_token = effective_min_token_score(self.cfg)
        if min_token > 0 and ctx.token_score < min_token:
            problems.append("Token puanı eşik altına düştü (son kontrol)")
        if 0 < ctx.token_liquidity_sol < self.cfg.min_liquidity_sol:
            problems.append("Likidite eşik altına düştü (son kontrol)")
        if ctx.market_price_sol <= 0:
            problems.append("Giriş fiyatı alınamadı")
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
            forced_amount=ctx.forced_sol_amount,
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
            row = self._execute_live(db, ctx, decision.sol_amount)
            decision.trade_id = row.id
            decision.trade_status = row.status
            if row.status == "failed":
                decision.allowed = False
                decision.reasons = [row.error or "Canlı alım gönderilemedi"]
        return decision

    def _execute_paper(self, db: Session, ctx: TradeContext, sol_amount: float) -> PaperTrade:
        reason = "ai-buy" if ctx.strategy == "ai" else "copy-buy"
        fill = self.paper.buy(ctx.token_mint, sol_amount, ctx.market_price_sol, reason=reason)
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
            reason=("ai-buy (paper)" if ctx.strategy == "ai" else "copy-buy (paper)"),
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

    def _open_live_position(self, db: Session, token_mint: str) -> tuple[float, float]:
        """Canlı trade kayıtlarından yaklaşık açık miktar ve maliyeti türetir.

        PumpPortal gönderiminde kesin fill miktarı dönmediği için canlı kapanış
        PnL'i yaklaşık tutulur; asıl amaç lider satışı gelince zincire sell emrini
        göndermek ve açık durumu güvenli kapatmaktır.
        """
        rows = (
            db.query(LiveTrade)
            .filter(LiveTrade.token_mint == token_mint, LiveTrade.status != "failed")
            .order_by(LiveTrade.created_at.asc())
            .all()
        )
        qty = 0.0
        cost = 0.0
        for r in rows:
            if r.side == "buy":
                qty += float(r.token_amount or 0.0)
                cost += float(r.sol_amount or 0.0)
            elif r.side == "sell" and qty > 0:
                sold_qty = min(qty, float(r.token_amount or 0.0))
                frac = sold_qty / qty if qty > 0 else 0.0
                cost -= cost * frac
                qty -= sold_qty
                if qty <= 1e-9:
                    qty = 0.0
                    cost = 0.0
        return qty, cost

    def _execute_live_sell(self, db: Session, ctx: TradeContext, fraction: float) -> LiveTrade | None:
        if not self.cfg.live_confirmed:
            raise LiveTradingNotConfigured("Canlı işlem onaylanmamış")
        if self.signer is None:
            raise LiveTradingNotConfigured("İmzalayıcı (PumpPortal) yapılandırılmamış")
        qty, cost = self._open_live_position(db, ctx.token_mint)
        if qty <= 1e-12:
            return None
        fraction = max(0.0, min(1.0, fraction))
        qty_sell = qty * fraction
        has_price = ctx.market_price_sol > 0
        proceeds_est = qty_sell * ctx.market_price_sol if has_price else 0.0
        cost_part = cost * fraction
        row = LiveTrade(
            wallet_address=ctx.wallet_address,
            token_mint=ctx.token_mint,
            side="sell",
            sol_amount=proceeds_est,
            token_amount=qty_sell,
            price_sol=ctx.market_price_sol if has_price else 0.0,
            status="pending",
            is_open=False,
            realized_pnl_sol=(proceeds_est - cost_part) if has_price else 0.0,
            source_signature=ctx.source_signature,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        try:
            sig = self.signer.submit_sell(
                ctx.token_mint,
                fraction,
                ctx.market_price_sol,
                max_slippage=self.cfg.max_slippage,
                priority_fee_sol=self.cfg.priority_fee_sol,
            )
            row.signature = sig
            row.status = "submitted"
            if fraction >= 0.999:
                self.day.open_positions.pop(ctx.token_mint, None)
            elif ctx.token_mint in self.day.open_positions:
                self.day.open_positions[ctx.token_mint] = max(0, self.day.open_positions[ctx.token_mint] - 1)
        except Exception as exc:  # noqa: BLE001
            row.status = "failed"
            row.error = str(exc)[:240]
            logger.warning("Canlı satış başarısız: %s", exc)
        row.created_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(row)
        return row

    def on_leader_sell(self, db: Session, ctx: TradeContext, leader_sell_fraction: float):
        """Hedef kısmi/tam satış yaptığında yansıt (paper/live)."""
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
        if self.cfg.mode == "live":
            return self._execute_live_sell(db, ctx, leader_sell_fraction)
        return None
