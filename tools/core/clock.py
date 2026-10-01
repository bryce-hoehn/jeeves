"""Clock tool — current time plus WoW reset/calendar context.

Timestamps from APIs (e.g. Undermine's `2026-10-01T03:22:58Z`) need "how stale
is this?" and "when does the next reset/restock cycle land?" answers. Use this
tool instead of guessing, and pair it with the `python` tool for date math.
"""

import datetime as dt

from tools import tool

# Weekly resets: (weekday, hour) in UTC — US Tuesday 15:00, EU Wednesday 04:00.
RESETS_UTC = {"us": (1, 15), "eu": (2, 4)}


@tool
def now() -> str:
    """Current UTC time, unix epoch, day of week, and the next US/EU weekly reset times (the auction-house deposit cycle and lockout reset). Use whenever a timestamp needs interpreting ('3 hours ago', 'stale snapshot') or a reset/cycle deadline matters. All times UTC."""
    now_utc = dt.datetime.now(dt.timezone.utc)
    lines = [
        f"utc_now: {now_utc.strftime('%Y-%m-%d %H:%M:%S')} ({now_utc.strftime('%A')})",
        f"epoch: {int(now_utc.timestamp())}",
    ]
    for region in ("us", "eu"):
        # Walk forward to the reset weekday at the reset hour.
        weekday, hour = RESETS_UTC[region]
        days_ahead = (weekday - now_utc.weekday()) % 7
        reset = now_utc.replace(hour=hour, minute=0, second=0, microsecond=0) + dt.timedelta(days=days_ahead)
        if reset <= now_utc:
            reset += dt.timedelta(days=7)
        delta = reset - now_utc
        hours = delta.total_seconds() / 3600
        lines.append(
            f"{region}_reset: {reset.strftime('%Y-%m-%d %H:%M UTC')} "
            f"(in {hours:.0f}h)"
        )
    return "\n".join(lines)
