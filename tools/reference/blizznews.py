"""WoW news & hotfixes — official Blizzard news plus MMO-Champion.

Blizzard's news page (worldofwarcraft.blizzard.com/en-us/news) is
server-rendered with article links like /en-us/news/{id}/{slug}; patch
notes and hotfix roundups land there first. MMO-Champion's RSS feed is the
fallback (and often faster on datamined changes). Both run through the
shared scraper (browser UA + cache) since Blizzard 403s plain bots.
"""

import re
import xml.etree.ElementTree as ET
from typing import Literal

from bs4 import BeautifulSoup

from tools import tool, web

BLIZZARD_NEWS = "https://worldofwarcraft.blizzard.com/en-us/news"
MMO_CHAMPION_RSS = "https://www.mmo-champion.com/external.php?type=RSS2"
_ARTICLE_HREF = re.compile(r"/news/(\d+)(?:/([a-z0-9\-]+))?")


@tool
def wow_news(source: Literal["blizzard", "mmo-champion"] = "blizzard", limit: int = 10) -> str:
    """Latest WoW news headlines and links — official Blizzard announcements (patch notes, hotfixes, events) or MMO-Champion (datamining, patch coverage), newest first. Use this before answering 'what changed in the latest patch/hotfix' — training data is always stale. Returns title + URL per article."""
    limit = max(1, min(limit, 25))

    if source == "mmo-champion":
        root = ET.fromstring(web.fetch(MMO_CHAMPION_RSS))
        items = root.findall(".//item")
        lines = [f"MMO-Champion — latest {min(limit, len(items))} articles:"]
        for item in items[:limit]:
            lines.append(
                f"  {item.findtext('title', '').strip()}\n    {item.findtext('link', '').strip()}"
            )
        return "\n".join(lines)

    html = web.fetch(BLIZZARD_NEWS)
    soup = BeautifulSoup(html, "html.parser")
    articles: dict[str, tuple[str, str]] = {}
    for anchor in soup.find_all("a", href=_ARTICLE_HREF):
        match = _ARTICLE_HREF.search(anchor["href"])
        article_id, slug = match.group(1), match.group(2)
        if article_id in articles:
            continue
        # anchors are image cards: take the title from the URL slug or img alt
        title = ""
        if slug:
            title = slug.replace("-", " ").title()
        else:
            image = anchor.find("img", alt=True)
            if image:
                title = image["alt"].strip()
        if not title:
            continue
        articles[article_id] = (
            title,
            f"https://worldofwarcraft.blizzard.com/news/{article_id}",
        )
    if not articles:
        raise RuntimeError("could not parse Blizzard news page")
    # article ids are sequential — higher = newer
    latest = [articles[i] for i in sorted(articles, key=int, reverse=True)[:limit]]
    lines = [f"Blizzard official WoW news — latest {len(latest)}:"]
    lines += [f"  {title}\n    {url}" for title, url in latest]
    return "\n".join(lines)
