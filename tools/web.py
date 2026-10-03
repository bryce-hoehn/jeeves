"""Shared web plumbing — the ONE HTTP layer for every tool module.

- Session: browser-like User-Agent + shared requests.Session. Blizzard's
  news site, raider.io, icy-veins.com, and warcraft.wiki.gg all 403
  non-browser bot UAs, so every request must look like a desktop browser.
- request_json()/fetch(): retried GET/POST; 4xx fail fast (they don't get
  better); fetch() adds the bounded 15-minute HTML cache used by scrapers.
- oauth_token(): client-credentials OAuth shared by the Blizzard and
  Warcraft Logs APIs (callers read their own env vars for good errors).
- text_from_html()/pick_link(): readable-text extraction and search-result
  scoring for scraping.
- TTLCache: the expiry-cache pattern used across tool modules.
"""

import base64
import re
import time
import urllib.parse
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0"
)

_session = requests.Session()
_session.headers.update(
    {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
)


class TTLCache:
    """In-memory key→value cache with a monotonic-clock expiry."""

    def __init__(self, ttl: float, max_entries: int = 0):
        self.ttl = ttl
        self.max_entries = max_entries
        self._data: dict = {}

    def get(self, key):
        hit = self._data.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        return None

    def put(self, key, value) -> None:
        if self.max_entries and len(self._data) >= self.max_entries:
            # drop the stalest entries first
            for k in sorted(self._data, key=lambda k: self._data[k][0]):
                del self._data[k]
                if len(self._data) < self.max_entries // 2:
                    break
        self._data[key] = (time.monotonic() + self.ttl, value)


def request(url: str, headers: dict | None = None, data: bytes | None = None,
            params: dict | None = None, timeout: float = 20) -> requests.Response:
    """GET (or POST when `data` is given) with retries; 4xx fail fast
    except 429, which is retried after the server's Retry-After."""
    last_error = None
    for attempt in range(3):
        try:
            response = _session.request(
                "POST" if data is not None else "GET",
                url, headers=headers, data=data, params=params, timeout=timeout,
            )
            response.raise_for_status()
            return response
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else 0
            if 400 <= code < 500:
                if code == 429 and attempt < 2:
                    try:  # seconds; fall back if absent or an HTTP date
                        delay = float(exc.response.headers.get("Retry-After", ""))
                    except ValueError:
                        delay = 1.5 * (attempt + 1)
                    time.sleep(min(delay, 30))
                    continue
                raise RuntimeError(f"HTTP {code} for {url}") from None
            last_error = exc
        except requests.RequestException as exc:  # throttling / hiccup
            last_error = exc
        if attempt < 2:  # no point sleeping after the final attempt
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"could not fetch {url}: {last_error}")


def request_json(url: str, headers: dict | None = None, data: bytes | None = None,
                 params: dict | None = None, timeout: float = 20):
    """request() + JSON parsing (for plain APIs and OAuth tokens)."""
    payload = request(url, headers=headers, data=data, params=params,
                      timeout=timeout).json()
    return payload


get_json = request_json  # readable alias for GET-style API calls


def fetch_bytes(url: str, timeout: float = 120) -> bytes:
    """GET raw bytes (large static files need a longer timeout)."""
    return request(url, timeout=timeout).content


# Page cache for scraping (pages are big; keep it bounded).
_page_cache = TTLCache(ttl=900, max_entries=64)


def fetch(url: str) -> str:
    """GET a page and return its HTML, cached for 15 minutes."""
    cached = _page_cache.get(url)
    if cached is not None:
        return cached
    text = request(url).text
    _page_cache.put(url, text)
    return text


# OAuth (client credentials) --------------------------------------------------

_oauth_cache: dict[str, tuple[float, str]] = {}


def oauth_token(token_url: str, client_id: str, client_secret: str) -> str:
    """Client-credentials access token, cached until expiry. Callers check
    their own env vars first so error messages name the right variables."""
    hit = _oauth_cache.get(token_url)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    payload = request_json(
        token_url,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data=body,
    )
    token = payload["access_token"]
    _oauth_cache[token_url] = (
        time.monotonic() + min(payload.get("expires_in", 86400) - 60, 86400),
        token,
    )
    return token


# HTML utilities ---------------------------------------------------------------

# Tags that never hold article content.
_STRIP = [
    "script", "style", "noscript", "nav", "header", "footer", "aside",
    "form", "iframe", "svg", "button",
]


def text_from_html(html: str) -> tuple[str, str, list[tuple[str, str]]]:
    """Extract (title, readable main text, [(link text, href), ...])."""
    soup = BeautifulSoup(html, "html.parser")

    title = ""
    og_title = soup.find("meta", attrs={"property": "og:title"})
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()
    elif soup.title and soup.title.string:
        title = soup.title.string.strip()

    links = [
        (a.get_text(" ", strip=True), a["href"])
        for a in soup.find_all("a", href=True)
    ]

    for tag in soup.find_all(_STRIP):
        tag.decompose()
    root = (
        soup.find("main")
        or soup.find(attrs={"role": "main"})
        or soup.find("article")
        or soup.find(id="content")
        or soup.find(id="main")
        or soup.find("body")
        or soup
    )
    text = root.get_text("\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    out: list[str] = []
    for line in lines:  # collapse runs of blank lines, not all of them
        if line or (out and out[-1]):
            out.append(line)
    return title, "\n".join(out).strip(), links


# Link candidates worth skipping when scoring search results.
_JUNK_SUBSTRINGS = (
    "/login", "/register", "/signup", "/premium", "/forums", "/comment",
    "javascript:", "mailto:", ".css", ".js", ".png", ".jpg", ".svg",
)


def pick_link(
    links: list[tuple[str, str]],
    query: str,
    base_url: str,
    path_include: list[str] | None = None,
) -> tuple[str, str] | None:
    """Pick the best on-site link for a query from a search page's links.

    Scores 2 points per query term in the link text, 1 per term in the URL,
    +2 if the URL contains one of `path_include` (e.g. WoW guide sections on
    a multi-game site). Returns (link text, absolute URL) or None.
    """
    terms = [t for t in re.split(r"[\W_]+", query.lower()) if len(t) > 2]
    best: tuple[int, str, str] | None = None
    for text, href in links:
        url = urljoin(base_url, href).split("#", 1)[0]
        if not url.startswith(base_url + "/"):
            continue
        if any(junk in url.lower() for junk in _JUNK_SUBSTRINGS):
            continue
        score = 2 * sum(t in text.lower() for t in terms)
        score += sum(
            t in urllib.parse.unquote(url).lower().replace("-", " ")
            for t in terms
        )
        if score and path_include and any(p in url for p in path_include):
            score += 2
        if score and (
            best is None
            or score > best[0]
            # ties -> shorter URL (the canonical page, not a subpage)
            or (score == best[0] and len(url) < len(best[2]))
        ):
            best = (score, text, url)
    return (best[1], best[2]) if best else None
