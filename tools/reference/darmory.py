"""WoW in-game calendar events — via darmory.com's event database.

Blizzard's web API has no calendar endpoint (the in-game C_Calendar Lua
namespace is client-only), so this reads darmory.com's community feed of
in-game events — holidays, bonus events, PvP brawls, Darkmoon Faire,
micro-holidays. The JSON API (https://api.darmory.com/events) lists every
event with its scheduled occurrences as UTC start/end timestamps; darmory
also publishes the same data as an iCal feed at
https://api.darmory.com/events/calendar/ics?region={region} for
calendar apps.
"""

import datetime as dt
from typing import Literal

from tools import tool, web
from tools.util import clamp

_cache = web.TTLCache(ttl=3600)  # event schedules change rarely

DATE_FMT = "%Y-%m-%d %H:%M"


def _events(region: str) -> list[dict]:
    cached = _cache.get(region)
    if cached is None:
        payload = web.get_json(
            f"https://api.darmory.com/events?region={region}"
        )
        cached = payload.get("events") or []
        _cache.put(region, cached)
    return cached


def _parse(stamp: str) -> dt.datetime:
    return dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))


@tool
def wow_events(
    query: str = "",
    region: Literal["us", "eu"] = "us",
    days: int = 30,
) -> str:
    """WoW in-game calendar events (holidays, bonus events, PvP brawls, Darkmoon Faire, micro-holidays) from darmory.com. With no query: everything currently running (marked LIVE) plus everything starting within `days` (default 30). With a query: that event's next occurrences — answers 'when is Darkmoon Faire / the next bonus event'. Times are UTC; events repeat yearly unless noted."""
    now = dt.datetime.now(dt.timezone.utc)
    window_end = now + dt.timedelta(days=clamp(days, 1, 365))
    q = query.strip().lower()

    lines: list[str] = []
    shown = 0
    # Flatten (event, occurrence) pairs inside the window, soonest first.
    occurrences = []
    for event in _events(region):
        if q and q not in event.get("name", "").lower():
            continue
        for occ in event.get("dates") or []:
            start, end = _parse(occ["dateStart"]), _parse(occ["dateEnd"])
            if end >= now and start <= window_end:
                occurrences.append((start, end, event))
    occurrences.sort(key=lambda o: o[0])

    if not occurrences:
        if q:
            return f"No in-game events matching '{query}' in the next {days} days."
        return f"No in-game events in the next {days} days (region {region.upper()})."

    for start, end, event in occurrences:
        if shown >= 25:
            lines.append(f"... {len(occurrences) - shown} more in the window")
            break
        live = start <= now <= end
        span = (
            f"{start.strftime(DATE_FMT)} → {end.strftime(DATE_FMT)} UTC"
            if (end - start).total_seconds() > 6 * 3600
            else f"{start.strftime(DATE_FMT)} UTC ({event.get('durationHours', '?')}h)"
        )
        desc = " ".join((event.get("description") or "").split())
        if len(desc) > 140:
            desc = desc[:140] + "…"
        tag = "LIVE NOW — " if live else ""
        lines.append(f"* {tag}{span}: {event['name']}")
        if desc:
            lines.append(f"    {desc}")
        shown += 1

    header = (
        f"In-game events matching '{query}'"
        if q
        else f"In-game events (region {region.upper()})"
    )
    return (
        f"{header}, {now.strftime('%Y-%m-%d %H:%M UTC')} → "
        f"{window_end.strftime('%Y-%m-%d')}:\n" + "\n".join(lines)
    )
