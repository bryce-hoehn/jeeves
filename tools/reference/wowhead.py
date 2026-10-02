"""Wowhead tooltips — item/spell embeds derived from Wowhead's own tooling.

Reimplements what the server's Wowhead bot's /tooltip command does, using the
same data sources as Wowhead's site (discovered from wow.zamimg.com/js/
tooltips.js):

1. Name resolution — https://www.wowhead.com/search?q=... embeds results as
   `WH.Gatherer.addData(typeId, 1, {id: {..., name_enus}})` payloads. The
   best match wins: exact name first, then prefix (lowest ID breaks ties —
   canonical player spells/items have far lower IDs than NPC abilities).
2. Tooltip data — https://nether.wowhead.com/tooltip/{type}/{id}?locale=0
   returns {name, quality, icon, tooltip(html)}.

The tool converts the tooltip HTML to text and posts a rich Discord embed
(icon thumbnail, quality-colored name, link back to Wowhead). Page scraping
for guides/news lives in wowhead_page below.
"""

import html as html_lib
import json
import re
import urllib.parse
from typing import Literal

import discord

from tools import tool, web
from tools.util import clamp

MAX_DESCRIPTION = 3900  # Discord embed descriptions cap at 4096

# WH.Types enum from tooltips.js — id -> URL segment used by the site.
TYPES = {
    1: "npc", 2: "object", 3: "item", 4: "item-set", 5: "quest", 6: "spell",
    7: "zone", 8: "faction", 10: "achievement", 11: "title", 17: "currency",
}
TEMPLATE_TO_TYPE = {
    "npc": 1, "object": 2, "item": 3, "itemset": 4, "quest": 5,
    "spell": 6, "zone": 7, "faction": 8, "achievement": 10, "title": 11,
    "currency": 17,
}
# Embed colors by item quality (Wowhead's q0..q6 classes).
QUALITY_COLORS = [0x9D9D9D, 0xFFFFFF, 0x1EFF00, 0x0070DD, 0xA335EE, 0xFF8000, 0xE5CC80]
DEFAULT_COLOR = 0xFFD100  # Wowhead gold

_search_cache = web.TTLCache(ttl=600)


def _extract_object(text: str, start: int) -> tuple[dict, int]:
    """Parse the JSON object starting at text[start] == '{', brace-matched."""
    depth, i, in_str, escaped = 0, start, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1]), i + 1
    raise ValueError("unbalanced JSON object")


def _resolve(query: str, kind: str) -> tuple[int, str, str]:
    """Resolve a search query to (typeId, id, name) of the top result."""
    cached = _search_cache.get(query.lower())
    if cached is not None:
        return cached

    url = f"https://www.wowhead.com/search?q={urllib.parse.quote(query)}"
    page = web.fetch(url)

    # Gathered result data, per WH type id: {id: {name_enus: ...}}.
    groups: dict[int, dict] = {}
    for m in re.finditer(r"WH\.Gatherer\.addData\((\d+),\s*\d+,\s*", page):
        type_id = int(m.group(1))
        if type_id not in TYPES:
            continue
        data, _ = _extract_object(page, m.end())
        groups.setdefault(type_id, {}).update(data)

    # Prefer exact name matches; among ties the lowest ID is the canonical
    # entity (player spells/items have much lower IDs than NPC abilities).
    q = query.strip().lower()
    order = [3, 6, 1, 5, 10, 2, 7, 8, 11, 17]  # item, spell, npc, quest, ...
    if kind in TEMPLATE_TO_TYPE:
        order = [TEMPLATE_TO_TYPE[kind]] + [t for t in order if t != TEMPLATE_TO_TYPE[kind]]

    def find(group: dict, matches) -> tuple[str, dict] | None:
        hits = {i: e for i, e in group.items() if matches((e.get("name_enus") or "").lower())}
        return min(hits.items(), key=lambda kv: int(kv[0])) if hits else None

    for matches in (lambda n: n == q, lambda n: n.startswith(q)):
        for type_id in order:
            hit = find(groups.get(type_id) or {}, matches)
            if hit:
                result = (type_id, hit[0], hit[1].get("name_enus") or query)
                _search_cache.put(query.lower(), result)
                return result

    # No name match anywhere — take the first entry of the first result tab.
    templates = re.findall(r'template:\s*"([a-z-]+)"', page)
    for template in templates:
        type_id = TEMPLATE_TO_TYPE.get(template)
        if type_id and groups.get(type_id):
            item_id, entry = next(iter(groups[type_id].items()))
            result = (type_id, str(item_id), entry.get("name_enus") or query)
            _search_cache.put(query.lower(), result)
            return result

    raise RuntimeError(f"no Wowhead results for '{query}'")


