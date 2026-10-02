"""Blizzard profile API tools — character & guild progression.

Official per-character data from https://{region}.api.blizzard.com/profile/wow
(namespace profile-{region}): Mythic+ runs, raid progress, PvP bracket
rating/record, and guild rosters. Needs BLIZZARD_CLIENT_ID /
BLIZZARD_CLIENT_SECRET (free at https://develop.battle.net).

For M+ scores and overall player rankings, Raider.IO (tools/progression/
raiderio.py) is usually the better answer — these endpoints are the raw
source underneath.
"""

import urllib.parse
from typing import Literal

from tools import tool, web
from tools.market.blizzard import auth_headers, http_json
from tools.util import realm_slug, slug

Regions = Literal["us", "eu", "tw", "kr"]
Brackets = Literal["2v2", "3v3", "rbg", "solo-shuffle"]


def _profile(region: str, path: str) -> dict:
    url = (
        f"https://{region}.api.blizzard.com/profile/wow{path}"
        f"?namespace=profile-{region}&locale=en_US"
    )
    return http_json(url, auth_headers(region))


def _game_data(region: str, path: str) -> dict:
    url = (
        f"https://{region}.api.blizzard.com/data/wow{path}"
        f"?namespace=dynamic-{region}&locale=en_US"
    )
    return http_json(url, auth_headers(region))


