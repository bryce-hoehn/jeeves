import os

import discord
from dotenv import load_dotenv

import agent

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True  # also enable this in the Discord Developer Portal

bot = discord.Bot(intents=intents)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} ({bot.user.id})")


MAX_ATTACHMENT_BYTES = 200_000


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
            agent.conversations.pop(channel.id, None)
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

    async with target.typing():
        reply = await agent.run_agent(target, text)

    # Discord caps messages at 2000 characters.
    for i in range(0, len(reply), 2000):
        await target.send(reply[i : i + 2000])

bot.run(os.environ["DISCORD_TOKEN"])
