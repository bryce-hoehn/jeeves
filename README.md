# wow-mcp

A Discord bot that chats with an AI. Tools are built-in Python functions in
the `tools/` package plus any external MCP servers configured in
[`mcp.json`](mcp.json.example), and conversations continue across messages
via the OpenAI Responses API's `previous_response_id`.

## Setup

Create a `.env` file in the project root (`uv run` loads it automatically):

```
DISCORD_TOKEN=...
OPENAI_API_KEY=...
```

Optional: `OPENAI_BASE_URL`, `OPENAI_MODEL`, `SYSTEM_PROMPT`,
`UNDERMINE_API_KEY`, `SIMC_PATH`, `RAIDBOTS_CACHE_DIR` (see the tool
sections below). Then install dependencies:

```sh
uv sync
```

Also enable **Message Content Intent** in the
[Discord Developer Portal](https://discord.com/developers/applications) under
*Bot → Privileged Gateway Intents*.

## Run

```sh
uv run main.py
```

## Docker

```sh
docker build -t wow-mcp .
docker run -d --name wow-mcp --env-file .env wow-mcp
```

Secrets come from the environment (`--env-file .env`, or `-e DISCORD_TOKEN=...`),
never baked into the image. If you use `mcp.json`, mount it in
(`-v ./mcp.json:/app/mcp.json`) — note that stdio servers listed there must
have their commands available inside the container. To persist the raidbots
cache (~50 MB after the first item search), add
`-v raidbots-cache:/root/.cache/raidbots`.

## Usage

- Mention the bot (or DM it, or reply to one of its messages) to chat.
- The bot remembers the conversation per channel.
- Send `!reset` (as a mention) to start a fresh conversation.

## Undermine Exchange tools

[`tools/undermine.py`](tools/undermine.py) wraps the
[Undermine Exchange](https://undermine.exchange/api.html) API for WoW auction
house data. Get an API key at
<https://undermine.exchange/api.html#gaining-access> and add it to `.env`:

```
UNDERMINE_API_KEY=yourkey
```

Prices come back in copper (1 gold = 10000 copper); the tools also render a
gold/silver/copper string. Commodities (stackables) sell region-wide;
non-commodities sell per realm — the model picks the matching tool.

| Tool | What it does |
|---|---|
| `commodity_now` | Current price, quantity, cheapest auctions for a commodity. |
| `commodity_price_history` | Daily history + average for a commodity. |
| `commodity_hourly_history` | Hourly snapshots (~14 days) for a commodity. |
| `item_summary` | Median/min price and realm count for a non-commodity. |
| `item_realm_prices` | Cheapest realms selling a non-commodity right now. |
| `item_price_history` | Region-aggregated daily history for a non-commodity. |
| `realm_item_now` | Current price and auctions on one realm. |
| `realm_item_history` | Daily history on one realm. |

## SimulationCraft tools

[`tools/simc.py`](tools/simc.py) drives the
[SimulationCraft](https://github.com/simulationcraft/simc) CLI. Install simc
yourself (on Linux, build from source; see the repo's HowToBuild wiki) and
make sure `simc` is on PATH, or point `SIMC_PATH` at the executable in `.env`:

```
SIMC_PATH=/path/to/simc
```

| Tool | What it does |
|---|---|
| `simc_check` | Verify simc is installed; report its version. |
| `simc_simulate` | Sim a `/simc` addon export (or any profile) — supports fight styles, iteration counts, stat weights (`scale_factors`), profileset comparisons, and raw simc options via `extra_options`. |
| `simc_armory_simulate` | Same, importing the character straight from the Blizzard armory. |

Sims are synchronous and can take minutes at high iteration counts; the tool
returns the report's summary tables (DPS ranking / scale factors / tail),
capped at ~4000 characters.

## Raidbots static data tools

[`tools/raidbots.py`](tools/raidbots.py) reads the JSON game-data files
Raidbots publishes for developers (<https://www.raidbots.com/developers>):
items, talents, enchants/gems, consumables, instances, item sets, and more.
No API key needed. Files are disk-cached under `~/.cache/raidbots`
(override with `RAIDBOTS_CACHE_DIR`) and refreshed only when Raidbots'
content hash changes, per their docs' request to cache locally.

| Tool | What it does |
|---|---|
| `raidbots_metadata` | Build number, content hash, and full file list for live/ptr/beta. |
| `raidbots_item_search` | Item name ↔ ID lookup across all equippable items. |
| `raidbots_enchant_search` | Enchants (with simc option names) and gems. |
| `raidbots_talents` | Talent tree nodes for a class/spec. |
| `raidbots_consumables` | Flasks/foods/potions/weapon buffs/augments with simc strings. |
| `raidbots_instances` | Dungeons/raids and their bosses. |
| `raidbots_item_sets` | Tier set bonuses and their items. |
| `raidbots_get_file` | Raw escape hatch for any other data file. |

The first item search downloads ~50 MB (cached afterwards). Together with
`simc_simulate` these cover the full loop: identify items/talents/consumables,
then sim the profile.

## Wowhead tooltip embeds

[`tools/wowhead.py`](tools/wowhead.py) reimplements the Wowhead bot's
`/tooltip` behavior using Wowhead's own data sources (derived from
`wow.zamimg.com/js/tooltips.js`): the search page's embedded
`WH.Gatherer` results resolve a name to the top result, then
`nether.wowhead.com/tooltip/{type}/{id}` provides the tooltip data. The tool
converts the tooltip HTML to text and posts a rich embed (icon thumbnail,
quality-colored title, link) via our own bot — no dependency on another bot.

This is the agent's preferred way to show a specific item or spell; the
system prompt says so automatically when the tool is registered. The agent
injects the Discord channel into any tool with a `channel` parameter, and
the dispatch awaits async tool functions.

## Adding a tool

Create a new module in [`tools/`](tools) — the `@tool` decorator builds the
JSON schema from type hints automatically:

```python
# tools/fetch_stats.py
from tools import tool


@tool
def fetch_stats(player: str, season: int = 2026) -> str:
    """Fetch stats for a player."""
    ...
```

Return a string (it's fed straight back to the model) or an async function
— the agent awaits coroutine results. A parameter named `channel` is
skipped in the schema and receives the Discord channel the conversation is
happening in. Then import the module at the bottom of
[`tools/__init__.py`](tools/__init__.py) so it registers, and the agent
picks it up automatically.

## External MCP servers

Tools from external MCP servers can be added without writing code. Copy
[`mcp.json.example`](mcp.json.example) to `mcp.json` (gitignored) and list
your servers in the standard `mcpServers` format:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/some/dir"]
    },
    "remote": { "url": "https://example.com/mcp" }
  }
}
```

Servers are connected on first use ([`mcp_servers.py`](mcp_servers.py)) and
their tools are offered to the model as `<server>__<tool>` so names never
collide with the built-ins. `${VAR}` placeholders in command/args/env values
are expanded from the environment.
