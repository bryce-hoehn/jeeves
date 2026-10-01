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


def _strip_mention(text: str) -> str:
    return (
        text.replace(f"<@{bot.user.id}>", "")
        .replace(f"<@!{bot.user.id}>", "")
        .strip()
    )


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    channel = message.channel

    # A message inside one of the bot's threads continues that thread's
    # conversation. Threads the bot didn't create are left alone.
    if isinstance(channel, discord.Thread):
        if channel.owner_id != bot.user.id:
            return
        text = _strip_mention(message.content)
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

if __name__ = "__main__":
    bot.run(os.environ["DISCORD_TOKEN"])
