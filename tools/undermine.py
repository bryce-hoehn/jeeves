"""Undermine Exchange tools — WoW auction house data.

Wraps the undermine.exchange API (docs: https://undermine.exchange/api.html).
Two kinds of items, two kinds of endpoints:

- **Commodities** (stackables: reagents, ores, cloth, consumables) sell on one
  region-wide market — use the `commodity_*` tools.
- **Non-commodities** (gear, pets, most equipment) sell per realm — use the
  `item_*` and `realm_item_*` tools.

All API prices are in copper (1 gold = 10000 copper); tools also render a
gold/silver/copper string. Requires an UNDERMINE_API_KEY env var (get one at
https://undermine.exchange/api.html#gaining-access).
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Literal

from tools import tool

BASE_URL = "https://api.undermine.exchange"

# Big list endpoints cost 3 rate-limit tokens each (budget: 3000/hour) and
# rarely change minute to minute, so cache them in-process for 5 minutes.
LIST_CACHE_SECONDS = 300

_list_cache: dict[str, tuple[float, object]] = {}


def _get(path: str, cache_seconds: int = 0):
    """GET an API endpoint and return its parsed `result` payload."""
    if cache_seconds:
        hit = _list_cache.get(path)
        if hit and hit[0] > time.monotonic():
            return hit[1]

    api_key = os.getenv("UNDERMINE_API_KEY")
    if not api_key:
        raise RuntimeError("UNDERMINE_API_KEY is not set")

    request = urllib.request.Request(
        f"{BASE_URL}{path}", headers={"Authorization": f"ApiKey {api_key}"}
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:200]
        raise RuntimeError(f"API error {exc.code} for {path}: {detail}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"could not reach {path}: {exc.reason}") from None

    result = payload.get("result", payload)
    if cache_seconds:
        _list_cache[path] = (time.monotonic() + cache_seconds, result)
    return result


def _gold(copper: int) -> str:
    """Format an amount of copper as gold/silver/copper."""
    gold, rest = divmod(int(copper), 10000)
    silver, cop = divmod(rest, 100)
    return f"{gold:,}g {silver:02d}s {cop:02d}c"


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(value, high))


# Region-wide commodities ------------------------------------------------------


@tool
def commodity_now(item_id: int, region: Literal["us", "eu"] = "us") -> str:
    """Current market price, total quantity for sale, and cheapest auctions for a commodity (stackable) item across the whole region, e.g. item_id 74250 for Tinker's Kit."""
    data = _get(f"/v1/region/{region}/commodities/{item_id}/now.json")
    if not data:
        return f"No commodity data for item {item_id} in {region.upper()}."

    lines = [
        f"Commodity {item_id} ({region.upper()}): {data['price']:,} copper "
        f"({_gold(data['price'])}) per unit, {data['quantity']:,} total for sale."
    ]
    for auction in (data.get("auctions") or [])[:5]:
        lines.append(f"  {_gold(auction['price'])} x {auction['quantity']:,}")
    if len(data.get("auctions") or []) > 5:
        lines.append(f"  ... {len(data['auctions']) - 5} more listings")
    lines.append(
        f"last seen {data.get('lastSeen', '?')}, updated {data.get('lastUpdated', '?')}"
    )
    return "\n".join(lines)


@tool
def commodity_price_history(
    item_id: int, region: Literal["us", "eu"] = "us", days: int = 7
) -> str:
    """Daily price and quantity history for a commodity (stackable) item, region-wide, plus the average price over those days. Use days=7 for the standard 7-day average."""
    data = _get(f"/v1/region/{region}/commodities/{item_id}/daily.json")
    daily = (data or {}).get("daily") or []
    if not daily:
        return f"No price history for commodity {item_id} in {region.upper()}."

    days = _clamp(days, 1, 30)
    rows = daily[-days:]
    avg = sum(r["price"] for r in rows) / len(rows)
    lines = [
        f"Commodity {item_id} ({region.upper()}) — last {len(rows)} days "
        f"(avg {avg:,.0f} copper / {_gold(avg)} per unit):",
        "day | price (copper) | gold | quantity",
    ]
    lines += [
        f"{r['day']} | {r['price']:,} | {_gold(r['price'])} | {r['quantity']:,}"
        for r in rows
    ]
    return "\n".join(lines)


@tool
def commodity_hourly_history(
    item_id: int, region: Literal["us", "eu"] = "us", snapshots: int = 24
) -> str:
    """Hourly price and quantity snapshots for a commodity (stackable) item over the past ~14 days. Returns the most recent `snapshots` entries (1 per hour), e.g. snapshots=24 for the last day."""
    data = _get(f"/v1/region/{region}/commodities/{item_id}/hourly.json")
    hourly = (data or {}).get("hourly") or []
    if not hourly:
        return f"No hourly history for commodity {item_id} in {region.upper()}."

    snapshots = _clamp(snapshots, 1, 96)
    rows = hourly[-snapshots:]
    lines = [
        f"Commodity {item_id} ({region.upper()}) — last {len(rows)} hourly snapshots:",
        "snapshot (UTC) | price (copper) | gold | quantity",
    ]
    lines += [
        f"{r['snapshot']} | {r['price']:,} | {_gold(r['price'])} | {r['quantity']:,}"
        for r in rows
    ]
    return "\n".join(lines)


