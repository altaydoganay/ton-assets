"""ORM modelleri — görev tanımındaki tüm tablolar.

wallets, wallet_scores, wallet_relationships, tokens, token_scores,
token_holders, swaps, positions, alerts, paper_trades, live_trades,
settings, risk_rules, audit_logs.

Puan geçmişi *_scores tablolarında saklanır; her yeniden analizde yeni satır
eklenir, böylece zaman içindeki değişim grafiklenebilir.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WalletStatus(str, enum.Enum):
    discovered = "discovered"       # keşfedildi, henüz analiz edilmedi
    analyzed = "analyzed"           # analiz edildi, eşik altında
    tracked = "tracked"             # puan >= eşik, takip listesinde
    below_threshold = "below_threshold"  # eşik altına düştü (silinmez)
    rejected = "rejected"           # veto/eleme kuralına takıldı
    blocked = "blocked"             # kullanıcı tarafından engellendi


class TokenStage(str, enum.Enum):
    bonding = "bonding"             # bonding curve aşamasında
    graduating = "graduating"
    graduated = "graduated"         # PumpSwap/DEX'e mezun oldu
    unknown = "unknown"


class TokenStatus(str, enum.Enum):
    discovered = "discovered"
    analyzed = "analyzed"
    tracked = "tracked"
    below_threshold = "below_threshold"
    vetoed = "vetoed"
    blocked = "blocked"


class SwapSide(str, enum.Enum):
    buy = "buy"
    sell = "sell"


class TradeMode(str, enum.Enum):
    paper = "paper"
    live = "live"


# --------------------------------------------------------------------------- #
# Cüzdanlar
# --------------------------------------------------------------------------- #
class Wallet(Base):
    __tablename__ = "wallets"

    id: Mapped[int] = mapped_column(primary_key=True)
    address: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=WalletStatus.discovered.value, index=True)
    discovery_source: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # En güncel hesaplanmış metrikler (detay *_scores'ta geçmişiyle tutulur)
    latest_score: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    risk_flags: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)  # veri yeterliliği 0-1

    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_analyzed: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    scores: Mapped[list["WalletScore"]] = relationship(back_populates="wallet", cascade="all, delete-orphan")


class WalletScore(Base):
    """Cüzdan puan geçmişi — alt kırılımlarıyla birlikte."""
    __tablename__ = "wallet_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id"), index=True)
    total: Mapped[float] = mapped_column(Float)
    # alt puanlar
    performance: Mapped[float] = mapped_column(Float, default=0.0)      # %25
    consistency: Mapped[float] = mapped_column(Float, default=0.0)      # %20
    risk: Mapped[float] = mapped_column(Float, default=0.0)             # %15
    organic: Mapped[float] = mapped_column(Float, default=0.0)          # %15
    hold_quality: Mapped[float] = mapped_column(Float, default=0.0)     # %10
    safety: Mapped[float] = mapped_column(Float, default=0.0)           # %10
    recency: Mapped[float] = mapped_column(Float, default=0.0)          # %5
    breakdown: Mapped[dict] = mapped_column(JSON, default=dict)         # gerekçeler
    vetoed: Mapped[bool] = mapped_column(Boolean, default=False)
    veto_reasons: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    wallet: Mapped[Wallet] = relationship(back_populates="scores")


class WalletRelationship(Base):
    """Cüzdanlar arası bağlantı (sybil/insider/copy kümeleri)."""
    __tablename__ = "wallet_relationships"
    __table_args__ = (
        UniqueConstraint("source_address", "target_address", "kind", name="uq_wallet_rel"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_address: Mapped[str] = mapped_column(String(64), index=True)
    target_address: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # copy | funding | cluster | insider
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------- #
# Tokenler
# --------------------------------------------------------------------------- #
class Token(Base):
    __tablename__ = "tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    mint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    creator: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    stage: Mapped[str] = mapped_column(String(32), default=TokenStage.unknown.value, index=True)
    status: Mapped[str] = mapped_column(String(32), default=TokenStatus.discovered.value, index=True)

    latest_score: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    risk_flags: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_on_chain_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_analyzed: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    scores: Mapped[list["TokenScore"]] = relationship(back_populates="token", cascade="all, delete-orphan")
    holders: Mapped[list["TokenHolder"]] = relationship(back_populates="token", cascade="all, delete-orphan")


class TokenScore(Base):
    __tablename__ = "token_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_id: Mapped[int] = mapped_column(ForeignKey("tokens.id"), index=True)
    total: Mapped[float] = mapped_column(Float)
    security: Mapped[float] = mapped_column(Float, default=0.0)         # %30
    holder_distribution: Mapped[float] = mapped_column(Float, default=0.0)  # %20
    creator_history: Mapped[float] = mapped_column(Float, default=0.0)  # %15
    liquidity_quality: Mapped[float] = mapped_column(Float, default=0.0)    # %15
    organic_growth: Mapped[float] = mapped_column(Float, default=0.0)   # %10
    trade_behavior: Mapped[float] = mapped_column(Float, default=0.0)   # %10
    breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    vetoed: Mapped[bool] = mapped_column(Boolean, default=False)
    veto_reasons: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    token: Mapped[Token] = relationship(back_populates="scores")


class TokenHolder(Base):
    __tablename__ = "token_holders"
    __table_args__ = (
        UniqueConstraint("token_id", "address", name="uq_token_holder"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    token_id: Mapped[int] = mapped_column(ForeignKey("tokens.id"), index=True)
    address: Mapped[str] = mapped_column(String(64), index=True)
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    pct: Mapped[float] = mapped_column(Float, default=0.0)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)  # LP/bonding curve/sistem
    is_insider: Mapped[bool] = mapped_column(Boolean, default=False)
    rank: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    token: Mapped[Token] = relationship(back_populates="holders")


# --------------------------------------------------------------------------- #
# İşlemler / pozisyonlar
# --------------------------------------------------------------------------- #
class Swap(Base):
    """Tespit edilmiş gerçek swap (al/sat). Transferler ayrıştırılır, burada tutulmaz."""
    __tablename__ = "swaps"
    __table_args__ = (
        Index("ix_swap_wallet_token", "wallet_address", "token_mint"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    signature: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    token_mint: Mapped[str] = mapped_column(String(64), index=True)
    side: Mapped[str] = mapped_column(String(8))
    sol_amount: Mapped[float] = mapped_column(Float, default=0.0)       # net SOL (ücretler hariç hareket)
    token_amount: Mapped[float] = mapped_column(Float, default=0.0)
    price_sol: Mapped[float] = mapped_column(Float, default=0.0)        # token başına SOL
    fee_sol: Mapped[float] = mapped_column(Float, default=0.0)          # ağ ücreti + priority + tip
    slippage_est: Mapped[float] = mapped_column(Float, default=0.0)
    venue: Mapped[str | None] = mapped_column(String(32), nullable=True)  # pumpfun | pumpswap | raydium
    block_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    slot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confirmation: Mapped[str] = mapped_column(String(16), default="confirmed")  # confirmed|finalized
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Position(Base):
    """Kapanmış/açık pozisyon (FIFO maliyetlendirme sonucu)."""
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    token_mint: Mapped[str] = mapped_column(String(64), index=True)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    qty_open: Mapped[float] = mapped_column(Float, default=0.0)
    cost_basis_sol: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pnl_sol: Mapped[float] = mapped_column(Float, default=0.0)
    unrealized_pnl_sol: Mapped[float] = mapped_column(Float, default=0.0)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hold_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------- #
# Bildirimler ve işlemler
# --------------------------------------------------------------------------- #
class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    # dedup anahtarı: tx imzası + cüzdan + token
    dedup_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    signature: Mapped[str] = mapped_column(String(128), index=True)
    wallet_address: Mapped[str] = mapped_column(String(64))
    token_mint: Mapped[str] = mapped_column(String(64))
    wallet_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    token_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    sent: Mapped[bool] = mapped_column(Boolean, default=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    auto_traded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class PaperTrade(Base):
    __tablename__ = "paper_trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)  # kopyalanan hedef cüzdan
    token_mint: Mapped[str] = mapped_column(String(64), index=True)
    side: Mapped[str] = mapped_column(String(8))
    sol_amount: Mapped[float] = mapped_column(Float, default=0.0)
    token_amount: Mapped[float] = mapped_column(Float, default=0.0)
    price_sol: Mapped[float] = mapped_column(Float, default=0.0)
    fee_sol: Mapped[float] = mapped_column(Float, default=0.0)
    slippage_est: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pnl_sol: Mapped[float] = mapped_column(Float, default=0.0)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_signature: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class LiveTrade(Base):
    __tablename__ = "live_trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    token_mint: Mapped[str] = mapped_column(String(64), index=True)
    side: Mapped[str] = mapped_column(String(8))
    sol_amount: Mapped[float] = mapped_column(Float, default=0.0)
    token_amount: Mapped[float] = mapped_column(Float, default=0.0)
    price_sol: Mapped[float] = mapped_column(Float, default=0.0)
    fee_sol: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(24), default="pending")  # pending|submitted|confirmed|failed
    signature: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    realized_pnl_sol: Mapped[float] = mapped_column(Float, default=0.0)
    source_signature: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


# --------------------------------------------------------------------------- #
# Ayarlar / kurallar / denetim
# --------------------------------------------------------------------------- #
class Setting(Base):
    """Anahtar-değer ayar deposu (puan ağırlıkları, eşikler, risk parametreleri)."""
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class RiskRule(Base):
    __tablename__ = "risk_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    level: Mapped[str] = mapped_column(String(16), default="info", index=True)
    category: Mapped[str] = mapped_column(String(48), index=True)
    message: Mapped[str] = mapped_column(Text)
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
