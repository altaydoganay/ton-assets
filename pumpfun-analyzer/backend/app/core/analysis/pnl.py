"""PnL ve performans metrikleri.

Maliyet hesaplama yöntemi: **FIFO (ilk giren ilk çıkar)**.
- Her alış, sıraya (lot) eklenir: (miktar, SOL maliyeti, zaman).
- Her satış, en eski lotlardan tüketir; gerçekleşmiş PnL = satış geliri - tüketilen
  lotların maliyeti. Ücretler (ağ + priority + tip) hem alışta hem satışta
  maliyete/gelire dahil edilir, böylece "ücretler sonrası" sonuç elde edilir.
- Açık pozisyonlar **kazanılmış işlem sayılmaz**; yalnızca gerçekleşmiş (kapanmış)
  kısımlar PnL'e ve başarı oranına girer.
- Gerçekleşmemiş PnL ayrı raporlanır (mevcut fiyat verilirse).

Tüm hesaplar SOL bazlıdır; USD'ye çevrim çağıran tarafça (sol_usd) opsiyoneldir.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from statistics import median, pstdev
from typing import Iterable


@dataclass
class SwapEvent:
    token_mint: str
    side: str            # "buy" | "sell"
    sol_amount: float    # mutlak SOL hareketi (ücret hariç)
    token_amount: float
    fee_sol: float
    block_time: int      # unix saniye


@dataclass
class ClosedTrade:
    token_mint: str
    qty: float
    cost_sol: float      # ücretler dahil maliyet
    proceeds_sol: float  # ücretler düşülmüş gelir
    pnl_sol: float
    open_time: int
    close_time: int
    hold_seconds: int

    @property
    def is_win(self) -> bool:
        return self.pnl_sol > 0


@dataclass
class Lot:
    qty: float
    cost_sol: float  # bu lotun (ücret dahil) toplam maliyeti
    time: int


@dataclass
class WalletPerformance:
    swaps_analyzed: int = 0
    tokens_traded: int = 0
    closed_positions: int = 0
    open_positions: int = 0
    win_rate: float = 0.0
    avg_hold_seconds: float = 0.0
    median_hold_seconds: float = 0.0
    realized_pnl_sol: float = 0.0
    unrealized_pnl_sol: float = 0.0
    profit_factor: float = 0.0
    avg_win_loss_ratio: float = 0.0
    max_drawdown_sol: float = 0.0
    avg_risk_per_trade_sol: float = 0.0
    token_diversity: int = 0
    trade_frequency_per_day: float = 0.0
    amount_consistency: float = 0.0      # 0-1, 1 = çok tutarlı
    short_hold_ratio: float = 0.0        # <10 dk kapanan oran
    largest_trade_pnl_share: float = 0.0 # tek işlemin toplam kârdaki payı
    closed_trades: list[ClosedTrade] = field(default_factory=list)
    confidence: float = 0.0              # veri yeterliliği 0-1


SHORT_HOLD_SECONDS = 600  # 10 dakika


def compute_performance(
    swaps: Iterable[SwapEvent],
    current_prices: dict[str, float] | None = None,
) -> WalletPerformance:
    """FIFO ile cüzdan performansını hesaplar."""
    swaps = sorted(swaps, key=lambda s: s.block_time)
    current_prices = current_prices or {}

    lots: dict[str, deque[Lot]] = defaultdict(deque)
    closed: list[ClosedTrade] = []
    tokens_seen: set[str] = set()
    invested_per_trade: list[float] = []

    for s in swaps:
        tokens_seen.add(s.token_mint)
        if s.side == "buy":
            cost = s.sol_amount + s.fee_sol  # ücret dahil maliyet
            lots[s.token_mint].append(Lot(qty=s.token_amount, cost_sol=cost, time=s.block_time))
            invested_per_trade.append(s.sol_amount)
        elif s.side == "sell":
            remaining = s.token_amount
            proceeds_total = s.sol_amount - s.fee_sol  # ücret düşülmüş gelir
            if s.token_amount <= 0:
                continue
            proceeds_per_unit = proceeds_total / s.token_amount
            q = lots[s.token_mint]
            while remaining > 1e-12 and q:
                lot = q[0]
                take = min(lot.qty, remaining)
                frac = take / lot.qty if lot.qty else 0
                cost_part = lot.cost_sol * frac
                proceeds_part = proceeds_per_unit * take
                pnl = proceeds_part - cost_part
                hold = max(0, s.block_time - lot.time)
                closed.append(
                    ClosedTrade(
                        token_mint=s.token_mint,
                        qty=take,
                        cost_sol=cost_part,
                        proceeds_sol=proceeds_part,
                        pnl_sol=pnl,
                        open_time=lot.time,
                        close_time=s.block_time,
                        hold_seconds=hold,
                    )
                )
                lot.qty -= take
                lot.cost_sol -= cost_part
                remaining -= take
                if lot.qty <= 1e-12:
                    q.popleft()
            # Eğer eldeki lot'tan fazla satış varsa (veri eksik), kalanı yok say.

    perf = WalletPerformance()
    perf.swaps_analyzed = len(swaps)
    perf.tokens_traded = len(tokens_seen)
    perf.token_diversity = len(tokens_seen)
    perf.closed_trades = closed
    perf.closed_positions = len(closed)

    # Açık pozisyonlar + gerçekleşmemiş PnL
    open_count = 0
    unrealized = 0.0
    for mint, q in lots.items():
        for lot in q:
            if lot.qty > 1e-9:
                open_count += 1
                price = current_prices.get(mint)
                if price is not None:
                    unrealized += lot.qty * price - lot.cost_sol
    perf.open_positions = open_count
    perf.unrealized_pnl_sol = unrealized

    if not closed:
        # Yine de örneklem güveni hesapla
        perf.confidence = _confidence(perf)
        return perf

    wins = [t for t in closed if t.is_win]
    losses = [t for t in closed if t.pnl_sol < 0]
    gross_profit = sum(t.pnl_sol for t in wins)
    gross_loss = abs(sum(t.pnl_sol for t in losses))

    perf.realized_pnl_sol = sum(t.pnl_sol for t in closed)
    perf.win_rate = len(wins) / len(closed)
    holds = [t.hold_seconds for t in closed]
    perf.avg_hold_seconds = sum(holds) / len(holds)
    perf.median_hold_seconds = median(holds)
    perf.profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0
    avg_win = (gross_profit / len(wins)) if wins else 0.0
    avg_loss = (gross_loss / len(losses)) if losses else 0.0
    perf.avg_win_loss_ratio = (avg_win / avg_loss) if avg_loss > 0 else (avg_win if avg_win else 0.0)
    perf.short_hold_ratio = sum(1 for t in closed if t.hold_seconds < SHORT_HOLD_SECONDS) / len(closed)

    # Tek işlemin toplam (pozitif) kârdaki payı
    if gross_profit > 0:
        perf.largest_trade_pnl_share = max((t.pnl_sol for t in wins), default=0.0) / gross_profit

    # Maksimum düşüş (kümülatif gerçekleşmiş PnL eğrisi üzerinde)
    perf.max_drawdown_sol = _max_drawdown([t.pnl_sol for t in sorted(closed, key=lambda c: c.close_time)])

    # İşlem başına risk = ortalama yatırılan SOL
    if invested_per_trade:
        perf.avg_risk_per_trade_sol = sum(invested_per_trade) / len(invested_per_trade)
        perf.amount_consistency = _consistency(invested_per_trade)

    # İşlem sıklığı (gün başına)
    times = [s.block_time for s in swaps]
    span_days = max(1e-9, (max(times) - min(times)) / 86400.0)
    perf.trade_frequency_per_day = len(swaps) / span_days if span_days > 0 else float(len(swaps))

    perf.confidence = _confidence(perf)
    return perf


def _max_drawdown(pnls: list[float]) -> float:
    """Kümülatif kâr eğrisindeki en büyük tepe-dip düşüşü (SOL, pozitif sayı)."""
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        dd = peak - cum
        max_dd = max(max_dd, dd)
    return max_dd


def _consistency(amounts: list[float]) -> float:
    """İşlem tutarlarının tutarlılığı: 1 - normalize edilmiş değişim katsayısı."""
    if len(amounts) < 2:
        return 0.5
    mean = sum(amounts) / len(amounts)
    if mean <= 0:
        return 0.0
    cv = pstdev(amounts) / mean
    return max(0.0, min(1.0, 1.0 - cv))


def _confidence(perf: WalletPerformance) -> float:
    """Veri yeterliliği güveni: örneklem büyüklüğü ve çeşitliliğe dayalı 0-1.

    "Tam güven" referansı GERÇEKÇİ bir aktif trader örneklemine hizalanır:
    ~20 kapalı pozisyon ve ~10 farklı token. Böylece eleme kriterlerini (8/4)
    rahatça aşan kaliteli bir cüzdanın yüksek ham puanı, düşük güven yüzünden 70
    altına EZİLMEZ; ama az veri (eleme minimumu) hâlâ temkinli (≈0.4) kalır —
    yani ince örnekleme yüksek puan verilmez (veri yeterliliği ilkesi korunur).
    """
    pos = min(1.0, perf.closed_positions / 16.0)
    div = min(1.0, perf.token_diversity / 8.0)
    return round(0.6 * pos + 0.4 * div, 3)
