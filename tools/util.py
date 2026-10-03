"""Tiny shared utilities used by several tool modules."""


def slug(value: str) -> str:
    """'Kel Thuzad' -> 'kel-thuzad' (guild/name slugs)."""
    return value.strip().lower().replace(" ", "-")


def realm_slug(value: str) -> str:
    """'Kel'Thuzad' -> 'kelthuzad' — Blizzard-style realm slug: lowercased,
    spaces become hyphens, apostrophes are removed. This is the format the
    Blizzard API, Raider.IO, Undermine Exchange, and Warcraft Logs all expect
    in URLs."""
    return value.strip().lower().replace("'", "").replace(" ", "-")


def clamp(value, low, high):
    """Keep `value` inside [low, high]."""
    return max(low, min(high, value))


def gold(copper: int) -> str:
    """Format an amount of copper as gold/silver/copper."""
    gold, rest = divmod(int(copper), 10000)
    silver, cop = divmod(rest, 100)
    return f"{gold:,}g {silver:02d}s {cop:02d}c"


def split_message(text: str, limit: int = 2000) -> list[str]:
    """Split text into chunks of at most `limit` chars (Discord's cap)
    without slicing through markdown: prefer paragraph breaks, then line
    breaks, then spaces. A ``` code fence left open at a chunk boundary is
    closed and reopened so both halves still render."""
    if len(text) <= limit:
        return [text]

    chunks = []
    remaining = text
    while remaining:
        cut = _best_cut(remaining, limit)
        chunk = remaining[:cut].rstrip("\n")
        remaining = remaining[cut:].lstrip("\n")
        if not chunk:  # pathological whitespace run; force a hard cut
            chunk, remaining = remaining[:limit], remaining[limit:]
        if chunk.count("```") % 2:  # chunk ends inside a code block
            chunk += "\n```"
            remaining = f"```\n{remaining}"
        chunks.append(chunk)
    return chunks


def _best_cut(text: str, limit: int) -> int:
    """Largest clean break point within text[:limit], else a hard cut."""
    for sep in ("\n\n", "\n", " "):
        i = text.rfind(sep, 0, limit)
        # Only take the break if it's reasonably far into the chunk,
        # otherwise chunks get uselessly small.
        if i >= limit // 2:
            return min(i + len(sep), limit)
    return limit
