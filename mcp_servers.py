"""External MCP servers. Any server listed in mcp.json is connected on first
use and its tools are offered to the model alongside the built-ins,
namespaced as "<server>__<tool>" so names never collide. mcp.json uses the
standard mcpServers format:

{
  "mcpServers": {
    "filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem"]},
    "remote": {"url": "https://example.com/mcp"}
  }
}
"""

import json
import logging
import os
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import ClientSession, StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from tools import TOOLS

CONFIG_FILE = "mcp.json"

_stack: AsyncExitStack | None = None
sessions: dict[str, ClientSession] = {}
# namespaced tool name -> (server name, original tool name)
routes: dict[str, tuple[str, str]] = {}
schemas: list[dict] = []

log = logging.getLogger("mcp")


async def start() -> None:
    """Connect to every server in mcp.json. No-op when there is no config."""
    global _stack
    if _stack is not None or not os.path.exists(CONFIG_FILE):
        return
    try:
        servers = json.loads(Path(CONFIG_FILE).read_text()).get("mcpServers", {})
    except (OSError, ValueError) as exc:
        # A broken config disables MCP tools; it must not break every turn.
        log.error("mcp: unusable %s (%s) — external tools disabled", CONFIG_FILE, exc)
        servers = {}
    _stack = AsyncExitStack()
    for name, conf in servers.items():
        try:
            sessions[name] = await _connect(conf)
            tools = (await sessions[name].list_tools()).tools
        except Exception as exc:
            log.error("mcp: skipping %r: %s", name, exc)
            continue
        for t in tools:
            full = f"{name}__{t.name}"
            if full in TOOLS or full in routes:
                log.warning("mcp: duplicate tool name %r, skipping", full)
                continue
            routes[full] = (name, t.name)
            schema = dict(t.input_schema)
            schema.pop("$schema", None)  # the API rejects this key
            schemas.append(
                {
                    "type": "function",
                    "name": full,
                    "description": t.description or "",
                    "parameters": schema,
                }
            )
        log.info("mcp: %s: %d tools", name, len(tools))


async def _connect(conf: dict) -> ClientSession:
    """Spawn/connect one server and return an initialized session."""
    if "url" in conf:
        streams = await _stack.enter_async_context(streamable_http_client(conf["url"]))
    else:
        params = StdioServerParameters(
            command=os.path.expandvars(conf["command"]),
            args=[os.path.expandvars(a) for a in conf.get("args", [])],
            env={
                **os.environ,
                **{k: os.path.expandvars(v) for k, v in conf.get("env", {}).items()},
            },
        )
        streams = await _stack.enter_async_context(stdio_client(params))
    read, write = streams
    session = await _stack.enter_async_context(ClientSession(read, write))
    await session.initialize()
    return session


async def stop() -> None:
    """Disconnect all servers. Call from the same task that called start();
    otherwise the sessions simply die with the process, which is fine."""
    global _stack
    if _stack is not None:
        await _stack.aclose()
        _stack = None


async def call(name: str, args: dict) -> str:
    """Call a namespaced MCP tool and return its text output."""
    server, tool = routes[name]
    result = await sessions[server].call_tool(tool, arguments=args)
    parts = [c.text for c in result.content if getattr(c, "text", None)]
    return "\n".join(parts) or f"(no output; isError={getattr(result, 'isError', False)})"
