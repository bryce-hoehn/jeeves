"""Built-in tools, grouped into subpackages by domain. Each module defines
one tool (or shared helpers); the @tool decorator registers it in TOOLS so
the agent can offer it to the model.

- core/        — sandboxed python execution, clock, persistent markdown
                  knowledge base
- market/      — Undermine Exchange, Blizzard API (realms, token, auctions)
- progression/ — character/guild progression: Blizzard profile, Raider.IO,
                 Warcraft Logs
- sim/         — SimulationCraft CLI, Raidbots static data
- reference/   — Wowhead tooltips/pages, Icy Veins & wow.gg guides, WoW wiki,
                  news & hotfix feeds, darmory event calendar
- discord_events.py — this Discord server's scheduled-event calendar
- discord_chat.py  — Discord users & channels: user lookup, DMs,
                     channel listing, reading chat history

Shared plumbing (registered as tools themselves? no): tools/web.py is the
single HTTP layer — browser-UA session with retries, page cache,
client-credentials OAuth, and HTML→text utilities — and tools/util.py holds
slug/clamp helpers.
"""

import inspect
from typing import get_type_hints

from pydantic import TypeAdapter

TOOLS: dict[str, dict] = {}


def tool(fn):
    """Register a function as a tool the model can call. A parameter named
    `channel` is left out of the schema — the agent injects the Discord
    channel the conversation is happening in."""
    hints = get_type_hints(fn)
    params = inspect.signature(fn).parameters

    TOOLS[fn.__name__] = {
        "fn": fn,
        "takes_channel": "channel" in params,
        "schema": {
            "type": "function",
            "name": fn.__name__,
            "description": inspect.getdoc(fn) or "",
            "parameters": {
                "type": "object",
                "properties": {
                    name: TypeAdapter(hints[name]).json_schema()
                    for name in params
                    if name != "channel"
                },
                "required": [
                    name
                    for name, p in params.items()
                    if p.default is p.empty and name != "channel"
                ],
            },
        },
    }
    return fn


# Importing these modules registers their tools.
from tools import discord_chat, discord_events  # noqa: E402, F401
from tools.core import clock, knowledge, python  # noqa: E402, F401
from tools.market import auctions, realms, token, undermine  # noqa: E402, F401
from tools.progression import blizzard, raiderio, warcraftlogs  # noqa: E402, F401
from tools.reference import (  # noqa: E402, F401
    blizznews,
    darmory,
    icyveins,
    wowgg,
    wowhead,
    wowwiki,
)
from tools.sim import raidbots, simc  # noqa: E402, F401
