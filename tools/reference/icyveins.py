"""Icy Veins scraper — guide text from icy-veins.com.

https://www.icy-veins.com/search?q=... lists result links; the best-scoring
match (query terms in the link text/URL, WoW guide sections preferred over
the site's other games) is fetched and its main content returned as text.
A full icy-veins.com URL skips the search step. If the site is unreachable
or blocks the request, the tool fails with a clear error the agent can
report — no fallbacks.
"""

from urllib.parse import quote_plus

from tools import tool, web
from tools.util import clamp

BASE_URL = "https://www.icy-veins.com"
# Game-guide sections of the site (vs. its Diablo, FFXIV, etc. sections).
WOW_SECTIONS = ("/wow/", "/wow-classic/", "/wotlk/", "/cata/")


@tool
def icy_veins(query_or_url: str, max_chars: int = 6000) -> str:
    """Scrape readable guide text from Icy Veins (icy-veins.com) — talent builds, rotations, stat priorities, leveling, raid boss guides, class guides. Pass a full icy-veins.com URL, or a search query like "devastation evoker dps guide" or "protection warrior tanking guide". Returns the page title, URL, and main guide text. Use this when the user wants guide content, not just an item tooltip."""
    max_chars = clamp(max_chars, 500, 12000)

    if query_or_url.startswith("http"):
        if "icy-veins.com" not in query_or_url:
            raise RuntimeError(f"not an Icy Veins URL: {query_or_url}")
        url = query_or_url.split("#", 1)[0]
    else:
        search_url = f"{BASE_URL}/search?q={quote_plus(query_or_url)}"
        _, _, links = web.text_from_html(web.fetch(search_url))
        hit = web.pick_link(links, query_or_url, BASE_URL, list(WOW_SECTIONS))
        if hit is None:
            raise RuntimeError(f"no Icy Veins results for '{query_or_url}'")
        _, url = hit

    title, text, _ = web.text_from_html(web.fetch(url))
    return f"{title or url}\n{url}\n\n{text[:max_chars]}"
