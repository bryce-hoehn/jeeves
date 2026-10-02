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
