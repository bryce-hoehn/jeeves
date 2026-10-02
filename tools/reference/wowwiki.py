"""WoW wiki lookups via the standard MediaWiki API.

warcraft.wiki.gg is the actively-updated community wiki (the successor to
Wowpedia/WowWiki after the 2023 fork off Fandom); wowwiki.fandom.com is the
frozen legacy copy, checked as a fallback. Both expose api.php:

- search:     action=query&list=search&srsearch=...
- plain text: action=query&prop=extracts&explaintext=1&titles=...

so articles come back as clean text with no HTML scraping needed. A full
wiki URL also works; its title is pulled out of the path.
"""

from urllib.parse import quote, unquote, urlparse

from tools import tool, web
from tools.util import clamp

WIKIS = [
    # (name, api endpoint, page URL prefix)
    ("warcraft.wiki.gg", "https://warcraft.wiki.gg/api.php", "https://warcraft.wiki.gg/wiki/"),
    ("wowwiki.fandom.com", "https://wowwiki.fandom.com/api.php", "https://wowwiki.fandom.com/wiki/"),
]


def _title_from_url(url: str) -> str:
    path = urlparse(url).path
    for prefix in ("/wiki/", "/"):
        if path.startswith(prefix):
            return unquote(path[len(prefix):]).replace("_", " ").strip("/")
    raise RuntimeError(f"cannot find an article title in {url}")


def _search(api: str, query: str) -> list[str]:
    data = web.get_json(
        api,
        params={
            "action": "query", "list": "search", "srsearch": query,
            "srlimit": 5, "format": "json",
        },
    )
    return [hit["title"] for hit in data["query"]["search"]]


def _extract(api: str, title: str) -> str:
    data = web.get_json(
        api,
        params={
            "action": "query", "prop": "extracts", "explaintext": 1,
            "redirects": 1, "titles": title, "format": "json",
        },
    )
    pages = data["query"]["pages"]
    page = next(iter(pages.values()))
    return page.get("extract") or ""


@tool
def wow_wiki(query_or_url: str, max_chars: int = 6000) -> str:
    """Scrape lore and mechanics article text from the WoW wikis — warcraft.wiki.gg (the current community wiki) with the old WowWiki Fandom copy as fallback. Pass a topic like "Illidan Stormrage", "Midnight expansion", or "arena rating system", or a full wiki article URL. Returns the article title, URL, and main text. Best source for lore, history, and encyclopedic game mechanics."""
    max_chars = clamp(max_chars, 500, 12000)

    title = (
        _title_from_url(query_or_url)
        if query_or_url.startswith("http")
        else None
    )
    errors = []
    for name, api, prefix in WIKIS:
        try:
            if title is None:
                hits = _search(api, query_or_url)
                if not hits:
                    continue
                article = hits[0]
            else:
                # URL given: only look on the wiki it points at.
                if prefix not in query_or_url:
                    continue
                article = title
            text = _extract(api, article)
            if not text.strip():
                continue
            url = prefix + quote(article.replace(" ", "_"))
            return f"{article} ({name})\n{url}\n\n{text[:max_chars]}"
        except RuntimeError as exc:
            errors.append(f"{name}: {exc}")
    raise RuntimeError(
        f"no wiki article for '{query_or_url}' ({'; '.join(errors) or 'no matches'})"
    )
