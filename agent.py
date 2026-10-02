"""AI chat agent with tools.

Built-in tool definitions live in the tools/ package; every @tool-registered
function there is offered to the model, plus any tools from external MCP
servers configured in mcp.json. When the model asks to call a tool we run it
and send the result back. Tool calls requested in the same round execute
concurrently (asyncio.gather), and synchronous tool functions are offloaded
to worker threads (asyncio.to_thread) so HTTP/subprocess work never blocks
the event loop. The `subagent` tool spawns a nested research agent with a
fresh transcript — several subagents launched in one round gather data from
multiple sources in parallel (subagents cannot spawn further subagents).

Conversations are tracked per thread (or DM channel) as an in-memory
transcript, sent in full each turn — server-side response storage
(previous_response_id) is unreliable behind proxies.
"""

import asyncio
import inspect
import json
import os

from dotenv import load_dotenv
from openai import AsyncOpenAI

import mcp_servers
from tools import TOOLS, tool

load_dotenv()

client = AsyncOpenAI(
    api_key=os.getenv("OPENAI_API_KEY"), base_url=os.getenv("OPENAI_BASE_URL")
)
MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")

DEFAULT_SYSTEM_PROMPT = """\
You are jeeves, a World of Warcraft research assistant.

Operating rules:

1. Assume your training data on World of Warcraft is at least one expansion
   out of date. Item stats, drop rates, mechanics, class tuning, prices,
   realm connections, and release dates may all have changed. Verify any
   factual claim about the current game with your tools before stating it;
   if you cannot verify something, say so instead of guessing.
2. Prefer your built-in tools over external MCP servers. MCP servers are a
   last resort only, when no built-in tool can answer the question.
3. Always cite where your information comes from — name the tool, API, or
   website each claim came from (e.g. "per Raider.IO", "from Wowhead", "per
   the Blizzard API"). If a claim is from your own (stale) training data
   and unverified, say that explicitly.
4. Never do mental math. ALL arithmetic, currency conversions, percentage
   and statistics work must go through the python tool — no exceptions,
   even for seemingly trivial calculations.
5. Unless the user asks otherwise, be direct and to the point. Write like a
   Wikipedia article: factual, structured, no filler, no quirkiness, and no
   pretending to be a person. Skip pleasantries and rhetorical questions.
6. When a task needs data from several independent sources, batch the tool
   calls in one turn — they run in parallel. For bigger multi-step research
   jobs, spawn subagents (one per source/topic); they also run in parallel.

You have a persistent markdown knowledge base (kb_list, kb_read, kb_write,
kb_append, kb_search). Check it for relevant notes before starting a task.

The knowledge base is a long-term library of universal verified truths —
NOT a notebook for this conversation. Write a note only when the content
is all of: (a) expected to stay true for months, (b) verified with your
tools in this conversation (never from training data alone), and (c)
useful to a future conversation that isn't about this one. The only
acceptable notes:

- Stable, verified game knowledge: broad mechanics (e.g. warbands),
  dungeon/boss mechanics, lore, expansion and patch overviews.
- "Where to find it" notes mapping a topic to the tool/API/site that
  answers it (e.g. "region commodity prices → commodity_now, The
  Undermine Exchange").
- Long-term market trends: timestamped data points from verified tool
  output, appended over time.

Never write plans, to-do lists, answers to one-off questions, session
summaries, user preferences, character-specific data, or anything you
could not verify. When in doubt, don't write — an empty knowledge base
is better than a polluted one."""

SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT)
if "wowhead_tooltip" in TOOLS:
    SYSTEM_PROMPT += (
        " When the user asks about a specific WoW item or spell, prefer the"
        " wowhead_tooltip tool — it posts a Wowhead tooltip embed into the"
        " channel instead of pasting raw stats."
    )

SUBAGENT_PROMPT = """\
You are a jeeves research subagent. Your only job is to carry out the task
you were given and report back to the calling agent.

- Use your tools to gather the requested information; verify facts, never
  guess from training data. Cite the tool/API/website each claim came from.
- Batch independent tool calls in one turn — they run in parallel.
- You cannot spawn further subagents.
- When done, reply with a concise, factual report. Your reply goes to the
  calling agent, not to the user — no pleasantries, no filler.
"""

# thread/DM channel id -> transcript items, so each conversation keeps context
conversations: dict[int, list] = {}
MAX_HISTORY_ITEMS = 60
# Max tool-call rounds per turn. Generous — each round can batch several calls,
# and exhausting it just forces a text-only wrap-up rather than an error.
MAX_TOOL_ROUNDS = 40
# Subagents get a smaller budget: they gather, they don't converse.
SUBAGENT_TOOL_ROUNDS = 12


