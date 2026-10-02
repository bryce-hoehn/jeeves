"""One-shot smoke test: call every registered tool with real arguments.

Usage: uv run python test_all_tools.py
Loads .env first so Blizzard/Undermine credentials are picked up.
"""

import asyncio
import inspect
import os
import shutil

from dotenv import load_dotenv

load_dotenv()

from tools import TOOLS  # noqa: E402
from tools.reference import wowhead as wh  # noqa: E402
from tools.sim import raidbots as rb  # noqa: E402


def head(text: str, n: int = 220) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n] + "…"


def resolve_item(query: str) -> int:
    _kind, item_id, _name = wh._resolve(query, "item")
    return int(item_id)


def main() -> None:
    # Look up real item ids up front so market tests use live data.
    ore = resolve_item("osmenite ore") or 171828
    print(f"[setup] ore item id: {ore}")

    simc_ok = shutil.which("simc") is not None
    if not simc_ok:
        print("[setup] simc CLI not found — sim tools will report unavailable")

    cases: list[tuple[str, dict]] = [
        # core
        ("now", {}),
        ("python", {"code": "print(sum(range(10)))"}),
        ("kb_list", {}),
        ("kb_search", {"query": "warband"}),
        ("simc_check", {}),
        # reference
        ("wowhead_tooltip", {"query": "frostweave cloth", "kind": "item", "channel": None}),
        ("wowhead_page", {"query_or_url": "frostweave cloth"}),
        ("wow_wiki", {"query_or_url": "Illidan Stormrage"}),
        ("wow_gg", {"query_or_url": "arms warrior guide"}),
        ("icy_veins", {"query_or_url": "fire mage guide"}),
        ("wow_news", {"source": "blizzard", "limit": 5}),
        ("wow_news", {"source": "mmo-champion", "limit": 5}),
        ("wow_events", {"days": 21}),
        ("wow_events", {"query": "darkmoon", "days": 120}),
        # market — Blizzard API (now with credentials)
        ("wow_token_price", {}),
        ("realm_metadata", {"realm": "Kel'Thuzad", "region": "us"}),
        ("realm_auctions", {"realm": "Kel'Thuzad", "item_id": ore, "region": "us"}),
        # market — Undermine Exchange (now with API key)
        ("item_summary", {"item_id": ore}),
        ("commodity_now", {"item_id": ore}),
        ("commodity_price_history", {"item_id": ore, "days": 7}),
        ("commodity_hourly_history", {"item_id": ore, "snapshots": 12}),
        ("item_realm_prices", {"item_id": ore, "limit": 5}),
        ("item_price_history", {"item_id": ore, "days": 7}),
        ("realm_item_now", {"realm": "Kel'Thuzad", "item_id": ore}),
        ("realm_item_history", {"realm": "Kel'Thuzad", "item_id": ore, "days": 7}),
        # progression
        ("raider_io", {"name": "Asmongold", "realm": "Kel'Thuzad", "region": "us"}),
        ("raider_io_guild", {"guild": "Liquid", "realm": "Illidan", "region": "us"}),
        ("character_mythic_plus", {"name": "Asmongold", "realm": "Kel'Thuzad", "region": "us"}),
        ("character_raid_progress", {"name": "Asmongold", "realm": "Kel'Thuzad", "region": "us"}),
        ("character_pvp", {"name": "Asmongold", "realm": "Kel'Thuzad", "bracket": "2v2", "region": "us"}),
        ("pvp_leaderboard", {"bracket": "2v2", "region": "us", "limit": 5}),
        ("guild_roster", {"guild": "Liquid", "realm": "Illidan", "region": "us"}),
        ("warcraft_logs", {"name": "Asmongold", "realm": "Kel'Thuzad", "region": "us"}),
        # sim — raidbots static data
        ("raidbots_metadata", {}),
        ("raidbots_item_search", {"query": "frostweave", "limit": 5}),
        ("raidbots_enchant_search", {"query": "versatility", "limit": 5}),
        ("raidbots_talents", {"class_name": "Mage", "spec_name": "Fire"}),
        ("raidbots_consumables", {"kind": "flasks"}),
        ("raidbots_instances", {"query": ""}),
        ("raidbots_item_sets", {"query": ""}),
    ]

    # raidbots_get_file needs a real file name from metadata.
    try:
        files = rb._metadata("live").get("files", [])
        if "seasons.json" in files:
            cases.append(("raidbots_get_file", {"name": "seasons.json"}))
    except Exception as exc:  # noqa: BLE001
        print(f"[setup] raidbots metadata unavailable: {exc}")

    if simc_ok:
        cases += [
            (
                "simc_simulate",
                {
                    "profile": "warrior simc=" + str(1500 + int(os.getpid() % 100)),
                    "iterations": 100,
                    "threads": 4,
                    "timeout": 120,
                },
            ),
            (
                "simc_armory_simulate",
                {
                    "region": "us",
                    "realm": "kel-thuzad",
                    "character": "asmongold",
                    "iterations": 100,
                    "threads": 4,
                    "timeout": 240,
                },
            ),
        ]

    passed = failed = 0
    for name, kwargs in cases:
        entry = TOOLS.get(name)
        if entry is None:
            print(f"SKIP {name}: not registered")
            failed += 1
            continue
        fn = entry["fn"]
        try:
            if inspect.iscoroutinefunction(fn):
                result = asyncio.run(fn(**kwargs))
            else:
                result = fn(**kwargs)
            print(f"PASS {name}\n     {head(result)}")
            passed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed, {len(TOOLS)} tools registered")


if __name__ == "__main__":
    main()
