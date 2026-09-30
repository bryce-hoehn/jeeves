"""AI chat agent with tools.

Built-in tool definitions live in the tools/ package; every @tool-registered
function there is offered to the model, plus any tools from external MCP
servers configured in mcp.json. When the model asks to call a tool we run it
and send the result back. Conversations are tracked per channel via
previous_response_id.
"""

import inspect
import json
import os

from dotenv import load_dotenv
from openai import AsyncOpenAI

import mcp_servers
from tools import TOOLS

load_dotenv()

client = AsyncOpenAI(
    api_key=os.getenv("OPENAI_API_KEY"), base_url=os.getenv("OPENAI_BASE_URL")
)
MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")
SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", "You are a helpful assistant.")
if "wowhead_tooltip" in TOOLS:
    SYSTEM_PROMPT += (
        " When the user asks about a specific WoW item or spell, prefer the"
        " wowhead_tooltip tool — it posts a Wowhead tooltip embed into the"
        " channel instead of pasting raw stats."
    )

# channel id -> last response id, so each channel keeps its own conversation
conversations: dict[int, str] = {}


async def run_agent(channel, user_text: str) -> str:
    """Run one agent turn for a channel and return the bot's reply."""
    channel_id = channel.id
    await mcp_servers.start()  # no-op without mcp.json
    schemas = [t["schema"] for t in TOOLS.values()] + mcp_servers.schemas

    response = await client.responses.create(
        model=MODEL,
        instructions=SYSTEM_PROMPT,
        input=user_text,
        previous_response_id=conversations.get(channel_id),
        tools=schemas,
    )

    # Run any tools the model asked for, then keep going until it replies with text.
    for _ in range(10):
        if response.output_text:
            break

        outputs = []
        for item in response.output:
            if item.type != "function_call":
                continue
            args = json.loads(item.arguments)
            print(f"tool call: {item.name}({args})")
            try:
                if item.name in TOOLS:
                    spec = TOOLS[item.name]
                    if spec["takes_channel"]:
                        args["channel"] = channel  # e.g. to post embeds
                    result = spec["fn"](**args)
                    if inspect.iscoroutine(result):
                        result = await result
                else:
                    result = await mcp_servers.call(item.name, args)
            except Exception as exc:  # let the model see and report the error
                result = f"Error: {exc}"
            outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": str(result),
                }
            )

        response = await client.responses.create(
            model=MODEL,
            input=outputs,
            previous_response_id=response.id,
            tools=schemas,
        )

    conversations[channel_id] = response.id
    return response.output_text