def _schemas(include_subagents: bool) -> list[dict]:
    """Tool schemas offered to the model: built-ins + MCP servers.

    Subagents never see the subagent tool, so recursion is impossible.
    """
    return [
        spec["schema"]
        for name, spec in TOOLS.items()
        if include_subagents or name != "subagent"
    ] + mcp_servers.schemas


async def _call_tool(name: str, raw_args: str, channel) -> str:
    """Run one tool call and return its output as text.

    Sync tool functions run in a worker thread so their HTTP/subprocess
    work never blocks the event loop; async tools and MCP calls are awaited
    directly on the loop.
    """
    try:
        args = json.loads(raw_args)
    except ValueError:
        return f"Error: invalid JSON arguments for {name}"
    print(f"tool call: {name}({args})")
    try:
        if name in TOOLS:
            spec = TOOLS[name]
            if spec["takes_channel"]:
                args["channel"] = channel  # e.g. to post embeds
            fn = spec["fn"]
            if inspect.iscoroutinefunction(fn):
                result = await fn(**args)
            else:
                result = await asyncio.to_thread(fn, **args)
        else:
            result = await mcp_servers.call(name, args)
    except Exception as exc:  # noqa: BLE001 — let the model see/report the error
        result = f"Error: {exc}"
    return str(result)


async def _agent_loop(
    channel, items: list, schemas: list[dict], instructions: str, max_rounds: int
) -> str:
    """Run tool rounds until the model replies with plain text.

    Every tool call requested in one round executes concurrently — including
    subagent calls, so data gathering from multiple sources happens in
    parallel. Models often narrate their reasoning ("Let me check X...")
    alongside tool calls — that chatter is transcript context only, NEVER
    part of the reply we post back.
    """

    async def create(**kwargs):
        return await client.responses.create(
            model=MODEL,
            instructions=instructions,
            input=items,
            tools=schemas,
            **kwargs,
        )

    response = await create()
    for _ in range(max_rounds):
        calls = [i for i in response.output if i.type == "function_call"]
        if response.output_text:
            items.append({"role": "assistant", "content": response.output_text})
        if not calls:
            return response.output_text

        # Execute the whole batch concurrently; gather preserves call order.
        outputs = await asyncio.gather(
            *(_call_tool(c.name, c.arguments, channel) for c in calls)
        )
        # Echo each call back so the API can pair it with its output.
        items.extend(
            {
                "type": "function_call",
                "call_id": c.call_id,
                "name": c.name,
                "arguments": c.arguments,
            }
            for c in calls
        )
        items.extend(
            {
                "type": "function_call_output",
                "call_id": c.call_id,
                "output": output,
            }
            for c, output in zip(calls, outputs)
        )
        response = await create()

    # Tool budget exhausted while the model was still calling tools.
    # Force a text-only wrap-up so the user gets an answer built from
    # whatever was gathered, instead of the intermediate narration.
    response = await create(tool_choice="none")
    return response.output_text


@tool
async def subagent(task: str, channel) -> str:
    """Spawn a research subagent that gathers data and reports back. Give it one self-contained research task, e.g. "get Galross-Rexxar's (US-Rexxar) current M+ rating, rated PvP rating, and raid progress". Make several subagent calls in the same turn to research multiple sources/topics at once — they run in parallel. The subagent can use the built-in tools (not subagents, not side effects beyond tool embeds) and replies with a concise report citing sources. For a single quick lookup, call the tool directly instead."""
    await mcp_servers.start()  # no-op without mcp.json / after first call
    return await _agent_loop(
        channel,
        [{"role": "user", "content": task}],
        _schemas(include_subagents=False),
        SUBAGENT_PROMPT,
        SUBAGENT_TOOL_ROUNDS,
    )


async def run_agent(channel, user_text: str) -> str:
    """Run one agent turn for a channel and return the bot's reply."""
    channel_id = channel.id
    await mcp_servers.start()  # no-op without mcp.json

    items = conversations.setdefault(channel_id, [])
    items.append({"role": "user", "content": user_text})
    reply = await _agent_loop(
        channel, items, _schemas(include_subagents=True), SYSTEM_PROMPT,
        MAX_TOOL_ROUNDS,
    )

    del items[:-MAX_HISTORY_ITEMS]
    # Never start the transcript on an orphaned tool call/output pair.
    while items and items[0].get("type") in ("function_call", "function_call_output"):
        items.pop(0)
    return reply
