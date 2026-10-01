"""Shared helpers for Blizzard's game-data API."""

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

_token_cache: tuple[float, str] | None = None


def http_json(url: str, headers: dict | None = None, data: bytes | None = None):
    """GET/POST a URL and return parsed JSON, raising RuntimeError on failure."""
    req = urllib.request.Request(url, headers=headers or {}, data=data)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:200]
        raise RuntimeError(f"API error {exc.code} for {url}: {detail}") from None
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError(f"could not reach {url}: {exc}") from None


def oauth_token() -> str:
    """Client-credentials access token (free client from develop.battle.net;
    set BLIZZARD_CLIENT_ID / BLIZZARD_CLIENT_SECRET). Cached until expiry."""
    global _token_cache
    client_id = os.getenv("BLIZZARD_CLIENT_ID")
    client_secret = os.getenv("BLIZZARD_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError(
            "BLIZZARD_CLIENT_ID / BLIZZARD_CLIENT_SECRET are not set — "
            "create free API credentials at https://develop.battle.net"
        )
    if _token_cache and _token_cache[0] > time.monotonic():
        return _token_cache[1]
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    payload = http_json(
        "https://oauth.battle.net/oauth/token",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data=body,
    )
    token = payload["access_token"]
    _token_cache = (
        time.monotonic() + min(payload.get("expires_in", 86400) - 60, 86400),
        token,
    )
    return token


def auth_headers(region: str) -> dict:
    """Authorization header for the dynamic-{region} game-data namespace."""
    return {"Authorization": f"Bearer {oauth_token()}"}
