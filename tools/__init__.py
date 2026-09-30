"""Built-in tools. Each module in this package defines one tool; the @tool
decorator registers it in TOOLS so the agent can offer it to the model."""

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
from tools import (  # noqa: E402, F401
    raidbots,
    simc,
    undermine,
    wowhead,
)