@tool
def character_mythic_plus(
    name: str, realm: str, region: Regions = "us"
) -> str:
    """A character's current-week and best-run Mythic+ keystone history from the official Blizzard API — dungeon, keystone level, affixes, completion time, and score-relevant timing for this keystone period. For the overall M+ SCORE and season bests use raider_io instead."""
    data = _profile(region, f"/character/{realm_slug(realm)}/{name.lower()}/mythic-keystone-profile")
    period = (data.get("current_period") or {}).get("best_runs") or []
    if not period:
        return f"{name}-{realm_slug(realm)} ({region.upper()}): no Mythic+ runs this period."

    lines = [f"{name}-{realm_slug(realm)} ({region.upper()}) — best runs this period:"]
    for run in sorted(period, key=lambda r: -r.get("keystone_level", 0)):
        dungeon = run.get("dungeon", {}).get("name", "?")
        level = run.get("keystone_level", "?")
        ms = run.get("duration") or 0
        minutes, seconds = divmod(ms // 1000, 60)
        lines.append(f"  +{level} {dungeon} ({minutes}:{seconds:02d})")
    return "\n".join(lines)


@tool
def character_raid_progress(
    name: str, realm: str, region: Regions = "us"
) -> str:
    """A character's raid progression from the official Blizzard API — bosses killed per difficulty (normal / heroic / mythic) for the current and recent raid tiers, e.g. '6/8 M'."""
    data = _profile(
        region, f"/character/{realm_slug(realm)}/{name.lower()}/encounters/raids"
    )
    expansions = data.get("expansions") or []
    if not expansions:
        return f"{name}-{realm_slug(realm)} ({region.upper()}): no raid data."

    lines = [f"{name}-{realm_slug(realm)} ({region.upper()}) — raid progress:"]
    # Expansions come back oldest-first; show the two most recent, newest
    # first. Blizzard nests the metadata: {"expansion": {...}, "instances":
    # [{"instance": {...}, "modes": [...]}]} — and old raids repeat a
    # difficulty across several wing-modes, so keep the best count per
    # difficulty letter.
    for expansion in reversed(expansions[-2:]):
        exp_name = (expansion.get("expansion") or expansion).get("name", "?")
        lines.append(f"  {exp_name}:")
        for entry in expansion.get("instances", []):
            instance = entry.get("instance") or entry
            best: dict[str, tuple[int, int]] = {}
            for mode in entry.get("modes", []):
                difficulty = mode.get("difficulty", {}).get("type", "?")
                progress = mode.get("progress") or {}
                completed = progress.get(
                    "completed_count", progress.get("completed")
                )
                total = progress.get("total_count", progress.get("total"))
                if completed is None:
                    continue
                letter = difficulty[0]
                prev = best.get(letter)
                if prev is None or (total or 0) > prev[1]:
                    best[letter] = (completed, total)
            marks = [
                f"{c}/{t} {letter}"
                for letter, (c, t) in sorted(best.items())
            ]
            if marks:
                lines.append(
                    f"    {instance.get('name', '?')}: {' | '.join(marks)}"
                )
    return "\n".join(lines)


@tool
def character_pvp(
    name: str,
    realm: str,
    bracket: Brackets = "3v3",
    region: Regions = "us",
) -> str:
    """A character's PvP rating and season record for one bracket from the official Blizzard API — rating, games won/lost, and weekly performance. Brackets: 2v2, 3v3, rbg, solo-shuffle."""
    path_bracket = urllib.parse.quote(bracket)
    try:
        data = _profile(
            region,
            f"/character/{realm_slug(realm)}/{name.lower()}/pvp-bracket/{path_bracket}",
        )
    except RuntimeError as exc:
        if "404" in str(exc):
            return (
                f"{name}-{realm_slug(realm)} ({region.upper()}): no {bracket} "
                "data (the character has never played that bracket)."
            )
        raise
    if not data.get("rating") and not data.get("season_match_statistics"):
        return f"{name}-{realm_slug(realm)} ({region.upper()}): no {bracket} data."

    season = data.get("season_match_statistics") or {}
    weekly = data.get("weekly_match_statistics") or {}
    lines = [
        f"{name}-{realm_slug(realm)} ({region.upper()}) — {bracket}: "
        f"{data.get('rating', '?')} rating "
        f"({(data.get('tier') or {}).get('name') or 'unranked'})"
    ]
    if season:
        lines.append(
            f"  season: {season.get('won', 0)}W / {season.get('lost', 0)}L"
        )
    if weekly:
        lines.append(
            f"  this week: {weekly.get('won', 0)}W / {weekly.get('lost', 0)}L"
        )
    return "\n".join(lines)


_season_cache = web.TTLCache(ttl=3600)


def _current_pvp_season(region: str) -> int:
    """Id of the current PvP season (leaderboards are season-scoped now)."""
    season = _season_cache.get(region)
    if season is None:
        index = _game_data(region, "/pvp-season/index")
        season = index["current_season"]["id"]
        _season_cache.put(region, season)
    return season


@tool
def pvp_leaderboard(
    bracket: str = "3v3", region: Regions = "us", limit: int = 10
) -> str:
    """Official Blizzard PvP leaderboard for a bracket and region — top players by rating with their realm and faction. Brackets: 2v2, 3v3, rbg, or a spec ladder like shuffle-mage-frost / blitz-warrior-arms."""
    season = _current_pvp_season(region)
    data = _game_data(
        region,
        f"/pvp-season/{season}/pvp-leaderboard/{urllib.parse.quote(bracket)}",
    )
    entries = data.get("entries") or []
    if not entries:
        return f"No {bracket} leaderboard data for {region.upper()}."

    limit = max(1, min(limit, 25))
    lines = [f"{bracket} leaderboard ({region.upper()}) — top {limit}:"]
    for i, entry in enumerate(entries[:limit], 1):
        character = entry.get("character", {})
        realm = character.get("realm", {}).get("slug", "?")
        faction = entry.get("faction", {}).get("type", "?")[:3].title()
        lines.append(
            f"  {i}. {character.get('name', '?')}-{realm} — "
            f"{entry.get('rating', '?')} ({faction})"
        )
    return "\n".join(lines)


def _guild(region: str, path: str) -> dict:
    # Guild endpoints live under /data/wow but keep the profile namespace.
    url = (
        f"https://{region}.api.blizzard.com/data/wow/guild{path}"
        f"?namespace=profile-{region}&locale=en_US"
    )
    return http_json(url, auth_headers(region))


@tool
def guild_roster(guild: str, realm: str, region: Regions = "us") -> str:
    """A guild's roster from the official Blizzard API — member count, guild master and officers (with realms), and rank distribution. Use guild name without spaces, e.g. 'Liquid', 'Echo'."""
    summary = _guild(region, f"/{realm_slug(realm)}/{slug(guild)}")
    roster = _guild(region, f"/{realm_slug(realm)}/{slug(guild)}/roster")

    members = roster.get("members") or []
    lines = [
        f"{summary.get('name', guild)}-{realm_slug(realm)} ({region.upper()}): "
        f"{len(members)} members, "
        f"{summary.get('achievement_points', 0):,} achievement points."
    ]
    ranks: dict[int, int] = {}
    for member in members:
        rank = member.get("rank", 99)
        ranks[rank] = ranks.get(rank, 0) + 1
    officers = [
        f"{m['character']['name']}-{m['character'].get('realm', {}).get('slug', realm_slug(realm))}"
        for m in members
        if m.get("rank", 99) <= 1
    ]
    if officers:
        lines.append(f"  GM/officers: {', '.join(officers[:20])}")
    lines.append(
        "  rank distribution: "
        + ", ".join(f"{rank}: {count}" for rank, count in sorted(ranks.items()))
    )
    return "\n".join(lines)
