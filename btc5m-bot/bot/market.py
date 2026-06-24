"""Target-market discovery and live quoting for <asset>-updown-5m series."""
from __future__ import annotations
import json
import time
from dataclasses import dataclass

from . import feeds


@dataclass
class Quote:
    market_id: str
    slug: str
    end_ts: int
    seconds_left: int
    up_token: str
    dn_token: str
    up_bid: float | None
    up_ask: float | None
    dn_bid: float | None
    dn_ask: float | None


def _end_ts_from_slug(slug: str) -> int | None:
    tail = slug.rsplit("-", 1)[-1]
    return int(tail) if tail.isdigit() else None


ROUND_SEC = 300   # 5-minute rounds align to multiples of 300s


def pick_target(asset: str, min_seconds_left: int = 5, lookahead_rounds: int = 6):
    """Choose the imminent open round by constructing its slug from the clock.

    Rounds end on 5-minute boundaries, so the slug is <asset>-updown-5m-<endTs>.
    We walk forward from the next boundary and take the soonest round whose
    time-to-close is still >= min_seconds_left.
    """
    now = int(time.time())
    base = ((now // ROUND_SEC) + 1) * ROUND_SEC      # next 5-min boundary
    m = None
    end_ts = None
    for k in range(lookahead_rounds):
        cand_end = base + ROUND_SEC * k
        if cand_end - now < min_seconds_left:
            continue
        cand = feeds.get_market_by_slug(f"{asset}-updown-5m-{cand_end}")
        if cand and not cand.get("closed"):
            m, end_ts = cand, cand_end
            break
    if m is None:
        return None
    toks = json.loads(m.get("clobTokenIds", "[]"))
    outcomes = m.get("outcomes")
    if isinstance(outcomes, str):
        outcomes = json.loads(outcomes)
    # map Up/Down to the right token by outcome order
    up_idx = 0 if (outcomes and outcomes[0].lower().startswith("up")) else 1
    up_token, dn_token = toks[up_idx], toks[1 - up_idx]
    return {
        "market_id": str(m.get("id")),
        "slug": m.get("slug"),
        "end_ts": end_ts,
        "up_token": up_token,
        "dn_token": dn_token,
    }


def quote(target: dict) -> Quote:
    up_bid, up_ask = feeds.order_book(target["up_token"])
    dn_bid, dn_ask = feeds.order_book(target["dn_token"])
    return Quote(
        market_id=target["market_id"],
        slug=target["slug"],
        end_ts=target["end_ts"],
        seconds_left=target["end_ts"] - int(time.time()),
        up_token=target["up_token"],
        dn_token=target["dn_token"],
        up_bid=up_bid, up_ask=up_ask, dn_bid=dn_bid, dn_ask=dn_ask,
    )
