"""Live data feeds: Coinbase BTC spot + Polymarket Gamma/CLOB (stdlib only)."""
from __future__ import annotations
import json
import urllib.request

_UA = {"User-Agent": "btc5m-bot/0.1"}


def _get(url: str, timeout: int = 12):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def btc_spot() -> float:
    """Live BTC/USD spot (Coinbase). Used for sanity/logging."""
    d = _get("https://api.exchange.coinbase.com/products/BTC-USD/ticker")
    return float(d["price"])


def list_updown_markets(asset: str = "btc") -> list[dict]:
    """All open <asset>-updown-5m markets from Polymarket Gamma (best-effort)."""
    d = _get("https://gamma-api.polymarket.com/markets?closed=false&limit=500"
             "&order=startDate&ascending=false")
    pref = f"{asset}-updown-5m"
    return [m for m in d if str(m.get("slug", "")).startswith(pref)]


def get_market_by_slug(slug: str) -> dict | None:
    """Fetch a single market by exact slug (reliable for imminent rounds)."""
    d = _get(f"https://gamma-api.polymarket.com/markets?slug={slug}")
    return d[0] if d else None


def order_book(token_id: str) -> tuple[float | None, float | None]:
    """Return (best_bid, best_ask) for a CLOB token, or (None, None)."""
    b = _get(f"https://clob.polymarket.com/book?token_id={token_id}")
    bids = b.get("bids") or []
    asks = b.get("asks") or []
    best_bid = max((float(x["price"]) for x in bids), default=None)
    best_ask = min((float(x["price"]) for x in asks), default=None)
    return best_bid, best_ask
