"""AI chat agent with tools.

Built-in tool definitions live in the tools/ package; every @tool-registered
function there is offered to the model, plus any tools from external MCP
servers configured in mcp.json. When the model asks to call a tool we run it
and send the result back. Conversations are tracked per thread (or DM channel)
as an in-memory transcript, sent in full each turn — server-side response
storage (previous_response_id) is unreliable behind proxies.
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

# thread/DM channel id -> transcript items, so each conversation keeps context
conversations: dict[int, list] = {}
MAX_HISTORY_ITEMS = 60


async def run_agent(channel, user_text: str) -> str:
    """Run one agent turn for a channel and return the bot's reply."""
    channel_id = channel.id
    await mcp_servers.start()  # no-op without mcp.json
    schemas = [t["schema"] for t in TOOLS.values()] + mcp_servers.schemas

    items = conversations.setdefault(channel_id, [])
    items.append({"role": "user", "content": user_text})
    response = await client.responses.create(
        model=MODEL,
        instructions=SYSTEM_PROMPT,
        input=items,
        tools=schemas,
    )

    # Run any tools the model asked for, then keep going until it replies with
    # text and asks for no further tool calls (models often emit a short
    # "Let me look that up:" message together with the tool call).
    reply = ""
    for _ in range(10):
        calls = [i for i in response.output if i.type == "function_call"]
        if response.output_text:
            reply += response.output_text
            items.append({"role": "assistant", "content": response.output_text})
        if not calls:
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
            # Echo the call back so the API can pair it with the output.
            items.append(
                {
                    "type": "function_call",
                    "call_id": item.call_id,
                    "name": item.name,
                    "arguments": item.arguments,
                }
            )
            outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": str(result),
                }
            )

        items.extend(outputs)
        response = await client.responses.create(
            model=MODEL,
            instructions=SYSTEM_PROMPT,
            input=items,
            tools=schemas,
        )

    del items[:-MAX_HISTORY_ITEMS]
    # Never start the transcript on an orphaned tool call/output pair.
    while items and items[0].get("type") in ("function_call", "function_call_output"):
        items.pop(0)
    return reply or response.output_text
