"""Shared helpers for Blizzard's game-data API."""

import os

from tools import web

OAUTH_URL = "https://oauth.battle.net/oauth/token"


def http_json(url: str, headers: dict | None = None, data: bytes | None = None):
    """GET/POST a Blizzard API URL and return parsed JSON."""
    return web.request_json(url, headers=headers, data=data)


def oauth_token() -> str:
    """Client-credentials access token (free client from develop.battle.net;
    set BLIZZARD_CLIENT_ID / BLIZZARD_CLIENT_SECRET). Cached until expiry."""
    client_id = os.getenv("BLIZZARD_CLIENT_ID")
    client_secret = os.getenv("BLIZZARD_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError(
            "BLIZZARD_CLIENT_ID / BLIZZARD_CLIENT_SECRET are not set — "
            "create free API credentials at https://develop.battle.net"
        )
    return web.oauth_token(OAUTH_URL, client_id, client_secret)


def auth_headers(region: str) -> dict:
    """Authorization header for game-data/profile API calls."""
    return {"Authorization": f"Bearer {oauth_token()}"}
