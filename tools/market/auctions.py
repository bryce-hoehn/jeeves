"""Blizzard auction-house snapshots — raw per-realm auctions.

The game-data API serves the full auction list for a connected-realm
group: /data/wow/connected-realm/{id}/auctions (updates hourly). This
complements the Undermine Exchange aggregates with per-listing detail:
unit prices of individual auctions, stack sizes, and time_left, e.g. for
wall detection or deposit math. The realm's connected-realm id comes from
the weekly realm cache built by tools/market/realms.py.

Needs BLIZZARD_CLIENT_ID / BLIZZARD_CLIENT_SECRET (free at
https://develop.battle.net).
"""

from typing import Literal

from tools import tool, web
from tools.market.blizzard import auth_headers, http_json
from tools.market.realms import _load_realms
from tools.util import gold as _gold, realm_slug

_snapshot_cache = web.TTLCache(ttl=1800)  # Blizzard refreshes hourly

TIME_LEFT_ORDER = {"SHORT": 0, "MEDIUM": 1, "LONG": 2, "VERY_LONG": 3}


def _connected_realm_id(realm: str, region: str) -> tuple[int, str]:
    wanted = realm_slug(realm)
    for group in _load_realms(region)["groups"]:
        if wanted in group["realms"]:
            return group["id"], wanted
    raise RuntimeError(f"realm '{wanted}' not found in region {region}")


def _snapshot(connected_id: int, region: str) -> list:
    key = f"{region}-{connected_id}"
    cached = _snapshot_cache.get(key)
    if cached is not None:
        return cached
    url = (
        f"https://{region}.api.blizzard.com/data/wow/connected-realm/"
        f"{connected_id}/auctions?namespace=dynamic-{region}&locale=en_US"
    )
    auctions = http_json(url, auth_headers(region)).get("auctions", [])
    _snapshot_cache.put(key, auctions)
    return auctions


@tool
def realm_auctions(
    realm: str,
    item_id: int | None = None,
    region: Literal["us", "eu", "tw", "kr"] = "us",
) -> str:
    """Raw Blizzard auction-house snapshot for one realm's connected-realm group (updates hourly). With item_id: every current listing for that item — unit price, stack size, time_left — cheapest 15 first, plus total quantity (use for wall detection and per-listing detail the Undermine tools don't show). Without item_id: a summary of the whole auction house (total auctions, distinct items). Use realm slugs like stormrage, illidan."""
    connected_id, slug = _connected_realm_id(realm, region)
    auctions = _snapshot(connected_id, region)

    def unit_price(a: dict) -> int | None:
        # commodities use unit_price; stack items put it in buyout
        return a.get("unit_price") or a.get("buyout")

    if item_id is None:
        items = {a["item"]["id"] for a in auctions}
        return (
            f"{slug} ({region.upper()}) auction house: {len(auctions):,} "
            f"active auctions across {len(items):,} distinct items "
            f"(connected-realm group {connected_id})."
        )

    listings = [a for a in auctions if a["item"]["id"] == item_id]
    if not listings:
        return f"Item {item_id} has no active auctions on {slug} ({region.upper()})."

    total_qty = sum(a["quantity"] for a in listings)
    priced = sorted(
        (a for a in listings if unit_price(a)), key=unit_price
    )
    lines = [
        f"Item {item_id} on {slug} ({region.upper()}): {len(listings):,} "
        f"auctions, {total_qty:,} total quantity. Cheapest:"
    ]
    lines += [
        f"  {_gold(unit_price(a))} each x{a['quantity']:,} "
        f"({a.get('time_left', '?').replace('_', ' ').lower()})"
        for a in priced[:15]
    ]
    if len(priced) > 15:
        lines.append(f"  ... {len(priced) - 15} more listings")
    return "\n".join(lines)
