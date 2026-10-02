"""Raider.IO API — M+ scores, best runs, and raid progression.

https://raider.io/api — simple REST, no auth for low-volume use; set
RAIDERIO_API_KEY (free at https://raider.io/api) for higher limits and it
is appended automatically. This is the source for M+ *scores* and overall
rankings; the Blizzard profile API (tools/progression/blizzard.py) has the
raw per-period runs.
"""

import os
import urllib.parse

from tools import tool, web
from tools.util import realm_slug

BASE_URL = "https://raider.io/api/v1"

FIELDS = ",".join(
    [
        "gear",
        "guild",
        "mythic_plus_scores_by_season:current",
        "mythic_plus_best_runs",
        "mythic_plus_recent_runs",
        "raid_progression",
    ]
)


def _pretty(raid_slug: str) -> str:
    return raid_slug.replace("-", " ").title()

def _run_line(run: dict) -> str:
    dungeon = run.get("dungeon", "?")
    level = run.get("mythic_level", "?")
    completed = run.get("completed_at", "")[:10]
    return f"  +{level} {dungeon} ({completed})"


@tool
def raider_io(name: str, realm: str, region: str = "us") -> str:
    """One-stop Raider.IO profile for a character — current-season M+ score (overall + per-role colors), best M+ runs, raid progression with boss counts, and equipped item level. THE tool for 'what's their score' / 'how geared are they'. Realm as slug, e.g. 'stormrage'."""
    query = urllib.parse.urlencode(
        {"region": region.lower(), "realm": realm_slug(realm), "name": name, "fields": FIELDS}
    )
    api_key = os.getenv("RAIDERIO_API_KEY")
    if api_key:
        query += f"&api_key={api_key}"
    # raider.io Cloudflare-blocks non-browser UAs — use the shared session
    data = web.get_json(f"{BASE_URL}/characters/profile?{query}")

    lines = [
        f"{data.get('name')}-{data.get('realm')} ({data.get('race')}, "
        f"{data.get('active_spec_name')} {data.get('class')}) — "
        f"{data.get('active_role', '?')}"
    ]
    if data.get("guild"):
        lines.append(f"  guild: <{data['guild']['name']}>")
    gear = data.get("gear") or {}
    if gear.get("item_level_equipped"):
        lines.append(f"  equipped ilvl: {gear['item_level_equipped']}")

    scores = (data.get("mythic_plus_scores_by_season") or [])
    if scores:
        overall = (scores[0].get("scores") or {}).get("all")
        if overall is not None:
            lines.append(f"  M+ score (current season): {overall:.0f}")
    best = data.get("mythic_plus_best_runs") or []
    if best:
        lines.append("  best M+ runs:")
        lines += [_run_line(r) for r in best[:5]]

    prog = data.get("raid_progression") or {}
    for raid, info in list(prog.items())[:3]:
        lines.append(
            f"  {_pretty(raid)}: {info.get('summary')} "
            f"(N {info.get('normal_bosses_killed')}/{info.get('total_bosses')}, "
            f"H {info.get('heroic_bosses_killed')}, "
            f"M {info.get('mythic_bosses_killed')})"
        )
    return "\n".join(lines)


@tool
def raider_io_guild(guild: str, realm: str, region: str = "us") -> str:
    """Raider.IO profile for a GUILD — raid progression and world/region rankings per raid tier, plus recent kills. Use for 'how far is this guild' questions."""
    query = urllib.parse.urlencode(
        {
            "region": region.lower(),
            "realm": realm_slug(realm),
            "name": guild,
            "fields": "raid_progression,raid_rankings",
        }
    )
    api_key = os.getenv("RAIDERIO_API_KEY")
    if api_key:
        query += f"&api_key={api_key}"
    data = web.get_json(f"{BASE_URL}/guilds/profile?{query}")

    lines = [f"<{data.get('name')}>-{data.get('realm')} ({region.upper()})"]
    prog = data.get("raid_progression") or {}
    rankings = data.get("raid_rankings") or {}
    for raid, info in prog.items():
        rank = (rankings.get(raid) or {}).get("mythic", {})
        world = rank.get("world")
        lines.append(
            f"  {_pretty(raid)}: {info.get('summary')}"
            + (f" (mythic world #{world})" if world else "")
        )
    return "\n".join(lines)
