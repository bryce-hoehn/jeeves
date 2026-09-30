"""Raidbots static data tools — WoW game data as JSON.

Raidbots publishes JSON files generated from game client data
(https://www.raidbots.com/developers), e.g. equippable items, talents,
enchants, gems, consumables, and dungeon/raid instances. Files live at
https://www.raidbots.com/static/data/{live|ptr|beta}/{name}.json; the current
file list and a content hash are in metadata.json.

The docs ask consumers to cache locally, so every file is disk-cached (under
~/.cache/raidbots, override with RAIDBOTS_CACHE_DIR) and re-downloaded only
when the environment's content hash changes. The big item file (~50 MB) is
parsed once per hash and reduced to compact search indexes. No API key
needed.
"""

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Literal

from tools import tool

DATA_URL = "https://www.raidbots.com/static/data"
MAX_OUTPUT_CHARS = 4000
METADATA_TTL = 3600  # seconds to trust the in-memory metadata

Env = Literal["live", "ptr", "beta"]

INVENTORY_TYPES = {
    1: "head", 2: "neck", 3: "shoulder", 4: "shirt", 5: "chest", 6: "waist",
    7: "legs", 8: "feet", 9: "wrist", 10: "hands", 11: "finger",
    12: "trinket", 13: "one-hand", 14: "shield", 16: "back", 17: "two-hand",
    21: "main hand", 22: "off hand", 23: "held off-hand", 26: "ranged",
}
QUALITIES = ["poor", "common", "uncommon", "rare", "epic", "legendary", "artifact"]

# Small per-kind consumable files whose entries carry simc option strings.
CONSUMABLE_KINDS = ("flasks", "foods", "potions", "temp-enchants", "augments")


def _cache_dir() -> Path:
    path = Path(
        os.getenv("RAIDBOTS_CACHE_DIR")
        or Path.home() / ".cache" / "raidbots"
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


def _http_get(url: str, timeout: int = 120) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "wow-mcp"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} for {url}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"could not reach {url}: {exc.reason}") from None


_metadata_cache: dict[str, tuple[float, dict]] = {}


def _metadata(env: str) -> dict:
    """Fetch (and briefly cache) metadata.json for an environment."""
    hit = _metadata_cache.get(env)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    data = json.loads(_http_get(f"{DATA_URL}/{env}/metadata.json"))
    _metadata_cache[env] = (time.monotonic() + METADATA_TTL, data)
    return data


_mem_cache: dict[tuple[str, str], tuple[str, object]] = {}


def _load(name: str, env: str, keep: bool = True):
    """Load a static data file, disk-cached and keyed by content hash."""
    meta = _metadata(env)
    content_hash = meta["contentHash"]
    key = (env, name)

    hit = _mem_cache.get(key)
    if hit and hit[0] == content_hash:
        return hit[1]

    path = _cache_dir() / f"{env}.{name}"
    marker = _cache_dir() / f"{env}.{name}.hash"
    if path.exists() and marker.read_text() == content_hash:
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        raw = _http_get(f"{DATA_URL}/{env}/{name}.json", timeout=600)
        path.write_bytes(raw)
        marker.write_text(content_hash)
        data = json.loads(raw)

    if keep:
        _mem_cache[key] = (content_hash, data)
    return data


# Item database: parse the ~50 MB equippable-items.json once per content hash
# and keep only compact indexes (by id, and lowercase name -> items).
_item_db_cache: dict[str, tuple[str, tuple[dict, dict]]] = {}


def _item_db(env: str) -> tuple[dict, dict]:
    content_hash = _metadata(env)["contentHash"]
    hit = _item_db_cache.get(env)
    if hit and hit[0] == content_hash:
        return hit[1]

    items = _load("equippable-items", env, keep=False)
    by_id = {}
    by_name: dict[str, list] = {}
    for item in items:
        by_id[item["id"]] = item
        by_name.setdefault(item["name"].lower(), []).append(item)
    _item_db_cache[env] = (content_hash, (by_id, by_name))
    return by_id, by_name


