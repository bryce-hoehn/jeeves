"""Cron-style scheduled prompts.

Jobs are declared in cron.json (see cron.json.example) as:

    [
      {
        "name": "changelogs",              # optional, for logs
        "schedule": "0 9 * * 1",           # 5-field cron expression (UTC)
        "timezone": "America/New_York",    # optional, default Etc/UTC
        "channel_id": 1234567890123456789, # where replies are posted
        "prompt": "fetch update changelogs and update the knowledgebase",
        "enabled": true                    # optional, default true
      }
    ]

Each job runs its prompt through the agent on schedule and posts the
reply to the configured channel, in 2000-char chunks like main.py.
Every run starts from a fresh conversation and its history is discarded
afterwards, so scheduled runs never pollute user conversations. Runs
missed while the container was down are skipped, not replayed.

The scheduler is started from main.py once the bot is logged in.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from croniter import croniter

import agent

log = logging.getLogger("cron")

MAX_SLEEP = 300  # cap the sleep so config/timezone changes still get picked up


class Job:
    def __init__(self, raw: dict):
        if not croniter.is_valid(raw.get("schedule", "")):
            raise ValueError(f"invalid cron expression {raw.get('schedule')!r}")
        self.name = raw.get("name") or raw["prompt"][:40]
        self.schedule = raw["schedule"]
        self.prompt = raw["prompt"]
        self.channel_id = int(raw["channel_id"])
        self.timezone = ZoneInfo(raw.get("timezone", "Etc/UTC"))
        self._iter = croniter(self.schedule, datetime.now(self.timezone))
        self.next = self._iter.get_next(datetime)

    def advance(self) -> datetime:
        """Mark this firing as done and return when it was due."""
        due = self.next
        self.next = self._iter.get_next(datetime)
        return due


def load_jobs(path: str | Path | None = None) -> list[Job]:
    path = Path(path or os.getenv("CRON_FILE", "cron.json"))
    if not path.exists():
        return []
    raw = json.loads(path.read_text())
    entries = raw.get("jobs", []) if isinstance(raw, dict) else raw
    jobs = []
    for i, entry in enumerate(entries):
        try:
            job = Job(entry)
        except (KeyError, ValueError, TypeError) as exc:
            log.error("skipping cron job #%s: %s", i, exc)
            continue
        if entry.get("enabled", True):
            jobs.append(job)
    return jobs


async def run_job(bot, job: Job) -> None:
    """Resolve the job's channel, run its prompt, post the reply."""
    channel = bot.get_channel(job.channel_id)
    if channel is None:
        channel = await bot.fetch_channel(job.channel_id)

    agent.conversations.pop(job.channel_id, None)  # fresh context per run
    try:
        async with channel.typing():
            reply = await agent.run_agent(channel, job.prompt)
    finally:
        agent.conversations.pop(job.channel_id, None)  # don't leak into user threads

    for i in range(0, len(reply), 2000):
        await channel.send(reply[i : i + 2000])


async def scheduler(bot) -> None:
    if getattr(scheduler, "_started", False):
        return
    scheduler._started = True

    jobs = load_jobs()
    if not jobs:
        log.info("cron: no jobs configured")
        return
    log.info("cron: %d job(s): %s", len(jobs), ", ".join(j.name for j in jobs))

    while True:
        now = datetime.now(timezone.utc)
        for job in jobs:
            if job.next <= now:
                job.advance()
                log.info("cron: firing %r", job.name)
                try:
                    await run_job(bot, job)
                except Exception:
                    log.exception("cron: job %r failed", job.name)
        delay = min((job.next - now).total_seconds() for job in jobs)
        await asyncio.sleep(max(1.0, min(delay, MAX_SLEEP)))
