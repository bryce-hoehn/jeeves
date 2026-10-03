# jeeves

A Discord bot that chats with an AI. Tools are built-in Python functions in
the `tools/` package plus any external MCP servers configured in
[`mcp.json`](mcp.json.example). Each conversation keeps an in-memory
transcript that is resent in full every turn; after a restart the transcript
is rebuilt from the thread's Discord history.

## Setup

Create a `.env` file in the project root (`uv run` loads it automatically):

```
DISCORD_TOKEN=...
OPENAI_API_KEY=...
```

Optional: `OPENAI_BASE_URL`, `OPENAI_MODEL`, `SYSTEM_PROMPT`,
`UNDERMINE_API_KEY`, `SIMC_PATH`, `RAIDBOTS_CACHE_DIR`,
`BLIZZARD_CLIENT_ID`/`BLIZZARD_CLIENT_SECRET` (auction house + character/guild
progression tools), `WCL_CLIENT_ID`/`WCL_CLIENT_SECRET` (Warcraft Logs),
`RAIDERIO_API_KEY` (optional, higher rate limits), `EPHEMR_API_KEY`,
`KNOWLEDGE_DIR` (knowledge-base folder, default `knowledge/`)
(see the tool sections below). Then install dependencies:

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

With [`docker-compose.yml`](docker-compose.yml):

```sh
docker compose up -d --build
```

Or plain Docker:

```sh
docker build -t jeeves .
docker run -d --name jeeves --env-file .env jeeves
```

Secrets come from the environment (`--env-file .env`, or `-e DISCORD_TOKEN=...`),
never baked into the image. The image includes a from-source build of the simc
CLI (multi-stage, in the [`Dockerfile`](Dockerfile)); pin a release tag with
`--build-arg SIMC_REF=<tag>` instead of tracking the development branch. If you
use `mcp.json`, mount it in (`-v ./mcp.json:/app/mcp.json` — in compose,
uncomment the volume) — note that stdio servers listed there must have their
commands available inside the container. To persist the raidbots cache
(~50 MB after the first item search), add
`-v raidbots-cache:/root/.cache/raidbots` (already a named volume in compose).

## Usage

- Mention the bot (or DM it) to chat — each message starts a fresh
  conversation in a new public thread.
- Every message inside one of the bot's threads continues that thread's
  conversation.
- Send `!reset` in a thread to start that conversation over.
- If the bot restarts, existing threads and DMs pick up where they left
  off — the conversation is rebuilt from the channel's message history.

## Undermine Exchange tools

[`tools/market/undermine.py`](tools/market/undermine.py) wraps the
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