def _fmt_item(item: dict) -> str:
    inv = INVENTORY_TYPES.get(item.get("inventoryType"), "?")
    quality = QUALITIES[item["quality"]] if item.get("quality", 0) < len(QUALITIES) else "?"
    return (
        f"{item['id']} | {item['name']} | ilvl {item.get('itemLevel', '?')} "
        f"| {quality} | {inv}"
    )


def _search(records: list[dict], query: str, fields: tuple[str, ...], limit: int) -> list[dict]:
    """Filter records where any field contains the query (case-insensitive)."""
    q = query.lower()
    return [
        r for r in records
        if any(q in str(r.get(f, "")).lower() for f in fields)
    ][:limit]


# Tools ------------------------------------------------------------------------


@tool
def raidbots_metadata(env: Env = "live") -> str:
    """Show the Raidbots static-data build for a game version (live/ptr/beta): WoW build number, generation date, content hash, and the full list of available JSON data files."""
    meta = _metadata(env)
    return (
        f"Raidbots static data ({env}): WoW build {meta['wowBuild']}, "
        f"generated {meta['generatedAt']}, content hash {meta['contentHash']}.\n"
        f"Files: {', '.join(meta['files'])}"
    )


@tool
def raidbots_item_search(query: str, env: Env = "live", limit: int = 10) -> str:
    """Look up WoW items by numeric item ID or (partial, case-insensitive) name — resolves names to IDs for other tools (auction prices, simc profiles, etc). Covers all equippable items from every expansion. The first call for a game version downloads ~50 MB and builds an index, so it may take a while; later calls are fast."""
    by_id, by_name = _item_db(env)
    limit = max(1, min(limit, 25))

    if query.strip().isdigit():
        item = by_id.get(int(query))
        if item:
            return _fmt_item(item)
        return f"No item with id {query}."

    q = query.strip().lower()
    matches = by_name.get(q, []) or _search(list(by_id.values()), q, ("name",), limit)
    if not matches:
        return f"No items matching '{query}'."

    lines = [f"Items matching '{query}' ({len(matches)} shown):"]
    lines += [_fmt_item(i) for i in matches[:limit]]
    return "\n".join(lines)


@tool
def raidbots_enchant_search(query: str, env: Env = "live", limit: int = 10) -> str:
    """Search weapon/armor enchantments and gems by (partial) name. Returns the simc option name for enchants (tokenizedName) and the enchantId/socket for gems — useful for building simc profiles or checking what enchants exist."""
    limit = max(1, min(limit, 25))
    q = query.lower()

    lines = []
    enchants = _search(
        _load("enchantments", env), q, ("displayName", "tokenizedName", "categoryName"), limit
    )
    for e in enchants:
        lines.append(
            f"[enchant] {e['displayName']} | simc: {e.get('tokenizedName', '?')} "
            f"| {e.get('categoryName', '?')} | spellId {e.get('spellId', '?')}"
        )

    gems = _search(_load("gems", env), q, ("name",), limit)
    for g in gems:
        lines.append(
            f"[gem] {g['name']} | item {g['id']} | enchantId {g.get('enchantId', '?')} "
            f"| {g.get('socket', '?').lower()} | ilvl {g.get('itemLevel', '?')}"
        )

    if not lines:
        return f"No enchants or gems matching '{query}'."
    return "\n".join(lines[:limit])


@tool
def raidbots_talents(
    class_name: str, spec_name: str = "", env: Env = "live"
) -> str:
    """Show the talent tree for a class/spec (e.g. class_name 'death knight', spec_name 'frost'): every node with its name, max ranks, and type. Omit spec_name to list every class/spec pair available. Names match what the /simc addon export uses."""
    trees = _load("talents", env)

    if not spec_name:
        pairs = sorted({(t["className"], t["specName"]) for t in trees})
        return "Available spec trees: " + ", ".join(
            f"{c}/{s}" for c, s in pairs
        )

    cls = class_name.lower()
    spec = spec_name.lower()
    tree = next(
        (t for t in trees
         if cls in t["className"].lower() and spec in t["specName"].lower()),
        None,
    )
    if not tree:
        return f"No talent tree for {class_name}/{spec_name}."

    lines = [f"{tree['className']} {tree['specName']} (tree {tree['traitTreeId']}):"]
    for key, nodes in tree.items():
        if not key.endswith("Nodes") or not isinstance(nodes, list):
            continue
        lines.append(f"-- {key} --")
        lines += sorted(
            f"{n['name']} (x{n.get('maxRanks', 1)}, {'choice' if n.get('type') == 'choice' else n.get('type', '?')})"
            for n in nodes
            if isinstance(n, dict) and n.get("name")
        )
    return "\n".join(lines)[:MAX_OUTPUT_CHARS]


