"""Realm metadata tool — connected-realm groups without scraping.

Answers "which realms share an auction house?" (connected realms trade
together, so a 'cheap realm' is really a cheap group) plus each realm's
timezone. Data comes from Blizzard's game-data API, which needs a client
credential (free at https://develop.battle.net — set BLIZZARD_CLIENT_ID and
BLIZZARD_CLIENT_SECRET). The full realm map changes rarely, so it is cached
to data/realms-{region}.json and refreshed weekly.

Blizzard does not publish faction splits; for those, cross-reference a census
site and do the join in the `python` tool.
"""

import json
import time
from pathlib import Path
from typing import Literal

from tools import tool
from tools.market.blizzard import auth_headers, http_json
from tools.util import realm_slug

CACHE_FILE_TTL_DAYS = 7


def _load_realms(region: str) -> dict:
    """Return the realm map for a region, refreshing the on-disk cache weekly."""
    path = Path("data") / f"realms-{region}.json"
    fresh = path.exists() and (
        time.time() - path.stat().st_mtime < CACHE_FILE_TTL_DAYS * 86400
    )
    if not fresh:
        api = f"https://{region}.api.blizzard.com/data/wow"
        auth = auth_headers(region)

        cr_index = http_json(
            f"{api}/connected-realm/index?namespace=dynamic-{region}", auth
        )
        groups = []
        for entry in cr_index["connected_realms"]:
            cr = http_json(entry["href"], auth)
            group = {
                "id": cr["id"],
                "population": cr.get("population", {}).get("type"),
                "realms": {
                    r["slug"]: {"name": r["name"], "timezone": r.get("timezone")}
                    for r in cr.get("realms", [])
                },
            }
            groups.append(group)

        data = {"region": region, "groups": groups}
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(data))
        return data
    return json.loads(path.read_text())


@tool
def realm_metadata(
    realm: str | None = None,
    region: Literal["us", "eu"] = "us",
) -> str:
    """Look up a realm's connected-realm group — the set of realms that share one auction house — plus its timezone and population tag. With no `realm`, returns a compact summary of the largest groups. Use this before cross-realm price comparisons: connected realms price identically, so buy/sell lanes only exist BETWEEN groups. Data cached weekly."""
    groups = _load_realms(region)["groups"]
    wanted = realm_slug(realm) if realm else None

    if wanted:
        for g in groups:
            if wanted in g["realms"]:
                members = ", ".join(
                    f"{r['name']} ({s})" for s, r in sorted(g["realms"].items())
                )
                return (
                    f"{wanted} is in connected-realm group {g['id']} "
                    f"(population: {g['population'] or 'unknown'}).\n"
                    f"Shared auction house with: {members}"
                )
        raise RuntimeError(
            f"realm '{wanted}' not found in region {region} — "
            "check the slug, e.g. 'area-52', 'moon-guard'"
        )

    lines = [f"Connected-realm groups for {region.upper()} (largest first):"]
    for g in sorted(groups, key=lambda x: len(x["realms"]), reverse=True)[:12]:
        members = ", ".join(sorted(g["realms"]))
        lines.append(f"  group {g['id']} ({g['population'] or '?'}): {members}")
    return "\n".join(lines)
