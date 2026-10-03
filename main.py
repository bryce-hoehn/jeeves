import logging
import os

import discord
from dotenv import load_dotenv

import agent
from tools.util import split_message

load_dotenv()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)

log = logging.getLogger("jeeves")

intents = discord.Intents.default()
intents.message_content = True  # also enable this in the Discord Developer Portal
intents.members = True  # likewise — needed for user lookup by name

bot = discord.Bot(intents=intents)


@bot.event
async def on_ready():
    log.info("logged in as %s (%s)", bot.user.name, bot.user.id)


# Attachment text goes straight into the model transcript, so keep the cap
# small — oversized files are skipped rather than eating the context window.
MAX_ATTACHMENT_BYTES = 20_000
# How many messages of history to replay when rebuilding a conversation.
BACKFILL_MESSAGE_LIMIT = 200


def _strip_mention(text: str) -> str:
    return (
        text.replace(f"<@{bot.user.id}>", "")
        .replace(f"<@!{bot.user.id}>", "")
        .strip()
    )


async def _attachment_text(message: discord.Message) -> str:
    """Fetch text-file attachments (e.g. simbot output past Discord's limit)."""
    parts = []
    for att in message.attachments:
        is_text = att.filename.endswith((".txt", ".json", ".csv", ".lua", ".md")) or (
            att.content_type or "").startswith("text/")
        if not is_text:
            continue
        if att.size > MAX_ATTACHMENT_BYTES:
            parts.append(f"[skipped {att.filename}: too large]")
            continue
        data = await att.read()
        parts.append(f"--- {att.filename} ---\n{data.decode('utf-8', errors='replace')}")
    return "\n".join(parts)


async def _backfill_conversation(channel, skip_message_id: int | None) -> None:
    """Rebuild a conversation transcript from Discord history.

    Used when a message arrives in a thread/DM the bot has no in-memory
    conversation for (i.e. after a restart): user messages become user
    items, the bot's own text messages become assistant items (consecutive
    chunks of one reply are joined). Embed-only messages, other bots, and
    system notices are skipped; a historical !reset clears what came
    before it. The message that triggered this run is skipped — run_agent
    adds it fresh.
    """
    items: list[dict] = []
    skip_bot_reply = False
    async for msg in channel.history(
        limit=BACKFILL_MESSAGE_LIMIT, oldest_first=True
    ):
        if msg.id == skip_message_id:
            continue
        if msg.author.id == bot.user.id:
            if skip_bot_reply:
                skip_bot_reply = False  # its "Conversation reset." notice
            elif msg.content:
                if items and items[-1]["role"] == "assistant":
                    items[-1]["content"] += "\n" + msg.content
                else:
                    items.append({"role": "assistant", "content": msg.content})
        elif not msg.author.bot and msg.content:
            text = _strip_mention(msg.content)
            if text == "!reset":
                items.clear()
                skip_bot_reply = True
            elif text:
                items.append({"role": "user", "content": text})
    if len(items) > agent.MAX_HISTORY_ITEMS:
        del items[:-agent.MAX_HISTORY_ITEMS]
    agent.conversations[channel.id] = items
    log.info("backfilled conversation %s: %d item(s)", channel.id, len(items))


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    channel = message.channel
    attachments = await _attachment_text(message)

    # A message inside one of the bot's threads continues that thread's
    # conversation. Threads the bot didn't create are left alone.
    if isinstance(channel, discord.Thread):
        if channel.owner_id != bot.user.id:
            return
        text = _strip_mention(message.content)
        if attachments:
            text = f"{text}\n{attachments}".strip()
        if text == "!reset":
            # Set an empty transcript rather than dropping the key, so the
            # history backfill below doesn't restore the old conversation.
            agent.conversations[channel.id] = []
            await message.reply("Conversation reset.")
            return
        if not text:
            return
        target = channel

    # Otherwise a DM or a mention starts a brand-new conversation: in a
    # guild that becomes a public thread on the triggering message.
    else:
        if message.guild and not bot.user.mentioned_in(message):
            return
        text = _strip_mention(message.content)
        if attachments:
            text = f"{text}\n{attachments}".strip()
        if not text:
            return
        if message.guild:
            name = text.replace("\n", " ")[:100] or "conversation"
            try:
                target = await message.create_thread(name=name)
            except discord.HTTPException as exc:
                await message.reply(f"could not create a thread: {exc}")
                return
        else:
            target = channel  # DMs keep chatting in the DM channel

    try:
        if target.id not in agent.conversations:
            # First contact after a restart: rebuild the transcript from
            # the thread's/DM's history so context survives restarts.
            await _backfill_conversation(target, message.id)
        async with target.typing():
            reply = await agent.run_agent(target, text)
    except Exception:
        log.exception("agent turn failed in channel %s", target.id)
        await target.send("Something went wrong handling that — see the logs.")
        return

    # Discord caps messages at 2000 characters; split on markdown
    # boundaries so formatting survives the chunking.
    for chunk in split_message(reply or "(no reply)"):
        await target.send(chunk)

bot.run(os.environ["DISCORD_TOKEN"])
