"""Cüzdanlar arası SOL/SPL transfer bağı tespiti.

Takip listesi için hedef: aynı kaynak/cluster'a bağlı cüzdanları birlikte takip
etmemek. Bir cüzdanın geçmişinde sistemdeki başka bir cüzdana SOL veya token
transferi varsa bu ilişki `wallet_relationships` tablosuna yazılır.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..models import Wallet, WalletRelationship, WalletStatus

TRANSFER_KINDS = {"funding", "token_transfer"}


def _same(a: str | None, b: str) -> bool:
    return bool(a) and a == b


def _known_wallets(db: Session, address: str) -> set[str]:
    rows = (
        db.query(Wallet.address)
        .filter(Wallet.address != address, Wallet.status != WalletStatus.blocked.value)
        .all()
    )
    return {str(a) for (a,) in rows if a}


def _upsert_relationship(
    db: Session,
    source: str,
    target: str,
    kind: str,
    evidence: dict[str, Any],
) -> bool:
    if not source or not target or source == target:
        return False
    existing = (
        db.query(WalletRelationship)
        .filter(
            WalletRelationship.source_address == source,
            WalletRelationship.target_address == target,
            WalletRelationship.kind == kind,
        )
        .first()
    )
    if existing:
        ev = dict(existing.evidence or {})
        ev.setdefault("examples", [])
        examples = list(ev.get("examples") or [])
        sig = evidence.get("signature")
        if sig and sig not in {x.get("signature") for x in examples if isinstance(x, dict)}:
            examples.append(evidence)
            ev["examples"] = examples[-5:]
            ev["count"] = int(ev.get("count") or 1) + 1
            existing.evidence = ev
            existing.confidence = max(float(existing.confidence or 0.0), 1.0)
            return True
        existing.confidence = max(float(existing.confidence or 0.0), 1.0)
        return False

    db.add(
        WalletRelationship(
            source_address=source,
            target_address=target,
            kind=kind,
            confidence=1.0,
            evidence={"count": 1, "examples": [evidence]},
        )
    )
    return True


def _native_transfer_relation(address: str, transfer: dict[str, Any], known: set[str]) -> tuple[str, str, dict] | None:
    src = transfer.get("fromUserAccount") or transfer.get("from")
    dst = transfer.get("toUserAccount") or transfer.get("to")
    if _same(src, address) and dst in known:
        direction = "out"
        other = str(dst)
    elif _same(dst, address) and src in known:
        direction = "in"
        other = str(src)
    else:
        return None
    try:
        amount_sol = float(transfer.get("amount") or 0.0) / 1_000_000_000
    except (TypeError, ValueError):
        amount_sol = 0.0
    return address, other, {"asset": "SOL", "amount_sol": amount_sol, "direction": direction}


def _token_transfer_relation(address: str, transfer: dict[str, Any], known: set[str]) -> tuple[str, str, dict] | None:
    src = transfer.get("fromUserAccount") or transfer.get("fromOwner")
    dst = transfer.get("toUserAccount") or transfer.get("toOwner")
    if _same(src, address) and dst in known:
        direction = "out"
        other = str(dst)
    elif _same(dst, address) and src in known:
        direction = "in"
        other = str(src)
    else:
        return None
    try:
        amount = float(transfer.get("tokenAmount") or transfer.get("amount") or 0.0)
    except (TypeError, ValueError):
        amount = 0.0
    return address, other, {
        "asset": "SPL",
        "mint": transfer.get("mint"),
        "amount": amount,
        "direction": direction,
    }


def record_transfer_relationships_from_enhanced(db: Session, address: str, txs: list[dict[str, Any]]) -> int:
    """Helius Enhanced tx listesinden sistemdeki başka cüzdanlarla transfer bağı yaz."""
    known = _known_wallets(db, address)
    if not known:
        return 0
    changed = 0
    for tx in txs:
        sig = tx.get("signature")
        ts = tx.get("timestamp")
        for nt in tx.get("nativeTransfers") or []:
            rel = _native_transfer_relation(address, nt, known)
            if rel is None:
                continue
            src, dst, evidence = rel
            evidence.update({"signature": sig, "timestamp": ts})
            changed += int(_upsert_relationship(db, src, dst, "funding", evidence))
        for tt in tx.get("tokenTransfers") or []:
            rel = _token_transfer_relation(address, tt, known)
            if rel is None:
                continue
            src, dst, evidence = rel
            evidence.update({"signature": sig, "timestamp": ts})
            changed += int(_upsert_relationship(db, src, dst, "token_transfer", evidence))
    if changed:
        db.commit()
    return changed


def relationship_summary(db: Session, address: str) -> dict[str, Any]:
    """Bir cüzdanın bilinen ve takipteki cüzdanlarla transfer bağı özeti."""
    rels = (
        db.query(WalletRelationship)
        .filter(
            WalletRelationship.kind.in_(TRANSFER_KINDS),
            or_(WalletRelationship.source_address == address, WalletRelationship.target_address == address),
        )
        .all()
    )
    others = {
        r.target_address if r.source_address == address else r.source_address
        for r in rels
    }
    tracked = set()
    if others:
        tracked = {
            a
            for (a,) in (
                db.query(Wallet.address)
                .filter(Wallet.address.in_(others), Wallet.status == WalletStatus.tracked.value)
                .all()
            )
        }
    return {
        "related_known_wallet_count": len(others),
        "related_tracked_wallet_count": len(tracked),
        "related_wallets": sorted(others)[:20],
        "related_tracked_wallets": sorted(tracked)[:20],
        "relationship_count": len(rels),
    }


def related_pairs(db: Session, addresses: list[str]) -> set[frozenset[str]]:
    addr_set = set(addresses)
    if len(addr_set) < 2:
        return set()
    rels = (
        db.query(WalletRelationship.source_address, WalletRelationship.target_address)
        .filter(
            WalletRelationship.kind.in_(TRANSFER_KINDS),
            WalletRelationship.source_address.in_(addr_set),
            WalletRelationship.target_address.in_(addr_set),
        )
        .all()
    )
    return {frozenset((a, b)) for a, b in rels if a in addr_set and b in addr_set and a != b}
