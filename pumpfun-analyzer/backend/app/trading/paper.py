"""Paper trading motoru (kağıt üzerinde simülasyon).

- Gerçek para kullanmaz; simüle slippage ve ücretlerle pozisyon açar/kapatır.
- Hedef cüzdanın **gerçek swap'larını** takip eder (transferleri değil).
- Kısmi satış: hedef cüzdan pozisyonunun bir kısmını satarsa, ayara göre aynı
  oranda satılır veya pozisyon tamamen kapatılır.
- FIFO maliyetlendirme ile gerçekleşmiş PnL hesaplanır.

Aynı mantık canlı motorun da temelini oluşturur; canlı motor yalnızca gerçek
imzalama/gönderme adımını ekler.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PaperPosition:
    token_mint: str
    qty: float = 0.0
    cost_sol: float = 0.0       # ücret dahil toplam maliyet
    realized_pnl_sol: float = 0.0

    @property
    def is_open(self) -> bool:
        return self.qty > 1e-9

    @property
    def avg_cost(self) -> float:
        return self.cost_sol / self.qty if self.qty > 1e-9 else 0.0


@dataclass
class PaperFill:
    token_mint: str
    side: str
    sol_amount: float
    token_amount: float
    price_sol: float
    fee_sol: float
    slippage: float
    realized_pnl_sol: float
    reason: str


@dataclass
class CloseMode:
    """Hedef kısmi satış yaptığında davranış."""
    PROPORTIONAL = "proportional"  # aynı oranda sat
    FULL = "full"                  # pozisyonu tamamen kapat


class PaperTradingEngine:
    def __init__(self, slippage: float = 0.0, priority_fee_sol: float = 0.0005,
                 close_mode: str = CloseMode.PROPORTIONAL):
        self.slippage = slippage
        self.priority_fee_sol = priority_fee_sol
        self.close_mode = close_mode
        self.positions: dict[str, PaperPosition] = {}
        self.fills: list[PaperFill] = []

    def _pos(self, mint: str) -> PaperPosition:
        return self.positions.setdefault(mint, PaperPosition(token_mint=mint))

    def buy(self, token_mint: str, sol_amount: float, market_price_sol: float, reason: str = "copy-buy") -> PaperFill:
        # Slippage alıcı aleyhine fiyatı yükseltir.
        exec_price = market_price_sol * (1 + self.slippage)
        fee = self.priority_fee_sol
        spend = sol_amount
        token_amount = (spend - fee) / exec_price if exec_price > 0 else 0.0
        pos = self._pos(token_mint)
        pos.qty += token_amount
        pos.cost_sol += spend  # ücret dahil
        fill = PaperFill(token_mint, "buy", spend, token_amount, exec_price, fee, self.slippage, 0.0, reason)
        self.fills.append(fill)
        return fill

    def sell_fraction(self, token_mint: str, fraction: float, market_price_sol: float, reason: str = "copy-sell") -> PaperFill | None:
        """Pozisyonun `fraction` (0-1) oranını sat. close_mode FULL ise tamamını kapat."""
        pos = self.positions.get(token_mint)
        if not pos or not pos.is_open:
            return None
        if self.close_mode == CloseMode.FULL:
            fraction = 1.0
        fraction = max(0.0, min(1.0, fraction))
        qty_to_sell = pos.qty * fraction
        if qty_to_sell <= 1e-12:
            return None

        exec_price = market_price_sol * (1 - self.slippage)  # satıcı aleyhine
        fee = self.priority_fee_sol
        proceeds = qty_to_sell * exec_price - fee
        cost_part = pos.avg_cost * qty_to_sell
        pnl = proceeds - cost_part

        pos.qty -= qty_to_sell
        pos.cost_sol -= cost_part
        pos.realized_pnl_sol += pnl
        if pos.qty <= 1e-9:
            pos.qty = 0.0
            pos.cost_sol = 0.0

        fill = PaperFill(token_mint, "sell", proceeds, qty_to_sell, exec_price, fee, self.slippage, pnl, reason)
        self.fills.append(fill)
        return fill

    def mirror_leader_sell(self, token_mint: str, leader_sell_fraction: float, market_price_sol: float) -> PaperFill | None:
        """Hedef cüzdanın sattığı oranı yansıt."""
        return self.sell_fraction(token_mint, leader_sell_fraction, market_price_sol, reason="mirror-sell")

    @property
    def total_realized_pnl(self) -> float:
        return sum(p.realized_pnl_sol for p in self.positions.values())

    def open_positions(self) -> list[PaperPosition]:
        return [p for p in self.positions.values() if p.is_open]
