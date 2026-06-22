"""API şemaları (Pydantic)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class WalletOut(ORMModel):
    id: int
    address: str
    label: str | None = None
    status: str
    discovery_source: str | None = None
    latest_score: float | None = None
    metrics: dict = {}
    risk_flags: list = []
    confidence: float | None = None
    last_analyzed: datetime | None = None


class WalletScoreOut(ORMModel):
    id: int
    total: float
    performance: float
    consistency: float
    risk: float
    organic: float
    hold_quality: float
    safety: float
    recency: float
    breakdown: dict = {}
    vetoed: bool
    veto_reasons: list = []
    confidence: float
    created_at: datetime


class WalletDetail(WalletOut):
    scores: list[WalletScoreOut] = []


class TokenOut(ORMModel):
    id: int
    mint: str
    name: str | None = None
    symbol: str | None = None
    creator: str | None = None
    stage: str
    status: str
    latest_score: float | None = None
    metrics: dict = {}
    risk_flags: list = []
    confidence: float | None = None
    last_analyzed: datetime | None = None


class TokenScoreOut(ORMModel):
    id: int
    total: float
    security: float
    holder_distribution: float
    creator_history: float
    liquidity_quality: float
    organic_growth: float
    trade_behavior: float
    breakdown: dict = {}
    vetoed: bool
    veto_reasons: list = []
    confidence: float
    created_at: datetime


class TokenDetail(TokenOut):
    scores: list[TokenScoreOut] = []


class SwapOut(ORMModel):
    id: int
    signature: str
    wallet_address: str
    token_mint: str
    side: str
    sol_amount: float
    token_amount: float
    price_sol: float
    fee_sol: float
    venue: str | None = None
    block_time: datetime
    confirmation: str


class AlertOut(ORMModel):
    id: int
    signature: str
    wallet_address: str
    token_mint: str
    wallet_score: float | None = None
    token_score: float | None = None
    payload: dict = {}
    sent: bool
    auto_traded: bool
    created_at: datetime


class PaperTradeOut(ORMModel):
    id: int
    wallet_address: str
    token_mint: str
    side: str
    sol_amount: float
    token_amount: float
    price_sol: float
    realized_pnl_sol: float
    is_open: bool
    reason: str | None = None
    created_at: datetime


class LiveTradeOut(ORMModel):
    id: int
    wallet_address: str
    token_mint: str
    side: str
    sol_amount: float
    status: str
    signature: str | None = None
    error: str | None = None
    is_open: bool
    realized_pnl_sol: float
    created_at: datetime


class SettingIn(BaseModel):
    value: dict[str, Any]


class HealthOut(BaseModel):
    status: str
    database: bool
    redis: bool | None = None
    chain_provider: str
    market_provider: str
    trading_mode: str
    telegram_enabled: bool
    version: str
