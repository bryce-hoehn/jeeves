"""Discord user & channel tools — look up users, DM them, and read chat.

Read/messaging only: the agent can view users, send them DMs, list
channels, and read channel history, but never edits other people's
messages and never creates, edits, or deletes channels. Together with
discord_events.py these cover the agent's Discord-side abilities.
"""

import re

import discord

from tools import tool
from tools.util import clamp, split_message

# '<@123>' / '<@!123>' user mention, '#general' channel mention
_USER_MENTION = re.compile(r"<@!?(\d+)>")
_CHANNEL_MENTION = re.compile(r"<#(\d+)>")

# Reading a full conversation is useful; reading thousands of messages
# is a context-window fire. The model asks for what it needs.
MAX_READ_MESSAGES = 200
MAX_HISTORY_CHARS = 20_000


def _guild(channel):
    return getattr(channel, "guild", None)


async def _resolve_member(channel, ref: str) -> discord.Member | discord.User | None:
    """Resolve '123456', '<@123456>', or a username/display name to a user.

    Prefers an explicit id/mention (exact REST fetch); falls back to a
    case-insensitive name search over the guild member cache, then to a
    gateway member query (covers members not in the cache).
    """
    guild = _guild(channel)
    ref = ref.strip()
    m = _USER_MENTION.fullmatch(ref)
    user_id = int(m.group(1)) if m else (int(ref) if ref.isdigit() else None)

    if user_id is not None:
        if guild:
            try:
                return await guild.fetch_member(user_id)
            except discord.HTTPException as exc:
                if exc.status == 404:
                    return None
                raise
        return channel._state.get_user(user_id)

    if not guild:
        partner = getattr(channel, "recipient", None)
        names = (partner.name, partner.display_name) if partner else ()
        return partner if ref.lower() in names else None

    ref_l = ref.lower()
    for member in guild.members:
        if ref_l in (member.name.lower(), member.display_name.lower()):
            return member
    try:  # not in the cache — ask the gateway
        found = await guild.query_members(query=ref, limit=1)
    except discord.HTTPException:
        return None
    return found[0] if found else None


def _user_summary(user) -> str:
    lines = [f"{user.display_name} (@{user.name}, id {user.id})"]
    if getattr(user, "guild", None):
        lines.append(f"joined {user.joined_at:%Y-%m-%d}" if user.joined_at else "")
        roles = [
            r.name
            for r in reversed(user.roles)
            if r.name != "@everyone"
        ]
        if roles:
            lines.append(f"roles: {', '.join(roles)}")
    lines.append(f"account created {user.created_at:%Y-%m-%d}")
    return "\n".join(x for x in lines if x)


@tool
async def discord_user_lookup(channel, user: str) -> str:
    """Look up a Discord user on this server: display name, username, id, roles, join date, and account creation date. `user` can be a user id, a <@mention>, a username, or a server nickname (case-insensitive)."""
    if not _guild(channel):
        return "User lookup only works in servers, not DMs."
    member = await _resolve_member(channel, user)
    if member is None:
        return f"No user matching '{user}' on this server."
    return _user_summary(member)


@tool
async def discord_dm_send(channel, user: str, text: str) -> str:
    """Send a direct message (DM) to a Discord user. `user` can be a user id, a <@mention>, a username, or a server nickname (case-insensitive). The user must share a server with the bot and have DMs from server members enabled. Use this for private/individual outreach — never for spam."""
    member = await _resolve_member(channel, user)
    if member is None:
        return f"No user matching '{user}'."
    if member.bot:
        return "That user is a bot; refusing to DM it."
    try:
        dm = await member.create_dm()
        for chunk in split_message(text):
            await dm.send(chunk)
    except discord.HTTPException as exc:
        return f"Could not DM {member.display_name}: {exc}"
    return f"DM sent to {member.display_name} (@{member.name})."


def _resolve_channel(channel, ref: str):
    """Resolve a channel reference: '#name', 'name', id, or <#mention>.

    An empty ref means the channel the conversation is happening in.
    """
    guild = _guild(channel)
    if guild is None:
        return channel
    ref = ref.strip()
    if not ref or ref == "here":
        return channel
    m = _CHANNEL_MENTION.fullmatch(ref)
    if m:
        return guild.get_channel_or_thread(int(m.group(1)))
    if ref.isdigit():
        return guild.get_channel_or_thread(int(ref))
    ref = ref.removeprefix("#")
    ref_l = ref.lower()
    for ch in guild.text_channels + guild.forums:
        if ch.name.lower() == ref_l:
            return ch
    return None


@tool
async def discord_channels_list(channel) -> str:
    """List this Discord server's text channels and their ids (grouped by category), so you can pick a channel to read with discord_channel_read."""
    guild = _guild(channel)
    if guild is None:
        return "This conversation is a DM — there is no server channel list."
    lines = []
    for category in guild.categories:
        chans = [c for c in category.text_channels]
        if chans:
            lines.append(f"# {category.name or '(no name)'}")
            lines.extend(f"  #{c.name} (id {c.id})" for c in chans)
    loose = [c for c in guild.text_channels if c.category is None]
    if loose:
        lines.append("# (no category)")
        lines.extend(f"  #{c.name} (id {c.id})" for c in loose)
    if not lines:
        return "No text channels visible on this server."
    return "\n".join(lines)


@tool
async def discord_channel_read(
    channel, channel_ref: str = "", limit: int = 50
) -> str:
    """Read a Discord channel's recent chat history (newest last). `channel_ref` is a channel name like 'general', an id, or empty for the channel this conversation is happening in. `limit` is how many messages to read (default 50, max 200). Returns timestamped messages with author names. Read-only — you cannot edit or delete other people's messages."""
    target = _resolve_channel(channel, channel_ref)
    if target is None:
        return f"No channel matching '{channel_ref}'. Use discord_channels_list to see what exists."
    if not isinstance(
        target, (discord.TextChannel, discord.Thread, discord.DMChannel)
    ):
        return f"#{getattr(target, 'name', target.id)} is not a readable text channel."
    perms = target.permissions_for(target.guild.me) if _guild(target) else None
    if perms is not None and not perms.read_message_history:
        return f"I don't have permission to read #{target.name}'s history."

    limit = clamp(int(limit), 1, MAX_READ_MESSAGES)
    lines = []
    total = 0
    async for msg in target.history(limit=limit, oldest_first=True):
        stamp = msg.created_at.strftime("%Y-%m-%d %H:%M UTC")
        author = f"{msg.author.display_name} (@{msg.author.name})"
        body = msg.content or "(no text)"
        if msg.attachments:
            body += " [" + ", ".join(a.filename for a in msg.attachments) + "]"
        if msg.edited_at:
            body += " (edited)"
        line = f"[{stamp}] {author}: {body}"
        total += len(line)
        if total > MAX_HISTORY_CHARS:
            lines.append("… (history truncated to protect the context window)")
            break
        lines.append(line)
    header = f"#{target.name}" if getattr(target, "name", None) else "DM"
    if not lines:
        return f"{header} has no recent messages."
    return f"Last {len(lines)} message(s) in {header}:\n" + "\n".join(lines)
