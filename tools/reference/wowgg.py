"""wow.gg scraper — class/spec guides and tools from wow.gg.

A Next.js site with server-rendered pages: class/spec guides live under
/classes/<class>/<spec> and feature guides under /guides/<slug>. The
sitemap index (https://wow.gg/sitemap.xml) lists all child sitemaps —
classes, guides, meta, pages. The tool matches a query against those URLs
(slug terms), fetches the best page, and returns its readable text. A full
wow.gg URL skips the search step.
"""

import re

from tools import tool, web
from tools.util import clamp

BASE_URL = "https://wow.gg"
SITEMAP_INDEX = f"{BASE_URL}/sitemap.xml"
# Locale variants (e.g. /zh-cn/...) duplicate the English guides; skip them.
_LOCALE_PATH = re.compile(rf"^{re.escape(BASE_URL)}/[a-z]{{2}}(?:-[a-z]{{2}})?/")


@tool
def wow_gg(query_or_url: str, max_chars: int = 6000) -> str:
    """Scrape readable guide text from wow.gg — current-spec class guides (talents, rotations, stat priorities, consumables, tier set analysis) and feature guides. Pass a full wow.gg URL, or a search query like "arms warrior", "devastation evoker", or "midnight season 2". Returns the page title, URL, and main guide text. Alternative to icy_veins for class/spec guide content."""
    max_chars = clamp(max_chars, 500, 12000)

    if query_or_url.startswith("http"):
        netloc = re.sub(r"^https?://", "", query_or_url).split("/")[0]
        if not netloc.endswith("wow.gg"):
            raise RuntimeError(f"not a wow.gg URL: {query_or_url}")
        url = query_or_url.split("#", 1)[0]
    else:
        urls: set[str] = set()
        for child in re.findall(
            r"<loc>([^<]+)</loc>", web.fetch(SITEMAP_INDEX)
        ):
            urls.update(re.findall(r"<loc>([^<]+)</loc>", web.fetch(child)))
        links = [
            (  # link text = the slug ("warrior-arms" -> "warrior arms")
                loc[len(BASE_URL):].strip("/").replace("-", " "),
                loc,
            )
            for loc in urls
            if loc.startswith(BASE_URL + "/") and not _LOCALE_PATH.match(loc)
        ]
        hit = web.pick_link(links, query_or_url, BASE_URL)
        if hit is None:
            raise RuntimeError(f"no wow.gg pages matching '{query_or_url}'")
        _, url = hit

    title, text, _ = web.text_from_html(web.fetch(url))
    return f"{title or url}\n{url}\n\n{text[:max_chars]}"
