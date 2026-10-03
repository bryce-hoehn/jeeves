"""Discord scheduled-event tools — read/write the guild's event calendar.

These operate on the guild of the channel the conversation is happening
in. Together with wow_events (darmory) they let the agent mirror the
in-game WoW calendar onto the Discord events calendar.
"""

from datetime import datetime, timezone

import discord

from tools import tool


def _parse_time(value: str) -> datetime:
    """ISO 8601 ('2026-10-18T10:00:00Z' or with offset); naive → UTC."""
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _fmt_time(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%a %Y-%m-%d %H:%M UTC")


@tool
async def discord_events_list(channel) -> str:
    """List this Discord server's scheduled events — name, times, status, and how many users marked themselves interested. Use this to check what's already on the calendar before creating or syncing events."""
    if not channel.guild:
        return "Scheduled events only exist in servers, not DMs."
    events = await channel.guild.fetch_scheduled_events()
    if not events:
        return "No scheduled events on this server's calendar."
    lines = []
    for ev in sorted(events, key=lambda e: e.start_time):
        when = f"{_fmt_time(ev.start_time)} → {_fmt_time(ev.end_time)}" if ev.end_time else _fmt_time(ev.start_time)
        lines.append(f"- {ev.name} ({ev.status.name}): {when}, {ev.subscriber_count} interested")
        if ev.description:
            desc = ev.description.replace("\n", " ")
            lines.append(f"  {desc[:150]}")
    return "\n".join(lines)


@tool
async def discord_events_create(
    channel,
    name: str,
    start_time: str,
    end_time: str = "",
    description: str = "",
) -> str:
    """Create a scheduled event on this Discord server's calendar. start_time/end_time are ISO 8601 (e.g. '2026-10-18T10:00:00Z' — UTC assumed when no offset is given); end_time is optional. Events are created as external events located 'In-game'."""
    if not channel.guild:
        return "Scheduled events can only be created in servers, not DMs."
    start = _parse_time(start_time)
    end = _parse_time(end_time) if end_time else None
    if end and end < start:
        return "end_time is before start_time."
    try:
        ev = await channel.guild.create_scheduled_event(
            name=name[:100],
            description=description[:1000] or None,
            start_time=start,
            end_time=end,
            location="In-game",
        )
    except discord.HTTPException as exc:
        return f"Discord rejected the event: {exc}"
    when = f"{_fmt_time(ev.start_time)} → {_fmt_time(ev.end_time)}" if ev.end_time else _fmt_time(ev.start_time)
    return f"Created '{ev.name}' — {when}. {ev.url}"


@tool
async def discord_events_edit(
    channel,
    name: str,
    new_name: str = "",
    start_time: str = "",
    end_time: str = "",
    description: str = "",
) -> str:
    """Edit an existing scheduled event on this Discord server's calendar, matching by name (case-insensitive, partial match ok). Only the fields provided are changed: new_name, start_time, end_time (ISO 8601, e.g. '2026-10-18T10:00:00Z' — UTC assumed when no offset is given), and description."""
    if not channel.guild:
        return "Scheduled events only exist in servers, not DMs."
    events = await channel.guild.fetch_scheduled_events()
    needle = name.strip().lower()
    matches = [ev for ev in events if needle in ev.name.lower()]
    if not matches:
        return f"No scheduled event matching '{name}'."
    kwargs: dict = {}
    if new_name:
        kwargs["name"] = new_name[:100]
    if start_time:
        kwargs["start_time"] = _parse_time(start_time)
    if end_time:
        kwargs["end_time"] = _parse_time(end_time)
    if description:
        kwargs["description"] = description[:1000]
    if not kwargs:
        return "Nothing to change — provide at least one of new_name, start_time, end_time, description."
    # Validate start < end against the merged (old + new) times before editing.
    new_start = kwargs.get("start_time") or matches[0].start_time
    new_end = kwargs.get("end_time") or matches[0].end_time
    if new_end and new_end < new_start:
        return (
            f"That would put the end ({_fmt_time(new_end)}) before the start"
            f" ({_fmt_time(new_start)}) — adjust both times."
        )
    try:
        for ev in matches:
            await ev.edit(**kwargs)
    except discord.HTTPException as exc:
        return f"Discord rejected the edit: {exc}"
    when = (
        f"{_fmt_time(new_start)} → {_fmt_time(new_end)}"
        if new_end
        else _fmt_time(new_start)
    )
    label = kwargs.get("name") or matches[0].name
    return f"Edited {len(matches)} event(s) → '{label}': {when}."


@tool
async def discord_events_delete(channel, name: str) -> str:
    """Delete a scheduled event from this Discord server's calendar, matching by name (case-insensitive, partial match ok). Returns the events removed."""
    if not channel.guild:
        return "Scheduled events only exist in servers, not DMs."
    events = await channel.guild.fetch_scheduled_events()
    needle = name.strip().lower()
    matches = [ev for ev in events if needle in ev.name.lower()]
    if not matches:
        return f"No scheduled event matching '{name}'."
    for ev in matches:
        await ev.delete()
    return f"Deleted {len(matches)} event(s): " + ", ".join(f"'{ev.name}'" for ev in matches)
