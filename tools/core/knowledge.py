"""Knowledge base — persistent markdown notes the agent can read and write.

A simple folder of markdown files (default `knowledge/`, override with the
KNOWLEDGE_DIR env var). The knowledge base is a long-term library of
universal verified truths, NOT a notebook for individual conversations:
stable game-mechanics/lore facts, "where to find it" pointers (topic →
tool/API), and timestamped long-term market data. One-off conversation
output (plans, session summaries, user preferences, unverified claims)
does not belong here — the write-tool docstrings enforce this policy.

Names are single path components (`flipping-notes`, `asmongold-gear.md`) —
the `.md` extension is added automatically and path traversal is rejected.
"""

import os
import re
import time
from pathlib import Path

from tools import tool

MAX_WRITE_BYTES = 256 * 1024  # refuse absurdly large notes
MAX_READ_CHARS = 16000
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._\-]*$", re.ASCII)


def _dir() -> Path:
    path = Path(os.getenv("KNOWLEDGE_DIR", "knowledge"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _resolve(name: str) -> Path:
    """Turn a note name into a safe path inside the knowledge dir."""
    name = name.strip()
    if not name or len(name) > 100 or not NAME_RE.match(name):
        raise RuntimeError(
            f"invalid note name '{name}' — use a short file name with "
            "letters, digits, spaces, hyphens, or underscores (no slashes)"
        )
    if not name.lower().endswith(".md"):
        name += ".md"
    return _dir() / name


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("#"):
            return line.lstrip("# ").strip()
    return ""


def _stamp(path: Path) -> str:
    mtime = path.stat().st_mtime
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(mtime))


@tool
def kb_list() -> str:
    """List every note in the knowledge base: name, last-modified time, size, and title. Check it at the start of a task to see what's already known. Writing is restricted to universal verified facts only — see the kb_write policy."""
    notes = sorted(_dir().glob("*.md"))
    if not notes:
        return (
            "Knowledge base is empty. Create the first note with kb_write"
            " (e.g. name 'market-watchlist')."
        )
    lines = [f"{len(notes)} note(s) in the knowledge base:"]
    for path in notes:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        title = _first_heading(text) or "(no heading)"
        lines.append(f"  {path.name} — {_stamp(path)}, {len(text):,} chars: {title}")
    return "\n".join(lines)


@tool
def kb_read(name: str) -> str:
    """Read one knowledge-base note by name (the .md extension is optional). Long notes are truncated to the first 16,000 characters."""
    path = _resolve(name)
    if not path.exists():
        available = ", ".join(sorted(p.name for p in _dir().glob("*.md"))) or "none"
        return f"No note named '{path.name}'. Existing notes: {available}"
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) > MAX_READ_CHARS:
        return text[:MAX_READ_CHARS] + f"\n\n... (truncated, {len(text):,} chars total)"
    return text


@tool
def kb_write(name: str, content: str) -> str:
    """Create or overwrite a knowledge-base note (markdown), for UNIVERSAL VERIFIED FACTS only — content that stays true for months and was verified with a tool in this conversation: (1) stable game knowledge (broad mechanics like warbands, dungeon/boss mechanics, lore, expansion/patch overviews), (2) "where to find it" notes mapping a topic to the tool/API/site that answers it, (3) long-term market trend records. NOT for one-off conversation output: no plans, to-do lists, answers to one-off questions, session summaries, user preferences, character specifics, or anything from training data you couldn't verify. When in doubt, don't write. Convention: start the note with a '# Title' heading and cite the source of each fact. The .md extension is added automatically."""
    if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
        return f"Note too large ({len(content):,} chars) — keep notes under 256 KB."
    path = _resolve(name)
    existed = path.exists()
    path.write_text(content, encoding="utf-8")
    action = "updated" if existed else "created"
    return f"Note {action}: {path.name} ({len(content):,} chars)."


@tool
def kb_append(name: str, content: str) -> str:
    """Append text to a knowledge-base note, creating it if it doesn't exist. For timestamped long-term records of VERIFIED observations (e.g. market prices with source and date) — same policy as kb_write: universal verified facts only, never one-off conversation output or unverified claims. Prefix each entry with its date; each append becomes a new line block at the end of the note."""
    path = _resolve(name)
    existing = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    combined = existing + content if existing.endswith("\n") or not existing else existing + "\n" + content
    if len(combined.encode("utf-8")) > MAX_WRITE_BYTES:
        return "Note would grow past 256 KB — split it or start a new note."
    path.write_text(combined, encoding="utf-8")
    action = "appended to" if existing else "created"
    return f"Note {action}: {path.name} (now {len(combined):,} chars)."


@tool
def kb_search(query: str) -> str:
    """Search every knowledge-base note for a (case-insensitive) term; returns the notes that match with each matching line shown. Use it to find what's already known about a topic before researching, and before writing a note to avoid duplicates."""
    q = query.lower()
    hits = []
    for path in sorted(_dir().glob("*.md")):
        matches = []
        for i, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            if q in line.lower():
                matches.append(f"    L{i}: {line.strip()[:160]}")
        if matches:
            hits.append(f"  {path.name} ({len(matches)} match(es)):")
            hits += matches[:8]
            if len(matches) > 8:
                hits.append(f"    ... {len(matches) - 8} more")
    if not hits:
        return f"No notes mention '{query}'."
    return "\n".join(hits)[:8000]
