"""WoW Token price tool — gold↔real-money conversion.

Primary source is Blizzard's game-data token endpoint (region-scoped); when
Blizzard API credentials are configured (BLIZZARD_CLIENT_ID/SECRET) they are
used, otherwise the public wowtokenprices.com aggregator is the fallback.
Prices update every few minutes; we cache for an hour, which is plenty for
judging flip profitability ("is 230k gold worth more than a $25 transfer?").
"""

import os
import time
from typing import Literal

from tools import tool
from tools.market.blizzard import auth_headers, http_json
from tools.market.util import gold as _gold

CACHE_SECONDS = 3600
_cache: dict[str, tuple[float, str]] = {}


@tool
def wow_token_price(region: Literal["us", "eu", "tw", "kr"] = "us") -> str:
    """Current WoW Token gold price for a region (how much gold one token sells for on the auction house). Use this to convert gold profit into real-money terms — e.g. to compare a flip's profit against the cost of a realm/faction transfer, or to price out 'just buying the gold'. Price is cached up to 1 hour."""
    hit = _cache.get(region)
    if hit and hit[0] > time.monotonic():
        return hit[1]

    url = (
        f"https://{region}.api.blizzard.com/data/wow/token/index"
        f"?namespace=dynamic-{region}"
    )
    headers = {"Accept": "application/json"}
    if os.getenv("BLIZZARD_CLIENT_ID") and os.getenv("BLIZZARD_CLIENT_SECRET"):
        headers.update(auth_headers(region))
    try:
        data = http_json(url, headers)
        price = int(data["price"])
        updated = time.strftime(
            "%Y-%m-%d %H:%M UTC",
            time.gmtime(data["last_modified_timestamp"] / 1000),
        )
        text = (
            f"WoW Token ({region.upper()}): {_gold(price)} per token\n"
            f"last updated: {updated}"
        )
    except RuntimeError:
        # Fallback: public aggregator (prices in gold).
        tokens = http_json("https://wowtokenprices.com/tokens.json")
        key = f"{region}_current_price"
        gold = tokens.get(key)
        if not gold:
            raise
        text = (
            f"WoW Token ({region.upper()}): {gold:,}g per token "
            "(via wowtokenprices.com)"
        )

    _cache[region] = (time.monotonic() + CACHE_SECONDS, text)
    return text
