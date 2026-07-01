"""Gecikmeli copyability simülasyonu.

Bu modül lider cüzdanın kendi PnL'inden ayrı olarak şunu ölçer:
"Lider aldıktan N saniye sonra 0.01 SOL ile alsaydık ve lider sattığında
satsaydık, ücret/slippage sonrası sonuç ne olurdu?"

Veri kaynağı sadece mevcut `Swap` kayıtlarıdır. Eksik fiyat verisi kesin kâr
sayılmaz; coverage/not_simulatable metriklerine yansıtılır.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from statistics import median
from typing import Iterable, Sequence


@dataclass
class CopyabilitySwap:
    token_mint: str
    side: str
    sol_amount: float
    token_amount: float
    price_sol: float
    fee_sol: float
    block_time: int
    wallet_address: str | None = None


@dataclass
class LeaderLot:
    qty: float
    cost_sol: float
    price_sol: float
    block_time: int


@dataclass
class LeaderClosedPosition:
    token_mint: str
    qty: float
    leader_buy_time: int
    leader_sell_time: int
    leader_buy_price_sol: float
    leader_sell_price_sol: float
    original_pnl_sol: float


@dataclass
class DelayStats:
    pnl_sol: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    sample_size: int = 0
    not_simulatable_count: int = 0
    coverage_ratio: float = 0.0
    avg_entry_jump: float = 0.0
    median_entry_jump: float = 0.0
    pnls: list[float] = field(default_factory=list)
    entry_jumps: list[float] = field(default_factory=list)


@dataclass
class CopyabilityResult:
    copyability_score: float
    copy_sample_size: int
    copy_coverage_ratio: float
    not_simulatable_count: int
    original_realized_pnl_sol: float
    copy_degradation_10s: float
    delays: dict[int, DelayStats]

    def as_metrics(self) -> dict:
        d5 = self.delays.get(5, DelayStats())
        d10 = self.delays.get(10, DelayStats())
        d30 = self.delays.get(30, DelayStats())
        return {
            "copyability_score": round(self.copyability_score, 2),
            "copy_pnl_5s_sol": round(d5.pnl_sol, 6),
            "copy_pnl_10s_sol": round(d10.pnl_sol, 6),
            "copy_pnl_30s_sol": round(d30.pnl_sol, 6),
            "copy_win_rate_5s": round(d5.win_rate, 4),
            "copy_win_rate_10s": round(d10.win_rate, 4),
            "copy_win_rate_30s": round(d30.win_rate, 4),
            "copy_profit_factor_10s": round(d10.profit_factor, 4) if d10.profit_factor != float("inf") else None,
            "copy_sample_size": self.copy_sample_size,
            "copy_coverage_ratio": round(self.copy_coverage_ratio, 4),
            "not_simulatable_count": self.not_simulatable_count,
            "avg_entry_jump_5s": round(d5.avg_entry_jump, 4),
            "avg_entry_jump_10s": round(d10.avg_entry_jump, 4),
            "avg_entry_jump_30s": round(d30.avg_entry_jump, 4),
            "median_entry_jump_10s": round(d10.median_entry_jump, 4),
            "copy_degradation_10s": round(self.copy_degradation_10s, 4),
        }


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _ts(value) -> int:
    if hasattr(value, "timestamp"):
        return int(value.timestamp())
    return int(value or 0)


def swap_from_model(row) -> CopyabilitySwap:
    return CopyabilitySwap(
        token_mint=row.token_mint,
        side=row.side,
        sol_amount=float(row.sol_amount or 0.0),
        token_amount=float(row.token_amount or 0.0),
        price_sol=float(row.price_sol or 0.0),
        fee_sol=float(row.fee_sol or 0.0),
        block_time=_ts(row.block_time),
        wallet_address=getattr(row, "wallet_address", None),
    )


def _leader_positions(swaps: Sequence[CopyabilitySwap]) -> list[LeaderClosedPosition]:
    lots: dict[str, deque[LeaderLot]] = defaultdict(deque)
    closed: list[LeaderClosedPosition] = []
    for s in sorted(swaps, key=lambda x: x.block_time):
        if s.token_amount <= 0:
            continue
        price = s.price_sol or (s.sol_amount / s.token_amount if s.token_amount > 0 else 0.0)
        if price <= 0:
            continue
        if s.side == "buy":
            lots[s.token_mint].append(LeaderLot(
                qty=s.token_amount,
                cost_sol=s.sol_amount + s.fee_sol,
                price_sol=price,
                block_time=s.block_time,
            ))
        elif s.side == "sell":
            remaining = s.token_amount
            proceeds_total = max(0.0, s.sol_amount - s.fee_sol)
            proceeds_per_unit = proceeds_total / s.token_amount
            q = lots[s.token_mint]
            while remaining > 1e-12 and q:
                lot = q[0]
                take = min(lot.qty, remaining)
                frac = take / lot.qty if lot.qty else 0.0
                cost_part = lot.cost_sol * frac
                proceeds_part = proceeds_per_unit * take
                closed.append(LeaderClosedPosition(
                    token_mint=s.token_mint,
                    qty=take,
                    leader_buy_time=lot.block_time,
                    leader_sell_time=s.block_time,
                    leader_buy_price_sol=lot.price_sol,
                    leader_sell_price_sol=price,
                    original_pnl_sol=proceeds_part - cost_part,
                ))
                lot.qty -= take
                lot.cost_sol -= cost_part
                remaining -= take
                if lot.qty <= 1e-12:
                    q.popleft()
    return closed


def _market_index(swaps: Sequence[CopyabilitySwap]) -> dict[str, list[CopyabilitySwap]]:
    by_mint: dict[str, list[CopyabilitySwap]] = defaultdict(list)
    for s in swaps:
        price = s.price_sol or (s.sol_amount / s.token_amount if s.token_amount else 0.0)
        if s.token_mint and price > 0 and s.block_time > 0:
            s.price_sol = price
            by_mint[s.token_mint].append(s)
    for rows in by_mint.values():
        rows.sort(key=lambda x: x.block_time)
    return by_mint


def _first_price_at_or_after(rows: Sequence[CopyabilitySwap], ts: int,
                             before: int | None = None) -> float | None:
    """`ts` (dahil) ve `before` (hariç) arasındaki İLK güvenilir fiyat.

    `before` (genelde liderin satış zamanı) verilirse, follower girişini liderin
    KENDİ satış tikinden ÖNCEYE zorlar. Aksi halde ara fiyat verisi olmayan bir
    trade'de follower yanlışlıkla tepe (satış) fiyatından alıyormuş gibi hesaplanır;
    bu da gerçek trade'i uydurma "chase/zarar" gösterir. Ara fiyat yoksa None döner
    (not_simulatable) — kesin kâr/zarar varsaymayız."""
    for row in rows:
        if row.block_time < ts:
            continue
        if before is not None and row.block_time >= before:
            return None
        if row.price_sol > 0:
            return row.price_sol
    return None


def _profit_factor(values: Sequence[float]) -> float:
    wins = [v for v in values if v > 0]
    losses = [v for v in values if v < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    if gross_loss > 0:
        return gross_profit / gross_loss
    return float("inf") if gross_profit > 0 else 0.0


def _delay_stats(
    positions: Sequence[LeaderClosedPosition],
    market: dict[str, list[CopyabilitySwap]],
    *,
    delay: int,
    copy_amount_sol: float,
    slippage: float,
    priority_fee_sol: float,
) -> DelayStats:
    pnls: list[float] = []
    jumps: list[float] = []
    missing = 0
    for pos in positions:
        rows = market.get(pos.token_mint, [])
        entry_price = _first_price_at_or_after(rows, pos.leader_buy_time + delay,
                                               before=pos.leader_sell_time)
        exit_price = _first_price_at_or_after(rows, pos.leader_sell_time)
        if entry_price is None or exit_price is None or entry_price <= 0 or exit_price <= 0:
            missing += 1
            continue
        buy_exec = entry_price * (1 + slippage)
        sell_exec = exit_price * (1 - slippage)
        spend_after_fee = copy_amount_sol - priority_fee_sol
        if spend_after_fee <= 0:
            missing += 1
            continue
        qty = spend_after_fee / buy_exec
        proceeds = qty * sell_exec - priority_fee_sol
        pnls.append(proceeds - copy_amount_sol)
        if pos.leader_buy_price_sol > 0:
            jumps.append((entry_price / pos.leader_buy_price_sol) - 1)

    sample = len(pnls)
    wins = sum(1 for p in pnls if p > 0)
    return DelayStats(
        pnl_sol=sum(pnls),
        win_rate=wins / sample if sample else 0.0,
        profit_factor=_profit_factor(pnls),
        sample_size=sample,
        not_simulatable_count=missing,
        coverage_ratio=sample / len(positions) if positions else 0.0,
        avg_entry_jump=sum(jumps) / len(jumps) if jumps else 0.0,
        median_entry_jump=median(jumps) if jumps else 0.0,
        pnls=pnls,
        entry_jumps=jumps,
    )


def _score_copyability(delays: dict[int, DelayStats], original_pnl: float, copy_amount_sol: float) -> float:
    d5 = delays.get(5, DelayStats())
    d10 = delays.get(10, DelayStats())
    d30 = delays.get(30, DelayStats())
    if d10.sample_size <= 0:
        return 0.0

    avg_pnl_pct_10 = (d10.pnl_sol / (d10.sample_size * copy_amount_sol)) * 100 if copy_amount_sol > 0 else 0.0
    pnl_score = _clamp((avg_pnl_pct_10 + 5) * 5.5)
    pf = d10.profit_factor
    pf_score = 100.0 if pf == float("inf") else _clamp((pf - 0.9) * 55)
    win_score = _clamp((d10.win_rate - 0.35) * 180)
    coverage_score = _clamp(d10.coverage_ratio * 100)
    robust_bonus = 0.0
    if d5.pnl_sol > 0:
        robust_bonus += 6
    if d30.pnl_sol > 0:
        robust_bonus += 10
    if original_pnl > 0 and d10.pnl_sol > 0:
        robust_bonus += _clamp((d10.pnl_sol / original_pnl) * 15, 0, 8)

    jump_penalty = _clamp(max(0.0, d10.avg_entry_jump - 0.10) * 180, 0, 45)
    if d10.avg_entry_jump > 0.30:
        jump_penalty += 25
    sample_penalty = 18 if d10.sample_size < 6 else 0
    top_share_penalty = 0.0
    wins = [p for p in d10.pnls if p > 0]
    gross_profit = sum(wins)
    if gross_profit > 0 and wins:
        top_share = max(wins) / gross_profit
        top_share_penalty = _clamp(max(0.0, top_share - 0.45) * 100, 0, 35)

    score = (
        pnl_score * 0.32
        + pf_score * 0.24
        + win_score * 0.18
        + coverage_score * 0.16
        + robust_bonus
        - jump_penalty
        - sample_penalty
        - top_share_penalty
    )
    return round(_clamp(score), 2)


def compute_copyability(
    wallet_address: str,
    wallet_swaps: Iterable,
    market_swaps: Iterable | None = None,
    *,
    copy_amount_sol: float = 0.01,
    delays_seconds: Sequence[int] = (5, 10, 30),
    slippage: float = 0.0,
    priority_fee_sol: float = 0.0005,
) -> CopyabilityResult:
    leader = [s if isinstance(s, CopyabilitySwap) else swap_from_model(s) for s in wallet_swaps]
    market_source = market_swaps if market_swaps is not None else leader
    market_rows = [s if isinstance(s, CopyabilitySwap) else swap_from_model(s) for s in market_source]
    positions = _leader_positions(leader)
    market = _market_index(market_rows)
    delays = {
        int(d): _delay_stats(
            positions,
            market,
            delay=int(d),
            copy_amount_sol=copy_amount_sol,
            slippage=slippage,
            priority_fee_sol=priority_fee_sol,
        )
        for d in delays_seconds
    }
    d10 = delays.get(10, DelayStats())
    original_pnl = sum(p.original_pnl_sol for p in positions)
    degradation = (d10.pnl_sol / original_pnl) if original_pnl > 0 else 0.0
    return CopyabilityResult(
        copyability_score=_score_copyability(delays, original_pnl, copy_amount_sol),
        copy_sample_size=d10.sample_size,
        copy_coverage_ratio=d10.coverage_ratio,
        not_simulatable_count=d10.not_simulatable_count,
        original_realized_pnl_sol=original_pnl,
        copy_degradation_10s=degradation,
        delays=delays,
    )