def _tooltip_to_text(tooltip_html: str) -> str:
    """Convert Wowhead tooltip HTML into plain text for an embed."""
    text = re.sub(r"<!--.*?-->", "", tooltip_html, flags=re.S)
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"</(tr|table|div|p|h\d)>", "\n", text)
    text = re.sub(r"<(div|p)[^>]*>", "\n", text)
    text = re.sub(r"<t[dh][^>]*>", " ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_lib.unescape(text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _fetch_tooltip(type_id: int, item_id: str) -> dict:
    slug = TYPES[type_id]
    url = f"https://nether.wowhead.com/tooltip/{slug}/{item_id}?locale=0"
    return web.get_json(url)


@tool
async def wowhead_tooltip(
    query: str,
    kind: Literal["", "item", "spell", "npc", "quest", "achievement", "zone", "currency"] = "",
    channel=None,
) -> str:
    """Show the user a WoW item, spell, NPC, quest, or achievement by posting a Wowhead tooltip embed (icon, stats, description) into the channel — same result as the server's Wowhead bot /tooltip command. This is the PREFERRED way to present a specific item or spell; do not paste raw stats when this would do. Not for lists, prices, or sims — use the other tools for those. One call per entity; returns the resolved name/ID so you can mention it."""
    type_id, item_id, name = _resolve(query, kind)
    data = _fetch_tooltip(type_id, item_id)

    url = f"https://www.wowhead.com/{TYPES[type_id]}={item_id}"
    color = (
        QUALITY_COLORS[data["quality"]]
        if "quality" in data and data["quality"] < len(QUALITY_COLORS)
        else DEFAULT_COLOR
    )

    embed = discord.Embed(
        title=data.get("name", name),
        url=url,
        color=color,
        description=_tooltip_to_text(data.get("tooltip", ""))[:MAX_DESCRIPTION],
    )
    icon = data.get("icon")
    if icon:
        embed.set_thumbnail(
            url=f"https://wow.zamimg.com/images/wow/icons/large/{icon}.jpg"
        )
    embed.set_footer(text="Wowhead")

    if channel is None:
        return f"Error: no Discord channel to post in. {name}: {url}"

    await channel.send(embed=embed)
    return f"Posted Wowhead tooltip embed: {name} ({TYPES[type_id]} {item_id}) — {url}"


@tool
def wowhead_page(query_or_url: str, max_chars: int = 6000) -> str:
    """Scrape the readable text of a Wowhead page — guides, news articles, or item/spell/NPC/quest pages — for when the user wants details beyond a tooltip (guide steps, drop sources, related-patch notes, article body). Pass a full www.wowhead.com URL, or a name like "frostweave cloth" to resolve to its Wowhead page. Returns the page title, URL, and main text. For showing a specific item/spell in chat, prefer wowhead_tooltip instead."""
    max_chars = clamp(max_chars, 500, 12000)
    if query_or_url.startswith("http"):
        netloc = urllib.parse.urlparse(query_or_url).netloc
        if not netloc.endswith("wowhead.com"):
            raise RuntimeError(f"not a Wowhead URL: {query_or_url}")
        url = query_or_url.split("#", 1)[0]
    else:
        type_id, item_id, _ = _resolve(query_or_url, "")
        url = f"https://www.wowhead.com/{TYPES[type_id]}={item_id}"

    title, text, _ = web.text_from_html(web.fetch(url))
    return f"{title or url}\n{url}\n\n{text[:max_chars]}"
