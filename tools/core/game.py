"""Game knowledge tool — current WoW mechanics as of Midnight (12.x).

The model's training data is stale on retail mechanics; this doc is the
ground truth to reason from for economy/gearing advice. Key correction that
motivated it: warbands made cross-realm flipping free — NO realm transfer,
NO faction transfer, NO character move is ever needed to arbitrage between
realms.
"""

from tools import tool

KNOWLEDGE = """\
WoW game mechanics ground truth — Midnight (12.x) era
=====================================================

Warbands (introduced in The War Within, 10.x; core system in Midnight)
- A warband is your entire account: all characters, all realms, both factions.
- The Warband Bank is account-wide: gold and items deposited on any character
  are withdrawable by ANY character on the account, on ANY realm, either
  faction, instantly and free.
- Therefore cross-realm flipping requires NO realm transfer, NO faction
  transfer, and NO gold-sink besides the AH cut: park gold in the warband
  bank, make a level-1 alt on the cheap realm, withdraw gold, buy the item,
  deposit the item, log into a seller character on the expensive realm,
  withdraw and post it. Total cost = 5% AH cut on the sale side only.
- BoE gear, pets, mounts, and most tradeables move through the warband bank
  freely. Warband-bound items (most raid/vendor gear) are account-locked but
  NOT sellable — irrelevant to flipping.
- Faction no longer matters for trading: cross-faction grouping, guilds, and
  mail exist since TWW. Faction split only matters as a DEMOGRAPHIC signal
  (which faction's crafters dump supply, which hubs have buyers).
- Warbands also made: transmog, most reputations, flight paths, and curio/
  delves unlocks account-wide.

Auction house structure (still true in Midnight)
- Commodities (stackables: reagents, consumables, gems) = ONE region-wide
  market; all realms share one price. There is no commodity arbitrage
  between realms, only timing plays.
- Non-commodities (gear, pets, mounts, most equipment) = still per
  connected-realm-group. THIS is where cross-realm flipping lives.
- Connected realms share one AH; check realm_metadata for group membership.
- AH cut is 5% on successful sale (deposit refunded). Failed auctions lose
  the deposit.
- Buying remotely: you can browse and buy from any realm's non-commodity AH
  only with a character ON that realm (alts are free and instant).

Economy mechanics
- WoW Token: sellable for gold region-wide; the gold<->USD yardstick.
- Realm/faction transfer services (~$25/$30) still exist but are NEVER
  required for flipping — an alt + warband bank does the same job free.
- Crafting orders and enchantments follow the warband rules above.

Gearing / sims context (Midnight)
- Current simc branch tracks Midnight (12.x); profilesets with json_output
  give the SEs needed for significance testing.
- Item level budgets scale exponentially with ilvl; secondary stat ratings
  have diminishing returns past 30% (pre-DR conversion matters when
  comparing gear).
"""


@tool
def game_knowledge() -> str:
    """Ground-truth reference for current WoW (Midnight, 12.x) game mechanics — warbands, cross-realm trading, auction house structure, and economy rules. READ THIS before giving any gold-making, flipping, realm, faction, or trading advice: mechanics have changed since older training data (e.g. cross-realm flipping is now free via the warband bank — no realm/faction transfers needed)."""
    return KNOWLEDGE
