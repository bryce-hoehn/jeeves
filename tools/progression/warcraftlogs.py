"""Warcraft Logs v2 API — character performance rankings.

GraphQL at https://www.warcraftlogs.com/api/v2/client, authenticated with
client-credentials OAuth (create a client at
https://www.warcraftlogs.com/api/clients — set WCL_CLIENT_ID /
WCL_CLIENT_SECRET). zoneRankings returns the character's best historical
performance percentiles per raid difficulty — the standard "are they
parsing well" check, complements sims: sims say what a character SHOULD
do, logs say what they DID do.
"""

import json
import os
import re

from tools import tool, web
from tools.util import realm_slug

OAUTH_URL = "https://www.warcraftlogs.com/oauth/token"
GRAPHQL_URL = "https://www.warcraftlogs.com/api/v2/client"

RANKINGS_QUERY = """
query($name: String!, $slug: String!, $region: String!) {
  characterData {
    character(name: $name, serverSlug: $slug, serverRegion: $region) {
      name
      zoneRankings
    }
  }
}
"""


def _token() -> str:
    client_id = os.getenv("WCL_CLIENT_ID")
    client_secret = os.getenv("WCL_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError(
            "WCL_CLIENT_ID / WCL_CLIENT_SECRET are not set — create an API"
            " client at https://www.warcraftlogs.com/api/clients"
        )
    return web.oauth_token(OAUTH_URL, client_id, client_secret)


def _graphql(query: str, variables: dict) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode()
    payload = web.request_json(
        GRAPHQL_URL,
        headers={
            "Authorization": f"Bearer {_token()}",
            "Content-Type": "application/json",
        },
        data=body,
    )
    if payload.get("errors"):
        raise RuntimeError(f"Warcraft Logs error: {payload['errors']}")
    return payload["data"]


@tool
def warcraft_logs(
    name: str, realm: str, region: str = "us", max_chars: int = 3000
) -> str:
    """A character's Warcraft Logs zone rankings — best historical performance percentile per boss aggregated by raid difficulty (e.g. ' heroic avg 87, mythic avg 64'). The answer to 'do they parse well / what did they actually do in raids'. Pairs with sims: sims show potential, logs show execution. Needs WCL API credentials configured."""
    data = _graphql(
        RANKINGS_QUERY,
        {"name": name, "slug": realm_slug(realm), "region": region.lower()},
    )
    character = (data.get("characterData") or {}).get("character")
    if not character:
        return f"No Warcraft Logs data for {name}-{realm} ({region.upper()})."

    lines = [f"{character.get('name')} — Warcraft Logs rankings:"]
    raw = str(character.get("zoneRankings") or "")
    for difficulty in ("mythic", "heroic", "normal"):
        # zoneRankings is a JSON blob inside GraphQL; pull the summary fields.
        pattern = rf'"{difficulty}".*?"averageRank":\s*([\d.]+).*?"amount":\s*(\d+)'
        match = re.search(pattern, raw, re.S)
        if match:
            lines.append(
                f"  {difficulty}: avg performance {float(match.group(1)):.0f}%"
                f" over {match.group(2)} boss kills"
            )
    if len(lines) == 1:
        lines.append(f"  no ranked kills found ({raw[:200]}...)")
    return "\n".join(lines)[:max_chars]
