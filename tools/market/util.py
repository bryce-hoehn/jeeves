"""Shared formatting helpers for market tools."""


def gold(copper: int) -> str:
    """Format an amount of copper as gold/silver/copper."""
    gold, rest = divmod(int(copper), 10000)
    silver, cop = divmod(rest, 100)
    return f"{gold:,}g {silver:02d}s {cop:02d}c"