@tool
def raidbots_consumables(
    query: str = "", kind: Literal["flasks", "foods", "potions", "temp-enchants", "augments"] = "", env: Env = "live"
) -> str:
    """Search raid consumables (flasks, foods, potions, weapon buffs, augments) with their simc option strings — pass several at once for a simc profile. kind picks one category; query filters by (partial) name; empty query + empty kind lists a sample from each category."""
    kinds = [kind] if kind else list(CONSUMABLE_KINDS)
    limit = 8 if not kind and not query else 15

    lines = []
    for k in kinds:
        entries = _load(k, env)
        if query:
            entries = _search(entries, query, ("name", "shortName", "value"), limit)
        else:
            entries = entries[:3]
        for e in entries:
            lines.append(
                f"[{k}] {e.get('shortName', e.get('name', '?'))} "
                f"| simc: {e.get('value', '?')} | item {e.get('itemId', '?')}"
            )
    if not lines:
        return f"No consumables matching '{query}'."
    return "\n".join(lines)[:MAX_OUTPUT_CHARS]


@tool
def raidbots_instances(query: str = "", env: Env = "live") -> str:
    """List dungeons and raids of the current expansion with their encounters (bosses), sourced from the Adventure Journal. query optionally filters by (partial) instance or encounter name; empty query lists everything."""
    instances = _load("instances", env)
    if query:
        instances = [
            i for i in instances
            if query.lower() in i["name"].lower()
            or any(query.lower() in e["name"].lower() for e in i.get("encounters", []))
        ]
    if not instances:
        return f"No instances matching '{query}'."

    lines = []
    for instance in instances:
        bosses = ", ".join(e["name"] for e in instance.get("encounters", []))
        lines.append(f"{instance['name']} ({instance.get('type', '?')}): {bosses}")
    return "\n".join(lines)[:MAX_OUTPUT_CHARS]


@tool
def raidbots_item_sets(query: str = "", env: Env = "live") -> str:
    """List item sets (tier/set bonuses): which items belong to each set and the spells unlocked at 2/4/5 pieces. query optionally filters by (partial) set name or item id."""
    sets = _load("item-sets", env)
    if query:
        q = query.lower()
        sets = [
            s for s in sets
            if q in s["name"].lower()
            or any(q in str(i) for i in s.get("items", []))
        ]
    if not sets:
        return f"No item sets matching '{query}'."

    lines = []
    for s in sets:
        spells = ", ".join(
            f"{p.get('reqItems', '?')}pc -> spell {p['spellId']}"
            for p in s.get("spells", [])
        )
        lines.append(f"{s['name']} (id {s['id']}): {spells}. Items: {', '.join(map(str, s.get('items', [])))}")
    return "\n".join(lines)[:MAX_OUTPUT_CHARS]


@tool
def raidbots_get_file(name: str, env: Env = "live") -> str:
    """Fetch any Raidbots static-data file by name (see raidbots_metadata for the list), returning its raw JSON truncated to fit. Good escape hatch for files without a dedicated tool. Huge files (equippable-items, equippable-items-full, item-names, enchantments-all, icon-lookup) are refused — use raidbots_item_search instead."""
    meta = _metadata(env)
    if name not in meta["files"]:
        return (
            f"Unknown file '{name}'. Available: {', '.join(meta['files'])}"
        )
    if name in {
        "equippable-items.json", "equippable-items-full.json",
        "item-names.json", "enchantments-all.json", "icon-lookup.json",
    }:
        return f"{name} is too large to dump; use raidbots_item_search for items."

    text = json.dumps(_load(name.removesuffix(".json"), env), indent=None)
    if len(text) > MAX_OUTPUT_CHARS:
        return text[:MAX_OUTPUT_CHARS] + " ... (truncated)"
    return text