[`tools/sim/simc.py`](tools/sim/simc.py) drives the
[SimulationCraft](https://github.com/simulationcraft/simc) CLI. The Docker
image builds simc from source, so it is on PATH in containers; outside Docker,
install it yourself (on Linux, build from source; see the repo's HowToBuild
wiki) and make sure `simc` is on PATH, or point `SIMC_PATH` at the executable
in `.env`:

```
SIMC_PATH=/path/to/simc
```

| Tool | What it does |
|---|---|
| `simc_check` | Verify simc is installed; report its version. |
| `simc_simulate` | Sim a `/simc` addon export (or any profile) — supports fight styles, iteration counts, stat weights (`scale_factors`), profileset comparisons, raw simc options via `extra_options`, and `json_output=true` for structured mean/SE results (feed into the `python` tool for A/B significance testing). |
| `simc_armory_simulate` | Same, importing the character straight from the Blizzard armory. The tool fetches a Blizzard API token itself (via `BLIZZARD_CLIENT_ID`/`SECRET`) and passes it to simc as `apitoken=` — recent simc builds removed `apisecret=` and their built-in shared key no longer works. |

Sims are synchronous and can take minutes at high iteration counts; the tool
returns the report's summary tables (DPS ranking / scale factors / tail),
capped at ~4000 characters.

Every simulation also generates simc's self-contained HTML report and
publishes it to [ephemr.io](https://ephemr.io) (ephemeral static hosting), so
the full interactive report is shared as a public link that expires after 72
hours. Create an API key in the [ephemr portal](https://ephemr.io/portal/keys)
and add it to `.env` to enable this:

```
EPHEMR_API_KEY=eph_live_...
```

Without a key, sims still run — the HTML report is just not hosted anywhere.

## Core tools: python, clock

[`tools/core/python.py`](tools/core/python.py) — the `python` tool runs generated code in
a sandboxed `python -I` subprocess (timeout, memory/CPU rlimits, no network)
with numpy and scipy available. This is the agent's calculator and stats
workbench: copper→gold conversions, price z-scores, Theil-Sen slopes, HHI,
Kelly sizing, and significance tests on sim results all happen here instead
of in mental math.

[`tools/core/clock.py`](tools/core/clock.py) — the `now` tool reports the current UTC
time, epoch, and the next US/EU weekly reset, for interpreting API timestamps
("3-hour-old snapshot") and reset/restock cycles.

## Knowledge base tools

[`tools/core/knowledge.py`](tools/core/knowledge.py) — a persistent markdown
knowledge base the agent reads and writes across conversations. Notes live as
plain `.md` files in `knowledge/` (override with `KNOWLEDGE_DIR`; mount it as
a volume in Docker so notes survive container restarts):

- `kb_list()` — every note with its title, size, and last-modified time
- `kb_read(name)` — full contents of one note (truncated past 16k chars)
- `kb_write(name, content)` — create or overwrite a note (256 KB cap)
- `kb_append(name, content)` — append to a note (running logs, price diaries)
- `kb_search(query)` — case-insensitive search across all notes

The base ships with `knowledge/game-mechanics.md` — the ground-truth
reference for current (Midnight, 12.x) mechanics (warbands, the account-wide
warband bank, per-realm vs. region-wide auction houses, AH fees) that used
to be a hardcoded `game_knowledge` tool. Typical uses for new notes: user
preferences ("bryce plays Alliance on Kel'Thuzad"), market watchlists,
summaries of guides the agent has scraped, and conclusions worth recalling
in later conversations.

## Market tools: token price, realms

[`tools/market/token.py`](tools/market/token.py) — `wow_token_price(region)` fetches the
current WoW Token gold price from Blizzard's public game-data API (no auth,
cached 1 hour) to convert gold profit into real-money terms.

[`tools/market/realms.py`](tools/market/realms.py) — `realm_metadata(realm, region)` maps a
realm to its connected-realm group (realms sharing one auction house), plus
timezone and population. Data is pulled from Blizzard's game-data API (set
`BLIZZARD_CLIENT_ID` / `BLIZZARD_CLIENT_SECRET` from a free
<https://develop.battle.net> client) and cached to `data/realms-{region}.json`,
refreshed weekly. Faction splits aren't published by Blizzard — join census
data in the `python` tool for faction-arbitrage analysis.

## Raidbots static data tools

[`tools/sim/raidbots.py`](tools/sim/raidbots.py) reads the JSON game-data files
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

[`tools/reference/wowhead.py`](tools/reference/wowhead.py) reimplements the Wowhead bot's
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

## In-game events calendar

[`tools/reference/darmory.py`](tools/reference/darmory.py) — the `wow_events` tool answers
"what's on the in-game calendar": holidays, bonus events, PvP brawls,
Darkmoon Faire, and micro-holidays, sourced from darmory.com's event
database (Blizzard's web API has no calendar endpoint). Without a query it
lists everything live now plus everything starting within `days` (default
30); with a query it shows that event's next occurrences. darmory also
publishes the same data as an iCal feed at
`https://api.darmory.com/events/calendar/ics?region={region}`.

## Discord scheduled events

[`tools/discord_events.py`](tools/discord_events.py) — `discord_events_list`,
`discord_events_create`, and `discord_events_delete` read and write the
scheduled-event calendar of the server the conversation is happening in.
Combined with `wow_events`, this lets the agent mirror the in-game WoW
calendar onto Discord's events calendar. Created events are external
events located "In-game"; times are ISO 8601 (UTC assumed when no
offset is given).

## Adding a tool

Create a new module in the matching subpackage of [`tools/`](tools) — `core/`
(python, clock, knowledge base), `market/` (auction/economy APIs),
`progression/` (character & guild APIs), `sim/` (SimulationCraft, Raidbots),
`reference/` (Wowhead, guides, news, event calendar), or the top level for
Discord-side tools (`discord_events.py`). The `@tool` decorator builds the
JSON schema from type hints automatically:

```python
# tools/sim/fetch_stats.py
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