# Region-wide non-commodity items ----------------------------------------------


@tool
def item_summary(item_id: int, region: Literal["us", "eu"] = "us") -> str:
    """Region-wide summary for a non-commodity (per-realm) item: median and minimum price across all realms currently selling it, and how many realms that is. Returns 'not on sale' if nobody is selling it."""
    data = _get(
        f"/v1/region/{region}/items.json", cache_seconds=LIST_CACHE_SECONDS
    )
    entry = (data or {}).get("items", {}).get(str(item_id))
    if not entry:
        return (
            f"Item {item_id} is not on sale on any realm in {region.upper()}."
        )

    return (
        f"Item {item_id} ({region.upper()}): median {entry['median']:,} copper "
        f"({_gold(entry['median'])}), cheapest {entry['min']:,} copper "
        f"({_gold(entry['min'])}), on sale on {entry['realms']} realm(s)."
    )


@tool
def item_realm_prices(
    item_id: int, region: Literal["us", "eu"] = "us", limit: int = 10
) -> str:
    """Cheapest realms to buy a non-commodity (per-realm) item right now: price and quantity per connected-realm group, cheapest first, across the whole region."""
    data = _get(f"/v1/region/{region}/items/{item_id}/now.json")
    if not data:
        return f"Item {item_id} is not on sale on any realm in {region.upper()}."

    limit = _clamp(limit, 1, 25)
    groups = sorted(data, key=lambda g: g["price"])[:limit]
    total_realms = len(data)
    lines = [
        f"Item {item_id} ({region.upper()}) — {total_realms} realm group(s) "
        f"selling, cheapest {len(groups)}:",
        "price (copper) | gold | qty | realms | last seen",
    ]
    lines += [
        f"{g['price']:,} | {_gold(g['price'])} | {g['quantity']:,} | "
        f"{', '.join(g['realms'])} | {g.get('lastSeen', '?')}"
        for g in groups
    ]
    return "\n".join(lines)


@tool
def item_price_history(
    item_id: int, region: Literal["us", "eu"] = "us", days: int = 7
) -> str:
    """Daily price and quantity history for a non-commodity (per-realm) item, aggregated across all realms in the region, plus the average price over those days."""
    data = _get(f"/v1/region/{region}/items/{item_id}/daily.json")
    daily = (data or {}).get("daily") or []
    if not daily:
        return f"No price history for item {item_id} in {region.upper()}."

    days = _clamp(days, 1, 30)
    rows = daily[-days:]
    avg = sum(r["price"] for r in rows) / len(rows)
    lines = [
        f"Item {item_id} ({region.upper()}, all realms) — last {len(rows)} days "
        f"(avg {avg:,.0f} copper / {_gold(avg)}):",
        "day | price (copper) | gold | quantity",
    ]
    lines += [
        f"{r['day']} | {r['price']:,} | {_gold(r['price'])} | {r['quantity']:,}"
        for r in rows
    ]
    return "\n".join(lines)


# Realm-specific non-commodity items --------------------------------------------


def _realm_slug(realm: str) -> str:
    return urllib.parse.quote(realm.strip().lower().replace(" ", "-"))


@tool
def realm_item_now(
    realm: str, item_id: int, region: Literal["us", "eu"] = "us"
) -> str:
    """Current price, quantity, and cheapest auctions for a non-commodity (per-realm) item on one specific realm, e.g. realm "stormrage". Use realm slugs like stormrage, proudmoore, illidan."""
    path = f"/v1/realm/{region}/{_realm_slug(realm)}/items/{item_id}/now.json"
    data = _get(path)
    if not data:
        return f"Item {item_id} is not on sale on {realm} ({region.upper()})."

    lines = [
        f"Item {item_id} on {realm} ({region.upper()}): {data['price']:,} copper "
        f"({_gold(data['price'])}), quantity {data['quantity']:,}."
    ]
    for auction in (data.get("auctions") or [])[:5]:
        lines.append(f"  {_gold(auction['price'])} x {auction['quantity']:,}")
    if len(data.get("auctions") or []) > 5:
        lines.append(f"  ... {len(data['auctions']) - 5} more listings")
    lines.append(
        f"last seen {data.get('lastSeen', '?')}, updated {data.get('lastUpdated', '?')}"
    )
    return "\n".join(lines)


@tool
def realm_item_history(
    realm: str,
    item_id: int,
    region: Literal["us", "eu"] = "us",
    days: int = 14,
) -> str:
    """Daily price and quantity history for a non-commodity (per-realm) item on one specific realm (max quantity per day and the price at that time), e.g. realm "stormrage"."""
    path = (
        f"/v1/realm/{region}/{_realm_slug(realm)}/items/{item_id}/daily.json"
    )
    data = _get(path)
    daily = (data or {}).get("daily") or []
    if not daily:
        return f"No history for item {item_id} on {realm} ({region.upper()})."

    days = _clamp(days, 1, 60)
    rows = daily[-days:]
    lines = [
        f"Item {item_id} on {realm} ({region.upper()}) — last {len(rows)} days:",
        "day | price (copper) | gold | quantity",
    ]
    lines += [
        f"{r['day']} | {r['price']:,} | {_gold(r['price'])} | {r['quantity']:,}"
        for r in rows
    ]
    return "\n".join(lines)
