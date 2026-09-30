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


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    # Only respond to DMs and messages that mention the bot.
    if message.guild and not bot.user.mentioned_in(message):
        return

    user_id = bot.user.id
    text = (
        message.content.replace(f"<@{user_id}>", "").replace(f"<@!{user_id}>", "").strip()
    )
    if not text:
        return

    if text == "!reset":
        agent.conversations.pop(message.channel.id, None)
        await message.reply("Conversation reset.")
        return

    async with message.channel.typing():
        reply = await agent.run_agent(message.channel, text)

    # Discord caps messages at 2000 characters.
    for i in range(0, len(reply), 2000):
        await message.channel.send(reply[i : i + 2000])


if __name__ == "__main__":
    bot.run(os.getenv("DISCORD_TOKEN"))
