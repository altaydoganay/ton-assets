"""Gerçek trading cüzdanı portföy snapshot'ı.

DB'deki `LiveTrade` kayıtları yaklaşık pozisyon defteridir; zincirdeki gerçek
cüzdan bakiyesiyle birebir aynı olmak zorunda değildir. Bu servis doğrudan Solana
RPC'den SOL ve SPL token bakiyelerini okur, panelde gerçek portföy referansı sağlar.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..adapters.base import MarketProvider


def resolve_trading_wallet_address() -> tuple[str | None, str]:
    """Varsayılan portföy adresini bul.

    Öncelik:
      1) `.env` TRADING_WALLET_ADDRESS
      2) Yerel keystore public adresi

    PumpPortal Lightning API key her kurulumda public adres olarak okunamadığı
    için bu alan ayrı tutulur.
    """
    from ..config import settings

    if settings.trading_wallet_address:
        return settings.trading_wallet_address, "env"
    try:
        from ..security.keystore import Keystore

        ks = Keystore(settings.keystore_path)
        if ks.exists():
            addr = ks.public_address()
            if addr:
                return addr, "keystore"
    except Exception:  # noqa: BLE001
        pass
    return None, "missing"


def _parse_token_account(row: dict[str, Any]) -> dict[str, Any] | None:
    try:
        info = row["account"]["data"]["parsed"]["info"]
        amount = info["tokenAmount"]
        ui_amount = amount.get("uiAmount")
        if ui_amount is None:
            ui_amount = float(amount.get("uiAmountString") or 0)
        ui_amount = float(ui_amount or 0.0)
        if ui_amount <= 0:
            return None
        return {
            "account": row.get("pubkey"),
            "mint": info.get("mint"),
            "amount": ui_amount,
            "decimals": int(amount.get("decimals") or 0),
            "raw_amount": amount.get("amount"),
            "program_id": row.get("program_id"),
            "source": "token_account",
        }
    except (KeyError, TypeError, ValueError):
        return None


def _das_metadata(asset: dict[str, Any]) -> dict[str, Any]:
    content = asset.get("content") or {}
    metadata = content.get("metadata") or {}
    links = content.get("links") or {}
    files = content.get("files") or []
    image = links.get("image")
    if not image and files:
        image = files[0].get("uri") if isinstance(files[0], dict) else None
    return {
        "name": metadata.get("name") or asset.get("name"),
        "symbol": metadata.get("symbol"),
        "image": image,
    }


def _parse_das_fungible(asset: dict[str, Any]) -> dict[str, Any] | None:
    token_info = asset.get("token_info") or {}
    interface = str(asset.get("interface") or "").lower()
    has_token_info = bool(token_info)
    if not has_token_info and "fungible" not in interface:
        return None
    mint = asset.get("id") or token_info.get("mint")
    if not mint:
        return None
    decimals = int(token_info.get("decimals") or 0)
    raw_balance = token_info.get("balance")
    amount = token_info.get("ui_amount")
    if amount is None:
        amount = token_info.get("amount")
    if amount is None and raw_balance is not None:
        try:
            amount = float(raw_balance) / (10 ** decimals)
        except (TypeError, ValueError):
            amount = 0.0
    try:
        amount_f = float(amount or 0.0)
    except (TypeError, ValueError):
        amount_f = 0.0
    if amount_f <= 0:
        return None
    meta = _das_metadata(asset)
    return {
        "account": None,
        "mint": mint,
        "amount": amount_f,
        "decimals": decimals,
        "raw_amount": raw_balance,
        "source": "helius_das",
        **meta,
    }


def _same(a: str | None, b: str) -> bool:
    return bool(a) and a == b


def _token_amount_from_transfer(t: dict[str, Any]) -> float:
    for key in ("tokenAmount", "amount"):
        try:
            if t.get(key) is not None:
                return float(t.get(key) or 0.0)
        except (TypeError, ValueError):
            pass
    return 0.0


def _enhanced_transfer_balances(chain, address: str, pages: int = 5) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    """Helius enhanced transaction geçmişinden yaklaşık token bakiyesi çıkar.

    Bu kesin muhasebe yerine bir fallback'tir: token account/DAS boş dönerse ama
    Helius geçmişinde son alım-satım transferleri varsa panelde pozisyonu görünür
    kılar. Özellikle PumpPortal/parsed-account gecikmesi durumunda faydalıdır.
    """
    getter = getattr(chain, "get_address_transactions", None)
    if getter is None:
        return {}, {"enhanced_pages": 0, "enhanced_transactions": 0, "enhanced_transfers": 0}
    deltas: dict[str, float] = {}
    meta: dict[str, dict[str, Any]] = {}
    before = None
    tx_count = 0
    transfer_count = 0
    pages_done = 0
    for _ in range(max(1, pages)):
        try:
            txs = getter(address, limit=100, before=before)
        except Exception:  # noqa: BLE001
            break
        if not txs:
            break
        pages_done += 1
        tx_count += len(txs)
        before = txs[-1].get("signature") or before
        for tx in txs:
            for tr in tx.get("tokenTransfers") or []:
                mint = tr.get("mint")
                if not mint:
                    continue
                amount = _token_amount_from_transfer(tr)
                if amount <= 0:
                    continue
                if _same(tr.get("toUserAccount"), address) or _same(tr.get("toOwner"), address):
                    deltas[mint] = deltas.get(mint, 0.0) + amount
                    transfer_count += 1
                if _same(tr.get("fromUserAccount"), address) or _same(tr.get("fromOwner"), address):
                    deltas[mint] = deltas.get(mint, 0.0) - amount
                    transfer_count += 1
                meta.setdefault(mint, {
                    "mint": mint,
                    "name": tr.get("tokenName"),
                    "symbol": tr.get("tokenSymbol"),
                    "source": "enhanced_tx_fallback",
                })
        if len(txs) < 100:
            break
    out = {}
    for mint, amount in deltas.items():
        if amount > 1e-9:
            out[mint] = {
                **meta.get(mint, {"mint": mint}),
                "account": None,
                "amount": amount,
                "decimals": None,
                "raw_amount": None,
                "source": "enhanced_tx_fallback",
            }
    return out, {
        "enhanced_pages": pages_done,
        "enhanced_transactions": tx_count,
        "enhanced_transfers": transfer_count,
    }


def fetch_wallet_portfolio(
    chain,
    market: MarketProvider | None,
    address: str,
    *,
    commitment: str = "processed",
    include_history_fallback: bool = False,
    include_das_balances: bool = False,
) -> dict:
    """RPC'den gerçek cüzdan bakiyesini al ve mevcut market fiyatlarıyla zenginleştir.

    Portföy ekranında eski işlem geçmişinden bakiye türetmek doğru değildir:
    satılmış/kapalı tokenler eski transferlerde pozitif görünüp paneli yanıltabilir.
    Bu yüzden varsayılan yalnızca anlık token account + Helius DAS snapshot'ıdır.
    """
    try:
        sol_balance = float(chain.get_balance_sol(address, commitment=commitment))
    except TypeError:
        sol_balance = float(chain.get_balance_sol(address))
    try:
        accounts = chain.get_token_accounts_by_owner(address, commitment=commitment)
    except TypeError:
        accounts = chain.get_token_accounts_by_owner(address)
    by_mint: dict[str, dict[str, Any]] = {}
    total_value_sol = sol_balance

    for row in accounts:
        item = _parse_token_account(row)
        if not item or not item.get("mint"):
            continue
        by_mint[item["mint"]] = item

    das_only_skipped = 0
    try:
        assets = chain.get_assets_by_owner(address)
    except Exception:  # noqa: BLE001
        assets = []
    for asset in assets:
        item = _parse_das_fungible(asset)
        if not item or not item.get("mint"):
            continue
        existing = by_mint.get(item["mint"])
        if existing:
            existing.update({k: v for k, v in item.items() if v not in (None, "") and k not in {"amount", "raw_amount"}})
            if existing.get("amount", 0) <= 0:
                existing["amount"] = item["amount"]
                existing["raw_amount"] = item.get("raw_amount")
            existing["source"] = "token_account+helius_das"
        elif include_das_balances:
            by_mint[item["mint"]] = item
        else:
            das_only_skipped += 1

    enhanced: dict[str, dict[str, Any]] = {}
    enhanced_debug = {"enhanced_pages": 0, "enhanced_transactions": 0, "enhanced_transfers": 0}
    if include_history_fallback:
        enhanced, enhanced_debug = _enhanced_transfer_balances(chain, address)
        for mint, item in enhanced.items():
            existing = by_mint.get(mint)
            if existing:
                if existing.get("amount", 0) <= 0:
                    existing["amount"] = item["amount"]
                existing["source"] = f"{existing.get('source') or 'unknown'}+enhanced_tx"
            else:
                item["stale_risk"] = True
                by_mint[mint] = item

    tokens: list[dict[str, Any]] = []
    for item in by_mint.values():
        price_sol = None
        liquidity_sol = None
        market_cap_usd = None
        pair_created_at = None
        source = None
        if market is not None:
            try:
                md = market.get_token_market(item["mint"])
                if md and md.ok:
                    price_sol = md.price_sol
                    liquidity_sol = md.liquidity_sol
                    market_cap_usd = md.market_cap_usd
                    pair_created_at = md.pair_created_at
                    source = md.source
            except Exception:  # noqa: BLE001
                pass
        value_sol = float(item["amount"]) * float(price_sol) if price_sol else None
        if value_sol is not None:
            total_value_sol += value_sol
        tokens.append({
            **item,
            "price_sol": price_sol,
            "value_sol": value_sol,
            "liquidity_sol": liquidity_sol,
            "market_cap_usd": market_cap_usd,
            "pair_created_at": pair_created_at,
            "price_source": source,
        })

    tokens.sort(key=lambda x: x.get("value_sol") if x.get("value_sol") is not None else -1, reverse=True)
    return {
        "address": address,
        "source": "onchain_rpc+das",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "commitment": commitment,
        "history_fallback_used": bool(include_history_fallback),
        "das_balance_used": bool(include_das_balances),
        "sol_balance": round(sol_balance, 9),
        "token_count": len(tokens),
        "total_value_sol": round(total_value_sol, 9),
        "priced_token_count": sum(1 for t in tokens if t.get("value_sol") is not None),
        "debug": {
            "token_account_rows": len(accounts),
            "das_assets": len(assets),
            "das_only_skipped": das_only_skipped,
            "snapshot_sources": "token_accounts+das",
            "enhanced_positive_mints": len(enhanced),
            **enhanced_debug,
        },
        "tokens": tokens,
    }
